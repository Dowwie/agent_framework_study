# Tool Interface Analysis: autogen

## Summary
- **Tool Modeling**: Protocol + ABC hybrid with Pydantic-based schema generation
- **Schema Generation**: Automatic via Pydantic model introspection with JSON Schema output
- **Registration Pattern**: Explicit list-based registration with automatic callable wrapping
- **Error Handling**: Structured exceptions with detailed error feedback to LLM
- **Built-in Tools**: 20+ tools across web surfing, file browsing, code execution, and agent delegation categories
- **Parallel Execution**: Full support via asyncio.gather for concurrent tool calls

## Tool Modeling

### Core Abstraction

Autogen uses a **Protocol + ABC hybrid pattern** for maximum flexibility:

```python
# Protocol for duck typing
@runtime_checkable
class Tool(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def schema(self) -> ToolSchema: ...

    def args_type(self) -> Type[BaseModel]: ...
    def return_type(self) -> Type[Any]: ...
    def state_type(self) -> Type[BaseModel] | None: ...

    def return_value_as_string(self, value: Any) -> str: ...

    async def run_json(
        self, args: Mapping[str, Any],
        cancellation_token: CancellationToken,
        call_id: str | None = None
    ) -> Any: ...

    async def save_state_json(self) -> Mapping[str, Any]: ...
    async def load_state_json(self, state: Mapping[str, Any]) -> None: ...

# ABC for concrete implementation
class BaseTool(ABC, Tool, Generic[ArgsT, ReturnT], ComponentBase[BaseModel]):
    def __init__(
        self,
        args_type: Type[ArgsT],
        return_type: Type[ReturnT],
        name: str,
        description: str,
        strict: bool = False,
    ) -> None:
        self._args_type = args_type
        self._return_type = normalize_annotated_type(return_type)
        self._name = name
        self._description = description
        self._strict = strict

    @abstractmethod
    async def run(self, args: ArgsT, cancellation_token: CancellationToken) -> ReturnT: ...
```

### Key Attributes

| Attribute | Type | Purpose |
|-----------|------|---------|
| `name` | str | Unique tool identifier |
| `description` | str | LLM-facing description of tool purpose |
| `schema` | ToolSchema | JSON Schema for tool parameters |
| `args_type` | Type[BaseModel] | Pydantic model defining input shape |
| `return_type` | Type[Any] | Expected output type |
| `state_type` | Type[BaseModel] \| None | Optional stateful tool state |
| `strict` | bool | Enforce strict schema (all params required, no defaults) |

### Design Patterns

**1. Generic Typing for Safety**
```python
class BaseTool(ABC, Tool, Generic[ArgsT, ReturnT]):
    # ArgsT must be BaseModel subclass
    # ReturnT can be any type
```

**2. Streaming Support**
```python
class StreamTool(Tool, Protocol):
    def run_json_stream(
        self, args: Mapping[str, Any],
        cancellation_token: CancellationToken,
        call_id: str | None = None
    ) -> AsyncGenerator[Any, None]: ...
```

**3. Stateful Tools**
```python
class BaseToolWithState(BaseTool[ArgsT, ReturnT], Generic[ArgsT, ReturnT, StateT]):
    @abstractmethod
    def save_state(self) -> StateT: ...

    @abstractmethod
    def load_state(self, state: StateT) -> None: ...
```

## Schema Generation

### Method Used

**Automatic Pydantic introspection** with JSON Schema generation:

```python
@property
def schema(self) -> ToolSchema:
    # Generate schema from Pydantic model
    model_schema: Dict[str, Any] = self._args_type.model_json_schema()

    # Resolve $defs references inline
    if "$defs" in model_schema:
        model_schema = cast(Dict[str, Any], jsonref.replace_refs(
            obj=model_schema, proxies=False
        ))
        del model_schema["$defs"]

    parameters = ParametersSchema(
        type="object",
        properties=model_schema["properties"],
        required=model_schema.get("required", []),
        additionalProperties=model_schema.get("additionalProperties", False),
    )

    # Strict mode validation
    if self._strict:
        if set(parameters["required"]) != set(parameters["properties"].keys()):
            raise ValueError("Strict mode: all args must be required")
        if parameters["additionalProperties"]:
            raise ValueError("Strict mode: no additional properties allowed")

    return ToolSchema(
        name=self._name,
        description=self._description,
        parameters=parameters,
        strict=self._strict,
    )
```

