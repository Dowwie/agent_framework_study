# Memory Orchestration: pydantic-ai

## Summary

- **Memory Model**: Simple message history list (no tiers, no eviction)
- **Context Assembly**: History processors for filtering/transforming
- **Persistence**: User-managed via message history access
- **Classification**: **Flat message history with optional processing**

## Detailed Analysis

### Memory Structure

**Single-tier**: Flat list of messages
```python
@dataclasses.dataclass(kw_only=True)
class GraphAgentState:
    message_history: list[ModelMessage] = dataclasses.field(default_factory=list)
```

**No built-in eviction** - history grows unbounded unless user intervenes.

### Message Types

```python
ModelMessage = ModelRequest | ModelResponse
```

**ModelRequest parts**:
- `UserPromptPart` - User input
- `SystemPromptPart` - System instructions
- `ToolReturnPart` - Tool results
- `RetryPromptPart` - Error feedback

**ModelResponse parts**:
- `TextPart` - Model text output
- `ToolCallPart` - Tool invocations
- `FilePart` - Images/files
- `ThinkingPart` - Extended thinking (e.g., Claude with thinking)

### Context Assembly

**History processors** - user-defined callbacks:
```python
HistoryProcessor = (
    Callable[[list[ModelMessage]], list[ModelMessage]]
    | Callable[[list[ModelMessage]], Awaitable[list[ModelMessage]]]
    | Callable[[RunContext[DepsT], list[ModelMessage]], list[ModelMessage]]
    | Callable[[RunContext[DepsT], list[ModelMessage]], Awaitable[list[ModelMessage]]]
)
```

**Applied before each model request**:
```python
original_history = ctx.state.message_history[:]
message_history = await _process_message_history(original_history, ctx.deps.history_processors, run_context)
# Replace contents, not reference (for capture_run_messages compatibility)
ctx.state.message_history[:] = message_history
```

**Use cases**:
- Limit to last N messages
- Remove old tool calls
- Compress text in old messages
- Filter sensitive content

### Message History Access

**Via RunContext**:
```python
@dataclass(kw_only=True)
class RunContext(Generic[AgentDepsT]):
    messages: list[ModelMessage]  # Read-only access to history

    # Also available:
    usage: RunUsage  # Token usage so far
    model: Model  # Current model
    retry: int  # Current retry count
```

**Via capture_run_messages** (context variable):
```python
from pydantic_ai._agent_graph import capture_run_messages

async with capture_run_messages() as messages:
    result = await agent.run(prompt)
    # messages now contains full history
```

### New Message Tracking

**new_message_index** tracks where new messages start:
```python
@dataclasses.dataclass(kw_only=True)
class GraphAgentDeps:
    new_message_index: int  # Index of first new message

# Updated after history processing:
ctx.deps.new_message_index -= len(original_history) - len(message_history)
```

**Access via result**:
```python
result = await agent.run(prompt)
new_messages = result.new_messages()  # Only messages from this run
```

### Message Cleaning

**Merge consecutive requests**:
```python
def _clean_message_history(history: list[ModelMessage]) -> list[ModelMessage]:
    # Merge trailing consecutive ModelRequest messages
    # Ensures clean user/assistant boundaries for models that need it
```

**Applied**:
- Before sending to model
- When copying history for capture

### No Built-in Memory Tiers

**Observation**: Unlike LangChain or Semantic Kernel:
- No short-term / long-term memory separation
- No automatic summarization
- No vector store integration
- No memory backends (Redis, etc.)

**Trade-off**: Simplicity vs. features
- Users must implement their own memory strategies
- Via history processors or external storage

### Persistence Pattern

**User-managed**:
```python
# Save
result = await agent.run(prompt)
save_to_db(result.all_messages())

# Restore
saved_messages = load_from_db()
result = await agent.run(prompt, message_history=saved_messages)
```

**No built-in persistence** - framework is stateless between runs.

## Code References

- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:86` - GraphAgentState with message_history
- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:67` - HistoryProcessor type definition
- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:504` - History processing before request
- `pydantic_ai_slim/pydantic_ai/_run_context.py` - RunContext with messages access

## Implications for New Framework

1. **Consider**: Built-in memory tiers
   - Pydantic-AI is too simple for complex agents
   - Add short-term (recent) / long-term (summarized) distinction
   - Optional, not mandatory

2. **Adopt**: History processors pattern
   - Clean extension point
   - User-defined strategies
   - Applied transparently before each request

3. **Avoid**: Unbounded message history
   - Will hit token limits eventually
   - Need built-in or recommended eviction strategies
   - At minimum, provide utility functions

4. **Adopt**: Message type hierarchy
   - Clear distinction between requests and responses
   - Structured parts within messages
   - Enables rich content (text, images, tools)

5. **Consider**: Built-in persistence layer (optional)
   - Many users need this
   - Could provide adapters for common DBs
   - Keep core stateless, add as extension

## Anti-Patterns Observed

1. **Unbounded growth**: No default eviction policy
   - **Risk**: Token limit errors in long conversations
   - **Mitigation**: Users must implement via history processors
   - **Recommendation**: Provide built-in eviction strategies

2. **No summarization support**: Users must roll their own
   - **Recommendation**: Provide example summarization processor

3. **Good pattern**: Message history is mutable list
   - Enables efficient in-place updates
   - Shared across nodes without copying
   - Simplifies implementation

## Notable Patterns Worth Adopting

1. **new_message_index tracking**:
   - Clean way to distinguish old vs. new messages
   - Adjusted after history processing
   - Enables result.new_messages() API

2. **Context variable for message capture**:
   - `capture_run_messages()` context manager
   - Non-invasive way to access history
   - Useful for logging/debugging

3. **Message cleaning before model request**:
   - Merge consecutive requests
   - Ensures clean boundaries
   - Transparent to user
