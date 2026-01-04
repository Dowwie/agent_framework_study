# Tool Interface Analysis: ms-agent-framework

## Summary
- **Tool Modeling**: Protocol + Generic base class (`ToolProtocol` + `BaseTool`) with specialized implementations
- **Schema Generation**: Automatic introspection via Pydantic + `@ai_function` decorator
- **Registration Pattern**: Explicit list-based registration via `ChatOptions.tools` or agent initialization
- **Error Handling**: Structured error feedback with optional detailed exceptions, returned to LLM for self-correction
- **Built-in Tools**: 5 hosted tool types (MCP, WebSearch, FileSearch, CodeInterpreter) + unlimited custom AI functions
- **Parallel Execution**: Full async support with `asyncio.gather()` for concurrent tool invocation

## Tool Modeling

### Core Abstraction

The framework uses a dual-layer approach: a structural `Protocol` for type checking and a `BaseTool` class for shared functionality:

```python
@runtime_checkable
class ToolProtocol(Protocol):
    """Structural typing - any object with these attributes is a tool."""
    name: str
    description: str
    additional_properties: dict[str, Any] | None

    def __str__(self) -> str: ...


class BaseTool(SerializationMixin):
    """Shared implementation for hosted tools."""
    DEFAULT_EXCLUDE: ClassVar[set[str]] = {"additional_properties"}

    def __init__(
        self,
        *,
        name: str,
        description: str = "",
        additional_properties: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.name = name
        self.description = description
        self.additional_properties = additional_properties
        # Dynamic attribute assignment for provider-specific fields
        for key, value in kwargs.items():
            setattr(self, key, value)
```

**Key Design Decision**: The Protocol allows duck typing (any object with `name`, `description`, and `additional_properties` is a valid tool), while `BaseTool` provides concrete implementation for hosted tools.

### AIFunction: The Primary Tool Type

Most user-defined tools are `AIFunction` instances created via the `@ai_function` decorator:

```python
class AIFunction(BaseTool, Generic[ArgsT, ReturnT]):
    """Wraps a Python function with automatic schema generation."""

    INJECTABLE: ClassVar[set[str]] = {"func"}
    DEFAULT_EXCLUDE: ClassVar[set[str]] = {"input_model", "_invocation_duration_histogram"}

    def __init__(
        self,
        *,
        name: str,
        description: str = "",
        approval_mode: Literal["always_require", "never_require"] | None = None,
        max_invocations: int | None = None,
        max_invocation_exceptions: int | None = None,
        additional_properties: dict[str, Any] | None = None,
        func: Callable[..., Awaitable[ReturnT] | ReturnT] | None = None,
        input_model: type[ArgsT] | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, description=description, additional_properties=additional_properties, **kwargs)
        self.func = func
        self._instance = None  # For bound methods (class tools)
        self.input_model = self._resolve_input_model(input_model)
        self.approval_mode = approval_mode or "never_require"
        self.max_invocations = max_invocations
        self.invocation_count = 0
        self.max_invocation_exceptions = max_invocation_exceptions
        self.invocation_exception_count = 0
        self.type: Literal["ai_function"] = "ai_function"
        self._forward_runtime_kwargs: bool = False  # Enables kwargs injection
```

**Innovative Features**:
1. **Descriptor Protocol**: AIFunction implements `__get__` to support bound methods (tools defined in classes)
2. **Kwargs Injection**: Functions with `**kwargs` signature receive runtime context (user_id, api_token, etc.)
3. **Invocation Limits**: Built-in circuit breakers (`max_invocations`, `max_invocation_exceptions`)
4. **Approval Flow**: Native support for human-in-the-loop approval (`approval_mode="always_require"`)

### Key Attributes

