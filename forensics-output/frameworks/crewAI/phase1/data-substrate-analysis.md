# Data Substrate Analysis: crewAI

## Summary
- **Typing Strategy**: Pydantic V2 with extensive use of BaseModel across all core abstractions
- **Immutability**: Mixed pattern - models are mutable by default with in-place modifications common
- **Serialization**: Pydantic-native with model_dump() and model_dump_json()
- **Validation**: Comprehensive field validators and model validators at boundaries

## Detailed Analysis

### Typing Strategy

crewAI employs a **Pydantic V2-first** typing strategy with near-universal adoption across the framework:

**Core Models** (all inherit from `pydantic.BaseModel`):
- `Task` (task.py:L63) - Task representation with description, expected_output, agent assignment
- `Crew` (crew.py:L102) - Crew orchestration with agents, tasks, process configuration
- `BaseAgent` (agents/agent_builder/base_agent.py:L61) - Abstract agent with role, goal, backstory
- `Agent` (agent/core.py:L101) - Concrete agent implementation
- `TaskOutput` (tasks/task_output.py:L12) - Task execution results
- `CrewOutput` (crews/crew_output.py:L13) - Crew execution results
- `BaseTool` (tools/base_tool.py:L54) - Tool abstraction with args_schema
- `UsageMetrics` (types/usage_metrics.py:L11) - Token tracking

**Field Configuration**:
- Extensive use of `Field()` with descriptions for auto-documentation
- `PrivateAttr()` for internal state (e.g., `_times_executed`, `_mcp_clients`)
- `ClassVar` for shared class-level attributes (e.g., `logger`)
- `model_config = ConfigDict(arbitrary_types_allowed=True)` for tools and LLM instances

**Hybrid Pattern Observed**:
While Pydantic dominates, `TypedDict` appears in utilities:
- `LLMMessage` (utilities/types.py:L8) - Using TypedDict instead of BaseModel
- This creates a typing inconsistency: core domain uses Pydantic, message passing uses TypedDict

**Validation Approach**:
- `@field_validator` for individual field constraints
- `@model_validator(mode="after")` for cross-field validation
- `PydanticCustomError` for custom error messages
- Example in TaskOutput:L46 - auto-generates summary from description

### Core Data Primitives

| Type | Location | Purpose | Mutability | Nesting |
|------|----------|---------|------------|---------|
| Task | task.py:L63 | Task definition with agent, description, output spec | Mutable | Deep (2-3 levels) |
| Crew | crew.py:L102 | Crew orchestration container | Mutable | Deep (agents, tasks, memory) |
| BaseAgent | base_agent.py:L61 | Agent abstraction (ABC) | Mutable | Medium |
| Agent | agent/core.py:L101 | Concrete agent | Mutable | Deep (tools, knowledge, memory) |
| TaskOutput | task_output.py:L12 | Task result | Mutable | Medium (pydantic, json_dict, raw) |
| CrewOutput | crew_output.py:L13 | Crew result | Mutable | Deep (tasks_output list) |
| UsageMetrics | usage_metrics.py:L11 | Token tracking | Mutable | Shallow |
| BaseTool | base_tool.py:L54 | Tool interface | Mutable | Medium (args_schema) |
| Memory | memory/memory.py:L15 | Base memory class | Mutable | Medium |

**Nesting Depth**: Generally 2-3 levels deep. Example:
```
Crew → agents: list[Agent] → tools: list[BaseTool] → args_schema: BaseModel
```

### Mutation Analysis

**Pattern**: **In-place mutation with mutable-by-default models**

**Evidence of In-Place Modification**:

1. **UsageMetrics.add_usage_metrics()** (usage_metrics.py:L36-46):
```python
def add_usage_metrics(self, usage_metrics: Self) -> None:
    self.total_tokens += usage_metrics.total_tokens
    self.prompt_tokens += usage_metrics.prompt_tokens
    # Direct field mutation
```

2. **Shallow Copy Pattern** (task.py:L4, crew.py:L6):
```python
from copy import copy as shallow_copy
# Used for creating task/agent copies, but underlying objects remain shared
```

3. **List Append Operations**:
- `CrewOutput.tasks_output: list[TaskOutput]` appended during execution
- `messages: list[LLMMessage]` accumulated in executor (crew_agent_executor.py:L138)

4. **Private Attribute Mutation**:
```python
_times_executed: int = PrivateAttr(default=0)
_mcp_clients: list[Any] = PrivateAttr(default_factory=list)
# These are mutated in-place during agent execution
```

**Risk Areas**:
- Shared mutable state between crew and agents (memory objects passed by reference)
- Task/Agent copies via `shallow_copy` don't prevent shared nested object mutation
- No `frozen=True` on any core models - all are mutable
- Concurrent execution could have race conditions (though Python GIL provides some protection)

