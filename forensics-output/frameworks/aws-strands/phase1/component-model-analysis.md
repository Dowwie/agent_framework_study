# Component Model Analysis: AWS Strands

## Summary
- **Key Finding 1**: ABC-based extensibility with thin abstract base classes
- **Key Finding 2**: Registry pattern for tools with dynamic loading support
- **Classification**: Plugin architecture with ABC contracts + event-driven hooks

## Detailed Analysis

### Abstraction Strategy
- **Primary Pattern**: Abstract Base Classes (ABC) for core extension points
- **Secondary Pattern**: Protocol (ToolFunc) for function-based tools
- **Depth**: Shallow (1-level inheritance typical)
- **Key Files**:
  - `src/strands/models/model.py` - Model ABC
  - `src/strands/types/tools.py` - AgentTool ABC + ToolFunc Protocol
  - `src/strands/agent/conversation_manager/conversation_manager.py` - ConversationManager ABC
  - `src/strands/hooks/registry.py` - HookProvider pattern
  - `src/strands/tools/registry.py` - Tool registry and loader

### Core Extension Points

#### 1. Model Provider (ABC)

**Location**: `src/strands/models/model.py:18`

**Interface**:
```python
class Model(abc.ABC):
    @abstractmethod
    def update_config(self, **model_config: Any) -> None: ...

    @abstractmethod
    def get_config(self) -> Any: ...

    @abstractmethod
    def structured_output(...) -> AsyncGenerator[dict[str, Union[T, Any]], None]: ...

    @abstractmethod
    def stream(...) -> AsyncIterable[StreamEvent]: ...
```

**Characteristics**:
- 4 abstract methods (config, config getter, structured output, stream)
- No shared implementation (pure interface)
- Uses TypeVar for generic structured output
- AsyncIterable/AsyncGenerator return types

**Implications**:
- Clean separation: providers handle I/O, agent handles logic
- No base class state (stateless ABC)
- Type-safe structured output via Pydantic generics

#### 2. AgentTool (ABC + Protocol Hybrid)

**Location**: `src/strands/types/tools.py:218`

**ABC Interface**:
```python
class AgentTool(ABC):
    @property
    @abstractmethod
    def tool_name(self) -> str: ...

    @property
    @abstractmethod
    def tool_spec(self) -> ToolSpec: ...

    @property
    @abstractmethod
    def tool_type(self) -> str: ...

    @abstractmethod
    def stream(...) -> ToolGenerator: ...

    # Concrete methods
    def mark_dynamic(self) -> None: ...
    @property
    def is_dynamic(self) -> bool: ...
    def get_display_properties(self) -> dict[str, str]: ...
```

**Protocol Alternative** (tools.py:L199):
```python
class ToolFunc(Protocol):
    __name__: str
    def __call__(...) -> Union[ToolResult, Awaitable[ToolResult]]: ...
```

**Characteristics**:
- ABC for class-based tools (4 abstract properties + 1 method)
- Protocol for function-based tools (structural typing)
- Concrete lifecycle management (_is_dynamic flag)
- Optional hot reload support

**Tool Loading Strategies** (registry.py:L44-L150):
1. String path: `"./path/to/tool.py"`
2. Module import path: `"strands_tools.file_read"`
3. Module path with function: `"my.module:specific_func"`
4. Imported module reference
5. AgentTool instance
6. Nested iterables (recursive)
7. ToolProvider (managed collections)

#### 3. ConversationManager (ABC)

**Location**: `src/strands/agent/conversation_manager/conversation_manager.py:12`

**Interface**:
```python
class ConversationManager(ABC):
    def __init__(self):
        self.removed_message_count = 0

    @abstractmethod
    def apply_management(self, agent: Agent, **kwargs) -> None: ...

    @abstractmethod
    def reduce_context(self, agent: Agent, e: Optional[Exception], **kwargs) -> None: ...

    # Concrete methods
    def restore_from_session(self, state: dict) -> Optional[list[Message]]: ...
    def get_state(self) -> dict: ...
```

**Characteristics**:
- 2 abstract methods (management strategy + overflow recovery)
- Shared state: `removed_message_count`
- Session serialization support (concrete)
- In-place message list modification

**Built-in Implementations**:
- `SlidingWindowConversationManager` - FIFO eviction
- `SummarizingConversationManager` - LLM-based compression
- `NullConversationManager` - No-op

#### 4. HookProvider (Interface Pattern)

**Location**: `src/strands/hooks/registry.py` (inferred from imports)

**Pattern**:
```python
class HookProvider:
    def register_hooks(self, registry: HookRegistry) -> None:
        # Register event callbacks
        registry.add_callback(EventType, self.handler)
```

