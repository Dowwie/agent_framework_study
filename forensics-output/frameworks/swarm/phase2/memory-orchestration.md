# Memory Orchestration: Swarm

## Summary
- **Context Assembly**: Simple concatenation - [system, history, user]
- **Memory Tiers**: Single tier (flat message list)
- **Eviction Strategy**: None - unbounded growth
- **Token Management**: None - no counting or budget enforcement
- **Persistence**: None - ephemeral per-run only

## Context Assembly

### Structure
```python
# core.py:L47
messages = [{"role": "system", "content": instructions}] + history
```

**Order**:
1. System message (agent instructions)
2. Full history (all previous messages and tool results)

**No user message separation** - user messages are part of history

### Dynamic System Message
```python
# core.py:L42-46
instructions = (
    agent.instructions(context_variables)
    if callable(agent.instructions)
    else agent.instructions
)
```

**Feature**: Instructions can be a function of context variables
**Use case**: "You are helping {user_name} with {task_type}"
**Evaluation**: Every turn (allows dynamic instruction updates)

### Message Format

**During conversation**:
```python
{
    "role": "user|assistant|tool",
    "content": "...",
    "tool_calls": [...],  # Optional, for assistant messages
    "tool_call_id": "...",  # For tool result messages
    "tool_name": "...",     # For tool result messages
}
```

**Special field for streaming**:
```python
# core.py:L158, L270
message.sender = active_agent.name  # Custom field, not in OpenAI spec
```

## Memory Tiers

**Count**: 1 (single flat list)

### Short-term Memory
- **Storage**: `history` - Python list
- **Capacity**: Unbounded
- **Location**: core.py:L151, L254
- **Scope**: Per-run (isolated via deep copy)

**Structure**:
```python
history = copy.deepcopy(messages)  # Initial user messages
# Then appended with:
# - LLM responses
# - Tool results
# - More LLM responses
# - ...
```

**No distinction** between:
- Recent vs. old messages
- Important vs. trivial messages
- Summary vs. detail

### Long-term Memory
**Not implemented** - No persistence across runs

### Working Memory
**Not explicitly modeled** - Conflated with short-term memory

## Eviction Strategy

**None**: Messages accumulate indefinitely

```python
# core.py:L196, L271
history.append(message)  # Always append, never remove

# core.py:L218, L283
history.extend(partial_response.messages)  # Always extend, never truncate
```

### Implications

**Growth pattern**:
```
Turn 1: 1 user msg + 1 assistant msg = 2 messages
Turn 2: 2 + 1 assistant + N tool results = 3+N messages
Turn 3: 3+N + 1 assistant + M tool results = 4+N+M messages
...
```

**Risk**: Linear growth → eventual context overflow

**Failure mode**:
```
Long conversation
    → History exceeds model context window
        → OpenAI API returns error (400 Bad Request)
            → Agent crashes (no graceful handling)
```

## Token Management

### Counting
**None**: No token counting anywhere in codebase

**No tracking of**:
- Input tokens per turn
- Output tokens per turn
- Cumulative tokens per conversation
- Tokens remaining in budget

### Budget Enforcement
**None**: No limits or warnings

**Missing**:
- Per-turn token limit
- Per-conversation token budget
- Warning threshold (e.g., at 80% of context window)
- Automatic truncation or summarization

### Context Window Awareness
```python
# core.py:L58-64
create_params = {
    "model": model_override or agent.model,
    "messages": messages,  # No length check
    ...
}
```

**No validation**: Framework sends full history regardless of model's context limit

**Model context limits** (known, but not enforced):
- gpt-4o: 128k tokens
- gpt-4-turbo: 128k tokens
- gpt-3.5-turbo: 16k tokens

If history exceeds limit → OpenAI SDK raises exception → Agent crashes

## Context Variables (Orthogonal State)

### Not Part of Message History
```python
# core.py:L52-56 - Hidden from LLM
for tool in tools:
    params = tool["function"]["parameters"]
    params["properties"].pop(__CTX_VARS_NAME__, None)  # Remove from schema
    if __CTX_VARS_NAME__ in params["required"]:
        params["required"].remove(__CTX_VARS_NAME__)  # Remove from required list
```