**Concurrency Safety**: **Partial**
- Uses `asyncio` for async operations
- No explicit locking for shared state
- Private attributes mutated without synchronization
- Relies on Python GIL and single-threaded event loop execution

### Serialization

**Method**: **Pydantic V2 native**

**Export Patterns**:

1. **JSON Output** (TaskOutput.json property, task_output.py:L58):
```python
@property
def json(self) -> str | None:
    if self.output_format != OutputFormat.JSON:
        raise ValueError(...)
    return json.dumps(self.json_dict)
```

2. **Dictionary Output** (TaskOutput.to_dict(), task_output.py:L81):
```python
def to_dict(self) -> dict[str, Any]:
    output_dict = {}
    if self.json_dict:
        output_dict.update(self.json_dict)
    elif self.pydantic:
        output_dict.update(self.pydantic.model_dump())
    return output_dict
```

3. **String Representation** (TaskOutput.__str__, task_output.py:L95):
```python
def __str__(self) -> str:
    if self.pydantic:
        return str(self.pydantic)
    if self.json_dict:
        return str(self.json_dict)
    return self.raw
```

**Serialization Features**:
- `model_dump()` for dictionary conversion
- `model_dump_json()` available but not heavily used (uses json.dumps on dict instead)
- Custom `to_dict()` methods that prioritize structured outputs (json_dict, pydantic) over raw
- Triple-format output support: raw string, JSON dict, Pydantic model

**Round-trip Testing**: Unknown (not visible in core files examined)

**Implicit/Explicit**: **Hybrid**
- Pydantic provides implicit serialization via `.model_dump()`
- Framework adds explicit `to_dict()` and `.json` properties for output flexibility
- Auto-conversion between formats (pydantic → json_dict → raw string)

### Configuration Injection

**Pattern**: Dictionary-based config with `process_config()` utility

Evidence:
- `config: dict[str, Any] | None` fields on Task, Agent, Crew
- `from crewai.utilities.config import process_config` (task.py:L44, base_agent.py:L32)
- Allows YAML/JSON file loading with variable interpolation via `interpolate_only`

## Implications for New Framework

**Adopt**:
1. **Pydantic V2 for all domain models** - strong typing, validation, auto-documentation
2. **Field() descriptions** - enables schema generation for LLMs and API docs
3. **Triple-format output** (raw, json_dict, pydantic) - supports diverse consumption patterns
4. **Validator-based constraints** - declarative validation at model boundaries

**Avoid**:
1. **Mutable-by-default models** - introduce `frozen=True` for immutable state where appropriate
2. **TypedDict for LLM messages** - inconsistent with Pydantic-first strategy; use BaseModel instead
3. **Shallow copy for state cloning** - use Pydantic's `model_copy()` with deep=True
4. **In-place mutation of metrics** - return new instances instead (`UsageMetrics.merge()` → new object)

**Improve**:
1. Add explicit immutability boundaries: configuration models frozen, runtime state mutable
2. Use `model_copy(update={...})` instead of direct mutation for state transitions
3. Consolidate serialization: prefer `model_dump_json()` over `json.dumps(obj.to_dict())`
4. Add concurrency primitives (asyncio.Lock) for shared mutable state if multi-agent concurrency is required

## Code References

- Task model: `lib/crewai/src/crewai/task.py:L63`
- Crew model: `lib/crewai/src/crewai/crew.py:L102`
- BaseAgent: `lib/crewai/src/crewai/agents/agent_builder/base_agent.py:L61`
- Agent: `lib/crewai/src/crewai/agent/core.py:L101`
- TaskOutput: `lib/crewai/src/crewai/tasks/task_output.py:L12`
- CrewOutput: `lib/crewai/src/crewai/crews/crew_output.py:L13`
- UsageMetrics: `lib/crewai/src/crewai/types/usage_metrics.py:L11`
- BaseTool: `lib/crewai/src/crewai/tools/base_tool.py:L54`
- LLMMessage (TypedDict): `lib/crewai/src/crewai/utilities/types.py:L8`
- Memory base: `lib/crewai/src/crewai/memory/memory.py:L15`

## Anti-Patterns Observed

1. **Inconsistent typing strategy**: Core uses Pydantic, utilities use TypedDict (LLMMessage)
2. **Mutable-by-default without copy-on-write**: Direct field mutation enables unintended side effects
3. **Shallow copy imports**: `from copy import copy as shallow_copy` doesn't protect nested objects
4. **In-place metric accumulation**: `add_usage_metrics()` mutates self instead of returning new instance
5. **Manual JSON serialization**: `json.dumps(self.json_dict)` instead of `model_dump_json()`
