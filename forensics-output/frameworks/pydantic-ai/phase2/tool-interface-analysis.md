# Tool Interface Analysis: pydantic-ai

## Summary

- **Tool Modeling**: Dataclass-based (`Tool[AgentDepsT]`) with function wrapping + Pydantic validation
- **Schema Generation**: Automatic via Pydantic introspection of function signatures and docstrings (Google/Numpy/Sphinx)
- **Registration Pattern**: Declarative via decorator (`@agent.tool`) or explicit (`agent.add_tool()`) with Toolset abstraction
- **Error Handling**: Three-layer validation with structured retry mechanism (Pydantic ValidationError → RetryPromptPart → model self-correction)
- **Built-in Tools**: 9 vendor-specific builtin tools (web search, code execution, etc.) + 2 common tools (DuckDuckGo, Tavily) + extensible toolset architecture
- **Parallel Execution**: Supported via asyncio with optional sequential mode (per-tool flag)

## Tool Modeling

### Core Abstraction

The framework uses a dual-layer abstraction:

1. **`Tool[AgentDepsT]`** - High-level wrapper for individual tools
2. **`AbstractToolset[AgentDepsT]`** - Container abstraction for tool collections

```python
@dataclass(init=False)
class Tool(Generic[ToolAgentDepsT]):
    """A tool function for an agent."""

    function: ToolFuncEither[ToolAgentDepsT]
    takes_ctx: bool
    max_retries: int | None
    name: str
    description: str | None
    prepare: ToolPrepareFunc[ToolAgentDepsT] | None
    docstring_format: DocstringFormat
    require_parameter_descriptions: bool
    strict: bool | None
    sequential: bool
    requires_approval: bool
    metadata: dict[str, Any] | None
    timeout: float | None
    function_schema: _function_schema.FunctionSchema
```

**Key Innovation: RunContext Auto-Detection**

Tools can optionally accept `RunContext[DepsT]` as the first parameter for dependency injection. The framework auto-detects this via signature introspection:

```python
# Tool with context
@agent.tool
async def customer_balance(ctx: RunContext[SupportDependencies]) -> str:
    balance = await ctx.deps.db.customer_balance(id=ctx.deps.customer_id)
    return f'${balance:.2f}'

# Tool without context
@agent.tool
def simple_calc(x: int, y: int) -> int:
    return x + y
```

### Key Attributes

| Attribute | Type | Purpose |
|-----------|------|---------|
| `function` | `ToolFuncEither[AgentDepsT]` | The actual Python function to call (sync or async) |
| `function_schema` | `FunctionSchema` | Pydantic-generated schema + validator |
| `name` | `str` | Tool identifier (defaults to function name) |
| `description` | `str \| None` | Tool description (extracted from docstring) |
| `takes_ctx` | `bool` | Whether function accepts RunContext as first param |
| `max_retries` | `int \| None` | Maximum retries for validation failures |
| `prepare` | `ToolPrepareFunc \| None` | Dynamic tool availability callback |
| `sequential` | `bool` | Forces serial execution (prevents parallelism) |
| `requires_approval` | `bool` | Human-in-the-loop approval flag |
| `timeout` | `float \| None` | Per-tool execution timeout in seconds |
| `metadata` | `dict[str, Any] \| None` | Arbitrary metadata (not sent to model) |
| `strict` | `bool \| None` | Enforce strict JSON schema (OpenAI/Anthropic) |

### ToolDefinition (Wire Format)

Separate from `Tool`, the `ToolDefinition` dataclass represents the minimal data sent to the model:

```python
@dataclass(repr=False, kw_only=True)
class ToolDefinition:
    name: str
    parameters_json_schema: ObjectJsonSchema
    description: str | None = None
    strict: bool | None = None
    sequential: bool = False
    kind: ToolKind = 'function'  # 'function' | 'output' | 'external' | 'unapproved'
    metadata: dict[str, Any] | None = None
    timeout: float | None = None
```

