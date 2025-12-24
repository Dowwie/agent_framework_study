# Tool Interface Analysis: CAMEL

## Tool Definition Model

### Function Tool Wrapper

**Core abstraction:**

```python
class FunctionTool:
    def __init__(
        self,
        func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        self.func = func
        self.name = name or func.__name__
        self.description = description or self._extract_description(func)

        # Generate OpenAI-compatible schema automatically
        self.openai_tool_schema = get_openai_tool_schema(func)

    def _extract_description(self, func: Callable) -> str:
        # Parse docstring using docstring_parser
        parsed_doc = parse(inspect.getdoc(func))
        return parsed_doc.short_description or ""
```

**Usage:**
```python
def search_web(query: str, max_results: int = 5) -> str:
    """Search the web for information.

    Args:
        query: The search query string
        max_results: Maximum number of results to return

    Returns:
        Formatted search results
    """
    # Implementation
    ...

tool = FunctionTool(search_web)
# Automatically generates OpenAI tool schema from signature + docstring
```

**Key Design:** Zero boilerplate - function signature and docstring are the entire interface

## Schema Generation

### Introspection-Based Schema

**Automatic schema from Python function:**

```python
def get_openai_tool_schema(func: Callable) -> Dict[str, Any]:
    # 1. Extract parameters from signature
    params = signature(func).parameters
    fields = {}

    for param_name, p in params.items():
        param_type = p.annotation if p.annotation != Parameter.empty else Any
        param_default = p.default

        if param_default is Parameter.empty:
            # Required parameter
            fields[param_name] = (param_type, FieldInfo())
        else:
            # Optional parameter with default
            fields[param_name] = (param_type, FieldInfo(default=param_default))

    # 2. Create Pydantic model dynamically
    model = create_model(
        f"{func.__name__}_params",
        **fields
    )

    # 3. Get Pydantic schema
    schema = get_pydantic_object_schema(model)

    # 4. Parse docstring for descriptions
    parsed_doc = parse(inspect.getdoc(func))
    description = parsed_doc.short_description

    # 5. Add parameter descriptions from docstring
    for param in parsed_doc.params:
        if param.arg_name in schema["properties"]:
            schema["properties"][param.arg_name]["description"] = param.description

    # 6. Build OpenAI tool schema
    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": description,
            "parameters": schema,
        }
    }
```

**Supported Docstring Styles:**
- **ReST:** `:param name: Description`
- **Google:** `Args:\n    name: Description`
- **NumPy:** `Parameters\n----------\nname : type\n    Description`
- **Epydoc:** `@param name: Description`

**Example:**
```python
def calculate(x: float, y: float, operation: Literal["add", "subtract", "multiply", "divide"]) -> float:
    """Perform a mathematical operation.

    Args:
        x: First number
        y: Second number
        operation: The operation to perform

    Returns:
        Result of the calculation
    """
    ...

# Generates:
{
    "type": "function",
    "function": {
        "name": "calculate",
        "description": "Perform a mathematical operation.",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "First number"},
                "y": {"type": "number", "description": "Second number"},
                "operation": {
                    "type": "string",
                    "enum": ["add", "subtract", "multiply", "divide"],
                    "description": "The operation to perform"
                }
            },
            "required": ["x", "y", "operation"]
        }
    }
}
```

**Strengths:**
- No manual schema writing
- Type hints → schema types
- Docstrings → descriptions
- Pydantic handles complex types (Literal, Union, List, Dict)

**Limitations:**
- Can't express all JSON Schema constraints (min/max, regex patterns)
- No validation of docstring completeness (missing param descriptions)

## Toolkit Abstraction

### BaseToolkit Pattern

**Template for creating tool collections:**

```python
class BaseToolkit(metaclass=AgentOpsMeta):
    timeout: Optional[float] = Constants.TIMEOUT_THRESHOLD

    def __init__(self, timeout: Optional[float] = None):
        self.timeout = timeout

    def get_tools(self) -> List[FunctionTool]:
        """Return list of tools in this toolkit."""
        raise NotImplementedError

    def __init_subclass__(cls, **kwargs):
        # Automatically wrap ALL methods with timeout
        super().__init_subclass__(**kwargs)
        for attr_name, attr_value in cls.__dict__.items():
            if callable(attr_value) and not attr_name.startswith("__"):
                if not getattr(attr_value, '_manual_timeout', False):
                    setattr(cls, attr_name, with_timeout(attr_value))
```

**Example Toolkit:**
```python
class MathToolkit(BaseToolkit):
    def add(self, a: float, b: float) -> float:
        """Add two numbers."""
        return a + b

    def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers."""
        return a * b

    def get_tools(self) -> List[FunctionTool]:
        return [
            FunctionTool(self.add),
            FunctionTool(self.multiply),
        ]
```

**Developer Experience:**
1. Create class extending `BaseToolkit`
2. Add methods (automatically get timeout wrapping)
3. Implement `get_tools()` to return FunctionTool wrappers
4. Done - no decorators, no schema writing

## Tool Execution