| Attribute | Type | Purpose | Required |
|-----------|------|---------|----------|
| `name` | `str` | Tool identifier for LLM calls | Yes |
| `description` | `str` | Natural language description for LLM | Yes |
| `input_model` | `type[BaseModel]` | Pydantic model for parameter validation | Auto-generated |
| `func` | `Callable` | The actual Python function to execute | Yes (except hosted) |
| `approval_mode` | `Literal["always_require", "never_require"]` | Human approval requirement | No (default: "never_require") |
| `additional_properties` | `dict[str, Any]` | Provider-specific metadata | No |
| `max_invocations` | `int` | Circuit breaker for total calls | No |
| `max_invocation_exceptions` | `int` | Circuit breaker for errors | No |

## Schema Generation

### Method Used: Automatic Introspection + Pydantic

The framework automatically generates JSON schemas from function signatures using Pydantic's `create_model`:

```python
def _create_input_model_from_func(func: Callable[..., Any], name: str) -> type[BaseModel]:
    """Create a Pydantic model from a function's signature."""
    sig = inspect.signature(func)
    fields = {
        pname: (
            _parse_annotation(param.annotation) if param.annotation is not inspect.Parameter.empty else str,
            param.default if param.default is not inspect.Parameter.empty else ...,
        )
        for pname, param in sig.parameters.items()
        if pname not in {"self", "cls"}
        and param.kind not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
    }
    return create_model(f"{name}_input", **fields)
```

**Annotation Parsing**: Handles `Annotated[type, "description"]` syntax:

```python
def _parse_annotation(annotation: Any) -> Any:
    """Convert string annotations to Pydantic Field descriptions."""
    origin = get_origin(annotation)
    if origin is not None:
        if origin is Literal:
            return annotation  # Preserve Literal types for enums

        args = get_args(annotation)
        if len(args) > 1 and isinstance(args[1], str):
            # Annotated[int, "The count"] -> Annotated[int, Field(description="The count")]
            return Annotated[args[0], Field(description=args[1])]
    return annotation
```

### Usage Example

```python
from typing import Annotated
from agent_framework import ai_function

@ai_function
def search_hotels(
    location: Annotated[str, "City or region to search"],
    check_in: Annotated[str, "Check-in date (YYYY-MM-DD)"],
    guests: int = 2,
) -> str:
    """Search for available hotels."""
    return f"Found 3 hotels in {location}"

# Generated schema:
{
    "type": "function",
    "function": {
        "name": "search_hotels",
        "description": "Search for available hotels.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City or region to search",
                    "title": "Location"
                },
                "check_in": {
                    "type": "string",
                    "description": "Check-in date (YYYY-MM-DD)",
                    "title": "Check In"
                },
                "guests": {
                    "type": "integer",
                    "default": 2,
                    "title": "Guests"
                }
            },
            "required": ["location", "check_in"],
            "title": "search_hotels_input"
        }
    }
}
```

### Advanced Type Support

**Literal Types** (for enums):
```python
@ai_function
def categorize(
    category: Annotated[Literal["Data", "Security", "Network"], "The category"],
    issue: str,
) -> str:
    return f"{category}: {issue}"

# Generated schema includes enum constraint:
# "category": {"enum": ["Data", "Security", "Network"], "type": "string"}
```

**Nested Objects** (from JSON Schema):
```python
# Can also accept raw JSON schema for complex types
tool = AIFunction(
    name="create_order",
    description="Create order",
    input_model={
        "type": "object",
        "properties": {
            "customer": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"}
                },
                "required": ["name", "email"]
            }
        },
        "required": ["customer"]
    },
    func=lambda customer: f"Order created for {customer['name']}"
)
```

## Built-in Tool Inventory

### Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| **User-Defined** | `AIFunction` | Custom Python functions decorated with `@ai_function` |
| **Hosted Search** | `HostedWebSearchTool`, `HostedFileSearchTool` | Delegate search to LLM provider (Azure, OpenAI) |
| **Hosted Execution** | `HostedCodeInterpreterTool` | Server-side code execution via provider |
| **MCP Integration** | `HostedMCPTool` | Connect to Model Context Protocol servers |
| **Agent Delegation** | `ChatAgent.as_tool()` | Convert agents into tools for hierarchical workflows |