### Function-to-Tool Conversion

Autogen automatically wraps callables using `FunctionTool`:

```python
def get_typed_signature(call: Callable[..., Any]) -> inspect.Signature:
    """Extract type hints from function signature."""
    signature = inspect.signature(call)
    globalns = getattr(call, "__globals__", {})
    type_hints = typing.get_type_hints(func_call, globalns, include_extras=True)
    typed_params = [
        inspect.Parameter(
            name=param.name,
            kind=param.kind,
            default=param.default,
            annotation=type_hints[param.name],
        )
        for param in signature.parameters.values()
    ]
    return inspect.Signature(typed_params, return_annotation=type_hints.get("return"))

def args_base_model_from_signature(name: str, sig: inspect.Signature) -> Type[BaseModel]:
    """Generate Pydantic model from function signature."""
    fields: Dict[str, tuple[Type[Any], Any]] = {}
    for param_name, param in sig.parameters.items():
        if param_name == "cancellation_token":
            continue  # Handled externally

        if param.annotation is inspect.Parameter.empty:
            raise ValueError("All parameters must be annotated")

        type = normalize_annotated_type(param.annotation)
        description = type2description(param_name, param.annotation)
        default_value = param.default if param.default != inspect.Parameter.empty else PydanticUndefined

        fields[param_name] = (type, Field(default=default_value, description=description))

    return create_model(name, **fields)
```

### Type Annotations Support

**Annotated types for descriptions:**
```python
def my_tool(
    query: Annotated[str, "The search query to execute"],
    limit: Annotated[int, "Maximum number of results"] = 10
) -> str:
    """Search for information."""
    pass

# Generates schema:
{
    "name": "my_tool",
    "description": "Search for information.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query to execute"},
            "limit": {"type": "integer", "description": "Maximum number of results", "default": 10}
        },
        "required": ["query"]
    }
}
```

### Generated Schema Example

```python
class MyArgs(BaseModel):
    query: str = Field(description="The search query")
    max_results: int = Field(default=10, description="Result limit")

class MyTool(BaseTool[MyArgs, str]):
    def __init__(self):
        super().__init__(
            args_type=MyArgs,
            return_type=str,
            name="search",
            description="Search the web"
        )

    async def run(self, args: MyArgs, cancellation_token: CancellationToken) -> str:
        return f"Found {args.max_results} results for {args.query}"

# schema property returns:
{
    "name": "search",
    "description": "Search the web",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "max_results": {"type": "integer", "description": "Result limit", "default": 10}
        },
        "required": ["query"],
        "additionalProperties": false
    },
    "strict": false
}
```

## Built-in Tool Inventory

### Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| Web Surfing | 13 tools | Browser automation, web search, page interaction |
| File Browsing | 5 tools | Local file navigation and search |
| Code Execution | Code executor | Execute Python code in sandboxed environments |
| Agent Delegation | 2 tools | Delegate tasks to sub-agents or teams |
| Video Processing | 5 tools | Video analysis, transcription, screenshots |

### Complete Tool List

