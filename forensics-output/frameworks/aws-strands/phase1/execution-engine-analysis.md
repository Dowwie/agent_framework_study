# Execution Engine Analysis: AWS Strands

## Summary
- **Key Finding 1**: Native async/await throughout with AsyncGenerator streaming pattern
- **Key Finding 2**: Dual agent architectures - traditional event loop (Agent) and bidirectional realtime (BidiAgent)
- **Classification**: Async-first with generator-based streaming

## Detailed Analysis

### Async Model
- **Approach**: Native async/await (no sync wrappers)
- **Runtime**: Asyncio event loop
- **Key Files**:
  - `src/strands/event_loop/event_loop.py` - Core event loop cycle
  - `src/strands/agent/agent.py` - Main agent implementation
  - `src/strands/experimental/bidi/agent/loop.py` - Bidirectional agent loop
- **Concurrency Model**: Cooperative multitasking with explicit task management

### Execution Topologies

#### 1. Traditional Agent (Event Loop Pattern)

**Entry Point**: `event_loop_cycle()` function (event_loop.py:L79)

**Control Flow**:
```
event_loop_cycle (generator)
  → Initialize cycle state + metrics
  → Start tracing span
  → Check if interrupts or tool_use in latest message
  → If not: _handle_model_execution()
  → If stop_reason == "tool_use": _handle_tool_execution()
  → _handle_tool_execution() recursively calls event_loop_cycle()
  → End cycle + collect metrics
```

**Streaming Pattern**:
- Returns `AsyncGenerator[TypedEvent, None]`
- Yields events: StartEvent → ModelMessageEvent → ToolEvents → EventLoopStopEvent
- Last event contains (StopReason, Message, Metrics, State)

**Key Characteristics**:
- Single-turn model invocation per cycle
- Synchronous tool execution (sequential or concurrent based on ToolExecutor)
- Recursive cycles for multi-turn tool interactions
- Max attempts: 6 with exponential backoff (INITIAL_DELAY=4s, MAX_DELAY=240s)

#### 2. Bidirectional Agent (Streaming Loop Pattern)

**Entry Point**: `_BidiAgentLoop` class (bidi/agent/loop.py:L40)

**Control Flow**:
```
start()
  → invoke before_invocation hooks
  → model.start() with system_prompt + tools + messages
  → create event queue (maxsize=1)
  → spawn _run_model() task in background
  → set send_gate (allows user input)

receive() (async generator)
  → while True: await _event_queue.get()
  → yield events from model or tool execution
  → if BidiConnectionRestartEvent: restart model connection

send(event)
  → wait for send_gate (blocks during model restart)
  → if BidiTextInputEvent: append to messages
  → model.send(event)
```

**Key Characteristics**:
- Persistent model connection (WebSocket-like)
- Concurrent send/receive (full duplex)
- Task pool for background execution (`_TaskPool`)
- Automatic connection restart on timeout
- Send gate pattern to block input during restart

### Event Architecture

#### Event Types Hierarchy

**Base**: `TypedEvent` (generic streaming event container)

**Agent Events**:
- StartEvent
- StartEventLoopEvent
- ModelMessageEvent
- EventLoopStopEvent
- ForceStopEvent

**Tool Events**:
- ToolInterruptEvent
- ToolResultEvent
- ToolResultMessageEvent
- ToolUseStreamEvent

**Bidi-Specific Events**:
- BidiInputEvent
- BidiOutputEvent
- BidiTextInputEvent
- BidiConnectionRestartEvent
- BidiConnectionCloseEvent
- BidiTranscriptStreamEvent

#### Event Flow Pattern
All execution follows generator streaming:
```python
async for event in agent.invoke_async(input):
    match event:
        case ModelMessageEvent: ...
        case ToolResultEvent: ...
        case EventLoopStopEvent: ...
```

### Concurrency Patterns

#### 1. Task Pool Pattern (Bidi)
```python
class _TaskPool:
    # tracks background tasks
    _task_pool.create(self._run_model())
    await _task_pool.cancel()  # cleanup
```

#### 2. Queue-Based Communication
```python
self._event_queue = asyncio.Queue(maxsize=1)  # bounded queue
await self._event_queue.get()  # consumer
await self._event_queue.put(event)  # producer
```

