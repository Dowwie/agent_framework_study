# Execution Engine Analysis: crewAI

## Summary
- **Async Model**: Hybrid - native asyncio with sync-to-async thread wrappers
- **Control Flow**: DAG-based with sequential and hierarchical process modes
- **Entry Point**: `Crew.kickoff()` with async variants (`kickoff_async`, `akickoff`)
- **Concurrency**: Thread-based parallelism for async tasks, asyncio for I/O-bound operations
- **Event Architecture**: Custom event bus with OpenTelemetry integration

## Detailed Analysis

### Async Model

**Classification**: **Hybrid - sync primary with async wrappers**

**Execution Paths**:

1. **Synchronous Main Path** (crew.py:L676):
```python
def kickoff(self, inputs: dict[str, Any] | None = None) -> CrewOutput:
    if self.process == Process.sequential:
        result = self._run_sequential_process()  # Sync
    elif self.process == Process.hierarchical:
        result = self._run_hierarchical_process()  # Sync
```

2. **Thread-Wrapped Async** (crew.py:L764):
```python
async def kickoff_async(self, inputs: dict[str, Any] | None = None):
    return await asyncio.to_thread(self.kickoff, inputs)
    # Wraps sync kickoff in thread to avoid blocking event loop
```

3. **Native Async Path** (crew.py:L834 - akickoff method exists):
```python
async def akickoff(self, inputs: dict[str, Any] | None = None):
    # True async implementation using _arun_sequential_process
```

**Agent Executor**: Dual execution modes
- `CrewAgentExecutor.invoke()` - synchronous (crew_agent_executor.py:L165)
- `CrewAgentExecutor.ainvoke()` - asynchronous variant (not shown in excerpt but referenced)

**Implications**:
- Framework designed for sync-first usage (most users call `kickoff()`)
- Async support added as compatibility layer
- Thread-based async (`asyncio.to_thread`) means true async isn't always used
- Can cause issues with context managers and thread-local storage

### Control Flow Topology

**Primary Pattern**: **Directed Acyclic Graph (DAG) with process-specific execution**

**Process Modes**:

1. **Sequential Process** (crew.py:L713):
```python
if self.process == Process.sequential:
    result = self._run_sequential_process()
```
- Tasks executed in order
- Each task completes before next starts
- Agent assigned per task
- Linear dependency chain

2. **Hierarchical Process** (crew.py:L715):
```python
elif self.process == Process.hierarchical:
    result = self._run_hierarchical_process()
```
- Manager agent coordinates worker agents
- Manager delegates tasks dynamically
- Requires `manager_llm` or `manager_agent` (validated at crew.py:L404)
- Manager cannot be in worker agent list (validated at crew.py:L417)

**Task Execution Model**:
- `Task.async_execution: bool` flag enables parallel execution (task.py:L70)
- Validation ensures max one async task at end of crew (crew.py:L463-479)
- ConditionalTask support with `check_conditional_skip` (crew.py:L40)

**Entry Points**:

| Method | Location | Type | Use Case |
|--------|----------|------|----------|
| `kickoff()` | crew.py:L676 | Sync | Primary entry point |
| `kickoff_async()` | crew.py:L764 | Thread-async | Legacy async support |
| `akickoff()` | crew.py:L834 | Native async | True async execution |
| `kickoff_for_each()` | crew.py:L737 | Sync batch | Multiple input sets |
| `kickoff_for_each_async()` | crew.py:L802 | Async batch | Async batch processing |
| `akickoff_for_each()` | crew.py:L881 | Native async batch | Native async batch |

### Agent Execution Loop

**Step Function**: `CrewAgentExecutor._invoke_loop()` (crew_agent_executor.py:L211)

**Loop Mechanics**:
```python
def _invoke_loop(self) -> AgentFinish:
    formatted_answer = None
    while not isinstance(formatted_answer, AgentFinish):  # Loop until finish
        # Check max iterations (crew_agent_executor.py:L220)
        if has_reached_max_iterations(self.iterations, self.max_iter):
            formatted_answer = handle_max_iterations_exceeded(...)
            break

        # Enforce rate limiting (crew_agent_executor.py:L231)
        enforce_rpm_limit(self.request_within_rpm_limit)

        # Get LLM response (crew_agent_executor.py:L233)
        answer = get_llm_response(llm=self.llm, messages=self.messages, ...)

        # Parse response (crew_agent_executor.py:L243)
        formatted_answer = process_llm_response(answer, self.use_stop_words)

        # Handle action if not finished (crew_agent_executor.py:L245)
        if isinstance(formatted_answer, AgentAction):
            # Execute tool, append observation to messages
```

**Termination Conditions**:
1. `AgentFinish` returned from LLM (final answer)
2. Max iterations exceeded (`max_iter`)
3. Exception raised

**State Accumulation**:
- Messages accumulated in `self.messages: list[LLMMessage]` (crew_agent_executor.py:L138)
- Iterations tracked in `self.iterations` (crew_agent_executor.py:L139)
- History persists across loop iterations

### Concurrency Mechanisms

**Async Task Execution**:
- `Task.async_execution = True` enables background execution
- Uses `concurrent.futures.Future` for task results (task.py:L3)
- Constraint: at most ONE async task at crew end (crew.py:L463-479)

**Batch Execution**:
- `kickoff_for_each()` - sequential execution of multiple inputs (crew.py:L737)
- `kickoff_for_each_async()` - concurrent execution with asyncio.gather pattern
- `run_for_each_async()` utility handles parallel crew execution (crew.py:L43)