| Tool Name | Location | Schema Method | Category |
|-----------|----------|---------------|----------|
| `visit_url` | `autogen_ext.agents.web_surfer._tool_definitions` | Manual ToolSchema | Web Surfing |
| `web_search` | `autogen_ext.agents.web_surfer._tool_definitions` | Manual ToolSchema | Web Surfing |
| `history_back` | `autogen_ext.agents.web_surfer._tool_definitions` | Manual ToolSchema | Web Surfing |
| `scroll_up` | `autogen_ext.agents.web_surfer._tool_definitions` | Manual ToolSchema | Web Surfing |
| `scroll_down` | `autogen_ext.agents.web_surfer._tool_definitions` | Manual ToolSchema | Web Surfing |
| `click` | `autogen_ext.agents.web_surfer._tool_definitions` | Manual ToolSchema | Web Surfing |
| `input_text` | `autogen_ext.agents.web_surfer._tool_definitions` | Manual ToolSchema | Web Surfing |
| `scroll_element_down` | `autogen_ext.agents.web_surfer._tool_definitions` | Manual ToolSchema | Web Surfing |
| `scroll_element_up` | `autogen_ext.agents.web_surfer._tool_definitions` | Manual ToolSchema | Web Surfing |
| `hover` | `autogen_ext.agents.web_surfer._tool_definitions` | Manual ToolSchema | Web Surfing |
| `answer_question` | `autogen_ext.agents.web_surfer._tool_definitions` | Manual ToolSchema | Web Surfing |
| `summarize_page` | `autogen_ext.agents.web_surfer._tool_definitions` | Manual ToolSchema | Web Surfing |
| `sleep` | `autogen_ext.agents.web_surfer._tool_definitions` | Manual ToolSchema | Web Surfing |
| `open_path` | `autogen_ext.agents.file_surfer._tool_definitions` | Manual ToolSchema | File Browsing |
| `page_up` | `autogen_ext.agents.file_surfer._tool_definitions` | Manual ToolSchema | File Browsing |
| `page_down` | `autogen_ext.agents.file_surfer._tool_definitions` | Manual ToolSchema | File Browsing |
| `find_on_page_ctrl_f` | `autogen_ext.agents.file_surfer._tool_definitions` | Manual ToolSchema | File Browsing |
| `find_next` | `autogen_ext.agents.file_surfer._tool_definitions` | Manual ToolSchema | File Browsing |
| `CodeExecutor` | `autogen_core.code_executor._base` | Component-based | Code Execution |
| `AgentTool` | `autogen_agentchat.tools._agent` | TaskRunnerTool | Agent Delegation |
| `TeamTool` | `autogen_agentchat.tools._team` | TaskRunnerTool | Agent Delegation |
| `extract_audio` | `autogen_ext.agents.video_surfer.tools` | FunctionTool | Video Processing |
| `transcribe_audio_with_timestamps` | `autogen_ext.agents.video_surfer.tools` | FunctionTool | Video Processing |
| `get_video_length` | `autogen_ext.agents.video_surfer.tools` | FunctionTool | Video Processing |
| `save_screenshot` | `autogen_ext.agents.video_surfer.tools` | FunctionTool | Video Processing |
| `transcribe_video_screenshot` | `autogen_ext.agents.video_surfer.tools` | FunctionTool | Video Processing |

### Tool Implementation Examples

**Manual Schema Definition (Web Surfer):**
```python
TOOL_VISIT_URL: ToolSchema = _load_tool({
    "type": "function",
    "function": {
        "name": "visit_url",
        "description": "Navigate directly to a provided URL using the browser's address bar.",
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning": {
                    "type": "string",
                    "description": "A short description of the action to be performed and reason for doing so",
                },
                "url": {
                    "type": "string",
                    "description": "The URL to visit in the browser.",
                },
            },
            "required": ["reasoning", "url"],
        },
    },
})
```

**Function-Based Tool (Video Processing):**
```python
def extract_audio(video_path: str, audio_output_path: str) -> str:
    """
    Extracts audio from a video file and saves it as an MP3 file.

    :param video_path: Path to the video file.
    :param audio_output_path: Path to save the extracted audio file.
    :return: Confirmation message with the path to the saved audio file.
    """
    ffmpeg.input(video_path).output(audio_output_path, format="mp3").run(
        quiet=True, overwrite_output=True
    )
    return f"Audio extracted and saved to {audio_output_path}."

# Automatically wrapped in FunctionTool by agent
```

## Registration & Discovery

### Pattern

**Explicit list-based registration** with automatic callable wrapping:

```python
class AssistantAgent(BaseChatAgent):
    def __init__(
        self,
        name: str,
        model_client: ChatCompletionClient,
        tools: List[BaseTool[Any, Any] | Callable[..., Any] | Callable[..., Awaitable[Any]]] | None = None,
        workbench: Workbench | Sequence[Workbench] | None = None,
        # ...
    ):
        self._tools: List[BaseTool[Any, Any]] = []
        if tools is not None:
            for tool in tools:
                if isinstance(tool, BaseTool):
                    self._tools.append(tool)
                elif callable(tool):
                    # Auto-wrap functions in FunctionTool
                    description = tool.__doc__ if hasattr(tool, "__doc__") and tool.__doc__ else ""
                    self._tools.append(FunctionTool(tool, description=description))
                else:
                    raise ValueError(f"Unsupported tool type: {type(tool)}")

        # Validate unique names
        tool_names = [tool.name for tool in self._tools]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError(f"Tool names must be unique: {tool_names}")
```

### Workbench Pattern

**Workbench abstracts tool collections with shared state:**

```python
class Workbench(ABC, ComponentBase[BaseModel]):
    """
    A workbench provides a set of tools that may share resources and state.
    Tools may be dynamic and change after each execution.
    """

    @abstractmethod
    async def list_tools(self) -> List[ToolSchema]:
        """List currently available tools (may change dynamically)."""
        ...

    @abstractmethod
    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        cancellation_token: CancellationToken | None = None,
        call_id: str | None = None,
    ) -> ToolResult:
        """Execute a tool by name."""
        ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def reset(self) -> None: ...
    async def save_state(self) -> Mapping[str, Any]: ...
    async def load_state(self, state: Mapping[str, Any]) -> None: ...
```

**Static Workbench Implementation:**
```python
class StaticWorkbench(Workbench):
    def __init__(
        self,
        tools: List[BaseTool[Any, Any]],
        tool_overrides: Optional[Dict[str, ToolOverride]] = None
    ):
        self._tools = tools
        self._tool_overrides = tool_overrides or {}

    async def list_tools(self) -> List[ToolSchema]:
        schemas = []
        for tool in self._tools:
            schema = tool.schema

            # Apply name/description overrides
            if tool.name in self._tool_overrides:
                override = self._tool_overrides[tool.name]
                schema = {
                    "name": override.name if override.name else schema["name"],
                    "description": override.description if override.description else schema.get("description", ""),
                    **{k: v for k, v in schema.items() if k not in ["name", "description"]}
                }

            schemas.append(schema)
        return schemas

    async def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None, ...) -> ToolResult:
        # Resolve override name to original
        original_name = self._override_name_to_original.get(name, name)
        tool = next((t for t in self._tools if t.name == original_name), None)

        if not tool:
            return ToolResult(
                name=name,
                result=[TextResultContent(content=f"Tool {name} not found.")],
                is_error=True
            )

        try:
            result = await tool.run_json(arguments or {}, cancellation_token, call_id)
            return ToolResult(
                name=name,
                result=[TextResultContent(content=tool.return_value_as_string(result))],
                is_error=False
            )
        except Exception as e:
            return ToolResult(
                name=name,
                result=[TextResultContent(content=str(e))],
                is_error=True
            )
```

### Registration Flow

```
User Code
    ↓
    |-- Creates functions or BaseTool instances
    ↓
AssistantAgent.__init__
    ↓
    |-- Inspects each tool
    |-- If callable: wraps in FunctionTool (auto-generates schema)
    |-- If BaseTool: uses directly
    |-- Validates unique names
    ↓
StaticWorkbench (if tools provided)
    ↓
    |-- Manages tool lifecycle
    |-- Handles name overrides
    |-- Provides unified call interface
    ↓
Agent Execution
    ↓
    |-- Sends schemas to LLM
    |-- Routes tool calls to workbench
    |-- Returns results to LLM
```

## Execution Flow

### Invocation Pattern

**Two-tier execution: Agent → Workbench → Tool**