### Complete Tool List

| Tool Name | Location | Schema Method | Category | Declaration-Only |
|-----------|----------|---------------|----------|------------------|
| `AIFunction` | `agent_framework._tools` | Introspection | User-Defined | No |
| `HostedWebSearchTool` | `agent_framework._tools` | Fixed schema | Hosted Search | Yes |
| `HostedFileSearchTool` | `agent_framework._tools` | Content-based | Hosted Search | Yes |
| `HostedCodeInterpreterTool` | `agent_framework._tools` | Content-based | Hosted Execution | Yes |
| `HostedMCPTool` | `agent_framework._tools` | MCP protocol | MCP Integration | Yes |
| `ChatAgent.as_tool()` | `agent_framework._agents` | Dynamic | Agent Delegation | No |

### Hosted Tool Examples

**Web Search Tool**:
```python
search_tool = HostedWebSearchTool(
    description="Search the web for information",
    additional_properties={"user_location": {"city": "Seattle", "country": "US"}},
)
```

**MCP Tool** (connects to external MCP servers):
```python
mcp_tool = HostedMCPTool(
    name="github_mcp",
    url="https://mcp-server.example.com",
    approval_mode={
        "always_require_approval": ["delete_repo", "push_code"],
        "never_require_approval": ["list_repos", "get_file"],
    },
    allowed_tools=["list_repos", "get_file", "create_issue"],
    headers={"Authorization": "Bearer token"},
)
```

**File Search Tool**:
```python
file_search = HostedFileSearchTool(
    inputs=[{"vector_store_id": "vs_abc123"}],
    max_results=10,
    description="Search uploaded documents",
)
```

**Code Interpreter**:
```python
code_tool = HostedCodeInterpreterTool(
    inputs=[{"file_id": "file-123"}, {"file_id": "file-456"}],
    description="Execute Python code with uploaded files",
)
```

### User-Defined Tool Examples (from samples)

The framework's sample applications demonstrate rich tool patterns:

**Travel Planning Domain** (11 tools):
1. `search_hotels` - Hotel search by location/dates
2. `get_hotel_details` - Detailed hotel information
3. `search_flights` - Flight search with routing
4. `get_flight_details` - Flight-specific details
5. `search_activities` - Activity/attraction search
6. `get_activity_details` - Activity-specific details
7. `confirm_booking` - Booking confirmation
8. `check_hotel_availability` - Real-time availability
9. `check_flight_availability` - Seat availability
10. `check_activity_availability` - Activity slots
11. `process_payment` - Payment processing
12. `validate_payment_method` - Payment validation

All defined using the same pattern:
```python
@ai_function(name="search_hotels", description="Search for available hotels")
def search_hotels(
    location: Annotated[str, Field(description="City or region")],
    check_in: Annotated[str, Field(description="Check-in date")],
    check_out: Annotated[str, Field(description="Check-out date")],
    guests: Annotated[int, Field(description="Number of guests")] = 2,
) -> str:
    """Returns JSON string with hotel search results."""
    # Implementation...
```

## Registration & Discovery

### Pattern: Explicit List-Based Registration

Tools are registered explicitly via agent initialization or chat options:

```python
# Method 1: Agent initialization
from agent_framework import ChatAgent, ai_function

@ai_function
def get_weather(location: str) -> str:
    return f"Weather in {location}: Sunny, 72°F"

agent = ChatAgent(
    chat_client=client,
    name="WeatherAgent",
    tools=[get_weather],  # Register tools at creation
)

# Method 2: ChatOptions (per-request)
from agent_framework import ChatOptions

response = await client.get_response(
    messages=["What's the weather?"],
    chat_options=ChatOptions(tools=[get_weather]),
)

# Method 3: Direct kwargs
response = await client.get_response(
    messages=["What's the weather?"],
    tools=[get_weather],
)
```

