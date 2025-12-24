## Multi-Agent Analysis: LangGraph

### Coordination Model
- **Type**: Flexible (supports Supervisor, P2P, Pipeline, all patterns)
- **Central Control**: User-defined
- **Location**: User-implemented via graph structure

### Core Insight

LangGraph is **not opinionated** about multi-agent coordination. It's a **general graph orchestrator** that enables any pattern:

1. **Supervisor**: Create central routing node
2. **Peer-to-Peer**: Agents route to each other via conditional edges
3. **Pipeline**: Sequential edges between agent nodes
4. **Hybrid**: Mix patterns in same graph

**Key**: Each "agent" is a **node** (or **subgraph**) in the larger graph.

### Multi-Agent Patterns

**Pattern 1: Supervisor (Router)**

```python
from langgraph.graph import StateGraph, MessagesState, START, END

class State(MessagesState):
    next_agent: str

# Define specialist agents
def research_agent(state: State):
    # Specialized for research tasks
    return {"messages": [research_llm.invoke(state["messages"])]}

def code_agent(state: State):
    # Specialized for coding tasks
    return {"messages": [code_llm.invoke(state["messages"])]}

def writer_agent(state: State):
    # Specialized for writing tasks
    return {"messages": [writer_llm.invoke(state["messages"])]}

# Supervisor routes to specialists
def supervisor(state: State):
    # Decide which specialist to use
    response = supervisor_llm.invoke([
        SystemMessage("Route to: research_agent, code_agent, or writer_agent"),
        *state["messages"]
    ])
    return {"next_agent": response.content}

# Build graph
builder = StateGraph(State)
builder.add_node("supervisor", supervisor)
builder.add_node("research_agent", research_agent)
builder.add_node("code_agent", code_agent)
builder.add_node("writer_agent", writer_agent)

# Routing logic
def route(state: State) -> str:
    if state["next_agent"] == "FINISH":
        return END
    return state["next_agent"]

builder.add_edge(START, "supervisor")
builder.add_conditional_edges("supervisor", route)
builder.add_edge("research_agent", "supervisor")  # Loop back
builder.add_edge("code_agent", "supervisor")
builder.add_edge("writer_agent", "supervisor")

graph = builder.compile()
```

**Characteristics**:
- Central control point (supervisor node)
- Explicit routing logic
- Loop back to supervisor after each specialist

**Pattern 2: Peer-to-Peer (Agent Mesh)**

```python
class State(MessagesState):
    pass

def agent_a(state: State) -> Command:
    response = llm_a.invoke(state["messages"])

    # Decide who to delegate to
    if needs_specialist_b(response):
        return Command(goto="agent_b", update={"messages": [response]})
    elif needs_specialist_c(response):
        return Command(goto="agent_c", update={"messages": [response]})
    else:
        return Command(goto=END, update={"messages": [response]})

def agent_b(state: State) -> Command:
    response = llm_b.invoke(state["messages"])
    return Command(goto="agent_c", update={"messages": [response]})  # Delegate to C

def agent_c(state: State) -> Command:
    response = llm_c.invoke(state["messages"])
    return Command(goto=END, update={"messages": [response]})  # Finish

builder = StateGraph(State)
builder.add_node("agent_a", agent_a)
builder.add_node("agent_b", agent_b)
builder.add_node("agent_c", agent_c)
builder.add_edge(START, "agent_a")
# No explicit edges - agents route themselves via Command

graph = builder.compile()
```

**Characteristics**:
- Decentralized (each agent decides next step)
- Uses `Command` object for routing
- No supervisor

**Pattern 3: Pipeline (Sequential)**

```python
builder = StateGraph(MessagesState)
builder.add_node("planner", planner_agent)
builder.add_node("executor", executor_agent)
builder.add_node("reviewer", reviewer_agent)

builder.add_edge(START, "planner")
builder.add_edge("planner", "executor")
builder.add_edge("executor", "reviewer")
builder.add_edge("reviewer", END)

graph = builder.compile()
```

**Characteristics**:
- Linear flow
- Clear stages
- No branching

**Pattern 4: Hierarchical (Nested Subgraphs)**

```python
# Inner team (subgraph)
inner_team = StateGraph(State)
inner_team.add_node("specialist_a", specialist_a)
inner_team.add_node("specialist_b", specialist_b)
# ... define inner team structure
compiled_inner = inner_team.compile()

# Outer supervisor
outer = StateGraph(State)
outer.add_node("supervisor", supervisor_node)
outer.add_node("team_1", compiled_inner)  # Subgraph as node
outer.add_node("team_2", other_team_graph)

# Supervisor routes to teams
outer.add_conditional_edges("supervisor", route_to_team)

graph = outer.compile()
```

