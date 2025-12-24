# Control Loop Extraction: AWS Strands

## Summary
- **Key Finding 1**: ReAct pattern with recursive event loop cycles
- **Key Finding 2**: Dual architectures - traditional turn-based (Agent) and streaming duplex (BidiAgent)
- **Classification**: ReAct (Reason + Act) with streaming event emission

## Detailed Analysis

### Reasoning Pattern Classification

**Pattern**: **ReAct** (Reasoning and Acting)

**Evidence**:
1. Model generates thoughts + tool calls
2. Tools execute and return results
3. Model reasons over tool results
4. Cycle continues until end_turn

**Key Difference from other patterns**:
- Not **Plan-and-Solve**: No upfront planning phase
- Not **ReWOO**: Tools execute immediately (not batched)
- Not **Reflexion**: No explicit self-reflection/critique step

### Step Function Topology

#### Traditional Agent Loop (event_loop.py:L79)

```
event_loop_cycle() [AsyncGenerator]:
  1. Initialize cycle state + metrics
  2. Create tracing span
  3. Check interrupt state
  4. If interrupted or has tool_use:
       → Skip model call
       → Use existing tool_use message
  5. Else:
       → _handle_model_execution()
         → validate_and_prepare_tools()
         → stream_messages() [calls model.stream()]
         → yield ModelMessageEvent
  6. Match stop_reason:
       → "max_tokens": raise MaxTokensReachedException
       → "tool_use": _handle_tool_execution()
         → Execute tools (sequential or concurrent)
         → Append tool results to messages
         → RECURSIVELY call event_loop_cycle()  <-- KEY
       → "end_turn": yield EventLoopStopEvent
  7. End cycle, collect metrics
```

**Critical Insight**: Recursion, not iteration
- `_handle_tool_execution()` calls `event_loop_cycle()` again
- Stack depth = number of tool interaction turns
- No maximum recursion depth check observed

**Termination Conditions**:
1. `stop_reason == "end_turn"` (model decides to stop)
2. `stop_reason == "max_tokens"` (exception raised)
3. `stop_reason == "interrupt"` (human intervention)
4. Exception in model/tool execution

#### Bidirectional Agent Loop (bidi/agent/loop.py:L40)

```
_BidiAgentLoop.start():
  1. Invoke before_invocation hooks
  2. model.start() (persistent connection)
  3. Create event queue (maxsize=1)
  4. Spawn _run_model() task in background
  5. Set send_gate (allow user input)

_BidiAgentLoop.receive() [AsyncGenerator]:
  while True:
    1. event = await _event_queue.get()
    2. if isinstance(event, ToolUseStreamEvent):
         → Execute tool
         → Yield tool result events
    3. elif isinstance(event, BidiConnectionRestartEvent):
         → Restart model connection
    4. else:
         → Yield event to caller

_BidiAgentLoop.send(event):
  1. await send_gate.wait() (blocks during restart)
  2. If BidiTextInputEvent: append to messages
  3. model.send(event)
```

**Critical Insight**: Full duplex streaming
- No recursion (loop runs indefinitely)
- Model and tools run concurrently
- User can send input while model is generating

### Reasoning Loop Mechanics

#### Turn Structure (Traditional Agent)

**Single Turn**:
```
User Input
  → Model Inference (streaming)
  → 0 or more Tool Calls
  → For each tool call:
       → Execute tool
       → Append ToolResult to messages
  → If stop_reason == "tool_use":
       → RECURSIVE call to event_loop_cycle()
  → Else:
       → Return final response
```

**Example Multi-Turn Flow**:
```
Turn 1: User: "What's the weather in SF?"
  → Model: [ToolUse: get_weather(location="SF")]
  → Tool: {"temp": "65F", "conditions": "sunny"}
  → Recursive call to event_loop_cycle()

Turn 2: (No new user input, just tool results)
  → Model: "The weather in SF is 65F and sunny."
  → stop_reason: "end_turn"
  → Return to user
```

#### Streaming Event Flow

**Event Types** (types/_events.py):
1. StartEvent - Cycle begins
2. StartEventLoopEvent - Model call starting
3. ModelStreamChunkEvent - Token streaming
4. ModelMessageEvent - Complete model message
5. ToolInterruptEvent - Tool needs human input
6. ToolResultEvent - Tool completed
7. ToolResultMessageEvent - Tool result added to history
8. EventLoopStopEvent - Cycle complete
9. ForceStopEvent - User requested stop

**Consumption Pattern**:
```python
async for event in agent.invoke_async(input):
    match event:
        case ModelStreamChunkEvent():
            print(event.chunk.text, end="")
        case ToolResultEvent():
            print(f"Tool: {event.result}")
        case EventLoopStopEvent():
            final_result = event
```

### State Transition Graph

