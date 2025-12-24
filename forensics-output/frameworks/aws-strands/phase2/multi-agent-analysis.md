# Multi-Agent Analysis: AWS Strands

## Summary
- **Key Finding 1**: Two multi-agent patterns - Graph (deterministic DAG) and Swarm (dynamic handoffs)
- **Key Finding 2**: Nested composition support (multi-agent systems as graph nodes)
- **Classification**: Hybrid orchestration with graph-based and swarm-based coordination

## Detailed Analysis

### Multi-Agent Patterns

#### Pattern 1: Graph (Directed Acyclic Graph)

**Location**: `src/strands/multiagent/graph.py`

**Model**: Deterministic dependency-based execution

**Structure**:
```python
graph = Graph()
graph.add_node("researcher", agent=researcher_agent)
graph.add_node("analyzer", agent=analyzer_agent)
graph.add_node("reporter", agent=reporter_agent)

graph.add_edge("researcher", "analyzer")  # researcher -> analyzer
graph.add_edge("analyzer", "reporter")    # analyzer -> reporter
graph.set_entry_point("researcher")

result = await graph.invoke_async("Research topic X")
```

**Characteristics**:
- Nodes: Agent instances or nested MultiAgentBase (Swarm, Graph)
- Edges: Directional dependencies with optional conditions
- Execution: Topological sort + async execution
- Output propagation: Previous node output → next node input
- Cyclic support: Yes (with max_node_executions limit)
- Parallel execution: Independent nodes run concurrently

**State**:
```python
@dataclass
class GraphState:
    task: MultiAgentInput  # Original input
    status: Status  # PENDING | EXECUTING | COMPLETED | FAILED | INTERRUPTED
    completed_nodes: set[GraphNode]
    failed_nodes: set[GraphNode]
    execution_order: list[GraphNode]
    results: dict[str, NodeResult]
    accumulated_usage: Usage
    accumulated_metrics: Metrics
```

#### Pattern 2: Swarm (Dynamic Handoffs)

**Location**: `src/strands/multiagent/swarm.py` (inferred from structure)

**Model**: Agent-driven handoff decisions

**Characteristics** (inferred):
- Agents decide next agent dynamically
- Handoffs via special tool or return value
- No predefined graph structure
- More flexible than Graph
- Less predictable execution path

### Coordination Models

#### Graph Execution Algorithm

**Initialization**:
1. Identify entry points (nodes with no dependencies or explicit start)
2. Build dependency graph
3. Validate acyclic (if cyclic, set max_node_executions)

**Execution Loop**:
```python
while should_continue():
    ready_nodes = find_ready_nodes(graph_state)  # All deps completed

    # Parallel execution of independent nodes
    tasks = [execute_node(node) for node in ready_nodes]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Update state
    for node, result in zip(ready_nodes, results):
        graph_state.results[node.id] = result
        graph_state.completed_nodes.add(node)

    # Check termination
    if all_nodes_complete() or max_executions_reached():
        break
```

**Termination Conditions**:
1. All nodes completed
2. `max_node_executions` reached (prevents infinite loops)
3. `execution_timeout` exceeded
4. Node failure (optional continue_on_error flag)

#### Edge Conditions

**Conditional Traversal**:
```python
GraphEdge(
    from_node=researcher,
    to_node=analyzer,
    condition=lambda state: "findings" in state.results["researcher"]
)
```

**Use Cases**:
- Conditional branching
- Error recovery paths
- Dynamic routing based on results

#### State Sharing

**Cross-Node Communication**:
1. **Explicit**: Output of node A → input of node B (via edge)
2. **Shared State**: GraphState accessible to all nodes
3. **Accumulated Metrics**: Rolled up across all nodes

**No shared memory** between agents:
- Each agent has isolated messages/state
- Communication only via explicit inputs/outputs
- No pub/sub or message broker

### Nested Composition

#### MultiAgentBase Abstraction

**Location**: `src/strands/multiagent/base.py:L126`

**Interface** (inferred):
```python
class MultiAgentBase(ABC):
    @abstractmethod
    async def invoke_async(
        self, input: MultiAgentInput, **kwargs
    ) -> AsyncIterator[TypedEvent]:
        pass
```

**Implementations**:
- Graph
- Swarm
- (Future patterns)

#### Nested Graph Example

```python
# Inner graph
research_graph = Graph()
research_graph.add_node("search", search_agent)
research_graph.add_node("validate", validate_agent)
research_graph.add_edge("search", "validate")

# Outer graph (research_graph as a node)
workflow = Graph()
workflow.add_node("research", research_graph)  # Nested!
workflow.add_node("report", report_agent)
workflow.add_edge("research", "report")
```

**Characteristics**:
- Nested results flattened in MultiAgentResult
- Metrics accumulated across all levels
- Execution traced with parent-child spans

### Result Aggregation

#### NodeResult (base.py:L42)

```python
@dataclass
class NodeResult:
    result: Union[AgentResult, MultiAgentResult, Exception]
    execution_time: int
    status: Status
    accumulated_usage: Usage  # Tokens consumed
    accumulated_metrics: Metrics  # Latency
    execution_count: int
    interrupts: list[Interrupt]
```

