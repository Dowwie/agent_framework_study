## Control Loop Extraction: LangGraph

### Reasoning Topology
- **Pattern**: Framework-agnostic (supports all patterns)
- **Location**: `libs/langgraph/langgraph/pregel/main.py:324-400` (Pregel class)
- **Design**: LangGraph is **not opinionated** about reasoning patterns - it's a general graph orchestrator

### Core Insight

LangGraph itself doesn't impose a reasoning pattern. It's a **graph execution engine** that users can configure to implement any pattern:
- **ReAct**: Build a graph with LLM → tool-calling → observation loop
- **Plan-and-Solve**: Build a graph with planning node → execution nodes
- **Reflection**: Build a graph with action → critique → adjust cycle
- **Custom**: Any DAG-based workflow

### Step Function (Pregel Loop)

The "step function" is the **Pregel algorithm** implementation (BSP model):

**Location**: `libs/langgraph/langgraph/pregel/_loop.py:140-200`

```python
class PregelLoop:
    status: Literal[
        "input",           # Initial state, waiting for input
        "pending",         # Tasks executing
        "done",            # Execution complete
        "interrupt_before", # Pre-node interrupt
        "interrupt_after",  # Post-node interrupt
        "out_of_steps",    # Max steps reached
    ]
```

**Execution phases** (from `pregel/main.py` docstring):

1. **Plan**: Select nodes to execute
   - First step: nodes triggered by START channel
   - Subsequent steps: nodes triggered by updated channels from previous step
   - Code: `prepare_next_tasks()` in `pregel/_algo.py`

2. **Execute**: Run selected nodes in parallel
   - All nodes execute simultaneously
   - Reads see previous step's state
   - Writes buffered (invisible to other nodes)
   - Code: `BackgroundExecutor` / `AsyncBackgroundExecutor` in `pregel/_executor.py`

3. **Update**: Apply buffered writes atomically
   - All writes become visible at once
   - Triggers next step's planning
   - Code: `apply_writes()` in `pregel/_algo.py:217-300`

### Loop Mechanics

**Input Assembly**: Channel-based
```python
# From _read.py PregelNode
def invoke(self, input: Any, config: RunnableConfig) -> Any:
    # 1. Read from channels (state)
    values = read_channels(channels, self.channels)

    # 2. Apply mapper (coerce to schema if needed)
    if self.mapper:
        input = self.mapper(values)

    # 3. Pass to node function
    return self.bound.invoke(input, config)
```

**LLM Call**: User-defined (in node function)
- LangGraph doesn't call LLMs directly
- User nodes typically wrap LangChain Runnables or call LLMs

**Parser**: User-defined (in node function)
- Node returns `dict` or structured output
- Framework validates against output schema if provided

**Dispatch Logic**: Channel writes
```python
# Node returns dict updates
def my_node(state: State) -> dict:
    return {"next_step": "tool_call", "tool_args": {...}}

# Or Command object for dynamic routing
def my_node(state: State) -> Command:
    return Command(goto="next_node", update={"key": "value"})
```

### Termination Conditions

LangGraph has **multiple termination conditions** (all checked):

1. **Max steps reached** (`recursion_limit`)
   - Location: Loop iteration counter
   - Default: 25 steps
   - Configurable: `graph.compile()` or per-invocation config
   - Risk: Medium (may truncate valid workflows)

2. **No more tasks**
   - Location: `prepare_next_tasks()` returns empty list
   - Trigger: No nodes triggered by channel updates
   - Risk: Low (clean termination)

3. **Explicit END**
   - Location: Node routes to `END` constant
   - Implementation: Special channel that triggers loop exit
   - Risk: Low (intentional)

4. **Interrupt**
   - Location: `interrupt_before` / `interrupt_after` nodes
   - Implementation: `should_interrupt()` in `pregel/_algo.py:140-170`
   - Behavior: Pause execution, save checkpoint
   - Risk: None (controlled pause, resumable)

5. **Unhandled Error**
   - Location: Task execution exception
   - Behavior: Captured in `PregelTask.error`, stops execution
   - Risk: Medium (may exit on recoverable errors if no retry)

6. **Out of steps** (status = "out_of_steps")
   - Same as max steps, but flagged explicitly
   - Available in state snapshot for inspection

### Loop Detection
- **Method**: None at framework level
- **Implementation**: User responsibility
- **Recommendation**: Use `recursion_limit` as backstop

