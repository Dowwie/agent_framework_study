# Component Model Analysis: crewAI

## Summary
- **Abstraction Pattern**: ABC-based with Pydantic BaseModel inheritance
- **Dependency Injection**: Constructor-based with Pydantic field injection
- **Configuration**: Code-first with optional YAML/dict config overlay
- **Extension Points**: Class inheritance + decorator-based tool registration

## Detailed Analysis

### Abstraction Strategy

**Primary Pattern**: **Abstract Base Classes (ABC) + Pydantic**

**Core Abstractions**:

1. **BaseAgent** (agents/agent_builder/base_agent.py:L61):
```python
class BaseAgent(BaseModel, ABC, metaclass=AgentMeta):
    # Abstract methods for third-party agent compatibility
    @abstractmethod
    def execute_task(task, context, tools) -> str: ...

    @abstractmethod
    def create_agent_executor(tools) -> None: ...
```
- Combines ABC for contract enforcement with Pydantic for validation
- Uses custom metaclass `AgentMeta` for additional processing
- Defines interface for third-party agent integrations

2. **BaseTool** (tools/base_tool.py:L54):
```python
class BaseTool(BaseModel, ABC):
    name: str
    description: str
    args_schema: type[PydanticBaseModel] = Field(default=_ArgsSchemaPlaceholder)

    @abstractmethod
    def _run(self, **kwargs) -> Any: ...
```
- Abstract `_run()` method for tool execution
- Pydantic schema generation for arguments
- Generic wrapper with `P = ParamSpec("P")` and `R = TypeVar("R")`

**Inheritance Depth**: **1-2 levels maximum**
- BaseAgent → Agent (depth 1)
- BaseAgent → LiteAgent (depth 1)
- BaseTool → specific tools (depth 1)
- Shallow hierarchies, good for maintainability

### Dependency Injection

**Pattern**: **Constructor injection via Pydantic fields**

**Agent Dependencies** (agent/core.py:L101):
```python
class Agent(BaseAgent):
    llm: str | InstanceOf[BaseLLM] | Any = Field(...)
    tools: list[Any] | None = Field(default=None)
    knowledge_sources: list[BaseKnowledgeSource] | None = Field(default=None)
    cache_handler: CacheHandler = Field(default_factory=CacheHandler)
```

**Crew Dependencies** (crew.py:L102):
```python
class Crew(BaseModel):
    agents: list[BaseAgent]
    tasks: list[Task]
    memory: bool = False  # Triggers memory subsystem instantiation
    manager_llm: str | BaseLLM | None = None
    manager_agent: Agent | None = None
```

**Injection Mechanism**:
- Dependencies declared as Pydantic fields
- Instantiation at construction time
- Shared instances (e.g., `RPMController`, `CacheHandler`) set via methods:
  - `agent.set_cache_handler(self._cache_handler)` (crew.py:L444)
  - `agent.set_rpm_controller(self._rpm_controller)` (crew.py:L446)

**DI Container**: None - manual wiring in Crew constructor and validators

### Configuration Approach

**Primary**: **Code-first with config overlay**

**Configuration Sources**:
1. **Direct instantiation** (primary):
```python
agent = Agent(role="researcher", goal="...", tools=[...])
```

2. **YAML/dict overlay** (crew.py:L38):
```python
from crewai.utilities.config import process_config

config: dict[str, Any] | None = Field(default=None)
```
- Optional `config` parameter on Crew, Agent, Task
- `_setup_from_config()` method processes YAML
- Variable interpolation via `interpolate_only` (task.py:L57, base_agent.py:L36)

3. **Environment variables**:
- Tools declare `env_vars: list[EnvVar]` (base_tool.py:L47-51)
- No centralized env management visible

**Validation**: Pydantic validators ensure config correctness
- `@model_validator(mode="after")` runs after field assignment
- Validates manager_llm requirement for hierarchical process (crew.py:L404)
- Validates task agent assignments for sequential process (crew.py:L451)

