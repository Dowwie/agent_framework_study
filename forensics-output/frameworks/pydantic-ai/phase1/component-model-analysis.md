# Component Model Analysis: pydantic-ai

## Summary

- **Abstraction Strategy**: ABC for core interfaces, minimal Protocol usage
- **Dependency Injection**: Generic type parameters (`AgentDepsT`) with RunContext
- **Extensibility**: Toolsets via ABC, Models via ABC, decorators for tools
- **Classification**: **Abstract base class hierarchy with generic DI**

## Detailed Analysis

### Abstraction Depth

**Two-tier abstraction model:**

1. **Core interfaces via ABC** (Abstract Base Classes):
   - `Model(ABC)` - LLM provider interface
   - `AbstractAgent(ABC)` - Agent interface
   - `AbstractToolset(ABC)` - Tool collection interface
   - `OutputSchema(ABC)` - Output processing interface
   - `StreamedResponse(ABC)` - Streaming response interface
   - `Provider(ABC)` - Provider initialization interface

2. **Minimal Protocol usage**:
   - `SchemaValidatorProt(Protocol)` - Duck typing for Pydantic validators
   - Used only where structural typing needed (compatibility with private types)

**Key observation**: Framework strongly prefers ABC over Protocol, contrary to modern Python trends.

### Model Interface

**Core abstraction**:
```python
class Model(ABC):
    @abstractmethod
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        raise NotImplementedError()

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        raise NotImplementedError(f'Streamed requests not supported by this {self.__class__.__name__}')
        yield  # pragma: no cover

    async def count_tokens(...) -> RequestUsage:
        raise NotImplementedError(...)

    def customize_request_parameters(...) -> ModelRequestParameters:
        # Hook for vendor-specific schema modifications
        ...
```

**Design pattern**: Template method pattern
- Base class provides `prepare_request()` orchestration
- Subclasses override `request()` and optionally `request_stream()`
- Hook methods for customization (`customize_request_parameters`)

### Toolset Interface

**AbstractToolset ABC**:
```python
class AbstractToolset(ABC, Generic[AgentDepsT]):
    @property
    @abstractmethod
    def id(self) -> str | None:
        """Unique ID among toolsets (required for durable execution)."""
        raise NotImplementedError()

    @property
    def label(self) -> str:
        """Name for error messages."""
        return self.__class__.__name__ + (f' {self.id!r}' if self.id else '')

    async def __aenter__(self) -> Self:
        """Enter toolset context."""
        return self

    async def __aexit__(...) -> None:
        """Exit toolset context."""
        pass

    @abstractmethod
    async def list_tools(
        self, ctx: RunContext[AgentDepsT]
    ) -> Sequence[ToolsetTool[AgentDepsT]]:
        """List all tools in the toolset."""
        raise NotImplementedError()

    @abstractmethod
    async def call_tool(
        self, ctx: RunContext[AgentDepsT], name: str, args: dict[str, Any]
    ) -> Any:
        """Call a tool by name with args."""
        raise NotImplementedError()
```

**Wrapper pattern**: Built-in wrapper toolsets
- `PrefixedToolset` - Add prefix to tool names
- `RenamedToolset` - Rename tools
- `FilteredToolset` - Filter tool subset
- `ApprovalRequiredToolset` - Require user approval
- `PreparedToolset` - Custom preparation logic

### Dependency Injection Pattern

**Generic type parameter approach**:
```python
class AbstractAgent(Generic[AgentDepsT, OutputDataT], ABC):
    @property
    @abstractmethod
    def deps_type(self) -> type:
        """The type of dependencies used by the agent."""
        raise NotImplementedError

# Usage in tools:
@agent.tool
async def get_data(ctx: RunContext[MyDeps]) -> str:
    return await ctx.deps.database.fetch_data()
```

**RunContext as dependency container**:
- Type-safe access to dependencies via `ctx.deps: AgentDepsT`
- Access to model, usage, retry info
- No global state - context passed explicitly

### Output Handling Extensibility

**Multiple output strategies via ABC hierarchy**:

```python
class OutputSchema(ABC, Generic[OutputDataT]):
    @abstractmethod
    async def process_result(...) -> OutputDataT:
        raise NotImplementedError()

class StructuredTextOutputSchema(OutputSchema[OutputDataT], ABC):
    # Specialization for prompted text extraction
    ...
```

**Concrete implementations**:
- `TextOutputSchema` - Plain text
- `ToolOutputSchema` - Structured via tool calls
- `NativeOutputSchema` - Provider-specific structured output
- `PromptedOutputSchema` - Prompt-based extraction

### Decorator Pattern for Tools

**Flexible tool registration**:
```python
# Simple function decoration
@agent.tool
def my_tool(arg: str) -> str:
    return arg.upper()

# With RunContext
@agent.tool
async def contextual_tool(ctx: RunContext[MyDeps], query: str) -> str:
    return await ctx.deps.service.search(query)

# With preparation callback
@agent.tool(prepare=only_if_condition)
def conditional_tool(...) -> str:
    ...
```