```
[IDLE]
  ↓ (user input)
[CYCLE_START]
  ↓
[MODEL_CALL] ←──────────────┐
  ↓                          │
  ├─ "end_turn" → [DONE]     │
  ├─ "interrupt" → [WAITING_INPUT]
  ├─ "max_tokens" → [ERROR]  │
  └─ "tool_use" → [TOOL_EXEC]│
       ↓                      │
       └──────────────────────┘ (recursive cycle)
```

**State Storage**:
- `invocation_state["request_state"]` - user-defined state
- `invocation_state["event_loop_cycle_id"]` - current cycle UUID
- `agent._interrupt_state` - interrupt tracking
- `agent.messages` - conversation history

### Tool Execution Coordination

#### Sequential vs Concurrent

**Sequential** (default):
```python
for tool_use in tool_uses:
    result = await tool.stream(tool_use)
    append_to_messages(result)
```

**Concurrent** (ConcurrentToolExecutor):
```python
tasks = [tool.stream(tu) for tu in tool_uses]
results = await asyncio.gather(*tasks)
for result in results:
    append_to_messages(result)
```

**Ordering**: Results appended in execution order (sequential) or completion order (concurrent)

#### Tool Interrupt Pattern

**Scenario**: Tool requests human input mid-execution

**Mechanism**:
1. Tool yields `ToolInterruptEvent`
2. Event loop sets `agent._interrupt_state.activated = True`
3. Event loop yields `EventLoopStopEvent(stop_reason="interrupt")`
4. User provides input via `agent.resume_async()`
5. Event loop resumes from interrupt state

**State Preservation**:
```python
agent._interrupt_state.context = {
    "tool_use_message": message,
    "pending_tool_uses": [...],
}
```

### Decision Points

#### When does the model stop?

**Provider-specific stop reasons**:
1. `"end_turn"` - Model generated stop token
2. `"tool_use"` - Model requested tool(s)
3. `"max_tokens"` - Hit output token limit
4. `"stop_sequence"` - Custom stop sequence matched
5. `"content_filtered"` - Content policy violation
6. `"guardrail_intervened"` - Guardrail blocked response

**Agent decision**:
- `"tool_use"` → Execute tools, recurse
- `"end_turn"` → Return response
- Everything else → Propagate/error

#### When does tool execution occur?

**Trigger**: `stop_reason == "tool_use"`

**Preconditions**:
1. Model message contains ToolUse content blocks
2. Tools are registered in ToolRegistry
3. No interrupt state active (or resuming from interrupt)

**Post-execution**:
- Always recurse to `event_loop_cycle()` for next model call
- No maximum tool execution depth observed

### Planning vs Reactive

**Classification**: **Reactive** (no upfront planning)

**Evidence**:
- Model generates next action immediately
- No separate planning phase
- Tool results trigger immediate model call
- No plan refinement loop

**Implication**: Suitable for:
- Interactive tasks (chat, Q&A)
- Simple tool sequences (1-3 steps)

**Limitation**: Not ideal for:
- Complex multi-step workflows
- Optimization problems
- Constraint satisfaction

### Metrics & Observability

**Per-Cycle Metrics** (event_loop.py:L127):
```python
cycle_start_time, cycle_trace = agent.event_loop_metrics.start_cycle(
    attributes={"event_loop_cycle_id": str(cycle_id)}
)
```

**Collected Metrics**:
- Cycle duration
- Model latency
- Time to first byte
- Token usage (input/output/cached)

**Tracing**:
- OpenTelemetry spans per cycle
- Parent-child span relationships
- Custom attributes via `trace_attributes`

## Code References
- `src/strands/event_loop/event_loop.py:79-200` - Core event_loop_cycle function
- `src/strands/event_loop/event_loop.py:179-195` - Tool execution recursion
- `src/strands/experimental/bidi/agent/loop.py:40-150` - Bidirectional loop
- `src/strands/types/event_loop.py:39-57` - StopReason enum
- `src/strands/types/_events.py` - Event type definitions

## Implications for New Framework
- **Adopt**: ReAct pattern for interactive tasks
- **Adopt**: Streaming events for progress visibility
- **Adopt**: Interrupt mechanism for human-in-the-loop
- **Adopt**: Per-cycle metrics and tracing
- **Reconsider**: Recursion for tool loops (use iteration with max depth)
- **Reconsider**: Add planning phase for complex tasks
- **Reconsider**: Add circuit breaker for infinite tool loops
- **Add**: Plan-and-Solve mode for multi-step tasks

## Anti-Patterns Observed
- **Unbounded Recursion**: No max depth check (stack overflow risk)
- **No Loop Detection**: Agent can call same tool repeatedly
- **No Planning**: Purely reactive (inefficient for complex tasks)
- **Tool Order Assumption**: Concurrent execution order non-deterministic
