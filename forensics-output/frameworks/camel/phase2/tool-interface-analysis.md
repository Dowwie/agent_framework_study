# Tool Interface Analysis: CAMEL

## Summary
- **Tool Modeling**: FunctionTool wrapper class + Toolkit base class pattern
- **Schema Generation**: Automatic introspection via Pydantic + docstring parsing
- **Registration Pattern**: Manual registration via get_tools() + agent initialization
- **Error Handling**: Try-catch with detailed error feedback to LLM
- **Built-in Tools**: 70+ tools organized in 60+ toolkit classes
- **Parallel Execution**: Yes (ThreadPoolExecutor for sync, asyncio for async)
- **Async Support**: First-class async support with automatic sync-to-async bridging

## Tool Modeling

### Core Abstraction

CAMEL uses a two-layer abstraction:

1. **FunctionTool** - wraps individual functions
2. **BaseToolkit** - groups related functions

```python
# FunctionTool wraps any Python function
class FunctionTool:
    def __init__(
        self,
        func: Callable,
        openai_tool_schema: Optional[Dict[str, Any]] = None,
        synthesize_schema: Optional[bool] = False,
        synthesize_output: Optional[bool] = False,
    ) -> None:
        self.func = func
        # Schema generated automatically or provided
        self.openai_tool_schema = openai_tool_schema or get_openai_tool_schema(func)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # Direct invocation
        return self.func(*args, **kwargs)

    async def async_call(self, *args: Any, **kwargs: Any) -> Any:
        if self.is_async:
            return await self.func(*args, **kwargs)
        else:
            # Auto-bridge sync functions to async using ThreadPoolExecutor
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                _SYNC_TOOL_EXECUTOR,
                functools.partial(self.func, *args, **kwargs),
            )
```

```python
# BaseToolkit groups related tools
class BaseToolkit(metaclass=AgentOpsMeta):
    def __init__(self, timeout: Optional[float] = Constants.TIMEOUT_THRESHOLD):
        self.timeout = timeout

    def get_tools(self) -> List[FunctionTool]:
        """Returns FunctionTool objects for all toolkit methods"""
        raise NotImplementedError("Subclasses must implement this method.")
```

### Key Attributes

| Attribute | Type | Purpose |
|-----------|------|---------|
| func | Callable | The underlying Python function |
| openai_tool_schema | Dict[str, Any] | OpenAI-compatible tool schema |
| synthesize_schema | bool | Auto-generate schema via LLM if invalid |
| synthesize_output | bool | LLM synthesizes output without execution |
| synthesize_output_model | BaseModelBackend | Model for output synthesis |
| is_async | bool | Whether function is async |

## Schema Generation

### Method Used

**Automatic introspection** combining:
1. Function signature analysis (via `inspect.signature`)
2. Pydantic model generation for parameters
3. Docstring parsing (supports ReST, Google, NumPy, Epydoc)

```python
def get_openai_tool_schema(func: Callable) -> Dict[str, Any]:
    # Extract parameters from function signature
    params = signature(func).parameters
    fields = {}

    for param_name, p in params.items():
        param_type = p.annotation if p.annotation != Parameter.empty else Any
        param_default = p.default

        if param_default is Parameter.empty:
            fields[param_name] = (param_type, FieldInfo())
        else:
            fields[param_name] = (param_type, FieldInfo(default=param_default))

    # Create Pydantic model from fields
    model = create_model(to_pascal(func.__name__), **fields)
    parameters_dict = get_pydantic_object_schema(model)

    # Parse docstring for descriptions
    docstring = parse(func.__doc__ or "")
    for param in docstring.params:
        if (name := param.arg_name) in parameters_dict["properties"]:
            if description := param.description:
                parameters_dict["properties"][name]["description"] = description

    # Build OpenAI schema
    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": f"{docstring.short_description}\n{docstring.long_description}",
            "strict": True,
            "parameters": parameters_dict,
        }
    }
```

### Type Mapping

Python → JSON Schema via Pydantic:
- `str` → `{"type": "string"}`
- `int` → `{"type": "integer"}`
- `float` → `{"type": "number"}`
- `bool` → `{"type": "boolean"}`
- `List[T]` → `{"type": "array", "items": {...}}`
- `Dict[K,V]` → `{"type": "object"}`
- `Optional[T]` → `{"type": [T, "null"]}`
- Pydantic models → nested object schemas with `$defs`