**Characteristics**:
- Nested graphs (teams within teams)
- Each subgraph is a black box to parent
- State flows through subgraphs

### Agent Inventory

In LangGraph, **agents are just nodes**. Example:

| Agent | Role | Can Delegate To |
|-------|------|-----------------|
| supervisor | Routing | All specialists |
| research_agent | Web research | Back to supervisor |
| code_agent | Code generation | Back to supervisor |
| writer_agent | Content writing | Back to supervisor |

**No special "agent" class** - all are nodes in graph.

### Handoff Mechanism
- **Type**: Explicit (via edges or Command objects)
- **Bidirectional**: Yes (if graph topology allows)
- **Context Preserved**: Full (entire state passed)

**Handoff via conditional edges**:
```python
def route(state: State) -> str:
    return state["next_agent"]  # Supervisor decides

builder.add_conditional_edges("supervisor", route)
```

**Handoff via Command**:
```python
def agent_node(state: State) -> Command:
    return Command(
        goto="next_agent",
        update={"messages": [...]}
    )
```

**Context**: Entire `state` dict passed to next node.

### State Sharing
- **Pattern**: Blackboard (shared global state)
- **Shared State**: All channels in state schema
- **Isolation Level**: None (all agents see same state)

**State structure**:
```python
class State(MessagesState):
    messages: Annotated[list, add_messages]  # Shared message history
    next_agent: str                          # Routing decision
    research_results: dict                   # Specialist output
```

**All agents read/write same state**. Isolation only via:
1. **Channel selection**: Nodes can read subset of channels
2. **Subgraphs**: Subgraph state isolated (unless explicitly shared)

**Example: Isolated subgraph state**
```python
class OuterState(TypedDict):
    messages: list

class InnerState(TypedDict):
    inner_messages: list
    temp_data: dict  # Not visible to outer graph

# Inner graph uses InnerState
inner = StateGraph(InnerState)
# ... build inner graph
compiled_inner = inner.compile()

# Outer graph uses OuterState
outer = StateGraph(OuterState)
outer.add_node("inner_team", compiled_inner)
```

**State mapping** between graphs handled automatically if schemas overlap.

### Communication Protocol
- **Method**: Direct (node invocation)
- **Async**: Yes (if using async API)
- **Location**: Pregel execution engine

**No explicit message passing** - state updates are the communication:
1. Agent A writes to state
2. Framework applies writes atomically
3. Agent B reads updated state

**Temporal isolation** (BSP model):
- Agents in **same step** see **previous step's** state
- Agents in **next step** see **current step's** state

### Loop Prevention
- **Mechanism**: Recursion limit (max steps)
- **Max Handoffs**: Configurable (default 25)

**Configuration**:
```python
graph.invoke(input, config={"recursion_limit": 50})
```

**User-level loop detection**:
```python
from typing import Annotated

def detect_loop(history: list, current: str) -> bool:
    return history.count(current) > 2

class State(TypedDict):
    visited_agents: Annotated[list, lambda x, y: x + [y]]
    current_agent: str

def supervisor(state: State) -> Command:
    next_agent = decide_next_agent(state)

    if detect_loop(state["visited_agents"], next_agent):
        return Command(goto=END)  # Break loop

    return Command(
        goto=next_agent,
        update={"visited_agents": [next_agent], "current_agent": next_agent}
    )
```

### Dynamic Parallelism (Send)

LangGraph supports **dynamic fan-out** via `Send`:

```python
from langgraph.types import Send

def supervisor(state: State) -> list[Send]:
    # Dynamically invoke multiple agents in parallel
    tasks = state["tasks"]
    return [Send("worker_agent", {"task": task}) for task in tasks]

builder.add_node("supervisor", supervisor)
builder.add_node("worker_agent", worker_agent)
builder.add_conditional_edges("supervisor", supervisor)
```

**Use case**: Map-reduce pattern (e.g., research multiple topics, then summarize).

### Subgraph Communication

**Parent → Child**:
- State passed to subgraph at invocation
- Subgraph input schema defines what it receives

**Child → Parent**:
- Subgraph returns updates
- Updates applied to parent state

