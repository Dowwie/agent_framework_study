# Tool Interface Analysis: llama_index

## Summary
- **Tool Modeling**: Hybrid approach - Abstract base class (AsyncBaseTool) + Pydantic-based metadata + ToolSpec pattern for integrations
- **Schema Generation**: Introspection from function signatures + Pydantic models with automatic JSON Schema generation
- **Registration Pattern**: Explicit - tools passed directly to agent/LLM, no global registry
- **Error Handling**: Exception capture with error-as-data pattern (ToolOutput.is_error flag)
- **Built-in Tools**: 6 core tools + 63+ integration packages
- **Parallel Execution**: Flag-based (allow_parallel_tool_calls) with async support throughout

## Tool Modeling

### Core Abstraction

llama_index uses a three-tier inheritance hierarchy for tools:

```python
# Base protocol
class BaseTool(DispatcherSpanMixin):
    @property
    @abstractmethod
    def metadata(self) -> ToolMetadata:
        pass

    @abstractmethod
    def __call__(self, input: Any) -> ToolOutput:
        pass

# Async-capable base
class AsyncBaseTool(BaseTool):
    def __call__(self, *args: Any, **kwargs: Any) -> ToolOutput:
        return self.call(*args, **kwargs)

    @abstractmethod
    def call(self, input: Any) -> ToolOutput:
        pass

    @abstractmethod
    async def acall(self, input: Any) -> ToolOutput:
        pass
```

**Design Philosophy**: Every tool must support both sync and async execution. The framework provides an adapter (`BaseToolAsyncAdapter`) that wraps sync tools to provide async capability via `asyncio.to_thread()`.

### Key Attributes

The `ToolMetadata` dataclass defines tool characteristics:

| Attribute | Type | Purpose |
|-----------|------|---------|
| name | Optional[str] | Tool identifier (must be unique) |
| description | str | Natural language description for LLM |
| fn_schema | Optional[Type[BaseModel]] | Pydantic model defining parameters |
| return_direct | bool | Whether to return tool output without LLM processing |

The `ToolOutput` model captures execution results:

| Attribute | Type | Purpose |
|-----------|------|---------|
| blocks | List[ContentBlock] | Structured output (text/image/audio/citation blocks) |
| tool_name | str | Name of tool that produced output |
| raw_input | Dict[str, Any] | Original arguments passed to tool |
| raw_output | Any | Unprocessed return value |
| is_error | bool | Whether execution failed |
| exception | Optional[Exception] | Captured exception (private attr) |

**Notable Design**: ToolOutput uses `ContentBlock` abstraction supporting multimodal outputs (TextBlock, ImageBlock, AudioBlock, CitableBlock, CitationBlock) - rare among frameworks.

### Tool Implementations

llama_index provides six primary tool types:

1. **FunctionTool** - Wraps arbitrary functions with automatic schema generation
2. **QueryEngineTool** - Wraps RAG query engines for knowledge base access
3. **RetrieverTool** - Wraps retrievers for document retrieval
4. **QueryPlanTool** - Meta-tool that orchestrates other tools via DAG execution
5. **OnDemandLoaderTool** - Loads data on-demand, indexes it, and queries
6. **EvalQueryEngineTool** - Wraps query engine with evaluation-based filtering

### ToolSpec Pattern

For integration packages, llama_index uses a `BaseToolSpec` pattern:

```python
class BaseToolSpec:
    spec_functions: List[Union[str, Tuple[str, str]]]

    def to_tool_list(self) -> List[FunctionTool]:
        # Converts spec functions to FunctionTool instances
        pass
```

Integration authors inherit from `BaseToolSpec`, list method names in `spec_functions`, and call `to_tool_list()` to generate tools.

## Schema Generation

### Method Used

llama_index uses **function signature introspection** combined with **Pydantic model generation**:

```python
def create_schema_from_function(
    name: str,
    func: Callable,
    additional_fields: Optional[List[Tuple[str, Type, Any]]] = None,
    ignore_fields: Optional[List[str]] = None,
) -> Type[BaseModel]:
    fields = {}
    params = signature(func).parameters

    for param_name in params:
        if param_name in ignore_fields:
            continue

        param_type = params[param_name].annotation
        param_default = params[param_name].default
        description = None

        # Extract from Annotated types
        if get_origin(param_type) is typing.Annotated:
            args = get_args(param_type)
            param_type = args[0]
            if isinstance(args[1], str):
                description = args[1]
            elif isinstance(args[1], FieldInfo):
                description = args[1].description

        # Build Pydantic field
        if param_default is params[param_name].empty:
            fields[param_name] = (param_type, FieldInfo(description=description))
        else:
            fields[param_name] = (param_type, FieldInfo(default=param_default, description=description))

    return create_model(name, **fields)
```