**Tool Kinds:**
- `'function'`: Standard tool executed during agent run
- `'output'`: Structured output extraction (ends the run)
- `'external'`: Deferred execution (requires manual result provision)
- `'unapproved'`: Requires human approval before execution

## Schema Generation

### Method Used: Pydantic Introspection + Docstring Parsing

The framework automatically generates JSON schemas from Python function signatures using Pydantic's internal APIs:

```python
# From _function_schema.py
def function_schema(
    function: Callable[..., Any],
    schema_generator: type[GenerateJsonSchema],
    takes_ctx: bool | None = None,
    docstring_format: DocstringFormat = 'auto',
    require_parameter_descriptions: bool = False,
) -> FunctionSchema
```

**Process:**

1. **Signature Inspection**: Extract parameters using `inspect.signature()`
2. **Type Hints Extraction**: Use `_typing_extra.get_function_type_hints()`
3. **Docstring Parsing**: Extract descriptions via `doc_descriptions()` (supports Google/Numpy/Sphinx)
4. **Pydantic Core Schema**: Build `TypedDictSchema` for parameters
5. **JSON Schema Generation**: Use `GenerateToolJsonSchema` (custom subclass)
6. **Validator Creation**: Create `SchemaValidator` for runtime validation

### Docstring Format Support

```python
DocstringFormat = Literal['google', 'numpy', 'sphinx', 'auto']
```

**Example (Google Style):**

```python
@agent.tool
def customer_balance(ctx: RunContext[SupportDependencies]) -> str:
    """Returns the customer's current account balance.

    Args:
        ctx: The run context with customer dependencies.

    Returns:
        The balance formatted as a dollar amount.
    """
    balance = ctx.deps.db.customer_balance(id=ctx.deps.customer_id)
    return f'${balance:.2f}'
```

### Generated Schema Example

For the `customer_balance` tool above, the generated schema:

```json
{
  "type": "object",
  "properties": {},
  "required": [],
  "additionalProperties": false
}
```

(The `ctx` parameter is filtered out since it's not a model parameter)

**For a tool with parameters:**

```python
@agent.tool
def search(query: str, max_results: int = 10) -> list[dict]:
    """Search for information."""
```

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "The search query"
    },
    "max_results": {
      "type": "integer",
      "default": 10,
      "description": "Maximum results to return"
    }
  },
  "required": ["query"],
  "additionalProperties": false
}
```

### Custom Schema Generator

The framework uses a customized `GenerateToolJsonSchema` that:

1. **Removes property titles** (reduces schema verbosity)
2. **Handles TypedDict extras** (workaround for Pydantic issue #12123)
3. **Preserves additionalProperties** for var_kwargs

```python
class GenerateToolJsonSchema(GenerateJsonSchema):
    def _named_required_fields_schema(self, named_required_fields):
        s = super()._named_required_fields_schema(named_required_fields)
        for p in s.get('properties', {}):
            s['properties'][p].pop('title', None)  # Remove property titles
        return s
```

## Built-in Tool Inventory

### Vendor-Specific Builtin Tools (9 tools)

These are NOT implemented in Python but provided by the LLM vendor:

| Tool Name | Vendors | Purpose | Category |
|-----------|---------|---------|----------|
| `WebSearchTool` | Anthropic, OpenAI, Groq, Google | Web search with domain filtering | Information Retrieval |
| `CodeExecutionTool` | Anthropic, OpenAI, Google | Execute code in sandboxed environment | Computation |
| `WebFetchTool` | Anthropic, Google | Fetch content from URLs | Information Retrieval |
| `ImageGenerationTool` | OpenAI, Google | Generate images from prompts | Generation |
| `MemoryTool` | Anthropic | Persistent memory across sessions | State Management |
| `MCPServerTool` | OpenAI, Anthropic | Connect to MCP servers | Integration |
| `FileSearchTool` | OpenAI, Google | Vector search over uploaded files (RAG) | Information Retrieval |
| `UrlContextTool` | (deprecated) | Alias for WebFetchTool | Information Retrieval |

**Location**: `/repos/pydantic-ai/pydantic_ai_slim/pydantic_ai/builtin_tools.py`

**Registration Pattern**: Passed via `ModelRequestParameters` to the model API, not executed by pydantic-ai.

```python
@dataclass(kw_only=True)
class AbstractBuiltinTool(ABC):
    kind: str = 'unknown_builtin_tool'

    @property
    def unique_id(self) -> str:
        return self.kind

    @property
    def label(self) -> str:
        return self.kind.replace('_', ' ').title()