#### 3. Send Gate Pattern
```python
self._send_gate = asyncio.Event()
await self._send_gate.wait()  # block send during restart
self._send_gate.set()  # allow send
self._send_gate.clear()  # block send
```

#### 4. Concurrent Tool Execution
Configurable via `tool_executor` parameter:
- Sequential (default)
- `ConcurrentToolExecutor` (parallel execution)

### State Management

#### Invocation State
Dictionary passed through execution stack:
```python
invocation_state = {
    "event_loop_cycle_id": uuid.uuid4(),
    "request_state": {},
    "event_loop_cycle_trace": Trace,
    "event_loop_cycle_span": Span,
    # user-provided context for tools
}
```

#### Agent State
- `AgentState` object for user-managed state
- `ConversationManager` for message history
- `_InterruptState` for interrupt handling (internal)

### Error Handling & Recovery

#### Retry Strategy (event_loop.py:L54-L56)
- MAX_ATTEMPTS = 6
- INITIAL_DELAY = 4 seconds
- MAX_DELAY = 240 seconds (4 minutes)
- Exponential backoff for throttling

#### Exception Types
- `ContextWindowOverflowException` - input too large
- `MaxTokensReachedException` - output truncated
- `ModelThrottledException` - rate limited
- `EventLoopException` - generic loop error
- `StructuredOutputException` - output parsing failed

#### Max Tokens Handling
**Fails hard by default** (event_loop.py:L163-L177):
```python
if stop_reason == "max_tokens":
    raise MaxTokensReachedException(...)
```

Rationale: Prevents silent truncation, forces explicit handling

#### Bidi Connection Recovery
Automatic restart on timeout:
```python
# Restart model connection
await hooks.invoke(BidiBeforeConnectionRestartEvent)
await model.stop()
await model.start(...)
await hooks.invoke(BidiAfterConnectionRestartEvent)
```

### Instrumentation & Observability

#### Tracing (OpenTelemetry)
- Per-cycle spans: `event_loop_cycle_span`
- Parent span: `agent.trace_span`
- Custom attributes via `trace_attributes` parameter

#### Metrics
- `EventLoopMetrics` tracks cycle duration
- `start_cycle()` / `end_cycle()` pattern
- Attributes attached: `event_loop_cycle_id`

#### Hooks System
Event emission at key points:
- Before/After model call
- Before/After invocation
- Message added
- Agent initialized
- Bidi connection events

### Callback Architecture

#### Callback Handler Pattern
```python
callback_handler: Union[Callable, PrintingCallbackHandler]
# Default: PrintingCallbackHandler()
# Explicit None: null_callback_handler
```

Sentinel pattern to distinguish explicit None from default.

## Code References
- `src/strands/event_loop/event_loop.py:79-200` - Core event loop cycle
- `src/strands/experimental/bidi/agent/loop.py:40-150` - Bidirectional loop
- `src/strands/agent/agent.py:89-200` - Agent initialization
- `src/strands/event_loop/event_loop.py:54-56` - Retry constants
- `src/strands/event_loop/event_loop.py:163-177` - Max tokens handling
- `src/strands/experimental/bidi/agent/loop.py:69` - Send gate pattern

## Implications for New Framework
- **Adopt**: Native async/await without sync wrappers (clean, performant)
- **Adopt**: AsyncGenerator streaming for event flow (composable, backpressure-aware)
- **Adopt**: Task pool pattern for background work management
- **Adopt**: Send gate pattern for coordinating concurrent access
- **Adopt**: Explicit retry constants (tunable, debuggable)
- **Adopt**: Fail-hard on max_tokens (prevents silent truncation)
- **Reconsider**: Dual agent architectures (increases complexity)
- **Reconsider**: Recursive event loop cycles (can make stack traces hard to follow)

## Anti-Patterns Observed
- **Recursive Event Loop Calls**: `_handle_tool_execution()` recursively calling `event_loop_cycle()` can make debugging difficult
- **Global Retry Constants**: MAX_ATTEMPTS/DELAY hardcoded at module level (should be configurable)
- **Sentinel Class for Defaults**: `_DefaultCallbackHandlerSentinel` is overly complex for distinguishing None vs default
- **Invocation State as Dict**: Untyped dictionary for critical state (should be dataclass/TypedDict)
