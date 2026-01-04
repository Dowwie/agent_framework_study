# Tool Interface Analysis: aws-strands

## Summary
- **Tool Modeling**: Dual-interface (Abstract base class + Decorator pattern)
- **Schema Generation**: Hybrid (Pydantic introspection for decorated functions, manual for class-based tools)
- **Registration Pattern**: Explicit registry with dynamic loading support
- **Error Handling**: Detailed with errors-as-data approach (ToolResult with status)
- **Built-in Tools**: 4 core tools (stop_conversation, noop, MCP adapter, structured_output)
- **Parallel Execution**: Full support via concurrent/sequential executors

## Tool Modeling

### Core Abstraction

AWS Strands uses a dual-interface approach with an abstract base class that all tools must implement:

```python
# src/strands/types/tools.py
class AgentTool(ABC):
    """Abstract base class for all SDK tools."""

    _is_dynamic: bool

    def __init__(self) -> None:
        self._is_dynamic = False

    @property
    @abstractmethod
    def tool_name(self) -> str:
        """The unique name of the tool used for identification and invocation."""
        pass

    @property
    @abstractmethod
    def tool_spec(self) -> ToolSpec:
        """Tool specification that describes its functionality and parameters."""
        pass

    @property
    @abstractmethod
    def tool_type(self) -> str:
        """The type of the tool implementation (e.g., 'python', 'function', 'mcp')."""
        pass

    @property
    def supports_hot_reload(self) -> bool:
        """Whether the tool supports automatic reloading when modified."""
        return False

    @abstractmethod
    def stream(self, tool_use: ToolUse, invocation_state: dict[str, Any], **kwargs: Any) -> ToolGenerator:
        """Stream tool events and return the final result."""
        ...

    @property
    def is_dynamic(self) -> bool:
        """Whether the tool was dynamically loaded during runtime."""
        return self._is_dynamic

    def mark_dynamic(self) -> None:
        """Mark this tool as dynamically loaded."""
        self._is_dynamic = True
```

### Concrete Implementations

**1. DecoratedFunctionTool** (function-based via `@tool` decorator):
```python
# src/strands/tools/decorator.py
class DecoratedFunctionTool(AgentTool, Generic[P, R]):
    """An AgentTool that wraps a function decorated with @tool."""

    _tool_name: str
    _tool_spec: ToolSpec
    _tool_func: Callable[P, R]
    _metadata: FunctionToolMetadata

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        """Call the original function with provided arguments."""
        return self._tool_func(*args, **kwargs)

    @property
    def tool_type(self) -> str:
        return "function"
```

**2. PythonAgentTool** (module-based):
```python
# src/strands/tools/tools.py
class PythonAgentTool(AgentTool):
    """Tool implementation for Python-based tools."""

    _tool_name: str
    _tool_spec: ToolSpec
    _tool_func: ToolFunc

    @property
    def tool_type(self) -> str:
        return "python"
```

**3. MCPAgentTool** (Model Context Protocol adapter):
```python
# src/strands/tools/mcp/mcp_agent_tool.py
class MCPAgentTool(AgentTool):
    """Adapter class that wraps an MCP tool and exposes it as an AgentTool."""

    mcp_tool: MCPTool
    mcp_client: MCPClient
    _agent_tool_name: str
    timeout: timedelta | None

    @property
    def tool_type(self) -> str:
        return "python"
```

**4. StructuredOutputTool** (Pydantic validation):
```python
# src/strands/tools/structured_output/structured_output_tool.py
class StructuredOutputTool(AgentTool):
    """Tool implementation for structured output validation."""

    _structured_output_type: Type[BaseModel]
    _tool_spec: ToolSpec
    _tool_name: str

    @property
    def tool_type(self) -> str:
        return "structured_output"
```

### Key Attributes

| Attribute | Type | Purpose |
|-----------|------|---------|
| tool_name | str | Unique identifier for tool invocation |
| tool_spec | ToolSpec | JSON schema + metadata for LLM consumption |
| tool_type | str | Implementation category (function/python/mcp/structured_output) |
| supports_hot_reload | bool | Whether tool can be reloaded at runtime |
| is_dynamic | bool | Whether loaded dynamically vs statically |