```

### Common Tools (2 tools)

Python-implemented tool functions for third-party APIs:

| Tool Name | Location | Schema Method | Category |
|-----------|----------|---------------|----------|
| `duckduckgo_search` | `common_tools/duckduckgo.py` | Function introspection | Web Search |
| `tavily_search` | `common_tools/tavily.py` | Function introspection | Web Search |

**Example: DuckDuckGo Tool**

```python
@dataclass
class DuckDuckGoSearchTool:
    client: DDGS
    max_results: int | None

    async def __call__(self, query: str) -> list[DuckDuckGoResult]:
        """Searches DuckDuckGo for the given query and returns the results."""
        search = functools.partial(self.client.text, max_results=self.max_results)
        results = await anyio.to_thread.run_sync(search, query)
        return duckduckgo_ta.validate_python(results)

def duckduckgo_search_tool(duckduckgo_client: DDGS | None = None, max_results: int | None = None):
    return Tool[Any](
        DuckDuckGoSearchTool(client=duckduckgo_client or DDGS(), max_results=max_results).__call__,
        name='duckduckgo_search',
        description='Searches DuckDuckGo for the given query and returns the results.',
    )
```

### Toolset Implementations (8+ varieties)

The framework provides composable toolset wrappers:

| Toolset | Purpose | File |
|---------|---------|------|
| `FunctionToolset` | Base toolset for Python functions | `toolsets/function.py` |
| `CombinedToolset` | Merge multiple toolsets | `toolsets/combined.py` |
| `FilteredToolset` | Filter tools by predicate | `toolsets/filtered.py` |
| `PrefixedToolset` | Add namespace prefix to tool names | `toolsets/prefixed.py` |
| `RenamedToolset` | Rename tools via mapping | `toolsets/renamed.py` |
| `PreparedToolset` | Dynamic tool modification | `toolsets/prepared.py` |
| `ApprovalRequiredToolset` | Human-in-the-loop wrapper | `toolsets/approval_required.py` |
| `FastMCPToolset` | MCP server integration | `toolsets/fastmcp.py` |
| `ExternalToolset` | Deferred execution wrapper | `toolsets/external.py` |

## Registration & Discovery

### Pattern: Declarative via Decorator + Explicit Add

**1. Decorator Pattern (Most Common)**

```python
agent = Agent('openai:gpt-5', deps_type=MyDeps)

@agent.tool
async def my_tool(ctx: RunContext[MyDeps], x: int) -> str:
    return f"{ctx.deps.value} {x}"
```

**2. Explicit Tool Addition**

```python
from pydantic_ai import Tool

def my_function(x: int) -> str:
    return f"Result: {x}"

tool = Tool(my_function, name='my_tool', description='Does something')
agent.add_tool(tool)
```

**3. Toolset Pattern**

```python
from pydantic_ai import FunctionToolset

toolset = FunctionToolset()

@toolset.tool
def tool_one(x: int) -> str:
    return str(x)

@toolset.tool
def tool_two(y: float) -> float:
    return y * 2

agent = Agent('openai:gpt-5', toolsets=[toolset])
```

### Registration Flow

```
User Code
    ↓
@agent.tool decorator
    ↓
Tool.__init__()
    ↓ (calls)
function_schema() - Introspects function, builds FunctionSchema
    ↓
FunctionSchema stores:
    - validator: SchemaValidator (Pydantic Core)
    - json_schema: ObjectJsonSchema
    - takes_ctx: bool
    - is_async: bool
    ↓
Agent stores Tool in internal registry
    ↓