```python
# Agent-level execution orchestration
async def _execute_tool_calls(
    function_calls: List[FunctionCall],
    stream_queue: asyncio.Queue[BaseAgentEvent | BaseChatMessage | None],
) -> List[Tuple[FunctionCall, FunctionExecutionResult]]:
    # Execute all tool calls concurrently
    results = await asyncio.gather(
        *[
            cls._execute_tool_call(
                tool_call=call,
                workbench=workbench,
                handoff_tools=handoff_tools,
                agent_name=agent_name,
                cancellation_token=cancellation_token,
                stream=stream_queue,
            )
            for call in function_calls
        ]
    )
    stream_queue.put_nowait(None)  # Signal completion
    return results

# Single tool execution
@staticmethod
async def _execute_tool_call(
    tool_call: FunctionCall,
    workbench: Sequence[Workbench],
    handoff_tools: List[BaseTool[Any, Any]],
    agent_name: str,
    cancellation_token: CancellationToken,
    stream: asyncio.Queue[BaseAgentEvent | BaseChatMessage | None],
) -> Tuple[FunctionCall, FunctionExecutionResult]:
    # Parse arguments
    try:
        arguments = json.loads(tool_call.arguments)
    except json.JSONDecodeError as e:
        return (
            tool_call,
            FunctionExecutionResult(
                content=f"Error: {e}",
                call_id=tool_call.id,
                is_error=True,
                name=tool_call.name,
            ),
        )

    # Check handoff tools first
    for handoff_tool in handoff_tools:
        if tool_call.name == handoff_tool.name:
            result = await handoff_tool.run_json(arguments, cancellation_token, call_id=tool_call.id)
            return (
                tool_call,
                FunctionExecutionResult(
                    content=handoff_tool.return_value_as_string(result),
                    call_id=tool_call.id,
                    is_error=False,
                    name=tool_call.name,
                ),
            )

    # Search workbenches for tool
    for wb in workbench:
        tools = await wb.list_tools()
        if any(t["name"] == tool_call.name for t in tools):
            # Handle streaming workbenches
            if isinstance(wb, StaticStreamWorkbench):
                tool_result: ToolResult | None = None
                async for event in wb.call_tool_stream(
                    name=tool_call.name,
                    arguments=arguments,
                    cancellation_token=cancellation_token,
                    call_id=tool_call.id,
                ):
                    if isinstance(event, ToolResult):
                        tool_result = event
                    elif isinstance(event, (BaseAgentEvent, BaseChatMessage)):
                        await stream.put(event)
                assert tool_result is not None
            else:
                tool_result = await wb.call_tool(
                    name=tool_call.name,
                    arguments=arguments,
                    cancellation_token=cancellation_token,
                    call_id=tool_call.id,
                )

            return (
                tool_call,
                FunctionExecutionResult(
                    content=tool_result.to_text(),
                    call_id=tool_call.id,
                    is_error=tool_result.is_error,
                    name=tool_call.name,
                ),
            )

    # Tool not found
    return (
        tool_call,
        FunctionExecutionResult(
            content=f"Error: tool '{tool_call.name}' not found in any workbench",
            call_id=tool_call.id,
            is_error=True,
            name=tool_call.name,
        ),
    )
```

### Validation Flow

**Multi-layer validation:**

1. **Schema validation (Pydantic)**
   ```python
   async def run_json(self, args: Mapping[str, Any], ...) -> Any:
       # Validate and parse using Pydantic
       return_value = await self.run(
           self._args_type.model_validate(args),  # Raises ValidationError if invalid
           cancellation_token
       )
       return return_value
   ```

2. **Strict mode validation (OpenAI structured output)**
   ```python
   if self._strict:
       # All fields must be required (no defaults)
       if set(parameters["required"]) != set(parameters["properties"].keys()):
           raise ValueError("Strict mode: all args must be required")
       # No additional properties allowed
       if parameters["additionalProperties"]:
           raise ValueError("Strict mode: no additional properties allowed")
   ```

3. **JSON parsing validation**
   ```python
   try:
       arguments = json.loads(tool_call.arguments)
   except json.JSONDecodeError as e:
       return FunctionExecutionResult(content=f"Error: {e}", is_error=True)
   ```

### Error Handling

| Error Type | Handling | Feedback to LLM |
|------------|----------|-----------------|
| JSON decode error | Caught in `_execute_tool_call` | `FunctionExecutionResult(is_error=True, content="Error: <details>")` |
| Pydantic validation error | Raised in `model_validate()` | Exception propagated, caught as `ToolResult(is_error=True)` |
| Tool not found | Detected in workbench search | `FunctionExecutionResult(is_error=True, content="Error: tool not found")` |
| Tool execution exception | Caught in workbench `call_tool` | `ToolResult(is_error=True, result=[TextResultContent(content=<error>)])` |
| Cancellation | CancellationToken evoked | `asyncio.CancelledError` propagated |
| Timeout | No built-in timeout | User must implement via `cancellation_token.link_future()` |