### Tool Conversion Pipeline

The framework automatically converts various formats to `AIFunction`:

```python
def _get_tool_map(tools: Sequence[ToolProtocol | Callable | dict]) -> dict[str, AIFunction]:
    """Convert heterogeneous tool list to unified tool map."""
    ai_function_list: dict[str, AIFunction] = {}
    for tool in tools if isinstance(tools, list) else [tools]:
        if isinstance(tool, AIFunction):
            ai_function_list[tool.name] = tool
        elif callable(tool):
            # Auto-wrap plain functions
            ai_tool = ai_function(tool)
            ai_function_list[ai_tool.name] = ai_tool
        # Dicts are passed through for provider-specific tools
    return ai_function_list
```

**Supported Formats**:
- `AIFunction` instances (pass-through)
- Plain callables (auto-wrapped with `@ai_function`)
- `ToolProtocol` implementations (custom tools)
- Dicts (provider-specific tool definitions)

### Registration Flow

```
User Code
    |
    v
[Tool Definition] --> @ai_function decorator
    |                      |
    v                      v
AIFunction <-- _create_input_model_from_func() [Pydantic model]
    |
    v
ChatOptions.tools / Agent.tools
    |
    v
_get_tool_map() --> {name: AIFunction}
    |
    v
FunctionInvocationConfiguration
    |
    v
use_function_invocation() decorator wraps client methods
    |
    v
_try_execute_function_calls() --> Parallel execution
```

### Additional Tools (Declaration-Only)

The framework supports "declaration-only" tools that are sent to the LLM but not executed locally:

```python
client.function_invocation_configuration.additional_tools = [
    # Tools the provider knows about but aren't in ChatOptions.tools
    HostedWebSearchTool(),
    HostedMCPTool(name="external_service", url="..."),
]
```

This is useful when:
- Provider pre-configures certain tools
- Tools execute on provider's infrastructure
- Avoiding duplicate tool declarations

## Execution Flow

### Invocation Pattern

Tools are invoked through a multi-layered wrapper system:

```python
async def _auto_invoke_function(
    function_call_content: FunctionCallContent | FunctionApprovalResponseContent,
    custom_args: dict[str, Any] | None = None,
    *,
    config: FunctionInvocationConfiguration,
    tool_map: dict[str, AIFunction],
    sequence_index: int | None = None,
    request_index: int | None = None,
    middleware_pipeline: Any = None,
) -> FunctionExecutionResult | Contents:
    """Execute a function call with validation and middleware."""

    # 1. Resolve tool from map
    tool = tool_map.get(function_call_content.name)

    # 2. Parse and validate arguments
    parsed_args = function_call_content.parse_arguments()
    try:
        args = tool.input_model.model_validate(parsed_args)
    except ValidationError as exc:
        return FunctionExecutionResult(
            content=FunctionResultContent(
                call_id=function_call_content.call_id,
                result="Error: Argument parsing failed.",
                exception=exc,
            )
        )

    # 3. Execute through middleware (if configured)
    if middleware_pipeline and middleware_pipeline.has_middlewares:
        context = FunctionInvocationContext(
            function=tool,
            arguments=args,
            kwargs=runtime_kwargs.copy(),
        )
        function_result = await middleware_pipeline.execute(
            function=tool,
            arguments=args,
            context=context,
            final_handler=lambda ctx: tool.invoke(arguments=ctx.arguments, **ctx.kwargs),
        )
        return FunctionExecutionResult(
            content=FunctionResultContent(call_id=..., result=function_result),
            terminate=context.terminate,  # Middleware can halt loop
        )

    # 4. Direct execution (no middleware)
    try:
        function_result = await tool.invoke(arguments=args, **runtime_kwargs)
        return FunctionExecutionResult(
            content=FunctionResultContent(call_id=..., result=function_result)
        )
    except Exception as exc:
        return FunctionExecutionResult(
            content=FunctionResultContent(
                call_id=...,
                result="Error: Function failed.",
                exception=exc,
            )
        )
```