### ToolSpec Structure

```python
class ToolSpec(TypedDict):
    """Specification for a tool that can be used by an agent."""

    description: str
    inputSchema: JSONSchema  # {"json": {...}}
    name: str
    outputSchema: NotRequired[JSONSchema]  # Optional, not all providers support
```

## Schema Generation

### Method Used

AWS Strands uses a **hybrid approach** depending on tool type:

**1. Decorator-Based (Automatic Introspection via Pydantic)**

```python
# src/strands/tools/decorator.py
class FunctionToolMetadata:
    """Helper class to extract and manage function metadata for tool decoration."""

    def _create_input_model(self) -> Type[BaseModel]:
        """Create a Pydantic model from function signature for input validation."""
        field_definitions: dict[str, Any] = {}

        for name, param in self.signature.parameters.items():
            # Skip special parameters (self, cls, agent, tool_context)
            if self._is_special_parameter(name):
                continue

            param_type = param.annotation
            if param_type is inspect.Parameter.empty:
                param_type = Any
            default = ... if param.default is inspect.Parameter.empty else param.default

            actual_type, field_info = self._extract_annotated_metadata(param_type, name, default)
            field_definitions[name] = (actual_type, field_info)

        model_name = f"{self.func.__name__.capitalize()}Tool"

        if field_definitions:
            return create_model(model_name, **field_definitions)
        else:
            return create_model(model_name)

    def extract_metadata(self) -> ToolSpec:
        """Extract metadata from the function to create a tool specification."""
        func_name = self.func.__name__
        description = self._extract_description_from_docstring()

        # Get schema directly from the Pydantic model
        input_schema = self.input_model.model_json_schema()

        # Clean up Pydantic-specific schema elements
        self._clean_pydantic_schema(input_schema)

        tool_spec: ToolSpec = {
            "name": func_name,
            "description": description,
            "inputSchema": {"json": input_schema}
        }

        return tool_spec
```

**Schema Cleaning Process**:
```python
def _clean_pydantic_schema(self, schema: dict[str, Any]) -> None:
    """Clean up Pydantic schema to match Strands' expected format."""
    # Remove Pydantic metadata
    keys_to_remove = ["title", "additionalProperties"]
    for key in keys_to_remove:
        if key in schema:
            del schema[key]

    # Process properties to clean up anyOf and similar structures
    if "properties" in schema:
        for _prop_name, prop_schema in schema["properties"].items():
            # Handle anyOf constructs (common for Optional types)
            if "anyOf" in prop_schema:
                any_of = prop_schema["anyOf"]
                # Handle Optional[Type] case (represented as anyOf[Type, null])
                if len(any_of) == 2 and any(item.get("type") == "null" for item in any_of):
                    # Find the non-null type and use it directly
                    for item in any_of:
                        if item.get("type") != "null":
                            for k, v in item.items():
                                prop_schema[k] = v
                            del prop_schema["anyOf"]
                            break
```

**2. Manual Schema (Module-Based Tools)**

```python
# Module-based tools require manual TOOL_SPEC definition
TOOL_SPEC = {
    "name": "my_tool",
    "description": "Does something useful",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "First parameter"}
            },
            "required": ["param1"]
        }
    }
}

def my_tool(tool_use: ToolUse, **invocation_state) -> ToolResult:
    # Implementation
    pass
```

**3. MCP Schema (Direct Passthrough)**

```python
# src/strands/tools/mcp/mcp_agent_tool.py
@property
def tool_spec(self) -> ToolSpec:
    """Convert MCP tool specification to agent framework ToolSpec format."""
    description: str = self.mcp_tool.description or f"Tool which performs {self.mcp_tool.name}"

    spec: ToolSpec = {
        "inputSchema": {"json": self.mcp_tool.inputSchema},
        "name": self.tool_name,
        "description": description,
    }

    if self.mcp_tool.outputSchema:
        spec["outputSchema"] = {"json": self.mcp_tool.outputSchema}

    return spec
```

### Type Mapping (Python -> JSON Schema)

