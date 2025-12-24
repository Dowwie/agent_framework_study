## Component Model Analysis: LangGraph

### Abstraction Assessment

| Component | Base Class | Depth | Type |
|-----------|-----------|-------|------|
| Graph | Pregel | 1 level | Mixed (Pregel is runtime, StateGraph is builder) |
| Node | PregelNode | 0 levels | Thin (dataclass wrapper) |
| Channel | BaseChannel | 1 level | Protocol + concrete implementations |
| Checkpointer | BaseCheckpointSaver | 1-2 levels | Thin protocol |
| Store | BaseStore | 1 level | Thin protocol |
| Cache | BaseCache | 1 level | Thin protocol |

### Dependency Injection
- **Primary Pattern**: Constructor Injection + Builder Pattern
- **Testability**: Easy (nodes are pure functions, channels are injectable)
- **Configuration**: Code-first with optional schema-driven node inputs

### Graph Builder Pattern

LangGraph uses a **two-stage builder pattern**:

**Stage 1: Graph Construction** (`StateGraph`):
```python
from langgraph.graph import StateGraph, START, END

builder = StateGraph(State)
builder.add_node("node1", my_function)
builder.add_node("node2", AnotherRunnable())
builder.add_edge(START, "node1")
builder.add_edge("node1", "node2")
builder.add_edge("node2", END)
```

**Stage 2: Compilation** (`CompiledStateGraph`):
```python
graph = builder.compile(
    checkpointer=InMemorySaver(),
    interrupt_before=["node2"],
)
```

**Key insight**: Builder validates topology, compiler creates runtime (Pregel instance).

### Node Definition Patterns

**Pattern 1: Function-based**
```python
def my_node(state: State, config: RunnableConfig) -> dict:
    return {"key": "value"}

builder.add_node("my_node", my_node)
```

**Pattern 2: Runnable-based**
```python
from langchain_core.runnables import RunnableLambda

runnable = RunnableLambda(lambda x: {"result": x["input"] * 2})
builder.add_node("double", runnable)
```

**Pattern 3: Class-based (via Runnable)**
```python
class CustomProcessor(Runnable):
    def invoke(self, input, config):
        return {"processed": input}

builder.add_node("processor", CustomProcessor())
```

**Flexibility**: High - any callable or Runnable works.

### Extension Points

| Extension | Mechanism | Difficulty |
|-----------|-----------|------------|
| Custom Channel | Inherit BaseChannel | Medium (implement update/from_checkpoint) |
| Custom Checkpointer | Inherit BaseCheckpointSaver | Medium (async put/get/list) |
| Custom Node | Function or Runnable | Easy (just return dict) |
| Custom Reducer | Provide to Annotated | Easy (binary function) |
| Custom Store | Inherit BaseStore | Medium (key-value ops) |
| Custom Cache | Inherit BaseCache | Medium (get/put with TTL) |

### BaseChannel Protocol

From `channels/base.py`:

```python
class BaseChannel(Generic[ValueT, UpdateT]):
    """Protocol for state channels"""

    def update(self, values: Sequence[UpdateT]) -> bool:
        """Apply updates to channel value"""
        ...

    def checkpoint(self) -> Any:
        """Serialize channel value"""
        ...

    @classmethod
    def from_checkpoint(cls, checkpoint: Any) -> Self:
        """Deserialize channel value"""
        ...
```

**Concrete implementations**:
- `LastValue`: Simple overwrite semantics
- `Topic`: Append-only list with deduplication
- `BinaryOperatorAggregate`: Custom binary operator aggregation
- `EphemeralValue`: Temporary value (not persisted in checkpoints)
- `NamedBarrierValue`: Synchronization barrier (waits for N inputs)

**Design**: Thin protocol + rich implementations (good extensibility).

### Configuration Strategy
- **Strategy**: Code-first with schema inference
- **Formats**: Python (primary), YAML/JSON (via langserve deployment)
- **Validation**: Pydantic for schemas, runtime validation for graph topology

### Schema-Driven Node Inputs

From `state.py` lines 359-572 (add_node method):

**Input schema inference**:
```python
def add_node(
    self,
    node: str | Callable,
    action: Callable | None = None,
    *,
    input_schema: type[Any] | None = None,  # Optional override
    ...
):
    # Infer input schema from function signature if not provided
    if input_schema is None and (hints := get_type_hints(action)):
        first_param = next(iter(signature(action).parameters.keys()))
        if input_hint := hints.get(first_param):
            input_schema = input_hint
```

**Benefits**:
- Type hints drive schema extraction
- IDE autocomplete for node inputs
- Runtime validation of node outputs

### NodeBuilder API (Low-Level)