**Key Features**:
- Supports `typing.Annotated` for inline parameter descriptions
- Extracts descriptions from `pydantic.Field` defaults
- Automatically maps `datetime.date`, `datetime.datetime`, `datetime.time` to JSON Schema formats
- Filters out special parameters (`self`, `Context`, partial params)
- Parses docstrings (Sphinx, Google, Javadoc styles) for parameter descriptions

### Docstring Parsing

FunctionTool extracts parameter descriptions from docstrings:

```python
@staticmethod
def extract_param_docs(docstring: str, fn_params: Optional[set] = None) -> Tuple[dict, set]:
    raw_param_docs = {}

    # Sphinx style: ":param name: description"
    for match in re.finditer(r":param (\w+): (.+)", docstring):
        raw_param_docs[match.group(1)] = match.group(2)

    # Google style: "name (type): description"
    for match in re.finditer(r"^\s*(\w+)\s*\(.*?\):\s*(.+)$", docstring, re.MULTILINE):
        raw_param_docs[match.group(1)] = match.group(2)

    # Javadoc style: "@param name description"
    for match in re.finditer(r"@param (\w+)\s+(.+)", docstring):
        raw_param_docs[match.group(1)] = match.group(2)

    return raw_param_docs, unknown_params
```

### Generated Schema Example

For a function like:

```python
def weather_at_location(location: str) -> List[Document]:
    """
    Finds the current weather at a location.

    Args:
        location (str): The place to find the weather at. Should be a city name and country.
    """
    pass
```

The generated schema would be:

```json
{
  "type": "object",
  "properties": {
    "location": {
      "type": "string",
      "description": "The place to find the weather at. Should be a city name and country."
    }
  },
  "required": ["location"]
}
```

### OpenAI Tool Format

`ToolMetadata.to_openai_tool()` generates the OpenAI-compatible format:

```python
def to_openai_tool(self, skip_length_check: bool = False) -> Dict[str, Any]:
    if not skip_length_check and len(self.description) > 1024:
        raise ValueError(
            "Tool description exceeds maximum length of 1024 characters. "
            "Please shorten your description or move it to the prompt."
        )
    return {
        "type": "function",
        "function": {
            "name": self.name,
            "description": self.description,
            "parameters": self.get_parameters_dict(),
        },
    }
```

**Notable**: llama_index enforces OpenAI's 1024-character description limit with helpful error message.

## Built-in Tool Inventory

### Core Tools (llama-index-core)

| Tool Name | Location | Schema Method | Purpose |
|-----------|----------|---------------|---------|
| FunctionTool | core/tools/function_tool.py | Introspection | Wraps arbitrary Python functions |
| QueryEngineTool | core/tools/query_engine.py | Default schema | Wraps RAG query engines |
| RetrieverTool | core/tools/retriever_tool.py | Default schema | Wraps document retrievers |
| QueryPlanTool | core/tools/query_plan.py | Pydantic (QueryPlan) | Executes multi-step query DAGs |
| OnDemandLoaderTool | core/tools/ondemand_loader_tool.py | Introspection | Loads/indexes/queries on-demand |
| EvalQueryEngineTool | core/tools/eval_query_engine.py | Default schema | Query engine with evaluation filter |

### Integration Categories (63 packages)

| Category | Count | Example Tools |
|----------|-------|---------------|
| Search | 8 | arxiv, brave-search, bing-search, duckduckgo, exa, wikipedia |
| Code Execution | 3 | code-interpreter, azure-code-interpreter, python-file |
| Cloud Services | 15 | aws-bedrock, azure-cv, azure-speech, azure-translate, box, salesforce |
| Data/Database | 5 | cassandra, database, vector-db, waii, vectara-query |
| Web | 6 | playwright, requests, chatgpt-plugin, openapi, graphql, scrapegraph |
| AI/ML | 5 | openai (image gen), text-to-image, elevenlabs, typecast |
| Communication | 3 | slack, jira, notion |
| Finance | 3 | finance, yahoo-finance, valyu |
| Productivity | 5 | jira-issue, shopify, zapier, signnow, cogniswitch |
| Research | 5 | tavily-research, linkup-research, dappier, desearch, metaphor |
| Other | 5 | weather, wolfram-alpha, yelp, ionic-shopping, mcp |