### Extension Mechanisms

**1. Tool Registration** (decorator pattern):
```python
from crewai.tools.base_tool import tool

@tool
def my_tool(query: str) -> str:
    return result
```
- Function introspection generates Pydantic schema
- Uses `inspect.signature()` for automatic arg schema generation (base_tool.py:L6)

**2. Agent Subclassing**:
```python
class CustomAgent(BaseAgent):
    def execute_task(self, task, context, tools):
        # Custom execution logic
```
- Must implement abstract methods
- Pydantic validation on construction

**3. Knowledge Source Plugin** (agent/core.py:L47):
```python
from crewai.knowledge.source.base_knowledge_source import BaseKnowledgeSource

class MyKnowledgeSource(BaseKnowledgeSource):
    # Custom retrieval logic
```

**4. Memory Provider Plugin** (short_term_memory.py:L44):
```python
if memory_provider == "mem0":
    from crewai.memory.storage.mem0_storage import Mem0Storage
    storage = Mem0Storage(type="short_term", ...)
```
- Pluggable storage backends (RAGStorage, Mem0Storage, SQLite)

**5. MCP Integration** (agent/core.py:L50-60):
```python
mcps: list[MCPServerConfig] | None = Field(default=None)
# Model Context Protocol for tool discovery
```
- Dynamic tool loading from external servers

## Implications for New Framework

**Adopt**:
1. **ABC + Pydantic hybrid** - gets contract enforcement AND validation
2. **Shallow inheritance** (max depth 2) - maintainability
3. **Field-based DI** - declarative, type-safe, self-documenting
4. **Code-first with config overlay** - programmatic by default, YAML for non-technical users
5. **Decorator-based tool registration** - ergonomic, low ceremony

**Avoid**:
1. **Manual instance sharing** (`set_cache_handler`, `set_rpm_controller`) - prefer DI container
2. **String-or-instance fields** (`llm: str | InstanceOf[BaseLLM]`) - ambiguous, error-prone
3. **Generic `Any` types** - defeats type checking (`tools: list[Any]`)
4. **Mixed config sources** - YAML vs dict vs code leads to confusion

**Improve**:
1. Use dependency injection container (e.g., `python-dependency-injector`) instead of manual wiring
2. Separate config schemas from runtime models (Pydantic Settings for config)
3. Use Protocol for interfaces where implementation sharing isn't needed
4. Type `llm` and `tools` properly instead of `Any`
5. Centralize environment variable management (Pydantic Settings)

## Code References

- BaseAgent: `lib/crewai/src/crewai/agents/agent_builder/base_agent.py:L61`
- Agent: `lib/crewai/src/crewai/agent/core.py:L101`
- Crew: `lib/crewai/src/crewai/crew.py:L102`
- BaseTool: `lib/crewai/src/crewai/tools/base_tool.py:L54`
- Tool decorator: `lib/crewai/src/crewai/tools/base_tool.py`
- Config processing: `lib/crewai/src/crewai/utilities/config.py` (referenced)
- Interpolation: `lib/crewai/src/crewai/utilities/string_utils.py` (referenced)
- Knowledge source: `lib/crewai/src/crewai/knowledge/source/base_knowledge_source.py`
- Memory provider: `lib/crewai/src/crewai/memory/short_term/short_term_memory.py:L44`
- Instance sharing: `lib/crewai/src/crewai/crew.py:L444-446`

## Anti-Patterns Observed

1. **String-or-instance union types**: `llm: str | InstanceOf[BaseLLM] | Any` - runtime string parsing required
2. **Manual instance wiring**: `agent.set_cache_handler()` instead of constructor injection
3. **Generic Any types**: `tools: list[Any]` defeats type checking
4. **Custom metaclass**: `AgentMeta` adds complexity without clear necessity
5. **Config dict without schema**: `config: dict[str, Any]` - no validation of structure