### Validation Stages

| Stage | What's Validated | Error Handling |
|-------|-----------------|----------------|
| **Pre-Call** | Tool exists in map | Return `FunctionResultContent` with error |
| **Argument Parsing** | JSON parse succeeds | Return `FunctionResultContent` with error |
| **Pydantic Validation** | Arguments match schema | Return `FunctionResultContent` with `ValidationError` |
| **Approval Check** | `approval_mode` satisfied | Return `FunctionApprovalRequestContent` |
| **Invocation Limits** | `max_invocations` not exceeded | Raise `ToolException` |
| **Execution** | Function completes | Return `FunctionResultContent` with exception |

### Error Handling

The framework returns all errors as `FunctionResultContent` back to the LLM:

```python
class FunctionResultContent(BaseContent):
    """Tool execution result sent back to LLM."""
    call_id: str
    result: Any  # Success result or error message
    exception: Exception | None = None  # Optional exception object


# Error feedback based on config
if config.include_detailed_errors:
    message = f"Error: Function failed. Exception: {exc}"
else:
    message = "Error: Function failed."

return FunctionResultContent(
    call_id=function_call_content.call_id,
    result=message,
    exception=exc,
)
```

**Error Types with Feedback**:

| Error Type | Feedback to LLM | Example |
|------------|-----------------|---------|
| **Unknown Tool** | "Error: Requested function '{name}' not found." | Model hallucinates tool name |
| **Validation Error** | "Error: Argument parsing failed. Exception: {details}" | Invalid JSON or missing required field |
| **Invocation Limit** | "Function '{name}' has reached its maximum invocation limit, you can no longer use this tool." | Circuit breaker triggered |
| **Exception Limit** | "Function '{name}' has reached its maximum exception limit, you tried to use this tool too many times and it kept failing." | Repeated failures |
| **Execution Error** | "Error: Function failed. Exception: {details}" | Runtime exception in tool code |

**Configuration**:
```python
config = FunctionInvocationConfiguration(
    include_detailed_errors=True,  # Send full exception details to LLM
    terminate_on_unknown_calls=False,  # Auto-generate "not found" message
    max_consecutive_errors_per_request=3,  # Stop after N errors in a row
)
```

### Retry Mechanisms

**Built-in Circuit Breakers**:
1. **Per-Tool Invocation Limit**:
   ```python
   @ai_function(max_invocations=5)
   def expensive_api_call(query: str) -> str:
       # Can only be called 5 times per session
       pass
   ```

2. **Per-Tool Exception Limit**:
   ```python
   @ai_function(max_invocation_exceptions=3)
   def flaky_service(data: str) -> str:
       # Stops after 3 failures
       pass
   ```

3. **Per-Request Error Limit**:
   ```python
   config.max_consecutive_errors_per_request = 3  # Stop after 3 errors in a row
   ```

**Self-Correction Loop**:
```python
for attempt_idx in range(config.max_iterations):  # Default: 40
    response = await client.get_response(messages=prepped_messages)

    if has_function_calls(response):
        results, should_terminate = await _try_execute_function_calls(...)

        # Check error count
        if errors_in_a_row >= config.max_consecutive_errors_per_request:
            logger.warning("Max errors reached. Stopping function calls.")
            break

        # Add results to message history for next iteration
        prepped_messages.extend([
            ChatMessage(role="assistant", contents=[function_calls]),
            ChatMessage(role="tool", contents=[function_results]),
        ])
        continue  # Next iteration with error feedback

    return response  # No more function calls

# Failsafe: force non-tool response
kwargs["tool_choice"] = "none"
return await client.get_response(messages=prepped_messages, **kwargs)
```

## Parallel Execution

### Full Async Support with `asyncio.gather()`