| Python Type | JSON Schema Type | Notes |
|-------------|------------------|-------|
| str | "string" | |
| int | "integer" | |
| float | "number" | |
| bool | "boolean" | |
| list, List[T] | "array" | Items type inferred from T |
| dict, Dict[K, V] | "object" | |
| Optional[T] | anyOf[T, null] → T | Simplified during cleaning |
| Literal["a", "b"] | enum: ["a", "b"] | |
| Pydantic BaseModel | Nested object | Via model_json_schema() |
| Annotated[T, "desc"] | T with description | String metadata extracted |

### Generated Schema Example

```python
@tool
def calculate_sum(a: int, b: int, precision: Optional[int] = 2) -> dict:
    """Calculate the sum of two numbers.

    Args:
        a: First number to add.
        b: Second number to add.
        precision: Decimal precision for result (default: 2).

    Returns:
        A dictionary with the sum.
    """
    return {"sum": round(a + b, precision)}

# Generated ToolSpec:
{
    "name": "calculate_sum",
    "description": "Calculate the sum of two numbers.\n\nReturns:\n    A dictionary with the sum.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "a": {
                    "type": "integer",
                    "description": "First number to add."
                },
                "b": {
                    "type": "integer",
                    "description": "Second number to add."
                },
                "precision": {
                    "type": "integer",
                    "description": "Decimal precision for result (default: 2)."
                }
            },
            "required": ["a", "b"]
        }
    }
}
```

## Built-in Tool Inventory

### Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| Conversation Control | stop_conversation | Gracefully end bidirectional conversations |
| Framework Internal | noop_tool | Satisfy tool spec requirements when no real tools exist |
| External Protocol | MCPAgentTool | Integrate Model Context Protocol tools |
| Output Validation | StructuredOutputTool | Validate LLM outputs against Pydantic schemas |

### Complete Tool List

| Tool Name | Location | Schema Method | Category |
|-----------|----------|---------------|----------|
| stop_conversation | src/strands/experimental/bidi/tools/stop_conversation.py | Decorator introspection | Conversation Control |
| noop | src/strands/tools/_tool_helpers.py | Decorator introspection | Framework Internal |
| MCPAgentTool | src/strands/tools/mcp/mcp_agent_tool.py | MCP schema passthrough | External Protocol |
| StructuredOutputTool | src/strands/tools/structured_output/structured_output_tool.py | Pydantic model schema | Output Validation |

### Tool Details

**1. stop_conversation**
```python
# src/strands/experimental/bidi/tools/stop_conversation.py
@tool
def stop_conversation() -> str:
    """Stop the bidirectional conversation gracefully.

    Use ONLY when user says "stop conversation" exactly.
    Do NOT use for: "stop", "goodbye", "bye", "exit", "quit", "end" or other farewells.

    Returns:
        Success message confirming the conversation will end
    """
    return "Ending conversation"
```

**2. noop_tool**
```python
# src/strands/tools/_tool_helpers.py
@tool(name="noop", description="This is a fake tool that MUST be completely ignored.")
def noop_tool() -> None:
    """No-op tool to satisfy tool spec requirement when tool messages are present.

    Some model providers (e.g., Bedrock) will return an error response if tool uses
    and tool results are present in messages without any tool specs configured.
    """
    pass
```

**3. MCPAgentTool** (Adapter Pattern)
- Wraps MCP (Model Context Protocol) tools
- Enables seamless integration with MCP servers
- Supports name disambiguation for conflicting tool names
- Configurable timeout support

**4. StructuredOutputTool**
- Validates LLM outputs against Pydantic models
- Auto-generates tool spec from Pydantic schema
- Returns detailed validation errors to LLM for correction
- Caches tool specs for performance

## Registration & Discovery

### Pattern

AWS Strands uses an **explicit registry pattern** with support for both static and dynamic tool loading.

```python
# src/strands/tools/registry.py
class ToolRegistry:
    """Central registry for all tools available to the agent."""

    def __init__(self) -> None:
        self.registry: Dict[str, AgentTool] = {}
        self.dynamic_tools: Dict[str, AgentTool] = {}
        self.tool_config: Optional[Dict[str, Any]] = None
        self._tool_providers: List[ToolProvider] = []
        self._registry_id = str(uuid.uuid4())
```