### Sync and Async Tools

**Unified execution handling:**

```python
async def _aexecute_tool(
    self,
    tool: FunctionTool,
    args: Dict[str, Any],
) -> ToolResult:
    try:
        if inspect.iscoroutinefunction(tool.func):
            # Native async tool
            result = await tool.func(**args)
        else:
            # Sync tool - run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                _SYNC_TOOL_EXECUTOR,  # Shared ThreadPoolExecutor(max_workers=64)
                lambda: tool.func(**args)
            )

        return ToolResult(
            success=True,
            result=result,
            tool_name=tool.name,
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error_message=str(e),
            tool_name=tool.name,
        )
```

**Shared Thread Pool:**
```python
_SYNC_TOOL_EXECUTOR = ThreadPoolExecutor(max_workers=64)
```

**Benefits:**
- Mix sync and async tools seamlessly
- Sync tools don't block event loop
- 64 workers support high concurrency

**Tradeoffs:**
- Thread pool overhead for simple sync tools
- Shared pool could contention under heavy load

### Parallel Tool Execution

**Execute multiple tool calls concurrently:**

```python
async def _execute_tools_async_with_status_accumulator(
    self,
    tool_calls: List[ToolCallRequest],
) -> List[ToolResult]:
    tasks = []

    for tool_call in tool_calls:
        # Create async task for each tool
        task = asyncio.create_task(
            self._aexecute_tool_from_stream_data(tool_call)
        )
        tasks.append(task)

    # Execute all tools in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return results
```

**Pattern:**
- All tool calls from a single model response execute in parallel
- Faster than sequential execution
- `return_exceptions=True` prevents one failure from killing all tasks

## Tool Result Handling

### ToolResult Structure

```python
@dataclass
class ToolResult:
    success: bool
    result: Any = None
    error_message: Optional[str] = None
    tool_name: str = ""
    tool_call_id: Optional[str] = None
    cached: bool = False

    def to_message(self) -> BaseMessage:
        """Convert to message for sending back to model."""
        if self.success:
            content = str(self.result)
        else:
            content = f"Error: {self.error_message}"

        return BaseMessage(
            role_name="Tool",
            role_type=RoleType.ASSISTANT,
            content=content,
            meta_dict={"tool_call_id": self.tool_call_id},
        )
```

**Conversion to Model Message:**
```python
# After tool execution:
tool_results = await self._execute_tools_async(tool_calls)

# Convert to messages for model
for result in tool_results:
    tool_message = result.to_message()
    self._append_message(tool_message)

# Send back to model
response = await self._aget_model_response(...)
```

### Tool Output Caching

**Caching mechanism for repeated tool calls:**

```python
class _ToolOutputHistoryEntry:
    tool_name: str
    tool_call_id: str
    result_text: str
    record_uuids: List[str]
    record_timestamps: List[float]
    cached: bool = False

class ChatAgent:
    def __init__(self, ...):
        self._tool_output_history: List[_ToolOutputHistoryEntry] = []

    async def _aexecute_tool(self, tool: FunctionTool, args: Dict):
        # Generate cache key
        cache_key = f"{tool.name}:{json.dumps(args, sort_keys=True)}"

        # Check cache
        for entry in self._tool_output_history:
            if entry.tool_call_id == cache_key and not entry.cached:
                # Cache hit
                return ToolResult(
                    success=True,
                    result=entry.result_text,
                    cached=True,
                )

        # Cache miss - execute tool
        result = await tool.func(**args)

        # Store in cache
        entry = _ToolOutputHistoryEntry(
            tool_name=tool.name,
            tool_call_id=cache_key,
            result_text=str(result),
            record_uuids=[],
            record_timestamps=[],
            cached=False,
        )
        self._tool_output_history.append(entry)

        return ToolResult(success=True, result=result, cached=False)
```

**Benefits:**
- Avoid redundant tool calls (especially expensive ones: web search, API calls)
- Faster response for repeated queries

**Limitations:**
- No TTL (cache never expires)
- No size limit (grows unbounded)
- No cache invalidation mechanism

## External Tools

### MCP Integration

**Model Context Protocol support:**

```python
class MCPToolkit(BaseToolkit):
    def __init__(
        self,
        server_command: List[str],
        server_name: str,
        timeout: Optional[float] = None,
    ):
        super().__init__(timeout)
        self.server_command = server_command
        self.server_name = server_name
        self._tools: List[FunctionTool] = []

    async def _connect(self):
        # Connect to MCP server
        self.session = await mcp.ClientSession.connect(self.server_command)

        # List available tools from server
        tools_response = await self.session.list_tools()

        # Convert MCP tools to FunctionTool
        for mcp_tool in tools_response.tools:
            func = self._create_func_from_mcp(mcp_tool)
            self._tools.append(FunctionTool(func))

    def _create_func_from_mcp(self, mcp_tool) -> Callable:
        async def tool_func(**kwargs):
            # Call MCP server
            result = await self.session.call_tool(
                mcp_tool.name,
                arguments=kwargs
            )
            return result.content

        tool_func.__name__ = mcp_tool.name
        tool_func.__doc__ = mcp_tool.description
        return tool_func

    def get_tools(self) -> List[FunctionTool]:
        return self._tools
```