The framework executes multiple tool calls concurrently:

```python
async def _try_execute_function_calls(
    function_calls: Sequence[FunctionCallContent],
    tools: Sequence[ToolProtocol],
    config: FunctionInvocationConfiguration,
) -> tuple[Sequence[Contents], bool]:
    """Execute multiple function calls in parallel."""

    tool_map = _get_tool_map(tools)

    # Check for approval requirements (if ANY need approval, ALL wait)
    approval_tools = [t for t in tool_map.values() if t.approval_mode == "always_require"]
    if any(fcc.name in [t.name for t in approval_tools] for fcc in function_calls):
        # Return approval requests for ALL calls
        return ([
            FunctionApprovalRequestContent(id=fcc.call_id, function_call=fcc)
            for fcc in function_calls
        ], False)

    # Execute all functions concurrently
    execution_results = await asyncio.gather(*[
        _auto_invoke_function(
            function_call_content=function_call,
            tool_map=tool_map,
            sequence_index=seq_idx,
            request_index=attempt_idx,
            middleware_pipeline=middleware_pipeline,
            config=config,
        )
        for seq_idx, function_call in enumerate(function_calls)
    ])

    # Unpack results and check for termination signal
    contents: list[Contents] = []
    should_terminate = False
    for result in execution_results:
        if isinstance(result, FunctionExecutionResult):
            contents.append(result.content)
            if result.terminate:
                should_terminate = True
        else:
            contents.append(result)

    return (contents, should_terminate)
```

**Key Parallel Execution Features**:

1. **Concurrent Execution**: All tool calls in a single LLM response execute simultaneously
2. **Approval Batching**: If one tool needs approval, all tools in the batch wait (prevents partial execution)
3. **Error Isolation**: Each tool execution is independent; one failure doesn't block others
4. **Termination Signaling**: Middleware can signal early termination via `context.terminate = True`

### Example: Parallel Tool Calls

```python
# LLM returns multiple tool calls
response = ChatResponse(
    messages=[ChatMessage(
        role="assistant",
        contents=[
            FunctionCallContent(call_id="1", name="get_weather", arguments='{"city": "Seattle"}'),
            FunctionCallContent(call_id="2", name="get_weather", arguments='{"city": "Portland"}'),
            FunctionCallContent(call_id="3", name="get_weather", arguments='{"city": "SF"}'),
        ]
    )]
)

# All three execute in parallel via asyncio.gather()
# Results returned together:
# [
#   FunctionResultContent(call_id="1", result="Seattle: 60°F, Rainy"),
#   FunctionResultContent(call_id="2", result="Portland: 62°F, Cloudy"),
#   FunctionResultContent(call_id="3", result="SF: 68°F, Sunny"),
# ]
```

## Code References

### Core Tool Implementation
- `python/packages/core/agent_framework/_tools.py:158-185` - ToolProtocol definition
- `python/packages/core/agent_framework/_tools.py:187-226` - BaseTool implementation
- `python/packages/core/agent_framework/_tools.py:533-830` - AIFunction class
- `python/packages/core/agent_framework/_tools.py:1140-1241` - @ai_function decorator

### Schema Generation
- `python/packages/core/agent_framework/_tools.py:916-935` - _create_input_model_from_func
- `python/packages/core/agent_framework/_tools.py:883-913` - _parse_annotation
- `python/packages/core/agent_framework/_tools.py:949-1112` - _build_pydantic_model_from_json_schema

### Hosted Tools
- `python/packages/core/agent_framework/_tools.py:228-280` - HostedCodeInterpreterTool
- `python/packages/core/agent_framework/_tools.py:282-325` - HostedWebSearchTool
- `python/packages/core/agent_framework/_tools.py:342-439` - HostedMCPTool
- `python/packages/core/agent_framework/_tools.py:441-497` - HostedFileSearchTool