### Registration Flow

**1. Static Registration (Agent Initialization)**
```python
from strands import Agent, tool

@tool
def my_tool(param: str) -> str:
    return f"Got: {param}"

# Direct registration via agent constructor
agent = Agent(tools=[my_tool])
```

**2. Dynamic Loading (String-Based)**
```python
# Tool registry supports multiple string formats:

# 1. Local file path
tools = ["./path/to/tool.py"]

# 2. Module import path
tools = ["strands_tools.file_read"]

# 3. Module with multiple tools
tools = ["tests.fixtures.say_tool"]

# 4. Module with specific function
tools = ["tests.fixtures.say_tool:say"]

# Process tools
agent.tool_registry.process_tools(tools)
```

**3. Directory Discovery**
```python
# Auto-discover tools from ./tools/ directory
agent.tool_registry.initialize_tools(load_tools_from_directory=True)

# Scans for:
# - ./tools/*.py files
# - Decorated @tool functions
# - Module-based tools with TOOL_SPEC
```

**4. ToolProvider Pattern (Advanced)**
```python
# MCP client as a ToolProvider
from strands.tools.mcp import MCPClient

mcp_client = MCPClient(server_params)
agent = Agent(tools=[mcp_client])  # Auto-loads all MCP tools
```

### Tool Name Validation

```python
# src/strands/tools/tools.py
def validate_tool_use_name(tool: ToolUse) -> None:
    """Validate the name of a tool use."""
    if "name" not in tool:
        raise InvalidToolUseNameException("tool name missing")

    tool_name = tool["name"]
    tool_name_pattern = r"^[a-zA-Z0-9_\-]{1,}$"
    tool_name_max_length = 64
    valid_name_pattern = bool(re.match(tool_name_pattern, tool_name))

    if not valid_name_pattern:
        raise InvalidToolUseNameException(f"tool_name=<{tool_name}> | invalid tool name pattern")

    if len(tool_name) > tool_name_max_length:
        raise InvalidToolUseNameException(
            f"tool_name=<{tool_name}>, tool_name_max_length=<{tool_name_max_length}> | invalid tool name length"
        )
```

### Duplicate Detection

```python
# src/strands/tools/registry.py
def register_tool(self, tool: AgentTool) -> None:
    """Register a tool function with the given name."""

    # Check duplicate tool name
    if tool.tool_name in self.registry and not tool.supports_hot_reload:
        raise ValueError(
            f"Tool name '{tool.tool_name}' already exists. Cannot register tools with exact same name."
        )

    # Check for normalized name conflicts (- vs _)
    if self.registry.get(tool.tool_name) is None:
        normalized_name = tool.tool_name.replace("-", "_")

        matching_tools = [
            tool_name
            for (tool_name, tool) in self.registry.items()
            if tool_name.replace("-", "_") == normalized_name
        ]

        if matching_tools:
            raise ValueError(
                f"Tool name '{tool.tool_name}' already exists as '{matching_tools[0]}'."
                " Cannot add a duplicate tool which differs by a '-' or '_'"
            )
```

## Execution Flow

### Invocation Pattern

**High-Level Flow:**
1. LLM returns ToolUse requests
2. Executor selects concurrent or sequential execution strategy
3. Before-tool-call hooks fire
4. Tool validation occurs
5. Tool.stream() executes and yields events
6. After-tool-call hooks fire with results
7. ToolResult returned to LLM

**Detailed Execution:**