### Structured Error Hierarchy

```python
@dataclass
class ToolException(BaseException):
    call_id: str
    content: str
    name: str

@dataclass
class ToolNotFoundException(ToolException):
    pass

@dataclass
class InvalidToolArgumentsException(ToolException):
    pass

@dataclass
class ToolExecutionException(ToolException):
    pass
```

**Used in ToolAgent (core runtime):**
```python
class ToolAgent(RoutedAgent):
    @message_handler
    async def handle_function_call(self, message: FunctionCall, ctx: MessageContext) -> FunctionExecutionResult:
        tool = next((tool for tool in self._tools if tool.name == message.name), None)

        if tool is None:
            raise ToolNotFoundException(
                call_id=message.id,
                content=f"Error: Tool not found: {message.name}",
                name=message.name
            )

        try:
            arguments = json.loads(message.arguments)
            result = await tool.run_json(args=arguments, cancellation_token=ctx.cancellation_token, call_id=message.id)
            result_as_str = tool.return_value_as_string(result)
        except json.JSONDecodeError as e:
            raise InvalidToolArgumentsException(
                call_id=message.id,
                content=f"Error: Invalid arguments: {message.arguments}",
                name=message.name
            ) from e
        except Exception as e:
            raise ToolExecutionException(
                call_id=message.id,
                content=f"Error: {e}",
                name=message.name
            ) from e

        return FunctionExecutionResult(
            content=result_as_str,
            call_id=message.id,
            is_error=False,
            name=message.name
        )
```

### Retry Mechanisms

**No built-in retry at tool layer.** Retry logic lives at agent level via `max_tool_iterations`:

```python
# Agent can make multiple sequential tool call iterations
for loop_iteration in range(max_tool_iterations):
    # Execute tool calls
    executed_calls_and_results = await _execute_tool_calls(...)

    # Check if should continue
    if loop_iteration == max_tool_iterations - 1:
        break  # Max iterations reached

    # Make another model call to see if more tool calls needed
    next_model_result = await cls._call_llm(...)

    if not isinstance(next_model_result.content, list):
        break  # No more tool calls, model returned text
```

## Parallel Execution

**Full concurrent execution support via asyncio.gather:**

```python
async def _execute_tool_calls(
    function_calls: List[FunctionCall],
    stream_queue: asyncio.Queue[BaseAgentEvent | BaseChatMessage | None],
) -> List[Tuple[FunctionCall, FunctionExecutionResult]]:
    # Execute ALL tool calls concurrently
    results = await asyncio.gather(
        *[
            cls._execute_tool_call(
                tool_call=call,
                workbench=workbench,
                handoff_tools=handoff_tools,
                agent_name=agent_name,
                cancellation_token=cancellation_token,
                stream=stream_queue,
            )
            for call in function_calls
        ]
    )
    return results
```

### Concurrency Control

**Model client controls parallel tool call generation:**

```python
# Disable parallel tool calls at model level
model_client = OpenAIChatCompletionClient(
    model="gpt-4o",
    parallel_tool_calls=False  # Model will only request one tool call at a time
)

agent = AssistantAgent(
    name="assistant",
    model_client=model_client,
    tools=[tool1, tool2, tool3]
)
```

### Thread Safety Warning

**Agent and tools are NOT thread-safe:**

```python
class AssistantAgent:
    """
    .. warning::
        The assistant agent is not thread-safe or coroutine-safe.
        It should not be shared between multiple tasks or coroutines, and it should
        not call its methods concurrently.
    """
```

**AgentTool explicitly disables parallel calls:**

```python
class AgentTool(TaskRunnerTool):
    """
    .. important::
        When using AgentTool, you **must** disable parallel tool calls in the model
        client configuration to avoid concurrency issues. Agents cannot run concurrently
        as they maintain internal state that would conflict with parallel execution.

        Set ``parallel_tool_calls=False`` for OpenAIChatCompletionClient.
    """
```