### Execution Flow
- `python/packages/core/agent_framework/_tools.py:1388-1527` - _auto_invoke_function
- `python/packages/core/agent_framework/_tools.py:1547-1635` - _try_execute_function_calls
- `python/packages/core/agent_framework/_tools.py:1736-1930` - _handle_function_calls_response
- `python/packages/core/agent_framework/_tools.py:1932-2133` - _handle_function_calls_streaming_response

### Configuration
- `python/packages/core/agent_framework/_tools.py:1247-1357` - FunctionInvocationConfiguration
- `python/packages/core/agent_framework/_tools.py:2135-2194` - use_function_invocation decorator

### Tests (Demonstrating Patterns)
- `python/packages/core/tests/core/test_tools.py` - Comprehensive tool tests
- `python/packages/core/tests/core/test_as_tool_kwargs_propagation.py` - Agent-as-tool delegation
- `python/packages/core/tests/workflow/test_agent_executor_tool_calls.py` - Approval flow tests

### Examples
- `python/samples/demos/workflow_evaluation/_tools.py` - 12 real-world travel planning tools

## Implications for New Framework

### Positive Patterns to Adopt

1. **Protocol-Based Tool Interface**
   - Structural typing (`ToolProtocol`) allows maximum flexibility
   - Any object with `name`, `description`, and `additional_properties` is a valid tool
   - Enables third-party tool implementations without inheritance

2. **Automatic Schema Generation**
   - Zero boilerplate: `@ai_function` infers schemas from type hints
   - Supports `Annotated[type, "description"]` for inline documentation
   - Handles complex types (Literal, nested objects, optional fields)
   - Falls back to manual JSON Schema when needed

3. **Unified Error Feedback**
   - All errors (validation, execution, limits) return as `FunctionResultContent`
   - LLM sees errors as tool results, enabling self-correction
   - Configurable detail level (generic vs full exception)

4. **Built-In Circuit Breakers**
   - `max_invocations` prevents runaway tool calls
   - `max_invocation_exceptions` stops failing tools
   - `max_consecutive_errors_per_request` prevents error loops
   - Self-correction with automatic failsafe (force non-tool response after max iterations)

5. **Kwargs Injection Pattern**
   - Tools with `**kwargs` signature receive runtime context
   - Enables passing auth tokens, user IDs, session context to tools
   - Middleware can inject/modify kwargs before tool execution
   - Crucial for stateful agents and multi-tenant systems

6. **Approval Flow Integration**
   - `approval_mode="always_require"` for sensitive operations
   - Batched approval (if one tool needs approval, all wait)
   - `FunctionApprovalRequestContent` → user decision → `FunctionApprovalResponseContent`
   - Supports granular MCP tool approval policies