```python
# src/strands/tools/executors/_executor.py
@staticmethod
async def _stream(
    agent: "Agent | BidiAgent",
    tool_use: ToolUse,
    tool_results: list[ToolResult],
    invocation_state: dict[str, Any],
    **kwargs: Any,
) -> AsyncGenerator[TypedEvent, None]:
    """Stream tool events with additional logic for validation, hooks, tracing, and errors."""

    tool_name = tool_use["name"]

    # 1. Lookup tool in registry
    tool_info = agent.tool_registry.dynamic_tools.get(tool_name)
    tool_func = tool_info if tool_info is not None else agent.tool_registry.registry.get(tool_name)
    tool_spec = tool_func.tool_spec if tool_func is not None else None

    # 2. Populate invocation state
    invocation_state.update({
        "agent": agent,
        "model": agent.model,
        "messages": agent.messages,
        "system_prompt": agent.system_prompt,
        "tool_config": ToolConfig(...)
    })

    # 3. Fire before-tool-call hook
    before_event, interrupts = await ToolExecutor._invoke_before_tool_call_hook(
        agent, tool_func, tool_use, invocation_state
    )

    if interrupts:
        yield ToolInterruptEvent(tool_use, interrupts)
        return

    if before_event.cancel_tool:
        # Tool cancelled by hook
        yield ToolCancelEvent(tool_use, cancel_message)
        yield ToolResultEvent(cancel_result)
        return

    # 4. Execute tool
    try:
        selected_tool = before_event.selected_tool

        if not selected_tool:
            # Unknown tool
            result: ToolResult = {
                "toolUseId": str(tool_use.get("toolUseId")),
                "status": "error",
                "content": [{"text": f"Unknown tool: {tool_name}"}]
            }
            yield ToolResultEvent(result)
            return

        # Stream tool execution
        async for event in selected_tool.stream(tool_use, invocation_state, **kwargs):
            if isinstance(event, ToolInterruptEvent):
                yield event
                return

            if isinstance(event, ToolResultEvent):
                event = event.tool_result
                break

            if isinstance(event, ToolStreamEvent):
                yield event
            else:
                yield ToolStreamEvent(tool_use, event)

        result = cast(ToolResult, event)

        # 5. Fire after-tool-call hook
        after_event, _ = await ToolExecutor._invoke_after_tool_call_hook(
            agent, selected_tool, tool_use, invocation_state, result
        )

        yield ToolResultEvent(after_event.result)
        tool_results.append(after_event.result)

    except Exception as e:
        # Return error result with exception details
        error_result: ToolResult = {
            "toolUseId": str(tool_use.get("toolUseId")),
            "status": "error",
            "content": [{"text": f"Error: {str(e)}"}]
        }

        after_event, _ = await ToolExecutor._invoke_after_tool_call_hook(
            agent, selected_tool, tool_use, invocation_state, error_result, exception=e
        )
        yield ToolResultEvent(after_event.result)
```

### Decorator-Based Tool Execution

```python
# src/strands/tools/decorator.py
@override
async def stream(self, tool_use: ToolUse, invocation_state: dict[str, Any], **kwargs: Any) -> ToolGenerator:
    """Stream the tool with a tool use specification."""

    tool_use_id = tool_use.get("toolUseId", "unknown")
    tool_input: dict[str, Any] = tool_use.get("input", {})

    try:
        # 1. Validate input against Pydantic model
        validated_input = self._metadata.validate_input(tool_input)

        # 2. Inject special framework-provided parameters
        self._metadata.inject_special_parameters(validated_input, tool_use, invocation_state)

        # 3. Execute based on function type
        if inspect.isasyncgenfunction(self._tool_func):
            # Async generator - yield streaming events and final result
            sub_events = self._tool_func(**validated_input)
            async for sub_event in sub_events:
                yield ToolStreamEvent(tool_use, sub_event)
            yield self._wrap_tool_result(tool_use_id, sub_event)

        elif inspect.iscoroutinefunction(self._tool_func):
            # Async function - yield only the result
            result = await self._tool_func(**validated_input)
            yield self._wrap_tool_result(tool_use_id, result)

        else:
            # Sync function - run in thread pool
            result = await asyncio.to_thread(self._tool_func, **validated_input)
            yield self._wrap_tool_result(tool_use_id, result)

    except InterruptException as e:
        yield ToolInterruptEvent(tool_use, [e.interrupt])
        return

    except ValueError as e:
        # Validation errors
        yield self._wrap_tool_result(tool_use_id, {
            "toolUseId": tool_use_id,
            "status": "error",
            "content": [{"text": f"Error: {str(e)}"}]
        })

    except Exception as e:
        # Other errors
        yield self._wrap_tool_result(tool_use_id, {
            "toolUseId": tool_use_id,
            "status": "error",
            "content": [{"text": f"Error: {type(e).__name__} - {str(e)}"}]
        })
```