**Event Types**:
- AgentInitializedEvent
- BeforeInvocationEvent / AfterInvocationEvent
- BeforeModelCallEvent / AfterModelCallEvent
- BeforeToolCallEvent / AfterToolCallEvent
- MessageAddedEvent
- Bidi-specific events (connection lifecycle)

**Characteristics**:
- Type-safe event system (replaces callback_handler)
- Multiple subscribers per event type
- Composable (multiple HookProviders per agent)
- Sync and async callback support

### Dependency Injection Patterns

#### 1. Constructor Injection
All major components use constructor DI:
```python
Agent(
    model: Model | str | None,
    tools: list[...],
    conversation_manager: ConversationManager | None,
    tool_executor: ToolExecutor | None,
    session_manager: SessionManager | None,
    hooks: list[HookProvider] | None,
)
```

**Defaults**:
- `model=None` → `BedrockModel()`
- `conversation_manager=None` → `SlidingWindowConversationManager()`
- `tool_executor=None` → Sequential executor

#### 2. Registry Pattern (Tools)
- Centralized `ToolRegistry` singleton per agent
- Dynamic loading: `load_tool_from_string()`, `load_tools_from_module()`
- Discovery: Scans module for `AgentTool` instances or `@tool` decorated functions
- Hot reload: `ToolWatcher` monitors file changes

#### 3. Provider Pattern (ToolProvider)
External tool management:
```python
class ToolProvider:
    async def load_tools(self) -> Sequence[AgentTool]: ...
    def add_consumer(self, registry_id: str) -> None: ...
```

Used for managed collections (e.g., MCP server tools).

### Configuration Strategy

#### Model Configuration
- Runtime updates: `model.update_config(**kwargs)`
- Getter: `model.get_config()`
- No validation (trusts provider)

#### Agent Configuration
Parameters passed through constructor:
- Explicit parameters (type-safe)
- No global config file
- Trace attributes: `trace_attributes: Mapping[str, AttributeValue]`

### Code Generation / Metaprogramming

#### Tool Schema Normalization
`normalize_tool_spec()` and `normalize_schema()` in tools.py:
- Converts function signatures to JSON Schema
- Handles composition keywords (_COMPOSITION_KEYWORDS)
- Validates against provider constraints

#### Dynamic Tool Loading
Module inspection:
```python
def load_tools_from_module(module, tool_name):
    # Scan for AgentTool instances
    for name, obj in inspect.getmembers(module):
        if isinstance(obj, AgentTool): ...
```

### Extensibility Trade-offs

#### Strengths
1. **Thin ABCs**: Minimal abstract methods (2-4 each)
2. **Clean Separation**: Extension points well-defined
3. **Hot Reload**: Dynamic tool loading for DX
4. **Type Safety**: Generic TypeVar for structured output
5. **Composable Hooks**: Multiple subscribers per event

#### Weaknesses
1. **ABC Required**: No Protocol alternative for Model/ConversationManager
2. **In-Place Mutation**: ConversationManager modifies agent.messages directly
3. **Registry Coupling**: Tools tightly bound to ToolRegistry
4. **No Validation**: Model config accepts `Any`
5. **Dynamic State**: `_is_dynamic` flag feels like metadata pollution

## Code References
- `src/strands/models/model.py:18-100` - Model ABC with 4 abstract methods
- `src/strands/types/tools.py:218-307` - AgentTool ABC with lifecycle methods
- `src/strands/types/tools.py:199-216` - ToolFunc Protocol for function-based tools
- `src/strands/agent/conversation_manager/conversation_manager.py:12-89` - ConversationManager ABC
- `src/strands/tools/registry.py:30-150` - ToolRegistry with 7 loading strategies
- `src/strands/hooks/__init__.py:1-60` - Hook system documentation and exports

## Implications for New Framework
- **Adopt**: Thin ABCs with 2-4 abstract methods (focused interfaces)
- **Adopt**: Hook system over callback_handler (composable, type-safe)
- **Adopt**: Registry pattern for dynamic tool loading
- **Adopt**: TypeVar generics for structured output
- **Reconsider**: Protocol for Model/ConversationManager (avoid ABC where no shared implementation)
- **Reconsider**: Functional approach to message management (avoid in-place mutation)
- **Reconsider**: Model config validation (use TypedDict or Pydantic)

## Anti-Patterns Observed
- **In-Place Message Mutation**: ConversationManager modifies agent.messages directly (breaks immutability)
- **ABC Overuse**: Model and ConversationManager have no shared implementation (Protocol would suffice)
- **Dynamic Flag Pollution**: `_is_dynamic` on AgentTool (should be external metadata)
- **Untyped Config**: `model.update_config(**model_config: Any)` lacks validation
- **String-Based Loading**: Tool paths as strings (fragile, no static analysis)