**Parallel Execution** (crew.py:L800):
```python
async def kickoff_async(...):
    return await asyncio.to_thread(self.kickoff, inputs)
    # Runs sync kickoff in thread pool
```

**Rate Limiting**:
- `enforce_rpm_limit()` - blocks if RPM exceeded (crew_agent_executor.py:L231)
- `RPMController` shared across agents (crew.py:L446)
- Max RPM configurable per crew and per agent

### Event Architecture

**Event Bus**: Custom `crewai_event_bus` with OpenTelemetry integration

**Event Types**:
1. **Crew Events** (crew.py:L55-64):
   - `CrewKickoffCompletedEvent`
   - `CrewKickoffFailedEvent`
   - `CrewTrainStartedEvent`, `CrewTrainCompletedEvent`, `CrewTrainFailedEvent`
   - `CrewTestStartedEvent`, `CrewTestCompletedEvent`, `CrewTestFailedEvent`

2. **Task Events** (task.py:L35-39):
   - `TaskStartedEvent`
   - `TaskCompletedEvent`
   - `TaskFailedEvent`

3. **Agent Events** (crew_agent_executor.py:L22-25):
   - `AgentLogsStartedEvent`
   - `AgentLogsExecutionEvent`

4. **Memory Events** (short_term_memory.py:L9-16):
   - `MemorySaveStartedEvent`, `MemorySaveCompletedEvent`, `MemorySaveFailedEvent`
   - `MemoryQueryStartedEvent`, `MemoryQueryCompletedEvent`, `MemoryQueryFailedEvent`

5. **Knowledge Events** (agent/core.py:L38-42):
   - `KnowledgeQueryStartedEvent`
   - `KnowledgeQueryCompletedEvent`
   - `KnowledgeQueryFailedEvent`

**Event Emission Pattern**:
```python
crewai_event_bus.emit(
    self,  # Publisher
    CrewKickoffFailedEvent(error=str(e), crew_name=self.name)
)
```

**Observability**: OpenTelemetry baggage for distributed tracing (crew.py:L17-18, L705-708)
```python
from opentelemetry import baggage
from opentelemetry.context import attach, detach
```

### Streaming Support

**Architecture**: Generator-based with state management

**Implementation** (crew.py:L680-703):
```python
if self.stream:
    enable_agent_streaming(self.agents)
    ctx = StreamingContext()

    def run_crew() -> None:
        # Execute in background thread
        crew_result = self.kickoff(inputs=inputs)
        ctx.result_holder.append(crew_result)

    streaming_output = CrewStreamingOutput(
        sync_iterator=create_chunk_generator(ctx.state, run_crew, ctx.output_holder)
    )
    return streaming_output
```

**Pattern**:
- Background thread executes crew synchronously
- Generator yields chunks as they arrive
- Final result captured in `result_holder`

**Streaming Types** (crew.py:L84):
- `CrewStreamingOutput` - returns chunks + final result

## Implications for New Framework

**Adopt**:
1. **Multi-mode entry points** - sync, async, batch variants for flexibility
2. **Event bus architecture** - decouples execution from observability
3. **OpenTelemetry integration** - production-grade distributed tracing
4. **Process abstraction** (sequential vs hierarchical) - supports different coordination patterns
5. **RPM controller** - prevents API rate limit violations
6. **Streaming with background execution** - non-blocking UX for long-running tasks

**Avoid**:
1. **Thread-wrapped async** (`asyncio.to_thread`) - prefer native async throughout
2. **Sync-first design** - makes true async an afterthought
3. **While-not-done loops** - prefer explicit state machines for readability
4. **Max one async task constraint** - unnecessarily restrictive

**Improve**:
1. Design async-first, add sync wrappers (inverse of crewAI)
2. Use `asyncio.TaskGroup` for structured concurrency instead of manual Future management
3. Make concurrent task execution the default, not limited to last task
4. Separate execution engine from process logic (currently tightly coupled in Crew class)
5. Use typed events (Pydantic models) instead of loosely-typed dict payloads

## Code References

- Crew.kickoff: `lib/crewai/src/crewai/crew.py:L676`
- Sequential process: `lib/crewai/src/crewai/crew.py:L713`
- Hierarchical process: `lib/crewai/src/crewai/crew.py:L715`
- CrewAgentExecutor.invoke: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L165`
- Agent loop: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L211`
- Process enum: `lib/crewai/src/crewai/process.py:L4`
- Task async validation: `lib/crewai/src/crewai/crew.py:L463`
- Hierarchical manager validation: `lib/crewai/src/crewai/crew.py:L404`
- Event bus emissions: `lib/crewai/src/crewai/crew.py:L729`, `lib/crewai/src/crewai/crew_agent_executor.py`
- Streaming implementation: `lib/crewai/src/crewai/crew.py:L680`
- Rate limiting: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L231`

## Anti-Patterns Observed

1. **Sync-to-async wrapper anti-pattern**: `asyncio.to_thread(self.kickoff)` defeats purpose of async
2. **Tight coupling**: Process logic embedded directly in Crew class (no separate executor abstraction)
3. **Inconsistent async support**: Some methods have `_async` suffix, others have separate `akickoff`
4. **Arbitrary concurrency limits**: "At most one async task at end" is overly restrictive
5. **While-not-isinstance loops**: `while not isinstance(formatted_answer, AgentFinish)` - harder to reason about than explicit state machine
6. **Message list mutation**: `self.messages.append()` creates shared mutable state across iterations
7. **Thread-based streaming**: Uses background threads instead of async generators