### Generated Schema Example

```python
def search_wiki(entity: str) -> str:
    """Search the entity in WikiPedia.

    Args:
        entity: The entity to be searched.

    Returns:
        The summary of the entity.
    """
```

Generates:
```json
{
  "type": "function",
  "function": {
    "name": "search_wiki",
    "description": "Search the entity in WikiPedia.",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "entity": {
          "type": "string",
          "description": "The entity to be searched."
        }
      },
      "required": ["entity"],
      "additionalProperties": false
    }
  }
}
```

### Schema Synthesis Feature

Unique feature: LLM-powered schema generation for functions with incomplete/missing docstrings:

```python
# If synthesize_schema=True and validation fails
tool = FunctionTool(
    func=my_func,
    synthesize_schema=True,
    synthesize_schema_model=model,
    synthesize_schema_max_retries=2
)
# → LLM generates docstring → schema created → validated → retries if needed
```

## Built-in Tool Inventory

### Categories

CAMEL ships with **70+ tools** organized into **60+ toolkit classes**:

| Category | Toolkit Classes | Representative Tools |
|----------|----------------|---------------------|
| **Search** | SearchToolkit | search_google, search_duckduckgo, search_brave, search_exa, search_serper, search_tavily, search_wiki, search_baidu, search_bing, search_linkup, search_bocha, search_metaso, search_alibaba_tongxiao, search_serpapi |
| **Math/Computation** | MathToolkit, SymPyToolkit | math_add, math_subtract, math_multiply, math_divide, math_round |
| **Code Execution** | CodeExecutionToolkit, TerminalToolkit | execute_code, execute_command |
| **Academic** | ArxivToolkit, GoogleScholarToolkit, SemanticScholarToolkit, PubMedToolkit | search_papers, download_paper |
| **Communication** | SlackToolkit, TwitterToolkit, WhatsAppToolkit, WeChatOfficialToolkit, DingtalkToolkit, ResendToolkit | send_message, post_update |
| **Productivity** | NotionToolkit, GoogleCalendarToolkit, GmailToolkit, ExcelToolkit, PPTXToolkit, NoteTakingToolkit | create_page, schedule_event |
| **Data Analysis** | NetworkXToolkit, DataCommonsToolkit, JinaRerankerToolkit, MemoryToolkit | graph_operations, statistical_queries |
| **Media** | ImageGenToolkit, VideoDownloaderToolkit, VideoAnalysisToolkit, AudioAnalysisToolkit, ImageAnalysisToolkit, ScreenshotToolkit | generate_image, analyze_video |
| **Web Interaction** | BrowserToolkit, AsyncBrowserToolkit, HybridBrowserToolkit, Crawl4AIToolkit | navigate, extract_content |
| **File Operations** | FileToolkit, MarkItDownToolkit, MinerUToolkit | read_file, write_file, convert_document |
| **APIs/Integration** | LinkedInToolkit, RedditToolkit, StripeToolkit, ZapierToolkit, MeshyToolkit, OpenBBToolkit, BohriumToolkit, DappierToolkit, KlavisToolkit, WolframAlphaToolkit | api_calls, integrations |
| **MCP Tools** | MCPToolkit, PulseMCPSearchToolkit, OrigeneToolkit, PlaywrightMCPToolkit, EdgeOnePagesMCPToolkit, GoogleDriveMCPToolkit, NotionMCPToolkit, MinimaxMCPToolkit | mcp_protocol_tools |
| **Specialized** | WeatherToolkit, HumanToolkit, TaskPlanningToolkit, ThinkingToolkit, PyAutoGUIToolkit, SQLToolkit, RetrievalToolkit, ContextSummarizerToolkit, AgentCommunicationToolkit, WebDeployToolkit, OutlookMailToolkit, EarthScienceToolkit, VertexAIVeoToolkit | domain_specific_operations |

### Complete Tool List (First 30 Representative)