**User-level loop detection example**:
```python
from typing import Annotated
from typing_extensions import TypedDict

def detect_loops(history: list, state: dict) -> bool:
    # User-defined heuristic
    state_hash = hash(frozenset(state.items()))
    return state_hash in {hash(frozenset(h.items())) for h in history}

class State(TypedDict):
    history: Annotated[list, lambda x, y: x + [y]]
    current: dict

def my_node(state: State) -> dict | Command:
    if detect_loops(state["history"], state["current"]):
        return Command(goto=END)  # Exit on loop
    # ... normal processing
```

### Prebuilt Agent Patterns

The `libs/prebuilt` library provides **opinionated agent implementations**:

**ReAct Agent** (`libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py`):
```python
def create_react_agent(model, tools, ...):
    """Creates a ReAct-style agent graph"""
    # Node 1: Call LLM with tools
    # Node 2: Execute tools
    # Conditional edge: LLM output has tool calls?
    #   Yes → execute tools → loop back to LLM
    #   No → END
```

**Step-by-step**:
1. LLM invoked with message history and tool schemas
2. If LLM returns tool calls → execute tools → add results to messages → loop
3. If LLM returns final answer → END

**Termination**: LLM chooses not to call tools (implicit finish).

### Conditional Edges (Routing Logic)

**Mechanism** (from `state.py:628-676`):
```python
def add_conditional_edges(
    self,
    source: str,
    path: Callable,  # Routing function
    path_map: dict | None = None,  # Target mapping
):
    """Add dynamic routing from source node"""
    # `path` is a function that returns target node name(s)
    # Can return single target or list of targets (parallel)
```

**Example**:
```python
def route(state: State) -> str:
    if state["needs_tool"]:
        return "tool_executor"
    else:
        return END

builder.add_conditional_edges("llm", route)
```

**Dynamic parallelism via Send**:
```python
def fan_out(state: State) -> list[Send]:
    return [Send("process", {"item": item}) for item in state["items"]]

builder.add_conditional_edges("split", fan_out)
```

### Control Flow Primitives

LangGraph provides:
1. **Linear edges**: `add_edge(source, target)`
2. **Conditional edges**: `add_conditional_edges(source, path_func)`
3. **Parallel edges**: `add_edge([source1, source2], target)` (wait for all)
4. **Dynamic Send**: Runtime fan-out to same node with different inputs
5. **Command object**: Node returns routing decision + state update

### No Built-In Scratchpad

LangGraph **does not provide** a scratchpad abstraction. Instead:
- **Messages**: Use `MessagesState` with `add_messages` reducer
- **Custom state fields**: Add any field to state schema
- **Managed values**: Special lifecycle-managed values (e.g., `is_last_step`)

**Scratchpad pattern** (user implementation):
```python
class State(TypedDict):
    messages: Annotated[list, add_messages]
    scratchpad: Annotated[list, lambda x, y: x + [y]]  # Append-only

def thinking_node(state: State) -> dict:
    thought = llm.invoke("Think about: ...")
    return {"scratchpad": thought}
```

### Comparison to Traditional Agent Loops

**Traditional loop**:
```python
while not done:
    action = llm.invoke(prompt)
    if action.type == "tool":
        result = execute_tool(action.tool, action.args)
        prompt += result
    else:
        return action.answer
```

**LangGraph equivalent**:
- **Loop**: Pregel step iteration
- **Condition**: Conditional edge from LLM node
- **State**: Shared channels (e.g., messages list)
- **Termination**: Route to END or hit recursion_limit

**Advantages**:
- Checkpointing: Pause/resume at any step
- Observability: Stream updates, debug mode
- Composability: Nodes can be subgraphs
- Parallelism: Execute independent nodes simultaneously

### Recommendations

**Strengths**:
- Framework-agnostic: supports any reasoning pattern
- Explicit termination conditions (multiple safety nets)
- Checkpointing enables pause/resume
- BSP model ensures determinism
- Recursion limit prevents infinite loops

**Weaknesses**:
- No built-in loop detection (user responsibility)
- No scratchpad abstraction (must build yourself)
- Step-based execution can be verbose for simple loops

**Best practices to adopt**:
1. Multi-condition termination (max steps, explicit END, interrupts)
2. Channel-based state management (avoids global variables)
3. Conditional edges for routing logic (declarative over imperative)
4. Command pattern for dynamic control flow
5. Checkpointing for long-running workflows
6. Prebuilt patterns for common use cases (ReAct, etc.)