### Error Handling

| Error Type | Handling | Feedback to LLM |
|------------|----------|-----------------|
| Validation Error (Pydantic) | Caught in decorator | ToolResult status="error" with validation details |
| Unknown Tool | Caught in executor | ToolResult status="error" with "Unknown tool: {name}" |
| Invalid Tool Name | Caught in validator | ToolResult status="error" with validation message |
| Tool Execution Exception | Caught in executor | ToolResult status="error" with exception type and message |
| InterruptException | Caught in decorator | ToolInterruptEvent yielded, execution halts |
| Tool Cancellation (hook) | Caught in executor | ToolCancelEvent + ToolResult status="error" |

### ToolContext Injection

```python
# Special parameter: tool_context
@tool(context=True)
def my_tool(param: str, tool_context: ToolContext) -> str:
    tool_id = tool_context.tool_use["toolUseId"]
    agent = tool_context.agent
    invocation_state = tool_context.invocation_state

    # Can also trigger interrupts
    tool_context.interrupt("user_confirmation", {"action": "delete_file"})

    return f"Processed with tool ID: {tool_id}"

# Alternative: custom context parameter name
@tool(context="ctx")
def my_tool(param: str, ctx: ToolContext) -> str:
    return str(ctx.tool_use)
```

### Retry Mechanisms

**No Built-in Retry** - AWS Strands follows an "errors-as-data" philosophy:
- Errors are returned as ToolResult with status="error"
- LLM receives error message and can self-correct
- Framework does not automatically retry failed tools
- Retry logic can be implemented in hooks if needed

**Example Error Feedback Loop:**
```python
# Tool fails with validation error
{
    "toolUseId": "123",
    "status": "error",
    "content": [{"text": "Validation failed: Field 'count': Input should be greater than 0"}]
}

# LLM receives this and can:
# 1. Fix parameters and retry
# 2. Choose different tool
# 3. Ask user for clarification
```

## Parallel Execution

### Concurrent Executor

```python
# src/strands/tools/executors/concurrent.py
class ConcurrentToolExecutor(ToolExecutor):
    """Execute tools concurrently using asyncio tasks."""

    @override
    async def _execute(
        self,
        agent: "Agent",
        tool_uses: list[ToolUse],
        tool_results: list[ToolResult],
        cycle_trace: Trace,
        cycle_span: Any,
        invocation_state: dict[str, Any],
        structured_output_context: "StructuredOutputContext | None" = None,
    ) -> AsyncGenerator[TypedEvent, None]:
        """Execute tools concurrently."""

        # Create task queue and events for synchronization
        task_queue: asyncio.Queue[tuple[int, Any]] = asyncio.Queue()
        task_events = [asyncio.Event() for _ in tool_uses]
        stop_event = object()

        # Launch all tasks concurrently
        tasks = [
            asyncio.create_task(
                self._task(
                    agent, tool_use, tool_results, cycle_trace, cycle_span,
                    invocation_state, task_id, task_queue, task_events[task_id],
                    stop_event, structured_output_context
                )
            )
            for task_id, tool_use in enumerate(tool_uses)
        ]

        # Stream results as they complete
        task_count = len(tasks)
        while task_count:
            task_id, event = await task_queue.get()
            if event is stop_event:
                task_count -= 1
                continue

            yield event
            task_events[task_id].set()  # Allow task to continue

    async def _task(
        self, agent, tool_use, tool_results, cycle_trace, cycle_span,
        invocation_state, task_id, task_queue, task_event, stop_event,
        structured_output_context
    ) -> None:
        """Execute a single tool and put results in the task queue."""
        try:
            events = ToolExecutor._stream_with_trace(
                agent, tool_use, tool_results, cycle_trace, cycle_span,
                invocation_state, structured_output_context
            )
            async for event in events:
                task_queue.put_nowait((task_id, event))
                await task_event.wait()  # Wait for consumer to process
                task_event.clear()
        finally:
            task_queue.put_nowait((task_id, stop_event))
```