| Tool Name | Location | Schema Method | Category |
|-----------|----------|---------------|----------|
| math_add | camel/toolkits/math_toolkit.py | Introspection | Math |
| math_subtract | camel/toolkits/math_toolkit.py | Introspection | Math |
| math_multiply | camel/toolkits/math_toolkit.py | Introspection | Math |
| math_divide | camel/toolkits/math_toolkit.py | Introspection | Math |
| math_round | camel/toolkits/math_toolkit.py | Introspection | Math |
| search_google | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_duckduckgo | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_wiki | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_brave | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_serper | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_tavily | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_exa | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_baidu | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_bing | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_linkup | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_bocha | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_metaso | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_alibaba_tongxiao | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_serpapi | camel/toolkits/search_toolkit.py | Introspection | Search |
| search_papers | camel/toolkits/arxiv_toolkit.py | Introspection | Academic |
| download_papers | camel/toolkits/arxiv_toolkit.py | Introspection | Academic |
| execute_code | camel/toolkits/code_execution.py | Introspection | CodeExec |
| execute_command | camel/toolkits/code_execution.py | Introspection | CodeExec |
| create_github_issue | camel/toolkits/github_toolkit.py | Introspection | Integration |
| retrieve_issue | camel/toolkits/github_toolkit.py | Introspection | Integration |
| create_pull_request | camel/toolkits/github_toolkit.py | Introspection | Integration |
| list_prs | camel/toolkits/github_toolkit.py | Introspection | Integration |
| get_repo_info | camel/toolkits/github_toolkit.py | Introspection | Integration |
| retrieve_file_content | camel/toolkits/github_toolkit.py | Introspection | Integration |
| create_repo | camel/toolkits/github_toolkit.py | Introspection | Integration |

### Toolkit Pattern Example

```python
@MCPServer()  # Optional MCP server decorator
class MathToolkit(BaseToolkit):
    def math_add(self, a: float, b: float) -> float:
        """Adds two numbers.

        Args:
            a: The first number to be added.
            b: The second number to be added.

        Returns:
            The sum of the two numbers.
        """
        return a + b

    def get_tools(self) -> List[FunctionTool]:
        """Returns FunctionTool wrappers for all methods"""
        return [
            FunctionTool(self.math_add),
            FunctionTool(self.math_subtract),
            FunctionTool(self.math_multiply),
            FunctionTool(self.math_divide),
            FunctionTool(self.math_round),
        ]
```

## Registration & Discovery

### Pattern

**Manual explicit registration** - No auto-discovery. Tools must be explicitly registered with agents.

```python
from camel.agents import ChatAgent
from camel.toolkits import MathToolkit, SearchToolkit

# Create toolkits
math_toolkit = MathToolkit()
search_toolkit = SearchToolkit()

# Register tools with agent
agent = ChatAgent(
    system_message="You are a helpful assistant",
    tools=[
        *math_toolkit.get_tools(),
        *search_toolkit.get_tools(),
    ]
)
# OR
agent = ChatAgent(
    system_message="You are a helpful assistant",
    toolkits=[math_toolkit, search_toolkit]  # Internally calls get_tools()
)
```

### Registration Flow

```
1. Instantiate Toolkit
   ↓
2. Call toolkit.get_tools()
   ↓
3. Returns List[FunctionTool]
   ↓
4. Pass to ChatAgent(tools=...)
   ↓
5. Agent stores in self._internal_tools dict
   ↓
6. Schema sent to LLM via model API
```

### Internal Storage

```python
# In ChatAgent.__init__
self._internal_tools: Dict[str, FunctionTool] = {}

for tool in tools:
    tool_schema = tool.get_openai_tool_schema()
    func_name = tool_schema["function"]["name"]
    self._internal_tools[func_name] = tool
```

### Registered Agent Pattern

Special pattern for tools that need access to the agent:

```python
class RegisteredAgentToolkit:
    """Mixin for toolkits needing ChatAgent reference"""

    def __init__(self):
        self._agent: Optional["ChatAgent"] = None

    @property
    def agent(self) -> Optional["ChatAgent"]:
        if self._agent is None:
            logger.warning("Toolkit not registered with agent")
        return self._agent

    def register_agent(self, agent: "ChatAgent") -> None:
        self._agent = agent
```

## Execution Flow

### Invocation Pattern