On agent.run():
    ↓
ToolManager.get_tools() - Calls prepare() if present
    ↓
Returns dict[str, ToolsetTool] to execution engine
```

### Dynamic Tool Availability: `prepare` Function

Tools can be conditionally registered per run:

```python
async def only_if_42(
    ctx: RunContext[int], tool_def: ToolDefinition
) -> ToolDefinition | None:
    if ctx.deps == 42:
        return tool_def
    return None  # Omit tool from this run

@agent.tool(prepare=only_if_42)
def hitchhiker(ctx: RunContext[int], answer: str) -> str:
    return f'{ctx.deps} {answer}'
```

### Multiple Tool Preparation: `prepare_tools`

Modify all tools at once:

```python
async def turn_on_strict_if_openai(
    ctx: RunContext[None], tool_defs: list[ToolDefinition]
) -> list[ToolDefinition] | None:
    if ctx.model.system == 'openai':
        return [replace(tool_def, strict=True) for tool_def in tool_defs]
    return tool_defs

agent = Agent('openai:gpt-4o', prepare_tools=turn_on_strict_if_openai)
```

## Execution Flow

### Invocation Pattern

```
Model returns ToolCallPart
    ↓
ToolManager.handle_call()
    ↓
ToolManager._call_tool()
    ↓
1. Retrieve tool from registry
2. Validate args via tool.args_validator
3. Call toolset.call_tool(name, args_dict, ctx, tool)
    ↓
FunctionSchema.call(args_dict, ctx)
    ↓
Execute function (sync or async)
    ↓
Return result to model
```

### Validation Flow

**From `_tool_manager.py`:**

```python
async def _call_tool(
    self,
    call: ToolCallPart,
    *,
    allow_partial: bool,
    wrap_validation_errors: bool,
    approved: bool,
) -> Any:
    name = call.tool_name
    tool = self.tools.get(name)

    try:
        if tool is None:
            raise ModelRetry(f'Unknown tool name: {name!r}. Available tools: ...')

        # Create execution context
        ctx = replace(
            self.ctx,
            tool_name=name,
            tool_call_id=call.tool_call_id,
            retry=self.ctx.retries.get(name, 0),
            max_retries=tool.max_retries,
        )

        # Validate arguments
        pyd_allow_partial = 'trailing-strings' if allow_partial else 'off'
        validator = tool.args_validator

        if isinstance(call.args, str):
            args_dict = validator.validate_json(
                call.args or '{}',
                allow_partial=pyd_allow_partial,
                context=ctx.validation_context
            )
        else:
            args_dict = validator.validate_python(
                call.args or {},
                allow_partial=pyd_allow_partial,
                context=ctx.validation_context
            )

        # Call tool
        return await self.toolset.call_tool(name, args_dict, ctx, tool)

    except (ValidationError, ModelRetry) as e:
        max_retries = tool.max_retries if tool is not None else 1
        current_retry = self.ctx.retries.get(name, 0)

        if current_retry == max_retries:
            raise UnexpectedModelBehavior(
                f'Tool {name!r} exceeded max retries count of {max_retries}'
            ) from e
        else:
            if wrap_validation_errors:
                if isinstance(e, ValidationError):
                    # Convert to retry prompt
                    m = RetryPromptPart(
                        tool_name=name,
                        content=e.errors(include_url=False, include_context=False),
                        tool_call_id=call.tool_call_id,
                    )
                    e = ToolRetryError(m)

            self.failed_tools.add(name)
            raise e