**Type-safe tool definition**:
- Automatic schema generation from function signatures
- Docstring parsing (Google/Numpy/Sphinx/auto)
- Pydantic validation for arguments
- Support for sync and async functions

### Provider System

**Two-level abstraction**:

1. **Provider ABC**: Handles client initialization
```python
class Provider(ABC, Generic[InterfaceClient]):
    @abstractmethod
    def init_sync_client(self) -> InterfaceClient:
        raise NotImplementedError()

    @abstractmethod
    def init_async_client(self) -> InterfaceClient:
        raise NotImplementedError()
```

2. **Model implementations**: Per-provider model classes
   - OpenAIModel, AnthropicModel, GeminiModel, etc.
   - All inherit from `Model(ABC)`
   - Factory function `infer_model()` auto-selects based on model string

### Agent Interface

**AbstractAgent** defines the contract:
```python
class AbstractAgent(Generic[AgentDepsT, OutputDataT], ABC):
    @property
    @abstractmethod
    def model(self) -> models.Model | models.KnownModelName | str | None: ...

    @property
    @abstractmethod
    def deps_type(self) -> type: ...

    @property
    @abstractmethod
    def output_type(self) -> OutputSpec[OutputDataT]: ...

    @property
    @abstractmethod
    def toolsets(self) -> Sequence[AbstractToolset[AgentDepsT]]: ...

    # Concrete implementation provided:
    def output_json_schema(...) -> JsonSchema:
        # Shared logic across all agents
        ...
```

**Pattern**: Interface segregation - abstract properties for behavior, concrete methods for shared logic

## Code References

- `pydantic_ai_slim/pydantic_ai/models/__init__.py:549` - Model ABC
- `pydantic_ai_slim/pydantic_ai/agent/abstract.py:78` - AbstractAgent
- `pydantic_ai_slim/pydantic_ai/toolsets/abstract.py:62` - AbstractToolset
- `pydantic_ai_slim/pydantic_ai/tools.py:54` - Tool function type aliases
- `pydantic_ai_slim/pydantic_ai/providers/__init__.py` - Provider ABC
- `pydantic_ai_slim/pydantic_ai/_output.py` - OutputSchema ABC hierarchy

## Implications for New Framework

1. **Reconsider**: Heavy ABC usage vs. Protocol
   - **Pro (ABC)**: Shared implementation, explicit inheritance, IDE support
   - **Pro (Protocol)**: Structural typing, no coupling, easier testing
   - **Recommendation**: Use Protocol for interfaces, ABC only when sharing implementation

2. **Adopt**: Generic type parameters for DI
   - Excellent type safety without magic
   - Pattern: `Agent[DepsType, OutputType]`
   - Scales well with RunContext pattern

3. **Adopt**: Decorator-based tool registration
   - Clean API for users
   - Automatic schema generation
   - Support both sync and async transparently

4. **Adopt**: Wrapper pattern for toolsets
   - Composable behavior (prefix, filter, approval)
   - Follows decorator pattern principles
   - Easy to extend with new wrappers

5. **Consider**: Template method pattern for Model interface
   - `prepare_request()` orchestrates common logic
   - Subclasses override specific methods
   - Good separation of concerns

## Anti-Patterns Observed

1. **Overuse of ABC**: Most interfaces could be Protocols
   - Example: `Model(ABC)` - no shared implementation in base class
   - `request()`, `request_stream()`, `count_tokens()` all raise NotImplementedError
   - **Recommendation**: Convert to Protocol unless shared logic needed

2. **Mixed ABC/typing.Generic inheritance order**:
   - Sometimes `ABC, Generic[T]`, sometimes `Generic[T], ABC`
   - **Recommendation**: Standardize on `Protocol` or consistent ABC order

3. **NotImplementedError anti-pattern**:
   - ABC methods that raise NotImplementedError
   - Should use `@abstractmethod` with `...` (ellipsis) instead
   - Pattern observed: `raise NotImplementedError(f'...')` with custom messages
   - **Recommendation**: Use ellipsis for true abstract methods, NotImplementedError only for optional hooks

## Notable Patterns Worth Adopting

1. **Type alias for function signatures**:
   ```python
   ToolFuncContext: TypeAlias = Callable[Concatenate[RunContext[AgentDepsT], ToolParams], Any]
   ```
   - Clean, reusable type hints
   - Supports both with and without context

2. **Contextmanager for streaming**:
   - `async with model.request_stream(...) as stream:`
   - Ensures cleanup even if not consumed

3. **Wrapper toolset composition**:
   - `PrefixedToolset(FilteredToolset(base_toolset))`
   - Composable behavior without subclassing