From `pregel/main.py` lines 160-322:

```python
(NodeBuilder()
    .subscribe_to("channel1", "channel2")  # Which channels trigger this node
    .do(my_runnable)                       # What to execute
    .write_to("output_channel")            # Where to write results
    .meta(tag1="value")                    # Metadata
    .add_retry_policies(RetryPolicy(...))  # Retry config
    .build()                               # Create PregelNode
)
```

**Use case**: Low-level graph construction (StateGraph uses this internally).

### Runnable Integration

LangGraph fully integrates with LangChain's Runnable protocol:

**Key interfaces**:
```python
# From LangChain
class Runnable(Generic[Input, Output]):
    def invoke(self, input: Input, config: RunnableConfig) -> Output: ...
    def stream(self, input: Input, config: RunnableConfig) -> Iterator[Output]: ...
    def batch(self, inputs: list[Input], config: RunnableConfig) -> list[Output]: ...
    # + async variants
```

**Coercion** (from `_internal/_runnable.py`):
- Functions → `RunnableLambda`
- Runnables → pass through
- Other callables → wrapped in Runnable

**Benefit**: Any LangChain component (chains, prompts, models) works as a node.

### Dependency Injection Details

**Constructor injection at compile time**:
```python
graph = builder.compile(
    checkpointer=PostgresSaver(...),  # Injected
    store=InMemoryStore(),            # Injected
    cache=RedisCache(...),            # Injected
)
```

**Runtime injection via config**:
```python
graph.invoke(
    input,
    config={
        "configurable": {
            "thread_id": "user-123",  # Injected at runtime
        },
        "callbacks": [MyCallback()],  # Injected
    }
)
```

**Context injection** (v0.6.0+):
```python
class Context(TypedDict):
    user_id: str
    db: DatabaseConnection

builder = StateGraph(State, context_schema=Context)

def my_node(state: State, runtime: Runtime[Context]):
    user_id = runtime.context["user_id"]
    db = runtime.context["db"]
    # Use injected dependencies
```

**Pattern**: Context schema + Runtime object for safe DI.

### Managed Values

From `managed/base.py`:

**Use case**: Resources with lifecycle (DB connections, file handles).

```python
class ManagedValueSpec:
    """Specification for a managed resource"""
    pass

# Example: is_last_step managed value
# Available to nodes, managed by framework
```

**Built-in managed values**:
- `is_last_step`: Boolean indicating final step
- Custom managed values: user can define

### Configuration Validation

**Graph validation** (from `state.py` lines 775-822):

```python
def validate(self, interrupt: Sequence[str] | None = None) -> Self:
    # Validate all edge sources exist as nodes
    for source in all_sources:
        if source not in self.nodes and source != START:
            raise ValueError(f"Found edge starting at unknown node '{source}'")

    # Validate all edge targets exist as nodes
    for target in all_targets:
        if target not in self.nodes and target != END:
            raise ValueError(f"Found edge ending at unknown node `{target}`")

    # Validate at least one entry point exists
    if START not in all_sources:
        raise ValueError("Graph must have an entrypoint")
```

**Validates at compile time**:
- All edges reference existing nodes
- Graph has entry point (START)
- Interrupt nodes exist
- No orphaned nodes (warning, not error)

### Subgraph Support

LangGraph supports **nested graphs**:

```python
# Inner graph
inner = StateGraph(InnerState).add_node("step1", ...).compile()

# Outer graph uses inner graph as a node
outer = StateGraph(OuterState)
outer.add_node("subgraph", inner)
outer.compile()
```

**Checkpointer inheritance**:
- Subgraph inherits parent checkpointer by default
- Can override with `compile(checkpointer=False)` to disable
- Can provide custom checkpointer for subgraph

### Registry Pattern

**No global registry** in LangGraph core. Instead:
- **Explicit imports**: `from my_nodes import node1, node2`
- **Dependency injection**: pass components at compile time
- **Runnable coercion**: framework wraps callables automatically

**Design choice**: Favors explicitness over magic.

### Recommendations

**Strengths**:
- Clean builder pattern separates construction from execution
- Thin protocols enable easy extension
- Runnable integration provides rich ecosystem
- Type-driven schema inference reduces boilerplate
- Context injection solves DI without global state

**Weaknesses**:
- Two-stage compilation can confuse beginners
- Channel abstraction adds learning curve
- No built-in dependency injection container (deliberate choice)

**Best practices to adopt**:
1. Builder pattern for graph construction
2. Thin protocols (BaseChannel, BaseCheckpointSaver) for extensibility
3. Type-driven schema inference from function signatures
4. Context injection via typed context schema
5. Validation at compile time to catch errors early
6. Runnable protocol for composability