### Complete Integration Tool List (Sample)

| Package | Tools | Description |
|---------|-------|-------------|
| llama-index-tools-arxiv | arxiv_query | Search academic papers on arXiv |
| llama-index-tools-weather | weather_at_location, forecast_tomorrow_at_location | Get weather data via OpenWeatherMap |
| llama-index-tools-code-interpreter | code_interpreter | Execute Python code in subprocess |
| llama-index-tools-brave-search | brave_search | Web search via Brave Search API |
| llama-index-tools-wikipedia | wikipedia_search | Search Wikipedia articles |
| llama-index-tools-wolfram-alpha | wolfram_query | Query Wolfram Alpha knowledge engine |
| llama-index-tools-playwright | browser_navigate, click_element, fill_form, etc. | Browser automation |
| llama-index-tools-database | load_data, describe_tables | SQL database queries |
| llama-index-tools-openai | generate_image | Image generation via DALL-E |
| llama-index-tools-slack | load_data, send_message | Slack integration |

**Total**: 6 core tools + 63 integration packages with 150+ individual tool functions

## Registration & Discovery

### Pattern: Explicit List-Based Registration

llama_index uses **explicit registration** - tools are passed directly to the agent or LLM:

```python
# Agent workflow registration
from llama_index.core.agent import FunctionAgent
from llama_index.core.tools import FunctionTool

tools = [
    FunctionTool.from_defaults(fn=my_function),
    QueryEngineTool.from_defaults(query_engine=engine),
]

agent = FunctionAgent(llm=llm, tools=tools)
```

**No global registry** - each agent/workflow maintains its own tool list.

### Discovery Flow

1. **Tool Creation**:
   - Direct instantiation: `FunctionTool(fn=func, metadata=metadata)`
   - Factory method: `FunctionTool.from_defaults(fn=func)`
   - ToolSpec conversion: `spec.to_tool_list()`

2. **Schema Generation** (lazy):
   - Schema generated during `from_defaults()` call
   - Cached in `ToolMetadata.fn_schema`

3. **LLM Integration**:
   - Agent calls `tool.metadata.to_openai_tool()` to get LLM-ready format
   - Tools serialized to function calling format at runtime

4. **Lookup**:
   - By name: `tools_by_name = {tool.metadata.name: tool for tool in tools}`
   - Linear scan through tool list (no index)

### Dynamic Tool Management

Tools can be added/removed during agent execution:

```python
# In workflow
async def step(ctx: Context):
    tools = await ctx.store.get("tools", default=[])
    new_tool = FunctionTool.from_defaults(fn=dynamic_func)
    tools.append(new_tool)
    await ctx.store.set("tools", tools)
```

**No registration hooks** - tools are just data passed between steps.

## Execution Flow

### Invocation Pattern

Tools are called via the `call()` / `acall()` methods:

```python
# Sync execution
result: ToolOutput = tool.call(*args, **kwargs)

# Async execution
result: ToolOutput = await tool.acall(*args, **kwargs)
```

### FunctionTool Execution Flow

```python
def call(self, *args: Any, **kwargs: Any) -> ToolOutput:
    # 1. Merge partial params
    all_kwargs = {**self.partial_params, **kwargs}

    # 2. Validate context requirement
    if self.requires_context and self.ctx_param_name not in all_kwargs:
        raise ValueError("Context is required for this tool")

    # 3. Execute function
    raw_output = self._fn(*args, **all_kwargs)

    # 4. Parse output into content blocks
    output_blocks = self._parse_tool_output(raw_output)

    # 5. Build default ToolOutput
    default_output = ToolOutput(
        blocks=output_blocks,
        tool_name=self.metadata.get_name(),
        raw_input={"args": args, "kwargs": all_kwargs},
        raw_output=raw_output,
    )

    # 6. Run callback if provided
    callback_result = self._run_sync_callback(raw_output)
    if callback_result is not None:
        if isinstance(callback_result, ToolOutput):
            return callback_result
        else:
            return ToolOutput(
                content=str(callback_result),
                tool_name=self.metadata.get_name(),
                raw_input={"args": args, "kwargs": all_kwargs},
                raw_output=raw_output,
            )

    # 7. Return default output
    return default_output
```

### call_tool Helper

The framework provides a `call_tool()` helper with error handling:

```python
def call_tool(tool: BaseTool, arguments: dict) -> ToolOutput:
    try:
        # Handle single-arg tools (positional vs kwargs)
        if (
            len(tool.metadata.get_parameters_dict()["properties"]) == 1
            and len(arguments) == 1
        ):
            try:
                single_arg = arguments[next(iter(arguments))]
                return tool(single_arg)
            except Exception:
                # Some tools require kwargs
                return tool(**arguments)
        else:
            return tool(**arguments)
    except Exception as e:
        return ToolOutput(
            content="Encountered error: " + str(e),
            tool_name=tool.metadata.get_name(),
            raw_input=arguments,
            raw_output=str(e),
            is_error=True,
            exception=e,
        )
```

**Key Behavior**: Exceptions are caught and returned as error ToolOutputs (error-as-data pattern).

## Error Handling

### Strategy: Error-as-Data with LLM Feedback

| Error Type | Handling | Feedback to LLM |
|------------|----------|-----------------|
| Tool execution exception | Caught, wrapped in ToolOutput | Error message in content field |
| Validation error | Raised immediately | Not sent to LLM (fails fast) |
| Context missing | Raised immediately | Not sent to LLM (fails fast) |
| Tool not found | KeyError in lookup dict | Not handled by tool layer |
| Invalid arguments | Exception during call | Wrapped as error ToolOutput |

### Error ToolOutput Structure

```python
ToolOutput(
    content="Encountered error: division by zero",
    tool_name="calculator",
    raw_input={"a": 10, "b": 0},
    raw_output="division by zero",
    is_error=True,
    exception=ZeroDivisionError("division by zero"),
)
```

The error is converted to a tool message and sent back to LLM:

```python
ChatMessage(
    role="tool",
    blocks=tool_output.blocks,  # Contains error text
    additional_kwargs={"tool_call_id": tool_id},
)
```

### Evaluation-Based Error Filtering

`EvalQueryEngineTool` adds evaluation layer:

```python
def call(self, *args: Any, **kwargs: Any) -> ToolOutput:
    tool_output = super().call(*args, **kwargs)

    # Evaluate the output
    evaluation_result = self._evaluator.evaluate_response(
        tool_output.raw_input["input"],
        tool_output.raw_output
    )

    # Replace content if evaluation fails
    if not evaluation_result.passing:
        tool_output.content = (
            f"Could not use tool {self.metadata.name} "
            f"because it failed evaluation.\nReason: {evaluation_result.feedback}"
        )

    return tool_output
```

**Pattern**: Tool executes successfully but output is replaced with evaluation failure message.

### Retry Mechanisms

**No built-in retry logic** - retry is handled at agent level via conversation loop:

1. Agent calls tool
2. Tool returns error ToolOutput
3. Error sent back to LLM as tool message
4. LLM sees error and generates new tool call (or gives up)

**Notable absence**: No retry limits, circuit breakers, or exponential backoff at tool level.

## Parallel Execution

### Support: Async-First with Parallel Flag

llama_index supports parallel tool execution via:

1. **Async primitives**: All tools have `acall()` method
2. **Parallel flag**: `allow_parallel_tool_calls` parameter
3. **LLM-driven**: LLM returns multiple tool calls, agent executes them concurrently

### Agent-Level Parallel Execution

```python
class FunctionAgent(BaseWorkflowAgent):
    allow_parallel_tool_calls: bool = Field(
        default=True,
        description="If True, call multiple tools in parallel. If False, call tools sequentially.",
    )

    async def _get_response(
        self, current_llm_input: List[ChatMessage], tools: Sequence[AsyncBaseTool]
    ) -> ChatResponse:
        return await self.llm.achat_with_tools(
            chat_history=current_llm_input,
            allow_parallel_tool_calls=self.allow_parallel_tool_calls,
            tools=tools,
        )
```

### Execution Pattern

When LLM returns multiple tool calls:

```python
# Sequential (allow_parallel_tool_calls=False)
for tool_call in tool_calls:
    result = await call_tool_with_selection(tool_call, tools)
    results.append(result)

# Parallel (allow_parallel_tool_calls=True) - conceptual
tasks = [
    call_tool_with_selection(tool_call, tools)
    for tool_call in tool_calls
]
results = await asyncio.gather(*tasks)
```

**Note**: The actual parallel execution logic is not shown in the tool layer code - it's handled by the workflow orchestration layer.

### Async Adapter

Sync tools are automatically wrapped for async execution:

```python
class BaseToolAsyncAdapter(AsyncBaseTool):
    def __init__(self, tool: BaseTool):
        self.base_tool = tool

    def call(self, input: Any) -> ToolOutput:
        return self.base_tool(input)

    async def acall(self, input: Any) -> ToolOutput:
        return await asyncio.to_thread(self.call, input)
```

**Thread pool execution** via `asyncio.to_thread()` for sync functions.

## Code References

### Core Tool Files
- `/llama-index-core/llama_index/core/tools/types.py:155-267` - BaseTool, AsyncBaseTool, ToolMetadata, ToolOutput
- `/llama-index-core/llama_index/core/tools/function_tool.py:67-449` - FunctionTool implementation
- `/llama-index-core/llama_index/core/tools/utils.py:21-108` - create_schema_from_function
- `/llama-index-core/llama_index/core/tools/calling.py:10-107` - call_tool, acall_tool helpers
- `/llama-index-core/llama_index/core/tools/query_engine.py:17-114` - QueryEngineTool
- `/llama-index-core/llama_index/core/tools/retriever_tool.py:26-136` - RetrieverTool
- `/llama-index-core/llama_index/core/tools/query_plan.py:84-234` - QueryPlanTool (DAG execution)
- `/llama-index-core/llama_index/core/tools/tool_spec/base.py:18-114` - BaseToolSpec

### Agent Integration
- `/llama-index-core/llama_index/core/agent/workflow/function_agent.py:18-196` - FunctionAgent (tool invocation)
- `/llama-index-core/llama_index/core/llms/function_calling.py:24-150` - FunctionCallingLLM interface

### Integration Examples
- `/llama-index-integrations/tools/llama-index-tools-arxiv/llama_index/tools/arxiv/base.py:9-40` - ArxivToolSpec
- `/llama-index-integrations/tools/llama-index-tools-weather/llama_index/tools/weather/base.py:9-128` - OpenWeatherMapToolSpec
- `/llama-index-integrations/tools/llama-index-tools-code-interpreter/llama_index/tools/code_interpreter/base.py:9-36` - CodeInterpreterToolSpec

## Implications for New Framework

### Positive Patterns

1. **Async-First Design**
   - Every tool has both sync and async methods
   - Automatic adapter for sync-only tools
   - Enables true parallel execution without blocking

2. **Multimodal ToolOutput**
   - ContentBlock abstraction (text/image/audio/citation)
   - Supports richer tool returns than plain strings
   - Future-proof for multimodal models

3. **ToolSpec Pattern**
   - Clean separation: core abstractions vs integrations
   - Integration authors don't write boilerplate
   - Automatic conversion from methods to tools

4. **Introspection + Pydantic**
   - No manual schema writing for most tools
   - Leverages Python type hints
   - Docstring parsing for descriptions

5. **Error-as-Data**
   - Exceptions don't crash agent loop
   - LLM can see and react to errors
   - Enables self-correction without retry logic

6. **Workflow Context Integration**
   - Tools can access workflow context
   - Filtered from schema automatically
   - Enables stateful tool execution

7. **Callback Hooks**
   - FunctionTool supports callbacks to override output
   - Useful for post-processing or side effects
   - Both sync and async callbacks supported

### Areas for Improvement

1. **No Retry Logic**
   - Error-as-data pattern relies on LLM to retry
   - No retry limits - LLM can loop indefinitely
   - Could benefit from circuit breaker pattern

2. **Linear Tool Lookup**
   - `tools_by_name` dict rebuilt each invocation
   - No indexing for large tool sets
   - Could use registry pattern for >100 tools

3. **Description Length Validation**
   - Only enforced for OpenAI tools
   - Other providers may have different limits
   - Should be provider-agnostic

4. **Partial Params Hidden**
   - `partial_params` filtered from schema but not documented
   - Tool appears to have fewer params than it accepts
   - Could confuse debugging

5. **Context Parameter Magic**
   - Automatically detects and filters `Context` params
   - Uses string comparison on type annotations
   - Could break with import aliases

6. **No Tool Versioning**
   - Tools identified only by name
   - No version field in metadata
   - Hard to deprecate or upgrade tools

7. **Limited Observability**
   - ToolOutput captures raw_input/raw_output
   - No timing, token usage, or cost tracking
   - Could integrate with instrumentation layer better

## Anti-Patterns Observed

### 1. Single-Arg Heuristic in call_tool

```python
if (
    len(tool.metadata.get_parameters_dict()["properties"]) == 1
    and len(arguments) == 1
):
    try:
        single_arg = arguments[next(iter(arguments))]
        return tool(single_arg)
    except Exception:
        return tool(**arguments)
```