```python
# Sync execution
def _execute_tool(
    self,
    tool_call_request: ToolCallRequest,
) -> ToolCallingRecord:
    func_name = tool_call_request.tool_name
    args = tool_call_request.args
    tool_call_id = tool_call_request.tool_call_id

    tool = self._internal_tools[func_name]

    try:
        raw_result = tool(**args)  # Direct __call__

        if self.mask_tool_output:
            # Store result securely, return masked message
            self._secure_result_store[tool_call_id] = raw_result
            result = "[Tool executed successfully, output masked]"
        else:
            result = raw_result

    except Exception as e:
        error_msg = f"Error executing tool '{func_name}': {e!s}"
        result = f"Tool execution failed: {error_msg}"
        logger.warning(error_msg)

    return self._record_tool_calling(func_name, args, result, tool_call_id)
```

```python
# Async execution with auto-bridging
async def _aexecute_tool(
    self,
    tool_call_request: ToolCallRequest,
) -> ToolCallingRecord:
    func_name = tool_call_request.tool_name
    args = tool_call_request.args
    tool = self._internal_tools[func_name]

    try:
        # Multi-path async invocation
        if hasattr(tool, 'func') and hasattr(tool.func, 'async_call'):
            result = await tool.func.async_call(**args)  # MCP tools
        elif hasattr(tool, 'async_call') and callable(tool.async_call):
            result = await tool.async_call(**args)  # FunctionTool.async_call
        elif hasattr(tool, 'func') and asyncio.iscoroutinefunction(tool.func):
            result = await tool.func(**args)  # Direct async function
        elif asyncio.iscoroutinefunction(tool):
            result = await tool(**args)  # Tool is coroutine
        else:
            # Fallback: run sync in executor
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, functools.partial(tool, **args)
            )
    except Exception as e:
        error_msg = f"Error executing async tool '{func_name}': {e!s}"
        result = f"Tool execution failed: {error_msg}"
        logger.warning(error_msg)

    return self._record_tool_calling(func_name, args, result, tool_call_id)
```

### Validation

1. **Pre-execution validation**:
   - JSON schema validation (via `jsonschema.validators.Draft202012Validator`)
   - Parameter type checking (via Pydantic)
   - Argument parsing validation

2. **Runtime validation**:
   - Tool existence check (`func_name in self._internal_tools`)
   - Argument deserialization (`json.loads(arguments)`)

### Error Handling

| Error Type | Handling | Feedback to LLM |
|------------|----------|-----------------|
| Tool not found | Log warning, return None | "Tool 'X' not found in internal tools" |
| Invalid arguments | Catch JSONDecodeError | Pass raw string as args |
| Execution exception | Catch all exceptions | "Tool execution failed: {error_msg}" |
| Timeout | ThreadPoolExecutor timeout | "Function 'X' timed out after N seconds" |
| Schema validation | Warn, allow execution | Warning logged but execution continues |
| Missing description | Warn, allow execution | "Function/parameter description missing" |

### Error Feedback Example

```python
try:
    result = tool(**args)
except Exception as e:
    error_msg = f"Error executing tool '{func_name}': {e!s}"
    result = f"Tool execution failed: {error_msg}"
    logger.warning(f"{error_msg} with result: {result}")

# Error message goes to LLM in FunctionCallingMessage
func_msg = FunctionCallingMessage(
    role_name=self.role_name,
    role_type=self.role_type,
    content="",
    func_name=function_name,
    result=result,  # Contains error message
    tool_call_id=tool_call_id,
)
```

### Retry Mechanisms

**No built-in retry** - Tool execution failures are reported to the LLM, which can:
1. Retry with corrected arguments
2. Try alternative tools
3. Ask user for clarification

Agent-level retry is handled by the model's self-correction capability.

## Parallel Execution

### Synchronous Parallel Execution

Uses **ThreadPoolExecutor** for concurrent execution:

```python
def _execute_tools_sync_with_status_accumulator(
    self,
    accumulated_tool_calls: Dict[str, Any],
    tool_call_records: List[ToolCallingRecord],
) -> Generator[ChatAgentResponse, None, None]:

    tool_calls_to_execute = [
        tc for tc in accumulated_tool_calls.values()
        if tc.get('complete', False)
    ]

    # Parallel execution with ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, len(tool_calls_to_execute))
    ) as executor:
        # Submit all tools (non-blocking)
        futures_map = {}
        for tool_call_data in tool_calls_to_execute:
            future = executor.submit(
                self._execute_tool_from_stream_data,
                tool_call_data
            )
            futures_map[future] = (function_name, tool_call_data)

        # Wait for completion with timeout
        for future in concurrent.futures.as_completed(
            futures_map.keys(),
            timeout=self.tool_execution_timeout
        ):
            try:
                tool_call_record = future.result()
                tool_call_records.append(tool_call_record)
            except concurrent.futures.TimeoutError:
                logger.warning(f"Function '{function_name}' timed out")
                future.cancel()
            except Exception as e:
                logger.error(f"Error executing tool: {e}")
```

### Asynchronous Parallel Execution

Uses **asyncio.create_task** and **asyncio.as_completed**:

```python
async def _execute_tools_async_with_status_accumulator(
    self,
    accumulated_tool_calls: Dict[str, Any],
    content_accumulator: StreamContentAccumulator,
    step_token_usage: Dict[str, int],
    tool_call_records: List[ToolCallingRecord],
) -> AsyncGenerator[ChatAgentResponse, None]:

    # Phase 1: Start all tools (non-blocking)
    tool_tasks = []
    for tool_call_data in accumulated_tool_calls.values():
        if tool_call_data.get('complete', False):
            # Create async task with optional timeout
            if self.tool_execution_timeout is not None:
                task = asyncio.create_task(
                    asyncio.wait_for(
                        self._aexecute_tool_from_stream_data(tool_call_data),
                        timeout=self.tool_execution_timeout,
                    )
                )
            else:
                task = asyncio.create_task(
                    self._aexecute_tool_from_stream_data(tool_call_data)
                )
            tool_tasks.append((task, tool_call_data))

    # Phase 2: Yield results as they complete
    if tool_tasks:
        for completed_task in asyncio.as_completed([t for t, _ in tool_tasks]):
            try:
                tool_call_record = await completed_task
                tool_call_records.append(tool_call_record)

                # Yield streaming response with updated content
                yield ChatAgentResponse(
                    msgs=[...],
                    terminated=False,
                    info={...}
                )
            except asyncio.TimeoutError:
                logger.warning(f"Function timed out")
            except Exception as e:
                logger.error(f"Error executing async tool: {e}")
```

### Parallel Execution Features

1. **True parallelism**: All tools start simultaneously
2. **Progressive streaming**: Results yielded as each tool completes
3. **Independent timeouts**: Per-tool timeout tracking
4. **Graceful degradation**: Failed tools don't block others
5. **Max workers = N tools**: One thread/task per tool

## Code References

Key files and line numbers:

| Component | File | Lines |
|-----------|------|-------|
| FunctionTool class | camel/toolkits/function_tool.py | 385-895 |
| Schema generation | camel/toolkits/function_tool.py | 96-198 |
| BaseToolkit | camel/toolkits/base.py | 28-124 |
| Tool execution (sync) | camel/agents/chat_agent.py | 3941-3986 |
| Tool execution (async) | camel/agents/chat_agent.py | 3987-4036 |
| Parallel sync execution | camel/agents/chat_agent.py | 4685-4758 |
| Parallel async execution | camel/agents/chat_agent.py | 5473-5530 |
| Auto async bridging | camel/toolkits/function_tool.py | 502-515 |
| Schema validation | camel/toolkits/function_tool.py | 522-574 |
| Toolkit examples | camel/toolkits/math_toolkit.py | 24-164 |
| Toolkit examples | camel/toolkits/search_toolkit.py | 33-1536 |

## Implications for New Framework

### Positive Patterns

1. **Zero-boilerplate function wrapping**
   - Any Python function becomes a tool with just type hints + docstring
   - No decorators or base classes required for simple functions
   - Automatic schema generation eliminates manual schema writing

2. **First-class async support**
   - Automatic sync-to-async bridging via ThreadPoolExecutor
   - Native async/await support for async functions
   - Multi-path invocation (handles MCP, native async, sync)