7. **Parallel Execution by Default**
   - `asyncio.gather()` runs all tool calls concurrently
   - No special syntax needed; framework handles it automatically
   - Proper error isolation (one failure doesn't block others)

8. **Agent-as-Tool Pattern**
   - `ChatAgent.as_tool()` converts agents to callable tools
   - Enables hierarchical multi-agent workflows
   - Kwargs propagate through delegation chains
   - Supports both streaming and non-streaming modes

### Considerations

1. **Approval Batching Trade-off**
   - **Pro**: Prevents partial execution (consistency)
   - **Con**: One sensitive tool blocks all parallel calls
   - **Alternative**: Consider executing non-approval tools immediately, only wait for approval-required subset

2. **Declaration-Only Tools Complexity**
   - Separate code paths for hosted vs local tools
   - `declaration_only` flag determines execution path
   - Consider unifying: treat hosted tools as async stubs with provider-side execution

3. **Invocation Limit Placement**
   - Limits are per-tool instance, not per-tool-name globally
   - Multiple agent instances = separate limit counters
   - Consider: global limit registry keyed by tool name

4. **Middleware Control Flow**
   - `context.terminate` is powerful but hidden
   - Only documented in middleware context, not tool execution flow
   - Consider: explicit `ToolExecutionDecision` return type

5. **Error Loop Failsafe**
   - After max iterations, forces `tool_choice="none"` for final answer
   - Could result in "I can't help" if LLM relies on tools
   - Consider: configurable failsafe strategy (raise exception, return partial, ask user)

6. **Schema Generation Limitations**
   - No support for generic types (`list[CustomClass]` becomes `list`)
   - Nested Pydantic models not auto-detected; requires manual JSON Schema
   - Consider: deeper introspection or explicit model registration

### Anti-Patterns Observed

1. **Tight Coupling to Pydantic**
   - Schema generation, validation, and serialization all require Pydantic
   - Tools cannot use other validation libraries (e.g., attrs, dataclasses with marshmallow)
   - **Mitigation**: Accept JSON Schema dict as input_model (framework does this, but not primary path)

2. **Mutable Invocation Counters**
   - `tool.invocation_count` and `tool.invocation_exception_count` are instance attributes
   - Not thread-safe (though async context makes this less critical)
   - State persists across agent runs if tool instance is reused
   - **Better**: Use context-aware counters tied to conversation/session ID

3. **Hidden Middleware Control**
   - Middleware can set `context.terminate = True` to halt tool loop
   - Not visible in tool signature or return value
   - Side-channel communication pattern
   - **Better**: Explicit return type indicating control flow decision

4. **Approval Request/Response Lifecycle**
   - `FunctionApprovalRequestContent` → user provides `FunctionApprovalResponseContent` → framework replaces with `FunctionCallContent` + `FunctionResultContent`
   - Multiple content transformations in message history
   - **Better**: Keep approval metadata separate from message content

5. **Kwargs Filtering**
   - Framework filters out internal kwargs (`_function_middleware_pipeline`, `middleware`, `thread`)
   - Magic strings hardcoded in execution path
   - **Better**: Explicit `runtime_context` object or reserved namespace

6. **Exception Serialization**
   - `FunctionResultContent.exception` stores raw exception object
   - May not serialize well (pickle issues, cloud storage)
   - **Better**: Structured error type (code, message, metadata) separate from exception

## Unique Innovations

1. **Descriptor Protocol for Class-Based Tools**
   ```python
   class MyToolkit:
       @ai_function
       def fetch_data(self, query: str) -> str:
           return self.database.query(query)  # Access instance state

   toolkit = MyToolkit(database=db)
   agent = ChatAgent(tools=[toolkit.fetch_data])  # Bound method as tool
   ```

2. **MCP Integration as First-Class Hosted Tool**
   - Native support for Model Context Protocol servers
   - Granular approval policies per MCP tool
   - Header injection for auth

3. **Failsafe Tool Loop**
   - After max_iterations, forces `tool_choice="none"` to get non-tool response
   - Prevents infinite tool loops
   - Logs warning before failsafe activation

4. **Content-Based Tool Input Parsing**
   - `_parse_inputs()` intelligently converts strings, dicts, and Content objects
   - Supports file IDs, vector store IDs, URIs, and raw data
   - Used by HostedCodeInterpreterTool and HostedFileSearchTool

5. **Streaming Tool Results**
   - `_handle_function_calls_streaming_response` executes tools mid-stream
   - Yields `FunctionCallContent`, then executes, then yields `FunctionResultContent`
   - Enables real-time tool execution UX

## Summary Recommendations

**Adopt**:
- Protocol-based tool interface (structural typing)
- Automatic schema generation from type hints
- Unified error feedback via tool results
- Built-in circuit breakers (invocation/exception limits)
- Kwargs injection for runtime context
- Parallel execution by default
- Agent-as-tool pattern

**Adapt**:
- Approval batching (consider partial execution)
- Middleware control flow (make explicit)
- Mutable counters (use session-scoped state)

**Avoid**:
- Tight Pydantic coupling (support alternative validation)
- Magic kwargs filtering (use explicit context object)
- Raw exception storage (use structured errors)
