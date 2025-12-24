# Component Model Analysis: Google ADK

## Summary
- **Key Finding 1**: Inheritance-heavy design with abstract base classes (BaseAgent, BaseTool, BaseLlm)
- **Key Finding 2**: Pydantic-powered configuration with ClassVar config_type pattern
- **Classification**: Object-oriented with thick base classes and minimal protocol usage

## Detailed Analysis

### Abstraction Strategy

The framework uses **class inheritance** as the primary extension mechanism:

```
BaseAgent (Pydantic BaseModel)
    ├─ LlmAgent (most agents inherit from this)
    ├─ Callback hooks: before_agent_callback, after_agent_callback
    └─ Sub-agent composition: parent_agent, sub_agents[]

BaseTool (ABC)
    ├─ FunctionTool (wraps Python functions)
    ├─ AgentTool (wraps agents as tools)
    ├─ BaseToolset (groups tools)
    ├─ LangChainTool (adapter)
    └─ Various specialized tools (BigQueryTool, PubSubTool, etc.)

BaseLlm (ABC)
    ├─ GoogleLlm (Gemini)
    ├─ LiteLlm (multi-provider)
    ├─ AnthropicLlm
    ├─ GemmaLlm
    └─ ApigeeLlm
```

### Extension Mechanisms

| Component | Extension Method | DI Pattern |
|-----------|-----------------|------------|
| **Agents** | Subclass BaseAgent | Config injection via config_type ClassVar |
| **Tools** | Subclass BaseTool or use @function_tool decorator | Passed to agent via tools=[] |
| **LLMs** | Subclass BaseLlm | Injected via LlmAgent(llm=...) |
| **Flows** | Subclass BaseLlmFlow | Injected via LlmAgent(flow=...) |
| **Memory** | Subclass BaseMemoryService | Registry pattern |
| **Sessions** | Subclass BaseSessionService | Registry pattern |

### Configuration Pattern

The framework uses a **config_type ClassVar** pattern:

```python
class MyAgentConfig(BaseAgentConfig):
    my_field: str = ''

class MyAgent(BaseAgent):
    config_type: ClassVar[type[BaseAgentConfig]] = MyAgentConfig
```

This allows:
- Type-safe configuration
- Pydantic validation at config boundary
- Separation of agent logic from config

### Composition vs Inheritance

- **Agent composition**: Hierarchical via parent_agent/sub_agents
- **Tool composition**: Tools grouped in BaseToolset
- **Flow composition**: Flows contain processor pipelines
- **Callback composition**: List of callbacks executed in sequence

**Depth Analysis**:
- Inheritance depth: 2-3 levels typical (BaseAgent → LlmAgent → CustomAgent)
- Composition depth: Unlimited (agent trees can be arbitrarily nested)

### Dependency Injection

**Constructor Injection**:
```python
LlmAgent(
    name="my_agent",
    llm=GoogleLlm(...),
    tools=[tool1, tool2],
    flow=AutoFlow(),
    memory_service=VertexAIMemoryBankService(),
    session_service=DatabaseSessionService(),
)
```

**Registry Pattern**:
- MemoryService, SessionService, ArtifactService use service registration
- Allows runtime selection of implementations

### Testability

- **Mocking surface**: Can mock BaseLlm, BaseTool, services
- **Constructor injection**: Easy to inject test doubles
- **Async**: Requires async test harness (pytest-asyncio)
- **State isolation**: Session/memory services can be swapped for in-memory versions

## Implications for New Framework

### Positive Patterns
- **ClassVar config_type**: Elegant way to associate config schema with agent class
- **Service abstraction**: Memory/Session/Artifact services allow pluggable backends
- **Callback hooks**: before_agent_callback/after_agent_callback enable cross-cutting concerns
- **Decorator pattern**: @function_tool makes tool creation ergonomic

### Considerations
- **Deep inheritance**: BaseAgent has 500+ lines with many responsibilities (SRP violation)
- **No Protocols**: Framework relies entirely on ABCs (rigid, requires inheritance)
- **Tight coupling**: Agents depend on Pydantic, Google GenAI types, specific flow interfaces
- **Limited composition**: Multi-agent requires inheritance from BaseAgent (can't compose arbitrary objects)

## Code References
- `agents/base_agent.py:85` - BaseAgent with Pydantic, sub-agent composition
- `agents/base_agent.py:94` - config_type ClassVar pattern
- `agents/llm_agent.py` - LlmAgent with constructor injection
- `tools/base_tool.py:47` - BaseTool ABC with minimal interface
- `tools/base_toolset.py` - BaseToolset for grouping tools
- `models/base_llm.py` - BaseLlm with abstract methods

## Anti-Patterns Observed
- **God class**: BaseAgent handles lifecycle, state, callbacks, composition (too many roles)
- **Inheritance over composition**: To add behavior, must subclass rather than compose
- **No interface segregation**: BaseAgent forces all subclasses to implement full interface
- **Tight coupling to Pydantic**: BaseAgent is a Pydantic BaseModel (can't use plain Python classes)