### Streaming Support

**Tools can stream intermediate results:**

```python
class StreamTool(Tool, Protocol):
    def run_json_stream(
        self,
        args: Mapping[str, Any],
        cancellation_token: CancellationToken,
        call_id: str | None = None
    ) -> AsyncGenerator[Any, None]:
        """Stream intermediate results before final return."""
        ...

# Execution handles streaming
if isinstance(wb, StaticStreamWorkbench):
    async for event in wb.call_tool_stream(...):
        if isinstance(event, ToolResult):
            tool_result = event  # Final result
        elif isinstance(event, (BaseAgentEvent, BaseChatMessage)):
            await stream.put(event)  # Stream to caller
```

## Code References

**Core Tool Abstractions:**
- `autogen-core/src/autogen_core/tools/_base.py:56-81` - Tool Protocol
- `autogen-core/src/autogen_core/tools/_base.py:96-215` - BaseTool ABC
- `autogen-core/src/autogen_core/tools/_base.py:217-268` - BaseStreamTool
- `autogen-core/src/autogen_core/tools/_base.py:270-295` - BaseToolWithState

**Schema Generation:**
- `autogen-core/src/autogen_core/tools/_base.py:115-148` - Schema property
- `autogen-core/src/autogen_core/_function_utils.py:34-58` - get_typed_signature
- `autogen-core/src/autogen_core/_function_utils.py:308-325` - args_base_model_from_signature

**Function Tool Wrapper:**
- `autogen-core/src/autogen_core/tools/_function_tool.py:30-182` - FunctionTool class
- `autogen-core/src/autogen_core/tools/_function_tool.py:105-132` - run method

**Workbench Pattern:**
- `autogen-core/src/autogen_core/tools/_workbench.py:78-217` - Workbench ABC
- `autogen-core/src/autogen_core/tools/_static_workbench.py:24-168` - StaticWorkbench
- `autogen-core/src/autogen_core/tools/_static_workbench.py:170-226` - StaticStreamWorkbench

**Agent Integration:**
- `autogen-agentchat/src/autogen_agentchat/agents/_assistant_agent.py:772-789` - Tool registration
- `autogen-agentchat/src/autogen_agentchat/agents/_assistant_agent.py:1196-1215` - Parallel execution
- `autogen-agentchat/src/autogen_agentchat/agents/_assistant_agent.py:1536-1624` - Single tool execution

**Built-in Tools:**
- `autogen-ext/src/autogen_ext/agents/web_surfer/_tool_definitions.py` - Web surfing tools
- `autogen-ext/src/autogen_ext/agents/file_surfer/_tool_definitions.py` - File browsing tools
- `autogen-ext/src/autogen_ext/agents/video_surfer/tools.py` - Video processing tools
- `autogen-agentchat/src/autogen_agentchat/tools/_agent.py` - AgentTool
- `autogen-agentchat/src/autogen_agentchat/tools/_team.py` - TeamTool

**Tool Agent (Core Runtime):**
- `autogen-core/src/autogen_core/tool_agent/_tool_agent.py:40-97` - ToolAgent class

## Implications for New Framework

### Positive Patterns

1. **Protocol + ABC Hybrid**
   - Protocol enables duck typing (any object matching signature works)
   - ABC provides structured base for inheritance
   - Generic typing (`Generic[ArgsT, ReturnT]`) ensures type safety
   - **Adoption**: Use Protocol for interface, ABC for default implementations

2. **Automatic Function Wrapping**
   - Zero-friction tool creation: just write typed functions
   - Introspection generates schemas automatically
   - Annotated types for rich descriptions
   - **Adoption**: Essential for developer experience

3. **Pydantic-Based Validation**
   - Automatic validation at runtime
   - Rich error messages with field-level detail
   - JSON Schema generation for free
   - **Adoption**: Use Pydantic for all tool input/output models

4. **Workbench Abstraction**
   - Clean separation: tool definition vs. tool collection
   - Shared state management across related tools
   - Dynamic tool discovery (tools can change between calls)
   - **Adoption**: Implement for complex tool ecosystems

