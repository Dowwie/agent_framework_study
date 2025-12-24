# Resilience Analysis: AWS Strands

## Summary
- **Key Finding 1**: Fail-hard philosophy with explicit exception types (no silent failures)
- **Key Finding 2**: Exponential backoff retry for throttling, no retry for other errors
- **Classification**: Defensive with transparent error propagation

## Detailed Analysis

### Exception Taxonomy

#### Custom Exception Hierarchy

**Location**: `src/strands/types/exceptions.py`

| Exception | Purpose | Recoverable | Action |
|-----------|---------|-------------|--------|
| EventLoopException | Generic loop error | Maybe | Wraps original + request_state |
| MaxTokensReachedException | Output truncated | No | Fail hard, no retry |
| ContextWindowOverflowException | Input too large | Yes | Trigger reduce_context() |
| ModelThrottledException | Rate limited | Yes | Exponential backoff retry |
| StructuredOutputException | Output parsing failed | Maybe | Max retry then fail |
| SessionException | Session ops failed | No | Propagate |
| ToolProviderException | Tool load/cleanup failed | No | Propagate |
| MCPClientInitializationError | MCP server init failed | No | Propagate |

**Characteristics**:
- All inherit from base `Exception` (no custom hierarchy)
- Some store original exception + state (EventLoopException)
- Some store just message (ModelThrottledException, StructuredOutputException)
- No error codes or structured metadata

### Error Handling Patterns

#### 1. Fail-Hard on Max Tokens (event_loop.py:L163-L177)

```python
if stop_reason == "max_tokens":
    raise MaxTokensReachedException(
        message="Agent has reached an unrecoverable state due to max_tokens limit..."
    )
```

**Rationale**: Prevents silent truncation of responses

**Alternative**: Framework could recover by:
- Extending max_tokens parameter
- Summarizing previous context
- Switching to streaming mode

**Design Decision**: Explicit failure forces developer handling

#### 2. Exponential Backoff for Throttling

**Constants** (event_loop.py:L54-L56):
```python
MAX_ATTEMPTS = 6
INITIAL_DELAY = 4  # seconds
MAX_DELAY = 240  # 4 minutes
```

**Pattern**: Referenced but implementation not visible in sampled code
- Likely in model-specific retry logic
- Standard exponential backoff formula: `min(INITIAL_DELAY * 2^attempt, MAX_DELAY)`

**Issue**: Constants are module-level (not configurable per-agent)

#### 3. Context Window Overflow Recovery

**Trigger**: `ContextWindowOverflowException` raised by model

**Handler**: Delegates to ConversationManager:
```python
try:
    # model.stream(...)
except ContextWindowOverflowException as e:
    conversation_manager.reduce_context(agent, e)
    # Retry with reduced context
```

**Built-in Strategies**:
- SlidingWindow: Remove N oldest messages
- Summarizing: LLM-based compression
- Null: No-op (propagate exception)

#### 4. EventLoopException Wrapping

**Pattern** (exceptions.py:L6-L18):
```python
class EventLoopException(Exception):
    def __init__(self, original_exception: Exception, request_state: Any = None):
        self.original_exception = original_exception
        self.request_state = request_state or {}
        super().__init__(str(original_exception))
```

**Purpose**:
- Preserve original exception for debugging
- Attach request state for context
- Allows inspection of agent state at failure point

**Usage Pattern**:
```python
try:
    # event loop execution
except Exception as e:
    raise EventLoopException(e, invocation_state["request_state"])
```

### Sandboxing & Isolation

#### Tool Execution Isolation

**No built-in sandboxing** observed in sampled code:
- Tools execute in same process
- No timeout enforcement (tool must self-timeout)
- No resource limits (CPU, memory)
- No capability-based security

**Implication**: Tools can:
- Block event loop indefinitely
- Consume unlimited memory
- Access agent internals via ToolContext

#### Concurrent Tool Execution

**ConcurrentToolExecutor** mentioned but not detailed:
- Likely uses asyncio.gather() for parallelism
- No isolation between concurrent tools
- Shared state risks if tools mutate agent state