3. **True parallel execution**
   - Both sync (ThreadPoolExecutor) and async (asyncio.create_task)
   - Tools execute simultaneously, not sequentially
   - Progressive streaming as results complete

4. **LLM-powered schema synthesis**
   - Unique feature: Use LLM to generate missing docstrings/schemas
   - Enables quick prototyping without complete documentation
   - Self-healing schema generation with retries

5. **Comprehensive error handling**
   - Detailed error messages fed back to LLM
   - Exceptions don't crash the framework
   - Timeout support at multiple levels

6. **Toolkit organization**
   - Clean grouping of related tools
   - Easy to create domain-specific toolkits
   - Extensible via inheritance

7. **Flexible tool schemas**
   - Support for manual schema override
   - Pydantic integration for complex types
   - OpenAI strict mode compliance

### Considerations

1. **Manual registration overhead**
   - Every toolkit must explicitly call `get_tools()`
   - No auto-discovery of tools
   - Consider: Plugin system for auto-registration

2. **Schema strictness trade-offs**
   - OpenAI strict mode requires `additionalProperties: false` everywhere
   - Complex recursive schema manipulation for strict compliance
   - Consider: Make strictness configurable per tool

3. **Memory management for tool results**
   - Tool outputs stored in agent memory
   - Large outputs (images, files) could bloat memory
   - Consider: Reference-based storage for large results

4. **Timeout configuration**
   - Global timeout threshold, not per-tool
   - Consider: Per-tool timeout annotations

5. **Error feedback verbosity**
   - Full error messages sent to LLM (could leak internals)
   - Consider: Sanitized vs. detailed error modes

6. **Schema validation warnings**
   - Missing descriptions only warn, don't fail
   - Could lead to poor LLM tool usage
   - Consider: Strict validation mode option

## Anti-Patterns Observed

1. **Thread pool as module global**
   ```python
   # Shared 64-worker pool at module level
   _SYNC_TOOL_EXECUTOR = ThreadPoolExecutor(max_workers=64)
   ```
   - **Issue**: Can't configure pool size per agent
   - **Better**: Per-agent executor or configurable global

2. **Mutation of Pydantic schemas**
   ```python
   # Recursive deletion of 'title' keys after generation
   _remove_title_recursively(parameters_dict)
   ```
   - **Issue**: Post-processing fragile, schema-dependent
   - **Better**: Configure Pydantic to not generate titles

3. **Silent fallback in async execution**
   ```python
   if hasattr(...):
       # Try path 1
   elif hasattr(...):
       # Try path 2
   else:
       # Silently run sync
   ```
   - **Issue**: No logging when fallback to sync executor
   - **Better**: Log execution path chosen

4. **Deep nesting in sanitize_and_enforce_required**
   ```python
   def sanitize_and_enforce_required(parameters_dict):
       def _add_additional_properties_false(obj):
           # 30+ lines of nested logic
   ```
   - **Issue**: Complex recursive function hard to test
   - **Better**: Split into composable validation functions

5. **Deprecated methods kept indefinitely**
   ```python
   def add(self, *args, **kwargs):
       warnings.warn("add is deprecated. Use math_add instead.")
       return self.math_add(*args, **kwargs)
   ```
   - **Issue**: API bloat, confusing for new users
   - **Better**: Removal schedule with version deprecation

6. **Tool output masking with side-channel storage**
   ```python
   if self.mask_tool_output:
       self._secure_result_store[tool_call_id] = raw_result
       result = "[output masked]"
   ```
   - **Issue**: No API to retrieve masked results
   - **Better**: Explicit result retrieval method

## Unique Innovations

1. **LLM-Powered Schema Synthesis**
   - First framework to use LLM for auto-generating tool schemas
   - Enables rapid prototyping without complete documentation

2. **Automatic Sync-to-Async Bridging**
   - Transparent executor-based async wrapping
   - Sync tools work seamlessly in async contexts

3. **Progressive Streaming with Parallel Execution**
   - Stream results as tools complete (not after all finish)
   - Better UX for long-running parallel tools

4. **MCP Protocol Integration**
   - Native Model Context Protocol support
   - MCPServer decorator for instant tool servers

5. **Secure Result Store**
   - Option to mask sensitive tool outputs from LLM
   - Results stored separately for secure access