**Example**:
```python
class ParentState(TypedDict):
    messages: list
    result: str

class ChildState(TypedDict):
    messages: list  # Overlapping field

# Child graph
child = StateGraph(ChildState)
# ... build child
child_compiled = child.compile()

# Parent graph
parent = StateGraph(ParentState)
parent.add_node("child_team", child_compiled)

# Invocation:
# 1. Parent passes state with "messages"
# 2. Child receives {"messages": [...]}
# 3. Child returns {"messages": [...updated]}
# 4. Parent receives update, merges into ParentState
```

**State mapping**: Automatic for overlapping keys.

### Checkpointing and Multi-Agent

**Each agent's execution is checkpointed**:
- After each step, state saved
- Includes which agent(s) ran
- Enables resume after crash

**Subgraph checkpointing**:
- Parent checkpointer inherited by default
- Or override with `child.compile(checkpointer=False)` to disable

### Real-World Example: Multi-Agent Collaboration

From LangGraph docs/examples:

```python
# Research team: coordinator + researchers
def create_research_team():
    class State(MessagesState):
        team_members: list[str]
        current_researcher: str

    def coordinator(state: State):
        # Assign research topics to team members
        response = llm.invoke("Assign topics to: " + str(state["team_members"]))
        return {"current_researcher": response.content}

    def researcher(state: State):
        # Individual researcher does work
        topic = state["messages"][-1].content
        research = llm.invoke(f"Research {topic}")
        return {"messages": [research]}

    builder = StateGraph(State)
    builder.add_node("coordinator", coordinator)
    builder.add_node("researcher_1", researcher)
    builder.add_node("researcher_2", researcher)
    builder.add_node("researcher_3", researcher)

    def route(state: State) -> str:
        return state["current_researcher"]

    builder.add_conditional_edges("coordinator", route)
    builder.add_edge("researcher_1", "coordinator")
    builder.add_edge("researcher_2", "coordinator")
    builder.add_edge("researcher_3", "coordinator")

    return builder.compile()
```

### Agent Specialization Patterns

**By model**:
```python
research_llm = ChatOpenAI(model="gpt-4-turbo", temperature=0.3)
creative_llm = ChatOpenAI(model="gpt-4", temperature=0.9)

def research_agent(state): return {"messages": [research_llm.invoke(state["messages"])]}
def creative_agent(state): return {"messages": [creative_llm.invoke(state["messages"])]}
```

**By tools**:
```python
research_tools = [web_search, wikipedia]
code_tools = [python_repl, file_system]

research_agent = create_react_agent(llm, tools=research_tools)
code_agent = create_react_agent(llm, tools=code_tools)
```

**By prompt**:
```python
def research_agent(state):
    messages = [SystemMessage("You are a research specialist.")] + state["messages"]
    return {"messages": [llm.invoke(messages)]}

def writer_agent(state):
    messages = [SystemMessage("You are a writing specialist.")] + state["messages"]
    return {"messages": [llm.invoke(messages)]}
```

### No Built-In Agent Abstraction

LangGraph does **not** provide:
- `Agent` base class
- Agent registry
- Agent lifecycle management
- Agent discovery

**Rationale**: Agents are just nodes. Use graph APIs directly.

**Third-party**: `langgraph.prebuilt` provides `create_react_agent()`, but it returns a **compiled graph**, not an "agent object".

### Recommendations

**Strengths**:
- Flexible: supports any coordination pattern
- Shared state (blackboard) is simple
- Subgraphs enable hierarchical teams
- Send enables dynamic parallelism
- Checkpointing works with multi-agent

**Weaknesses**:
- No built-in agent abstraction (user implements)
- No isolation (all agents see same state by default)
- No message queue pattern (synchronous steps)
- Loop detection is user responsibility

**Best practices to adopt**:
1. **Graph-based multi-agent**: Agents as nodes, not classes
2. **Shared state blackboard**: Simple, effective for small teams
3. **Subgraph isolation**: For large teams, nest graphs
4. **Command pattern**: Agents return routing decisions
5. **Conditional edges**: Declarative routing
6. **Send for parallelism**: Dynamic fan-out within step
7. **Recursion limit**: Prevent infinite delegation loops

**For new framework**:
- Consider **optional isolation** (per-agent state + shared state)
- Provide **agent templates** (supervisor, worker, etc.)
- Support **async message passing** (queue-based) as option
- Keep **graph-based approach** (very flexible)
- Add **loop detection helpers** (track visited agents)
- Provide **team abstractions** (supervisor + N workers)