### Error Recovery Strategies

#### Retry Logic

**Where retry happens**:
1. **Throttling**: Exponential backoff (up to 6 attempts)
2. **Context Overflow**: Single retry after reduce_context()
3. **Structured Output**: Multiple attempts (max count unclear)

**Where NO retry**:
1. **MaxTokensReached**: Fail immediately
2. **Tool Errors**: Propagate to user
3. **Session Errors**: Propagate to user
4. **Generic Exceptions**: Wrapped in EventLoopException and propagated

#### Graceful Degradation

**Limited graceful degradation**:
- Context overflow → reduce context → retry
- Structured output failure → retry with validation errors in prompt
- No fallback models
- No circuit breaker pattern

### Observability for Errors

#### Tracing Integration

**OpenTelemetry spans** (event_loop.py:L134-L141):
```python
cycle_span = tracer.start_event_loop_cycle_span(
    invocation_state=invocation_state,
    messages=agent.messages,
    parent_span=agent.trace_span,
    custom_trace_attributes=agent.trace_attributes,
)
```

**Error Capture**:
- Exceptions likely recorded in span events
- Request state attached to EventLoopException
- Cycle ID for correlation

#### Logging

**Standard Python logging**:
- `logger = logging.getLogger(__name__)` in most modules
- No structured logging observed
- Log levels unclear from sampling

### Tool Error Handling

#### ToolResult Status

**Type** (types/tools.py:L83):
```python
ToolResultStatus = Literal["success", "error"]

class ToolResult(TypedDict):
    content: list[ToolResultContent]
    status: ToolResultStatus
    toolUseId: str
```

**Pattern**:
- Tools return explicit success/error status
- Error details in ToolResultContent (text field)
- Agent can continue despite tool errors

**Implication**: Tool errors are data, not exceptions

### Session Persistence & Recovery

#### Session State Management

**SessionException** for failures:
- Save operation failed
- Load operation failed
- State corruption

**No automatic recovery**:
- Application must handle SessionException
- No retry logic for persistence
- No state versioning for migrations

### Interrupt Handling

#### Interrupt Pattern

**Type** (types/event_loop.py:L46):
```python
StopReason = Literal[
    "content_filtered",
    "end_turn",
    "guardrail_intervened",
    "interrupt",  # <-- Human-in-the-loop
    "max_tokens",
    "stop_sequence",
    "tool_use",
]
```

**Usage**:
- Agent can pause for human input
- Interrupt state stored in `_InterruptState`
- Resumable after interrupt

**Resilience Benefit**: Human validation step prevents runaway agents

## Code References
- `src/strands/types/exceptions.py:1-97` - All exception definitions
- `src/strands/event_loop/event_loop.py:54-56` - Retry constants
- `src/strands/event_loop/event_loop.py:163-177` - Max tokens fail-hard
- `src/strands/types/tools.py:83-99` - ToolResult with status field
- `src/strands/agent/conversation_manager/conversation_manager.py:69-88` - reduce_context() interface

## Implications for New Framework
- **Adopt**: Fail-hard on max_tokens (prevents silent truncation)
- **Adopt**: EventLoopException pattern (preserves original + state)
- **Adopt**: ToolResult status field (errors as data)
- **Adopt**: Explicit StopReason types (clear failure modes)
- **Adopt**: Interrupt mechanism for human-in-the-loop
- **Reconsider**: Make retry constants configurable (not hardcoded)
- **Reconsider**: Add circuit breaker for repeated failures
- **Reconsider**: Add tool execution timeouts
- **Reconsider**: Add sandboxing for untrusted tools

## Anti-Patterns Observed
- **Hardcoded Retry Constants**: MAX_ATTEMPTS/DELAY at module level (not per-agent tunable)
- **No Tool Sandboxing**: Tools execute without isolation (can block event loop)
- **Flat Exception Hierarchy**: All exceptions inherit from base Exception (no structured error handling)
- **No Circuit Breaker**: Repeated failures don't trigger automatic fallback
- **No Structured Logging**: Plain Python logging (no JSON/structured fields)