**Issue**: Tries positional call first, falls back to kwargs on exception. Fragile heuristic that hides argument mismatch errors.

**Better approach**: Normalize to kwargs-only or require tools to declare positional preference.

### 2. Silent Callback Override

```python
callback_result = self._run_sync_callback(raw_output)
if callback_result is not None:
    if isinstance(callback_result, ToolOutput):
        return callback_result  # Completely replaces output
```

**Issue**: Callback can silently replace entire ToolOutput, bypassing raw_input/raw_output capture.

**Better approach**: Separate hooks for pre-processing, post-processing, and output transformation.

### 3. ToolSpec Magic String List

```python
class MyToolSpec(BaseToolSpec):
    spec_functions = ["method1", "method2"]  # String references
```

**Issue**: String-based references break refactoring tools and static analysis.

**Better approach**: Use decorators or explicit method registration.

### 4. Exception-as-Content

```python
ToolOutput(
    content="Encountered error: " + str(e),
    is_error=True,
)
```

**Issue**: Error details lost in string conversion. No structured error codes or categories.

**Better approach**: Structured error field with code, category, recoverable flag.

### 5. Global Default Schema

```python
class DefaultToolFnSchema(BaseModel):
    input: str
```

**Issue**: All schema-less tools default to single string input. Doesn't enforce any contract.

**Better approach**: Require explicit schema or raise error.

### 6. Context Filtering Side Effect

```python
tool_output_kwargs = {
    k: v for k, v in all_kwargs.items() if k != self.ctx_param_name
}
```

**Issue**: Context removed from ToolOutput raw_input, making it impossible to reproduce execution.

**Better approach**: Mark context as internal but preserve in debug output.

### 7. Evaluation Result Content Replacement

```python
if not evaluation_result.passing:
    tool_output.content = (
        f"Could not use tool {self.metadata.name} "
        f"because it failed evaluation.\nReason: {evaluation_result.feedback}"
    )
```

**Issue**: Mutates ToolOutput content after execution. Original output lost.

**Better approach**: Wrap original output or add evaluation metadata field.

## Recommendations for Elixir Framework

### Adopt from llama_index

1. **Async-first design** - All tools should support both sync and async execution
2. **Multimodal outputs** - Support rich content types beyond strings
3. **Error-as-data pattern** - Capture exceptions in structured output
4. **Introspection-based schemas** - Generate from function specs and typespecs
5. **Spec pattern for integrations** - Clean interface for third-party tools
6. **Workflow context support** - Tools can access agent context when needed

### Improve Upon

1. **Add structured error taxonomy** - Error codes, categories, recoverability flags
2. **Built-in retry/circuit breaker** - Don't rely solely on LLM retry
3. **Tool versioning** - Support deprecation and upgrades
4. **Observability hooks** - Timing, cost, token usage tracking
5. **Explicit registration** - Decorator-based or compile-time registration
6. **Validation layer** - Pre-execution argument validation
7. **Tool composition** - Support chaining and pipelines natively

### Elixir-Specific Adaptations

1. **Behaviour instead of base class** - Define `ToolBehaviour` with callbacks
2. **Spec-based validation** - Use Dialyzer specs for schema generation
3. **Process-based execution** - Isolate tool execution in supervised processes
4. **GenServer registry** - Use Registry for tool lookup (O(1) instead of linear)
5. **Telemetry integration** - Emit events for observability
6. **Pattern matching on results** - `{:ok, result} | {:error, reason}` instead of is_error flag
7. **Streaming results** - Support chunked/streaming outputs natively

### Example Elixir Tool API

```elixir
defmodule MyApp.Tools.Weather do
  use Elixir.ToolBehaviour

  @impl true
  def metadata do
    %ToolMetadata{
      name: "weather_lookup",
      description: "Get current weather for a location",
      schema: %{
        location: {:string, required: true, description: "City name"}
      }
    }
  end

  @impl true
  def call(%{location: location}, context) do
    case WeatherAPI.fetch(location) do
      {:ok, data} ->
        {:ok, %ToolOutput{
          content: format_weather(data),
          metadata: %{source: "openweathermap"}
        }}
      {:error, reason} ->
        {:error, %ToolError{
          code: :api_error,
          message: reason,
          recoverable: true
        }}
    end
  end
end
```

This leverages Elixir's strengths (pattern matching, supervision, processes) while adopting llama_index's successful patterns (async-first, error-as-data, introspection).