```

### Error Handling

| Error Type | Handling | Feedback to LLM |
|------------|----------|-----------------|
| `ValidationError` (Pydantic) | Convert to `RetryPromptPart` with error details | Structured error list sent to model |
| `ModelRetry` (tool-raised) | Convert to `RetryPromptPart` with custom message | Custom message sent to model |
| `ToolRetryError` | Propagate up to graph execution layer | Retry prompt added to message history |
| `UnexpectedModelBehavior` | Raised when max retries exceeded | Run terminates with error |
| `TimeoutError` (per-tool timeout) | Convert to `ModelRetry` | "Timed out after X seconds" sent to model |

**Key Innovation: Validation Errors Fed Back to Model**

Unlike most frameworks that crash on validation errors, pydantic-ai formats them and sends them back to the model:

```python
# Example validation error sent to model
{
  "tool_name": "customer_balance",
  "content": [
    {
      "type": "missing",
      "loc": ["customer_id"],
      "msg": "Field required"
    }
  ],
  "tool_call_id": "call_123"
}
```

The model can then self-correct and retry the tool call.

### Retry Mechanisms

**Three-Layer Retry System:**

1. **Graph-Level Retries** (`max_result_retries`): For output validation failures
2. **Tool-Level Retries** (`max_retries` per tool): For tool execution/validation failures
3. **Model Retry Exception** (`ModelRetry`): Tool code can request retry with custom message

**Retry Counter Tracking:**

```python
# From _tool_manager.py
async def for_run_step(self, ctx: RunContext[AgentDepsT]) -> ToolManager[AgentDepsT]:
    if self.ctx is not None:
        if ctx.run_step == self.ctx.run_step:
            return self

        # Increment retry count for failed tools
        retries = {
            failed_tool_name: self.ctx.retries.get(failed_tool_name, 0) + 1
            for failed_tool_name in self.failed_tools
        }
        ctx = replace(ctx, retries=retries)

    return self.__class__(
        toolset=self.toolset,
        ctx=ctx,
        tools=await self.toolset.get_tools(ctx),
    )
```

### Timeout Handling

Tools can specify execution timeouts:

```python
@agent.tool(timeout=5.0)  # 5 second timeout
async def slow_operation(x: int) -> str:
    await asyncio.sleep(10)  # Will timeout
    return "Done"
```

**Implementation:**

```python
# From function.py
async def call_tool(self, name: str, tool_args: dict[str, Any], ctx: RunContext[AgentDepsT], tool: ToolsetTool[AgentDepsT]) -> Any:
    timeout = tool.timeout if tool.timeout is not None else self.timeout
    if timeout is not None:
        try:
            with anyio.fail_after(timeout):
                return await tool.call_func(tool_args, ctx)
        except TimeoutError:
            raise ModelRetry(f'Timed out after {timeout} seconds.') from None
    else:
        return await tool.call_func(tool_args, ctx)
```

## Parallel Execution

### Supported: Asyncio with Optional Sequential Mode

**Default Behavior**: Parallel execution via `asyncio.gather()`

```python
# From graph execution code
results = await asyncio.gather(
    *(tool_manager.handle_call(call) for call in tool_calls),
    return_exceptions=True
)
```

**Per-Tool Sequential Flag:**

```python
@agent.tool(sequential=True)
async def database_write(ctx: RunContext[DB], data: str) -> str:
    """This tool modifies shared state, must run serially."""
    await ctx.deps.db.write(data)
    return "Written"
```

**Enforcement:**

```python
# From _tool_manager.py
def should_call_sequentially(self, calls: list[ToolCallPart]) -> bool:
    return _sequential_tool_calls_ctx_var.get() or any(
        tool_def.sequential
        for call in calls
        if (tool_def := self.get_tool_def(call.tool_name))
    )
```

**Context Manager for Global Sequential Mode:**

```python
async with ToolManager.sequential_tool_calls():
    # All tool calls in this context run sequentially
    result = await agent.run("Do multiple things")
