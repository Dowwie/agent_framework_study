# Execution Engine Analysis: Swarm

## Summary
- **Async Model**: Synchronous only, no async/await
- **Control Flow**: Linear while loop with tool execution branch
- **Streaming**: Dual-mode (streaming/non-streaming) with code duplication
- **Concurrency**: Sequential tool execution, no parallelism

## Async Model

**Style**: Fully synchronous
- **No async/await**: All methods are synchronous functions
- **Event Loop**: None - relies on OpenAI SDK's synchronous client
- **Implications**: Blocking I/O on every LLM call, cannot leverage async benefits

### Evidence
```python
# core.py:L231-241 - synchronous signature
def run(
    self,
    agent: Agent,
    messages: List,
    context_variables: dict = {},
    model_override: str = None,
    stream: bool = False,
    debug: bool = False,
    max_turns: int = float("inf"),
    execute_tools: bool = True,
) -> Response:
```

No `async def` anywhere in codebase. OpenAI client initialized as synchronous:
```python
# core.py:L27-30
def __init__(self, client=None):
    if not client:
        client = OpenAI()  # Synchronous client
    self.client = client
```

## Control Flow Topology

**Pattern**: Linear imperative loop with branching

### Structure
```
Entry (run/run_and_stream)
  │
  ├─> Deep copy inputs (isolation)
  │
  └─> While loop (max_turns condition)
       │
       ├─> Get LLM completion
       │     └─> Build messages = [system] + history
       │     └─> Convert functions to tools
       │     └─> Call OpenAI API
       │
       ├─> Append message to history
       │
       ├─> If no tool_calls OR not execute_tools:
       │     └─> BREAK (return response)
       │
       ├─> Parse tool calls
       │
       ├─> Execute tools sequentially
       │     └─> handle_tool_calls()
       │           ├─> For each tool_call:
       │           │     ├─> Lookup function by name
       │           │     ├─> Inject context_variables if needed
       │           │     ├─> Execute function
       │           │     ├─> Handle result (str/Agent/dict)
       │           │     └─> Append tool response to history
       │           └─> Return partial_response
       │
       ├─> Update context_variables
       │
       ├─> If agent handoff:
       │     └─> Switch active_agent
       │
       └─> Loop back
```

### Topology Classification
- **Type**: Imperative while loop
- **Complexity**: Low (single loop, no nesting beyond tool iteration)
- **Termination Conditions**:
  1. No tool calls from LLM
  2. `execute_tools=False` flag
  3. `max_turns` reached
  4. `active_agent` becomes None (edge case, not explicitly handled)

## Entry Points

### Primary: `Swarm.run()`
- **Location**: core.py:L231
- **Signature**: `run(agent, messages, context_variables, model_override, stream, debug, max_turns, execute_tools) -> Response`
- **Branching**: If `stream=True`, delegates to `run_and_stream()` (L242-251)

### Streaming Variant: `Swarm.run_and_stream()`
- **Location**: core.py:L139
- **Returns**: Generator yielding deltas + final response
- **Duplication**: ~80% code overlap with `run()`, different only in completion handling

## Step Function

**No explicit step function** - logic inlined in main loop

Closest equivalent: `handle_tool_calls()` (core.py:L89-137)
- **Purpose**: Execute all tool calls from one LLM turn
- **Inputs**: tool_calls, functions, context_variables, debug
- **Outputs**: `Response` with messages, updated context, optional agent handoff
- **Side Effects**: None (pure function, returns new state)

## Concurrency

**Parallel Execution**: Configurable but not implemented

```python
# core.py:L67
create_params["parallel_tool_calls"] = agent.parallel_tool_calls
```
Sets OpenAI parameter for parallel tool calls, but framework executes tools sequentially:

```python
# core.py:L100-136 - sequential for loop
for tool_call in tool_calls:
    # Execute one by one
    raw_result = function_map[name](**args)
```

**Implication**: Even if LLM requests parallel tool execution, framework runs them serially. Missed optimization opportunity.

## Streaming Architecture

### Dual Implementation Pattern

**Non-streaming** (core.py:L231-292):
```python
completion = self.get_chat_completion(..., stream=False)
message = completion.choices[0].message  # Single object
history.append(json.loads(message.model_dump_json()))
```

**Streaming** (core.py:L139-229):
```python
completion = self.get_chat_completion(..., stream=True)
for chunk in completion:  # Incremental deltas
    delta = json.loads(chunk.choices[0].delta.json())
    yield delta
    merge_chunk(message, delta)  # Accumulate into message
```

### Stream Processing
- **Merge Strategy**: `util.py:L21-28` - `merge_chunk()` accumulates string fields and nested dicts
- **Tool Call Handling**: Special logic for incremental tool_calls (L25-28)
- **Delimiters**: Yields `{"delim": "start"}` and `{"delim": "end"}` for message boundaries

### Code Duplication Issue

Lines duplicated between `run()` and `run_and_stream()`:
- Deep copy setup (L150-152 vs L253-254)
- Main while loop structure
- Tool call parsing (L203-212 vs implicit in non-stream)
- Context variable updates
- Agent switching logic

**DRY Violation**: ~100 lines of duplicated logic. Refactoring opportunity: extract common loop body.

## Events & Callbacks

**None**: No event system, callbacks, or hooks

Only side effect is debug printing:
```python
# core.py:L48
debug_print(debug, "Getting chat completion for...:", messages)
```

No extension points for:
- Pre/post completion hooks
- Tool execution middleware
- State change observers
- Error handlers

## Execution Context

**Isolation**: Each `run()` call is isolated via deep copy

**Shared State**: Only `self.client` (OpenAI client instance)
- Safe because OpenAI SDK handles its own thread safety
- No mutable framework state persists across calls

## Implications for New Framework

### Adopt
1. **Deep copy isolation pattern** - Clean separation between runs
2. **Explicit termination conditions** - `max_turns`, `execute_tools` flag gives user control
3. **Simple imperative loop** - Easy to understand, debug, and modify

### Improve
1. **Add async/await support** - Modern Python frameworks should support async
2. **Implement actual parallel tool execution** - Honor `parallel_tool_calls` flag
3. **Eliminate streaming duplication** - Single implementation with streaming abstraction
4. **Add event hooks** - Pre/post completion, tool execution, agent handoff
5. **Extract step function** - Make loop body testable and reusable

### Anti-Patterns Observed
1. **Streaming mode duplication** - Same logic in two places, maintenance burden
2. **Sequential tool execution despite parallel flag** - Misleading configuration
3. **No async support** - Limits scalability and modern integration patterns
4. **Inline loop logic** - Hard to test, extend, or compose

## Performance Characteristics

| Aspect | Current State | Impact |
|--------|--------------|--------|
| **I/O Blocking** | Synchronous API calls | Entire process blocks on LLM response |
| **Tool Execution** | Sequential | Tools run one-by-one even if independent |
| **Message Building** | Per-turn reconstruction | O(n) message list building each turn |
| **Context Merging** | String concatenation | Efficient for small contexts |

## Code References

- `swarm/core.py:26-30` - Synchronous client initialization
- `swarm/core.py:32-69` - get_chat_completion (sync)
- `swarm/core.py:89-137` - handle_tool_calls (sequential execution)
- `swarm/core.py:139-229` - run_and_stream (duplicated loop)
- `swarm/core.py:231-292` - run (main loop)
- `swarm/util.py:21-28` - merge_chunk (streaming accumulation)