**Supported MCP Toolkits:**
- `NotionMCPToolkit`: Notion API
- `PlaywrightMCPToolkit`: Browser automation
- `GoogleDriveMCPToolkit`: Google Drive access
- `MinimaxMCPToolkit`: Minimax model tools
- `OrigeneToolkit`: Origene MCP server
- `ACIToolkit`: Azure Container Instances

**Design:** MCP servers expose tools → CAMEL wraps as FunctionTool → Agent uses normally

### OpenAPI Tools

**Automatic tool generation from OpenAPI specs:**

```python
class OpenAPIToolkit(BaseToolkit):
    def __init__(
        self,
        spec_url: str,
        timeout: Optional[float] = None,
    ):
        super().__init__(timeout)
        self.spec = self._load_openapi_spec(spec_url)
        self._tools = self._generate_tools_from_spec(self.spec)

    def _generate_tools_from_spec(self, spec: Dict) -> List[FunctionTool]:
        tools = []

        for path, path_item in spec["paths"].items():
            for method, operation in path_item.items():
                if method not in ["get", "post", "put", "delete"]:
                    continue

                # Create function for this endpoint
                func = self._create_func_from_operation(
                    path, method, operation
                )
                tools.append(FunctionTool(func))

        return tools

    def _create_func_from_operation(self, path, method, operation) -> Callable:
        def api_call(**kwargs):
            # Build request from kwargs
            url = self._build_url(path, kwargs)
            response = requests.request(method, url, **kwargs)
            return response.json()

        api_call.__name__ = operation.get("operationId", f"{method}_{path}")
        api_call.__doc__ = operation.get("description", "")
        return api_call
```

**Benefits:**
- Instant API integration from OpenAPI spec
- Auto-generates function signatures from schema
- No manual tool writing needed

## Tool Discovery

### Agent Toolkit Registration

**RegisteredAgentToolkit mixin:**

```python
class RegisteredAgentToolkit:
    """Mixin for toolkits that need agent reference."""

    def __init__(self):
        self._agent: Optional["ChatAgent"] = None

    def register_agent(self, agent: "ChatAgent") -> None:
        self._agent = agent

# ChatAgent automatically registers itself
class ChatAgent:
    def __init__(
        self,
        ...,
        toolkits_to_register_agent: Optional[List[RegisteredAgentToolkit]] = None,
    ):
        # Register agent with toolkits that need it
        if toolkits_to_register_agent:
            for toolkit in toolkits_to_register_agent:
                toolkit.register_agent(self)
```

**Use Case:** Tools that need agent context (memory access, agent state)

```python
class MemoryToolkit(BaseToolkit, RegisteredAgentToolkit):
    def recall(self, query: str) -> str:
        """Search agent memory."""
        # Access agent's memory
        context = self._agent.memory.get_context(query=query)
        return context.context_string

agent = ChatAgent(
    toolkits_to_register_agent=[MemoryToolkit()]
)
# MemoryToolkit now has access to agent.memory
```

## Tool Interface Score

**Overall: 9/10**

**Breakdown:**
- Schema Generation: 10/10 (introspection-based is excellent)
- Developer Experience: 9/10 (zero boilerplate)
- Execution Model: 9/10 (sync/async unified, parallel execution)
- External Integration: 9/10 (MCP + OpenAPI support)
- Caching: 7/10 (basic, missing TTL and size limits)
- Discovery: 8/10 (agent registration pattern is clever)
- Timeout Handling: 10/10 (automatic via metaclass)

## Patterns to Adopt

1. **Introspection-based schema generation:** Type hints + docstrings → OpenAI schema
2. **Metaclass auto-enhancement:** `__init_subclass__` for automatic timeout wrapping
3. **Unified sync/async execution:** ThreadPoolExecutor for sync tools
4. **Parallel tool execution:** `asyncio.gather()` for concurrent calls
5. **RegisteredAgentToolkit mixin:** Tools that need agent context
6. **MCP integration:** Wrap external servers as native tools
7. **OpenAPI auto-generation:** Instant API integration from specs

## Patterns to Avoid

1. **Unbounded cache:** Need TTL and size limits
2. **No cache invalidation:** Stale data can persist indefinitely
3. **Shared thread pool:** Could cause contention
4. **No schema validation:** Missing param descriptions go unnoticed

## Recommendations

1. **Add cache eviction:** TTL-based expiration and LRU eviction
2. **Cache invalidation API:** Let tools invalidate their cache entries
3. **Per-toolkit thread pools:** Isolate resource usage
4. **Schema validation:** Warn if docstring params don't match signature
5. **Tool versioning:** Track tool schema changes for compatibility
6. **Tool categories:** Group tools by domain for better organization
7. **Tool usage analytics:** Track which tools are used most
8. **Tool result streaming:** For tools with long-running output