5. **Structured Error Feedback**
   - Errors returned as `FunctionExecutionResult(is_error=True)`
   - LLM sees detailed error messages
   - Enables self-correction via reflection
   - **Adoption**: Always return structured errors, never raise to LLM

6. **Parallel Execution by Default**
   - `asyncio.gather` for concurrent tool calls
   - Massive speedup for independent operations
   - Opt-out via model client configuration
   - **Adoption**: Default to parallel, provide escape hatch

7. **Streaming Support**
   - Tools can emit intermediate results
   - Enables progress reporting for long operations
   - Clean protocol extension (`StreamTool`)
   - **Adoption**: Build streaming into core protocol

8. **Strict Mode for Structured Output**
   - Compatible with OpenAI structured output mode
   - No defaults, no additional properties
   - Enforced at schema generation time
   - **Adoption**: Support for models requiring strict schemas

9. **Cancellation Token Pattern**
   - Explicit cancellation support throughout
   - Link to asyncio futures for timeout control
   - **Adoption**: Essential for production reliability

10. **Component Serialization**
    - Tools can be serialized to/from config
    - Enables persistence and distribution
    - Security warning for code execution
    - **Adoption**: Implement with clear security boundaries

### Considerations

1. **Thread Safety Assumptions**
   - Agent and tools are NOT thread-safe by design
   - State mutation expected during execution
   - **Implication**: Document clearly, provide thread-safe alternatives if needed

2. **No Built-in Retry at Tool Layer**
   - Retry logic lives at agent orchestration level
   - Tools execute once, failures bubble up
   - **Implication**: Consider tool-level retry decorators for transient failures

3. **Manual Schema Definitions Coexist**
   - Some tools (web surfer) use manual `ToolSchema` objects
   - Bypasses Pydantic validation benefits
   - **Implication**: Prefer Pydantic, allow manual as escape hatch

4. **Workbench Adds Indirection**
   - Tool → Workbench → Agent creates extra layer
   - Benefits shared state, costs simplicity
   - **Implication**: Make workbench optional for simple use cases

5. **Function Tool Security Warning**
   - `_from_config` executes arbitrary code
   - Only load from trusted sources
   - **Implication**: Implement sandboxing or code signing for config loading

6. **Limited Timeout Support**
   - No built-in timeout mechanism
   - Relies on `CancellationToken.link_future()` pattern
   - **Implication**: Provide higher-level timeout utilities

7. **Tool Discovery at Call Time**
   - Workbench tools queried via `await wb.list_tools()` during execution
   - Dynamic but adds latency
   - **Implication**: Cache tool schemas where possible

## Anti-Patterns Observed

1. **Inconsistent Schema Sources**
   - Some tools use Pydantic (`FunctionTool`)
   - Others use manual dictionaries (web surfer tools)
   - Breaks type safety and validation uniformity
   - **Avoid**: Standardize on single schema source

2. **Stateful Tools Without State Management**
   - Some tools maintain state but don't implement `BaseToolWithState`
   - State not serializable/restorable
   - **Avoid**: All stateful tools must implement state protocol

3. **Error Message Formatting Inconsistency**
   - Some errors just `str(e)`
   - Others format recursively through `ExceptionGroup`
   - **Avoid**: Standardize error serialization

4. **No Tool Versioning**
   - Tool schemas can change, breaking compatibility
   - No version field in `ToolSchema`
   - **Avoid**: Add version metadata to tool definitions

5. **Hardcoded Tool Discovery Order**
   - Handoff tools checked before workbench tools
   - No priority/ordering mechanism
   - **Avoid**: Implement explicit tool precedence

6. **Limited Return Type Serialization**
   - `return_value_as_string()` uses basic `str()` fallback
   - No customization for complex types
   - **Avoid**: Provide serialization registry or protocol

7. **No Tool Call Tracing Correlation**
   - `call_id` parameter optional, not always propagated
   - Difficult to trace tool execution through logs
   - **Avoid**: Make call_id required, use correlation IDs

8. **Implicit Function Naming**
   - Function name becomes tool name automatically
   - Refactoring breaks LLM expectations
   - **Avoid**: Require explicit tool name in production systems
