# Execution Engine Analysis: pydantic-ai

## Summary

- **Async Model**: Native asyncio with sync wrappers via `run_in_executor`
- **Control Flow**: Graph-based state machine (pydantic_graph library)
- **Streaming**: First-class support with AsyncIterator protocols
- **Classification**: **Graph-based async orchestration with streaming**

## Detailed Analysis

### Architecture Pattern: Graph State Machine

The framework uses a **graph-based execution model** powered by the `pydantic_graph` library, implementing a three-node state machine:

```
UserPromptNode → ModelRequestNode → CallToolsNode → (loop or End)
```

**Node Responsibilities:**
1. **UserPromptNode**: Assembles user prompts, instructions, and system prompts
2. **ModelRequestNode**: Makes LLM requests (streaming or non-streaming)
3. **CallToolsNode**: Processes responses, executes tools, validates output

### State Management

**GraphAgentState** (mutable dataclass):
```python
@dataclasses.dataclass(kw_only=True)
class GraphAgentState:
    message_history: list[_messages.ModelMessage] = dataclasses.field(default_factory=list)
    usage: _usage.RunUsage = dataclasses.field(default_factory=_usage.RunUsage)
    retries: int = 0
    run_step: int = 0
    run_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
```

**GraphAgentDeps** (configuration/dependencies passed to graph):
- User dependencies (`user_deps: DepsT`)
- Model and settings
- Tool manager
- Output validators
- Usage limits
- Instrumentation (OpenTelemetry Tracer)

### Async Execution Model

**Native async throughout:**
- All node `run()` methods are `async def`
- Model requests are async: `await ctx.deps.model.request(...)`
- Tool execution supports both sync and async: `is_async_callable()` check
- Sync tools wrapped via `run_in_executor`

**Example from ModelRequestNode:**
```python
async def run(
    self, ctx: GraphRunContext[GraphAgentState, GraphAgentDeps[DepsT, NodeRunEndT]]
) -> CallToolsNode[DepsT, NodeRunEndT]:
    if self._result is not None:
        return self._result
    if self._did_stream:
        raise exceptions.AgentRunError('You must finish streaming before calling run()')
    return await self._make_request(ctx)
```

### Streaming Architecture

**Two-level streaming support:**

1. **Model-level streaming** (ModelRequestNode):
```python
@asynccontextmanager
async def stream(
    self, ctx: GraphRunContext[GraphAgentState, GraphAgentDeps[DepsT, T]]
) -> AsyncIterator[result.AgentStream[DepsT, T]]:
    async with ctx.deps.model.request_stream(...) as streamed_response:
        self._did_stream = True
        agent_stream = result.AgentStream[DepsT, T](...)
        yield agent_stream
        # Ensure full consumption for usage tracking
        async for _ in agent_stream:
            pass
```

2. **Event-level streaming** (CallToolsNode):
```python
@asynccontextmanager
async def stream(
    self, ctx: GraphRunContext[GraphAgentState, GraphAgentDeps[DepsT, NodeRunEndT]]
) -> AsyncIterator[AsyncIterator[_messages.HandleResponseEvent]]:
    stream = self._run_stream(ctx)
    yield stream
    # Auto-complete stream if not consumed
    async for _event in stream:
        pass
```

**Key innovation**: Streams auto-complete if not manually consumed, ensuring usage tracking accuracy.

### Control Flow Topology

**Node Transitions:**

1. **UserPromptNode** → ModelRequestNode | CallToolsNode
   - Direct to CallToolsNode if resuming from deferred tool results
   - Otherwise prepares request and transitions to ModelRequestNode

2. **ModelRequestNode** → CallToolsNode
   - Always transitions after model response received
   - Caches result in `_result` field to prevent duplicate requests

3. **CallToolsNode** → End | ModelRequestNode
   - End if final output validated successfully
   - ModelRequestNode to continue loop for tool execution or retries

**Retry Logic:**
- Tracks retries in `GraphAgentState.retries`
- Increments on validation failures
- Raises `UnexpectedModelBehavior` when `max_result_retries` exceeded
- Special handling for incomplete tool calls due to token limits

### Message History Management

**Mutable message history** shared across nodes:
```python
# From UserPromptNode.run() line 212
messages[:] = _clean_message_history(ctx.state.message_history)
# Use the `capture_run_messages` list as the message history
ctx.state.message_history = messages
ctx.deps.new_message_index = len(messages)
```

**History processing pipeline:**
1. Clean message history (merge consecutive requests)
2. Apply `history_processors` callbacks
3. Update `new_message_index` for tracking new messages

### Concurrency & Context Management

**Context variables for RunContext:**
```python
from ._run_context import set_current_run_context

with set_current_run_context(run_context):
    model_response = await ctx.deps.model.request(...)
```

**Parallel tool execution** (not shown in excerpts but inferred from architecture):
- Tools can execute concurrently via asyncio.gather
- Event stream yields start/end events for each tool call

### Edge Cases & Error Handling

1. **Empty model responses**:
   - Retry with empty request to re-submit
   - Fall back to previous text response if available

2. **Token limit exceeded**:
   - Detect via `finish_reason == 'length'`
   - Provide clear error messages with max_tokens guidance
   - Special case for incomplete tool call JSON

3. **Deferred tool results**:
   - Skip ModelRequestNode and go directly to CallToolsNode
   - Merge approvals and custom results
   - Validate no duplicate tool call overrides

## Code References

- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:86` - GraphAgentState definition
- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:179` - UserPromptNode
- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:422` - ModelRequestNode with streaming
- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:554` - CallToolsNode response processing
- `pydantic_ai_slim/pydantic_ai/run.py:27` - AgentRun wrapper for graph execution

## Implications for New Framework

1. **Adopt**: Graph-based execution model for clarity
   - Explicit state machine nodes vs. implicit loops
   - Easier to reason about, test, and extend
   - Enables fine-grained control (pause, resume, inspect)

2. **Adopt**: First-class streaming support
   - AsyncIterator protocols throughout
   - Auto-completion for reliability (usage tracking)
   - Dual-level streaming (model + events)

3. **Adopt**: Contextmanager pattern for streaming
   - `async with node.stream(ctx) as stream:`
   - Ensures cleanup even if stream not consumed
   - Natural Python idiom

4. **Consider**: Mutable state + deep copying for snapshots
   - Trade-off: Performance vs. immutability guarantees
   - pydantic-ai chooses performance
   - Use `deepcopy` strategically for rollback points

5. **Adopt**: Native async with sync wrappers
   - Don't force users to choose sync XOR async
   - Provide both via `run_in_executor` for sync tools
   - Check callability with `is_async_callable()`

## Anti-Patterns Observed

1. **Minor**: Stateful nodes with `_result` caching
   - Nodes cache results in instance variables (`_result`, `_did_stream`)
   - Risk: Reusing node instances could cause stale data
   - Mitigation: Nodes are created per-execution, not reused
   - **Recommendation**: Consider making nodes immutable and returning new instances

2. **None observed**: Overall excellent async/streaming design with proper cleanup