**Purpose**: Store state that tools need but LLM shouldn't see
**Examples**: User ID, session token, database connection, API keys

### Injection into Tools
```python
# core.py:L120-121
if __CTX_VARS_NAME__ in func.__code__.co_varnames:
    args[__CTX_VARS_NAME__] = context_variables
```

**Magic parameter**: Framework detects `context_variables` param and injects automatically

### Mutation
```python
# core.py:L133, L219, L284
context_variables.update(result.context_variables)
```

**Persistence**: Within run only (isolated by deep copy at start)
**Use case**: Tool sets `context_variables["user_id"] = "123"` for later tools

## Memory Patterns

### Pattern 1: Append-Only History
```python
history.append(message)
history.extend(tool_results)
```
**Pro**: Simple, preserves all information
**Con**: Unbounded growth, no prioritization

### Pattern 2: Deep Copy Isolation
```python
# core.py:L150-151
context_variables = copy.deepcopy(context_variables)
history = copy.deepcopy(messages)
```
**Pro**: Prevents caller state mutation
**Con**: Memory overhead for large histories

### Pattern 3: Defaultdict for Safe Access
```python
# core.py:L41
context_variables = defaultdict(str, context_variables)
```
**Pro**: Missing keys return empty string instead of raising KeyError
**Con**: Silently creates empty entries, may hide bugs

## Implications for New Framework

### Adopt
1. **Deep copy isolation** - Clean separation between runs
2. **Context variables pattern** - Separate state channel for non-LLM data
3. **Dynamic instructions** - Context-aware system prompts

### Critical Additions Needed
1. **Token counting** - Use tiktoken or model-specific counter
2. **Automatic truncation** - When approaching context limit:
   - Oldest messages first (FIFO)
   - Summarization of old messages
   - Sliding window with pinned system message
3. **Memory tiers**:
   - Short-term: Recent N messages
   - Long-term: Summarized history or vector DB
   - Working memory: Current task context
4. **Budget enforcement** - Stop run when token budget exhausted
5. **Context window detection** - Know each model's limit, enforce proactively
6. **Importance scoring** - Retain high-value messages, evict low-value

### Anti-Patterns Observed
1. **No token awareness** - Will silently accumulate messages until crash
2. **No eviction policy** - Unbounded growth is unsustainable
3. **No summarization** - Old messages stay at full verbosity
4. **No prioritization** - All messages treated equally
5. **Magic parameter injection** - `context_variables` detection is implicit

## Advanced Memory Patterns Missing

**Not supported**:
- Semantic memory (vector DB for retrieval)
- Episodic memory (distinct conversation episodes)
- Message compression/summarization
- Selective forgetting (remove low-value messages)
- Memory checkpointing (save/restore state)
- Cross-run persistence (database, file storage)

## Token Budget Example (Missing Implementation)

**What SHOULD exist**:
```python
# Hypothetical desired behavior
def _enforce_token_budget(self, history, max_tokens):
    current_tokens = count_tokens(history)
    if current_tokens > max_tokens:
        # Option 1: Truncate oldest
        history = truncate_oldest(history, max_tokens)
        # Option 2: Summarize old messages
        history = summarize_and_truncate(history, max_tokens)
        # Option 3: Raise error
        raise TokenBudgetExceeded(current_tokens, max_tokens)
    return history
```

**Current reality**: None of this exists

## Code References

- `swarm/core.py:41` - Defaultdict conversion
- `swarm/core.py:42-46` - Dynamic instruction evaluation
- `swarm/core.py:47` - Context assembly (system + history)
- `swarm/core.py:52-56` - Context variables hidden from LLM
- `swarm/core.py:120-121` - Magic context_variables injection
- `swarm/core.py:150-151` - Deep copy isolation
- `swarm/core.py:196` - Append to history (unbounded)
- `swarm/core.py:218` - Extend history with tool results (unbounded)