```

## Code References

### Core Files

- **`tools.py`**: Tool class, ToolDefinition, type aliases (lines 1-539)
- **`_function_schema.py`**: Schema generation from functions (lines 1-304)
- **`_tool_manager.py`**: Tool execution and retry logic (lines 1-275)
- **`builtin_tools.py`**: Vendor-specific builtin tool definitions (lines 1-471)

### Toolset Architecture

- **`toolsets/abstract.py`**: AbstractToolset protocol (lines 1-192)
- **`toolsets/function.py`**: FunctionToolset implementation (lines 1-384)
- **`toolsets/combined.py`**: Toolset composition (lines 1-100)
- **`toolsets/fastmcp.py`**: MCP integration (lines 1-100+)

### Schema Generation

- **`_griffe.py`**: Docstring parsing for parameter descriptions
- **`_json_schema.py`**: JSON schema transformation utilities (lines 1-200)

### Error Handling

- **`exceptions.py`**: ModelRetry, ToolRetryError, ValidationError handling
- **`messages.py`**: RetryPromptPart, ToolCallPart, ToolReturn message types

## Implications for New Framework

### Positive Patterns

1. **RunContext Auto-Detection**: Elegant dependency injection without explicit registration
   - Introspection of first parameter type eliminates boilerplate
   - Type-safe via generic `RunContext[DepsT]`

2. **Validation Errors as Feedback**: Game-changing error handling
   - Pydantic ValidationError → Structured JSON → Model self-correction
   - Dramatically reduces retry loops vs. crashing

3. **Dual-Layer Abstraction**: Tool vs. Toolset separation
   - Tool: Individual function wrapper
   - Toolset: Composable collection with lifecycle management
   - Enables filtering, prefixing, approval workflows

4. **Prepare Functions**: Dynamic tool availability
   - Tools can be conditionally available based on runtime context
   - `prepare` callback receives ToolDefinition, returns modified or None

5. **Schema Generator Customization**: Extensible JSON schema generation
   - Custom `GenerateToolJsonSchema` subclass
   - Can override per-tool via `schema_generator` parameter

6. **Toolset Composition**: Decorator pattern for toolsets
   - `.filtered()`, `.prefixed()`, `.renamed()`, `.approval_required()`
   - Fluent API for building complex tool hierarchies

7. **Timeout Support**: Per-tool execution timeouts
   - Graceful timeout → ModelRetry with message
   - Prevents hung tool calls from blocking agent

### Considerations

1. **Complex Type System**: Heavy use of TypeVars and Generics
   - `Tool[ToolAgentDepsT]`, `RunContext[AgentDepsT]`, etc.
   - May be challenging for developers unfamiliar with advanced typing

2. **Pydantic Internal APIs**: Brittle dependency on private Pydantic APIs
   - `_generate_schema.GenerateSchema`, `_decorators`, `_typing_extra`
   - Risk of breakage on Pydantic version updates

3. **Docstring Format Detection**: Auto-detection can be fragile
   - Supports Google/Numpy/Sphinx but may misparse
   - Recommend explicit `docstring_format` parameter

4. **Toolset Visitor Pattern**: Complex traversal for nested toolsets
   - `apply()` and `visit_and_replace()` methods
   - Required for durable execution (Temporal) but adds complexity

5. **No Built-in Tool Implementations**: Vendor tools are just schemas
   - Framework doesn't implement builtin tools, relies on vendor APIs
   - Common tools (DuckDuckGo, Tavily) require separate dependencies

## Anti-Patterns Observed

1. **Overloaded Tool Class**: Too many responsibilities
   - Schema generation, validation, execution, retry logic all in one
   - Consider splitting into ToolDefinition (schema) vs. ToolExecutor (runtime)

2. **Global ContextVar for Sequential Mode**: Hidden state
   - `_sequential_tool_calls_ctx_var` is a module-level ContextVar
   - Prefer explicit parameter passing

3. **Retry Counter in RunContext**: Mutable state propagation
   - `ctx.retries` dict modified during execution
   - Could lead to surprising behavior in nested calls

4. **Tool Name Conflicts**: Late detection
   - Conflicts only detected at `get_tools()` time (during run)
   - Should validate at registration time

5. **TypedDict Schema Workaround**: Pydantic issue workaround
   - Custom `GenerateToolJsonSchema.typed_dict_schema()` for additionalProperties
   - Technical debt from upstream Pydantic issue #12123

6. **String-Based Tool Invocation**: Dict-based call args
   - `call_tool(name: str, tool_args: dict[str, Any], ...)`
   - Loses type safety at invocation boundary

## Unique Innovations

1. **FunctionSchema Dataclass**: Unified schema + validator + callable
   ```python
   @dataclass(kw_only=True)
   class FunctionSchema:
       function: Callable[..., Any]
       description: str | None
       validator: SchemaValidator
       json_schema: ObjectJsonSchema
       takes_ctx: bool
       is_async: bool

       async def call(self, args_dict: dict[str, Any], ctx: RunContext[Any]) -> Any:
           # Unified invocation handling sync/async
   ```

2. **ToolDefinition Kind System**: Multi-purpose tool abstraction
   - `'function'`: Normal tool execution
   - `'output'`: Structured output extraction (ends run)
   - `'external'`: Deferred execution (human/service completes)
   - `'unapproved'`: Human-in-the-loop approval required

3. **DeferredToolRequests/Results**: Async tool execution pattern
   ```python
   # Run returns deferred requests instead of output
   result = await agent.run("Transfer $1000")
   if isinstance(result.output, DeferredToolRequests):
       # Present to user for approval
       approved = get_user_approval(result.output.approvals)
       # Resume with results
       final = await agent.run(
           "Continue",
           deferred_tool_results=DeferredToolResults(approvals={...})
       )
   ```

4. **Metadata Not Sent to Model**: Tool metadata for framework use
   - `tool.metadata` dict for filtering, behavior customization
   - Not included in JSON schema sent to model
   - Enables framework-level tool categorization

5. **Partial Validation Support**: Streaming-friendly validation
   ```python
   args_dict = validator.validate_json(
       call.args,
       allow_partial='trailing-strings'
   )
   ```
   - Enables validation of incomplete JSON during streaming
   - Graceful degradation for slow tool calls

## Recommendations for Elixir Framework

1. **Adopt RunContext Pattern**: Dependency injection via special first parameter
   - Use pattern matching on function clauses to detect context parameter
   - Provide `ToolContext.t()` typespec for type safety

2. **Implement Validation-as-Feedback**: Don't crash on validation errors
   - Use Ecto changeset errors as structured retry messages
   - Format changesets as JSON, send to model for self-correction

3. **Dual Abstraction Layer**: Separate Tool from Toolset
   - Tool: Individual function metadata + schema
   - Toolset: Behaviour for tool discovery, validation, execution

4. **Schema Generation via Typespecs**: Extract from function typespecs
   - Parse `@spec` annotations to generate JSON schema
   - Support `@doc` extraction for descriptions
   - Fallback to runtime introspection via `Function.info/1`

5. **Composable Toolset Protocols**: Define Toolset behaviour
   ```elixir
   @callback get_tools(context :: ToolContext.t()) :: {:ok, [Tool.t()]} | {:error, term()}
   @callback call_tool(name :: String.t(), args :: map(), context :: ToolContext.t()) ::
       {:ok, term()} | {:error, term()}
   ```

6. **Avoid Global State**: No process dictionary for sequential mode
   - Pass execution mode explicitly in context
   - Use Agent state for retry counters, not hidden ContextVars

7. **Timeout via Task.yield**: Per-tool timeouts
   ```elixir
   task = Task.async(fn -> call_tool(name, args, ctx) end)
   case Task.yield(task, timeout) || Task.shutdown(task) do
     {:ok, result} -> {:ok, result}
     nil -> {:error, :timeout}
   end
   ```

8. **Prepare Callbacks as Optional MFA**: Dynamic tool availability
   ```elixir
   defmodule MyTool do
     def prepare(%ToolContext{} = ctx, %ToolDefinition{} = tool_def) do
       if authorized?(ctx), do: {:ok, tool_def}, else: :skip
     end
   end
   ```

9. **Metadata in Tool Struct**: Don't send to model, use for filtering
   ```elixir
   defstruct [:name, :description, :parameters, :metadata, :category, :requires_approval]
   ```

10. **Error Tuple Normalization**: Consistent error shape
    ```elixir
    {:error, %ToolError{tool: name, retry: count, message: msg, details: validation_errors}}
    ```