**Concurrency Model:**
- Uses asyncio.create_task() for true concurrent execution
- Task queue coordinates event streaming
- Events from different tools can interleave
- All tools execute in parallel, results streamed as available

### Sequential Executor

```python
# src/strands/tools/executors/sequential.py
class SequentialToolExecutor(ToolExecutor):
    """Execute tools sequentially (one at a time)."""

    @override
    async def _execute(
        self,
        agent: "Agent",
        tool_uses: list[ToolUse],
        tool_results: list[ToolResult],
        cycle_trace: Trace,
        cycle_span: Any,
        invocation_state: dict[str, Any],
        structured_output_context: "StructuredOutputContext | None" = None,
    ) -> AsyncGenerator[TypedEvent, None]:
        """Execute tools sequentially. Breaks early if an interrupt is raised."""

        interrupted = False

        for tool_use in tool_uses:
            events = ToolExecutor._stream_with_trace(
                agent, tool_use, tool_results, cycle_trace, cycle_span,
                invocation_state, structured_output_context
            )
            async for event in events:
                if isinstance(event, ToolInterruptEvent):
                    interrupted = True

                yield event

            if interrupted:
                break  # Stop executing remaining tools
```

**Sequential Model:**
- Tools execute one after another
- Next tool waits for previous to complete
- Early termination on interrupt
- Deterministic execution order

### Execution Strategy Configuration

```python
from strands import Agent
from strands.tools.executors.concurrent import ConcurrentToolExecutor
from strands.tools.executors.sequential import SequentialToolExecutor

# Concurrent execution (default)
agent = Agent(tools=[...], tool_executor=ConcurrentToolExecutor())

# Sequential execution
agent = Agent(tools=[...], tool_executor=SequentialToolExecutor())
```

## Code References

### Key Files and Lines

| Component | File | Key Lines |
|-----------|------|-----------|
| AgentTool Base Class | src/strands/types/tools.py | 218-307 |
| DecoratedFunctionTool | src/strands/tools/decorator.py | 427-661 |
| @tool Decorator | src/strands/tools/decorator.py | 676-778 |
| FunctionToolMetadata | src/strands/tools/decorator.py | 80-421 |
| ToolRegistry | src/strands/tools/registry.py | 30-723 |
| PythonAgentTool | src/strands/tools/tools.py | 157-236 |
| ToolExecutor Base | src/strands/tools/executors/_executor.py | 31-340 |
| ConcurrentToolExecutor | src/strands/tools/executors/concurrent.py | 18-119 |
| SequentialToolExecutor | src/strands/tools/executors/sequential.py | 17-61 |
| MCPAgentTool | src/strands/tools/mcp/mcp_agent_tool.py | 24-120 |
| StructuredOutputTool | src/strands/tools/structured_output/structured_output_tool.py | 26-159 |
| Tool Validation | src/strands/tools/tools.py | 33-72 |
| Tool Loading | src/strands/tools/loader.py | 23-149 |
| Schema Normalization | src/strands/tools/tools.py | 104-154 |

## Implications for New Framework

### Positive Patterns

1. **Dual Interface Design**
   - Decorator for ergonomics (`@tool`)
   - Base class for extensibility (MCP, custom implementations)
   - Best of both worlds approach

2. **Pydantic-Powered Introspection**
   - Automatic schema generation from type hints
   - Built-in validation before execution
   - Reduces boilerplate dramatically

3. **Errors-as-Data Philosophy**
   - ToolResult always has status field ("success" | "error")
   - Error messages flow back to LLM for self-correction
   - No hidden exception swallowing

4. **ToolContext for Framework Data**
   - Clean way to inject agent, tool_use, invocation_state
   - Optional parameter (only inject if requested)
   - Avoids polluting tool signatures

5. **Streaming Event Model**
   - Tools can yield intermediate progress (ToolStreamEvent)
   - Final result is ToolResultEvent
   - Supports long-running operations with feedback

6. **Concurrent + Sequential Executors**
   - Pluggable execution strategy
   - Concurrent by default for performance
   - Sequential option for determinism/debugging

