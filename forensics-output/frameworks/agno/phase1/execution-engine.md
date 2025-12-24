# Execution Engine Analysis: Agno

## Summary
- **Key Finding 1**: Dual sync/async execution model - 128 sync methods, 56 async methods in core Agent class
- **Key Finding 2**: Iterator-based streaming with distinct execute() and execute_stream() paths
- **Key Finding 3**: Workflow orchestration via loop constructs with early termination support
- **Classification**: Hybrid sync/async engine with manual coordination

## Async Model
- **Approach**: Native async/await with synchronous counterparts
- **Pattern**: Separate sync and async code paths (no sync-to-async wrappers observed)
- **Concurrency**: asyncio for I/O, concurrent.futures for background tasks
- **Event Loop**: Caller-managed (framework doesn't own event loop)

## Control Flow Topology
- **Architecture**: Multi-level orchestration
  - Workflow level: Sequential, parallel, conditional, loop, router steps
  - Agent level: ReAct-style reasoning with tool execution
  - Tool level: Individual function calls with error handling

## Detailed Analysis

### Execution Modes

The framework provides three execution modes:

1. **Synchronous Blocking** - `execute()` methods
2. **Asynchronous Blocking** - `aexecute()` methods (56 in agent.py)
3. **Streaming** - `execute_stream()` / `aexecute_stream()` methods with Iterator/AsyncIterator

**Evidence**: `libs/agno/agno/workflow/loop.py:130-143` shows synchronous execute signature:
```python
def execute(
    self,
    step_input: StepInput,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    workflow_run_response: Optional[WorkflowRunOutput] = None,
    # ...
) -> StepOutput:
```

**Evidence**: `libs/agno/agno/workflow/loop.py:230-248` shows streaming execute signature:
```python
def execute_stream(
    self,
    step_input: StepInput,
    # ...
) -> Iterator[Union[WorkflowRunOutputEvent, StepOutput]]:
```

### Loop-Based Workflow Orchestration

**Core Loop Pattern** (`workflow/loop.py:154-228`):
```python
while iteration < self.max_iterations:
    iteration_results: List[StepOutput] = []
    current_step_input = step_input
    loop_step_outputs = {}

    for i, step in enumerate(self.steps):
        step_output = step.execute(
            current_step_input,
            # ... context propagation
        )

        iteration_results.append(step_output)

        if step_output.stop:
            logger.info(f"Early termination requested")
            break

        # Chain outputs to next step
        current_step_input = self._update_step_input_from_outputs(
            current_step_input, step_output, loop_step_outputs
        )

    all_results.append(iteration_results)
    iteration += 1

    # User-defined termination condition
    if self.end_condition and callable(self.end_condition):
        should_break = self.end_condition(iteration_results)
        if should_break:
            break
```

**Key Patterns**:
- Max iteration limit (default 3)
- Early termination via `step_output.stop` flag
- Custom end conditions via callable
- Step output chaining - each step's output becomes next step's input
- Flattened results across iterations

### Agent Execution Flow

**Run Orchestration** (`agent/agent.py:1000-1099`):
```
1. Register run for cancellation tracking
2. Retry loop (configurable attempts)
3. Execute pre-hooks
4. Determine tools for model
5. Prepare run messages (context assembly)
6. Start background memory creation (concurrent.futures.Future)
7. Start background cultural knowledge creation
8. Cancellation check
9. Reasoning phase (if enabled)
10. Cancellation check
11. Generate model response (with tool execution)
```

**Cancellation Points**: The framework checks for cancellation at strategic points (lines 1081, 1087) using `raise_if_cancelled()`.

**Background Task Pattern**: Memory and cultural knowledge creation run in background threads via `Future` objects (lines 1069-1079), allowing overlap with main execution.

### Retry Logic

**Pattern** (`agent/agent.py:1006-1011`):
```python
num_attempts = self.retries + 1
for attempt in range(num_attempts):
    if num_attempts > 1:
        log_debug(f"Retrying Agent run. Attempt {attempt + 1} of {num_attempts}")
    try:
        # Execute run
```

Simple retry without backoff or jitter - retries happen immediately.

### Streaming Architecture

**Iterator Pattern**: Streaming methods yield events incrementally rather than blocking until complete.

**Event Types** (from imports in `loop.py:10-17`):
- `LoopExecutionStartedEvent`
- `LoopIterationStartedEvent`
- `LoopIterationCompletedEvent`
- `LoopExecutionCompletedEvent`
- `WorkflowRunOutputEvent`

This allows real-time progress monitoring and incremental UI updates.

### Step Type Polymorphism

**Evidence** (`workflow/loop.py:64-87`):
```python
def _prepare_steps(self):
    prepared_steps: WorkflowSteps = []
    for step in self.steps:
        if callable(step) and hasattr(step, "__name__"):
            prepared_steps.append(Step(name=step.__name__, executor=step))
        elif isinstance(step, Agent):
            prepared_steps.append(Step(agent=step))
        elif isinstance(step, Team):
            prepared_steps.append(Step(team=step))
        elif isinstance(step, (Step, Steps, Loop, Parallel, Condition, Router)):
            prepared_steps.append(step)
        else:
            raise ValueError(f"Invalid step type: {type(step).__name__}")
```

**Flexibility**: Steps can be:
- Raw callables (functions)
- Agent instances
- Team instances
- Structured step objects (Step, Loop, Parallel, Condition, Router)

All are normalized to a common Step interface.

## Implications for New Framework

1. **Dual sync/async is expensive** - Maintaining 184 methods (128 sync + 56 async) creates duplication burden; consider async-only with sync wrappers
2. **Iterator-based streaming is elegant** - Event-driven progress reporting is good for UX
3. **Loop abstraction works well** - Max iterations + early termination + custom end conditions cover most use cases
4. **Background futures for I/O** - Memory creation while model runs is smart parallelization
5. **Cancellation points are essential** - Strategic cancellation checks prevent resource waste
6. **Step polymorphism** - Accepting callables, agents, teams as "steps" improves DX

## Anti-Patterns Observed

1. **No retry backoff** - Immediate retries can overwhelm failing services
2. **Silent end condition failures** - `except Exception: logger.warning()` in line 210-212 continues loop on predicate failure
3. **Dual code paths** - Sync and async implementations likely have drift risk
4. **No circuit breaker** - Retry logic doesn't prevent cascading failures
5. **Mutable state chaining** - `_update_step_input_from_outputs` modifies step_input in place (mutation risk)

## Code References
- `libs/agno/agno/workflow/loop.py:130` - Synchronous execute method
- `libs/agno/agno/workflow/loop.py:154-228` - Loop orchestration logic
- `libs/agno/agno/workflow/loop.py:230` - Streaming execute method
- `libs/agno/agno/workflow/loop.py:64-87` - Step polymorphism preparation
- `libs/agno/agno/agent/agent.py:1000-1099` - Agent run orchestration with retry
- `libs/agno/agno/agent/agent.py:1069-1079` - Background memory creation pattern
- `libs/agno/agno/agent/agent.py:1081,1087` - Cancellation checkpoints