**Flattening**:
```python
def get_agent_results(self) -> list[AgentResult]:
    if isinstance(self.result, AgentResult):
        return [self.result]
    elif isinstance(self.result, MultiAgentResult):
        # Recursively flatten nested results
        return flatten([nr.get_agent_results() for nr in self.result.results.values()])
```

#### MultiAgentResult (base.py:L127)

```python
@dataclass
class MultiAgentResult:
    status: Status
    results: dict[str, NodeResult]  # Keyed by node ID
    accumulated_usage: Usage
    accumulated_metrics: Metrics
    execution_count: int
    execution_time: int
    interrupts: list[Interrupt]
```

### Event Streaming

#### Multi-Agent Events

**Types** (types/_events.py):
- MultiAgentNodeStartEvent - Node begins execution
- MultiAgentNodeStreamEvent - Streaming output from node
- MultiAgentNodeStopEvent - Node completes
- MultiAgentNodeCancelEvent - Node canceled
- MultiAgentHandoffEvent - Agent hands off to another
- MultiAgentResultEvent - Final result

**Usage**:
```python
async for event in graph.invoke_async(input):
    match event:
        case MultiAgentNodeStartEvent():
            print(f"Starting {event.node_id}")
        case MultiAgentNodeStreamEvent():
            print(event.content)
        case MultiAgentResultEvent():
            final = event.result
```

### Interrupt Handling

#### Node-Level Interrupts

**Propagation**:
1. Agent in node raises interrupt
2. Node execution pauses
3. MultiAgentResult.interrupts accumulates interrupt
4. MultiAgentBase yields interrupt event
5. User resolves interrupt
6. Graph resumes from interrupted node

**State Preservation**:
- GraphState includes `results` dict
- Interrupted node state saved
- Resume via `resume_async(interrupt_response)`

### Hook System Integration

#### Multi-Agent Hooks (experimental/hooks/multiagent)

**Events**:
- MultiAgentInitializedEvent
- BeforeMultiAgentInvocationEvent / AfterMultiAgentInvocationEvent
- BeforeNodeCallEvent / AfterNodeCallEvent

**Usage**:
```python
class GraphLogger(HookProvider):
    def register_hooks(self, registry: HookRegistry):
        registry.add_callback(BeforeNodeCallEvent, self.log_node)

graph = Graph(hooks=[GraphLogger()])
```

### Failure Handling

#### Node Failure Strategies

**Options**:
1. **Fail Fast** (default): Graph stops on first node failure
2. **Continue on Error**: Graph continues, failed node skipped
3. **Retry**: Node retries N times before failing

**Error Propagation**:
```python
NodeResult(
    result=Exception("Node failed"),
    status=Status.FAILED,
)
```

**Downstream Impact**:
- Dependent nodes cannot execute (missing input)
- Graph status = FAILED
- Partial results available in GraphState

### Session Persistence

#### Multi-Agent State Serialization

**Support** (base.py:L71-L89):
```python
def to_dict(self) -> dict[str, Any]:
    return {
        "type": "multiagent_result",
        "status": self.status.value,
        "results": {k: v.to_dict() for k, v in self.results.items()},
        "accumulated_usage": self.accumulated_usage,
        # ...
    }

@classmethod
def from_dict(cls, data: dict) -> MultiAgentResult:
    # Rehydrate from JSON
```

**Use Case**: Pause/resume long-running graphs

### Resource Management

#### Concurrency Limits

**No built-in limits observed**:
- All ready nodes execute concurrently
- Could overwhelm system with wide graph
- No semaphore or rate limiting

**Workaround**: Use edge conditions to serialize

#### Timeout Management

**Graph-Level**:
- `execution_timeout` parameter
- Cancels all running nodes on timeout

**Node-Level**:
- Agent's own timeout handling
- No per-node timeout configuration

## Code References
- `src/strands/multiagent/base.py:42-124` - NodeResult and MultiAgentResult
- `src/strands/multiagent/graph.py:59-116` - GraphState structure
- `src/strands/multiagent/graph.py:131-147` - GraphEdge with conditions
- `src/strands/types/multiagent.py:8` - MultiAgentInput type alias
- `src/strands/types/_events.py` - Multi-agent event types

## Implications for New Framework
- **Adopt**: Graph pattern for deterministic workflows
- **Adopt**: Nested composition (multi-agent as nodes)
- **Adopt**: Accumulated metrics across all nodes
- **Adopt**: Conditional edges for dynamic routing
- **Adopt**: Event streaming for progress visibility
- **Reconsider**: Add concurrency limits (max parallel nodes)
- **Reconsider**: Add per-node timeout configuration
- **Reconsider**: Add circuit breaker for repeated node failures
- **Add**: Supervisor pattern (central coordinator)
- **Add**: Pub/sub for async communication

## Anti-Patterns Observed
- **Unbounded Parallelism**: All ready nodes execute concurrently (no max_concurrency)
- **No Resource Limits**: No memory/CPU limits per node
- **Flat Error Handling**: Node failures are exceptions (no structured error codes)
- **No Supervisor**: No central coordinator for cross-agent decisions
- **State Mutation**: GraphState mutated in-place (not immutable)