7. **Hot Reload Support**
   - Dynamic tool replacement without restart
   - Useful for development and production updates
   - Opt-in via supports_hot_reload flag

8. **MCP Integration**
   - First-class support for Model Context Protocol
   - Tool adapter pattern for external systems
   - Name disambiguation for conflicts

### Considerations

1. **Schema Cleaning Complexity**
   - Pydantic v2 schemas need post-processing
   - anyOf handling for Optional types
   - Metadata removal (title, additionalProperties)
   - **Recommendation**: Document expected schema format clearly

2. **Manual TOOL_SPEC for Module-Based Tools**
   - Module-based tools require manual schema definition
   - Error-prone compared to decorator introspection
   - **Recommendation**: Prefer decorator pattern unless legacy compatibility needed

3. **Special Parameter Handling**
   - Multiple special params: self, cls, agent, tool_context
   - Context parameter name is configurable
   - **Recommendation**: Standardize on one context parameter name

4. **Type Hint Limitations**
   - Annotated[T, Field(...)] explicitly not supported
   - Must use simple string descriptions
   - **Recommendation**: Document supported Annotated metadata

5. **No Built-in Retry Logic**
   - Framework doesn't auto-retry failed tools
   - Relies on LLM self-correction
   - **Recommendation**: Provide hook examples for custom retry logic

6. **Tool Name Constraints**
   - Max 64 characters
   - Pattern: `^[a-zA-Z0-9_\-]{1,}$`
   - Duplicate detection includes normalization (- vs _)
   - **Recommendation**: Validate names at registration time

## Anti-Patterns Observed

1. **ToolContext Type Annotation**
   ```python
   # agent: Any - loses type safety
   # Should use Union[Agent, BidiAgent] or Protocol
   agent: Any  # Agent or BidiAgent - using Any for backwards compatibility
   ```
   **Impact**: Loss of type checking for agent methods in tool implementations
   **Recommendation**: Define shared Protocol or use Union type

2. **Runtime Import for Type Checking**
   ```python
   @staticmethod
   def _is_agent(agent: "Agent | BidiAgent") -> bool:
       from ...agent import Agent  # Runtime import to avoid circular dependency
       return isinstance(agent, Agent)
   ```
   **Impact**: Hidden dependency, fragile to refactoring
   **Recommendation**: Restructure to avoid circular imports or use Protocol

3. **Inconsistent Error Handling**
   - Some tools raise exceptions
   - Some return error ToolResult
   - Executor catches all and converts to ToolResult
   **Impact**: Inconsistent behavior across tool types
   **Recommendation**: Standardize error handling pattern in base class

4. **Global Schema Cache**
   ```python
   _TOOL_SPEC_CACHE: dict[Type[BaseModel], ToolSpec] = {}
   ```
   **Impact**: Global mutable state, potential memory leak
   **Recommendation**: Make cache an instance variable or use LRU cache

5. **Sync Functions Run in Thread Pool**
   ```python
   result = await asyncio.to_thread(self._tool_func, **validated_input)
   ```
   **Impact**: Thread pool overhead for every sync tool call
   **Recommendation**: Document async tool pattern as preferred, warn about sync overhead

6. **Mutation of Input Schema During Validation**
   ```python
   # validate_tool_spec mutates tool_spec in place
   def validate_tool_spec(self, tool_spec: ToolSpec) -> None:
       # ...
       if "json" not in tool_spec["inputSchema"]:
           json_schema = normalize_schema(tool_spec["inputSchema"])
           tool_spec["inputSchema"] = {"json": json_schema}  # Mutation
   ```
   **Impact**: Surprising side effects, hard to debug
   **Recommendation**: Make validation pure, return normalized spec

7. **Noop Tool as Workaround**
   ```python
   @tool(name="noop", description="This is a fake tool that MUST be completely ignored.")
   def noop_tool() -> None:
       """Workaround for Bedrock requiring tool specs when tool messages present."""
       pass
   ```
   **Impact**: Framework working around provider limitations, pollutes tool namespace
   **Recommendation**: Handle this at the provider adapter level, not in shared tool layer
