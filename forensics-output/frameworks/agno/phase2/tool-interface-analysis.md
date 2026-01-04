# Tool Interface Analysis: agno

## Summary
- **Tool Modeling**: Pydantic BaseModel (Function class) with auto-registration via Toolkit base class
- **Schema Generation**: Automatic introspection from type hints + docstrings via custom JSON schema converter
- **Registration Pattern**: Declarative (Toolkit subclasses) with auto-registration + explicit decorator (@tool)
- **Error Handling**: Structured with self-correction loops (RetryAgentRun/StopAgentRun exceptions)
- **Built-in Tools**: 100+ tools across 15+ categories (web, database, cloud, APIs, development)
- **Parallel Execution**: Full async support via asyncio.gather with concurrent tool call execution

## Tool Modeling

### Core Abstraction

Tools in agno are modeled using a **Function** Pydantic model that wraps callable Python functions. The framework provides three ways to define tools:

1. **Raw callables** - Any Python function can be converted to a Function
2. **Toolkit classes** - Collections of related tools via inheritance
3. **@tool decorator** - Declarative configuration with metadata

**Core Function Model** (`tools/function.py:65-144`):

```python
class Function(BaseModel):
    # Core identification
    name: str
    description: Optional[str] = None
    parameters: Dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []}
    )
    strict: Optional[bool] = None

    # Instructions and documentation
    instructions: Optional[str] = None
    add_instructions: bool = True

    # Execution
    entrypoint: Optional[Callable] = None
    skip_entrypoint_processing: bool = False
    show_result: bool = False
    stop_after_tool_call: bool = False

    # Hooks and lifecycle
    pre_hook: Optional[Callable] = None
    post_hook: Optional[Callable] = None
    tool_hooks: Optional[List[Callable]] = None

    # Human-in-the-loop
    requires_confirmation: Optional[bool] = None
    requires_user_input: Optional[bool] = None
    user_input_fields: Optional[List[str]] = None
    user_input_schema: Optional[List[UserInputField]] = None
    external_execution: Optional[bool] = None

    # Caching
    cache_results: bool = False
    cache_dir: Optional[str] = None
    cache_ttl: int = 3600

    # Internal context (injected at runtime)
    _agent: Optional[Any] = None
    _team: Optional[Any] = None
    _run_context: Optional[RunContext] = None
    _session_state: Optional[Dict[str, Any]] = None
    _dependencies: Optional[Dict[str, Any]] = None
    _images: Optional[Sequence[Image]] = None
    _videos: Optional[Sequence[Video]] = None
    _audios: Optional[Sequence[Audio]] = None
    _files: Optional[Sequence[File]] = None
```

### Key Attributes

| Attribute | Type | Purpose |
|-----------|------|---------|
| name | str | Unique identifier (max 64 chars, alphanumeric + underscores/dashes) |
| description | Optional[str] | Auto-extracted from docstring or manual override |
| parameters | Dict[str, Any] | JSON Schema object describing function parameters |
| entrypoint | Optional[Callable] | The actual Python callable to execute |
| strict | Optional[bool] | Enable OpenAI strict mode (all fields required, no additionalProperties) |
| instructions | Optional[str] | Additional instructions added to system prompt |
| pre_hook | Optional[Callable] | Called before execution for validation/logging |
| post_hook | Optional[Callable] | Called after execution (success or failure) |
| tool_hooks | Optional[List[Callable]] | Nested chain of middleware-style hooks |
| requires_confirmation | Optional[bool] | Pause execution for user approval |
| requires_user_input | Optional[bool] | Pause to collect user input for specific fields |
| external_execution | Optional[bool] | Tool executed outside agent control (external system) |
| cache_results | bool | Enable file-based caching with TTL |
| cache_dir | Optional[str] | Custom cache directory (defaults to system temp) |
| cache_ttl | int | Cache time-to-live in seconds (default 3600) |

**Distinctive Features**:
1. **Context Injection**: Functions can access `agent`, `team`, `run_context`, `session_state`, `dependencies` by including them in signature
2. **Media Support**: Built-in support for images, videos, audios, files as injected parameters
3. **Hook System**: Pre/post hooks + nested tool_hooks for middleware-style execution chains
4. **Human-in-the-Loop**: Three distinct modes (confirmation, user_input, external_execution) - mutually exclusive
5. **File-Based Caching**: MD5-keyed JSON cache with TTL expiration

## Schema Generation

### Method Used

**Automatic introspection** combining:
1. Type hints via `typing.get_type_hints()`
2. Docstring parsing via `docstring_parser` library
3. Function signature inspection via `inspect.signature()`
4. Custom JSON Schema converter with Pydantic model support

**Schema Generation Flow** (`tools/function.py:186-312`):

```python
@classmethod
def from_callable(cls, c: Callable, name: Optional[str] = None, strict: bool = False) -> "Function":
    from inspect import getdoc, signature
    from agno.utils.json_schema import get_json_schema

    function_name = name or c.__name__
    parameters = {"type": "object", "properties": {}, "required": []}

    try:
        sig = signature(c)
        type_hints = get_type_hints(c)

        # Remove special parameters that are injected at runtime
        for param in ["agent", "team", "run_context", "session_state", "dependencies",
                      "images", "videos", "audios", "files"]:
            if param in sig.parameters and param in type_hints:
                del type_hints[param]

        # Filter out return type and special params
        param_type_hints = {
            name: type_hints.get(name)
            for name in sig.parameters
            if name != "return" and name not in excluded_params
        }

        # Parse docstring for parameter descriptions
        param_descriptions: Dict[str, Any] = {}
        if docstring := getdoc(c):
            parsed_doc = parse(docstring)
            for param in parsed_doc.params:
                param_name = param.arg_name
                param_type = param.type_name
                if param_type is None:
                    param_descriptions[param_name] = param.description
                else:
                    param_descriptions[param_name] = f"({param_type}) {param.description}"

        # Generate JSON Schema from type hints
        parameters = get_json_schema(
            type_hints=param_type_hints,
            param_descriptions=param_descriptions,
            strict=strict
        )

        # Determine required fields based on default values
        if strict:
            parameters["required"] = list(parameters["properties"].keys())
        else:
            parameters["required"] = [
                name for name, param in sig.parameters.items()
                if param.default == param.empty and name not in excluded_params
            ]

    except Exception as e:
        log_warning(f"Could not parse args for {function_name}: {e}")

    entrypoint = cls._wrap_callable(c)

    return cls(
        name=function_name,
        description=get_entrypoint_docstring(entrypoint=c),
        parameters=parameters,
        entrypoint=entrypoint,
    )
```

**Type Mapping** (`utils/json_schema.py:20-42`):

| Python Type | JSON Schema Type |
|-------------|------------------|
| int, float, complex, Decimal | number |
| str, string | string |
| bool, boolean | boolean |
| NoneType, None | null |
| list, tuple, set, frozenset | array |
| dict, mapping | object |
| Enum subclass | string with enum values |
| Pydantic BaseModel | object (schema inlined) |
| dataclass | object (fields mapped) |
| Union types | anyOf |
| Optional[T] | Extracted to non-null type |

**Pydantic Model Inlining** (`utils/json_schema.py:148-151`):
```python
if isinstance(type_hint, type) and issubclass(type_hint, BaseModel):
    # Get the schema and inline it (resolve $ref to actual definitions)
    schema = type_hint.model_json_schema()
    return inline_pydantic_schema(schema)
```

### Generated Schema Example

For this function:
```python
def get_weather(city: str, units: Optional[str] = "celsius") -> str:
    """Get weather for a city.

    Args:
        city (str): The city name to get weather for.
        units (str): Temperature units (celsius or fahrenheit).
    """
    pass
```

Generated JSON Schema:
```json
{
  "type": "object",
  "properties": {
    "city": {
      "type": "string",
      "description": "(str) The city name to get weather for."
    },
    "units": {
      "type": "string",
      "description": "(str) Temperature units (celsius or fahrenheit)."
    }
  },
  "required": ["city"]
}
```

With `strict=True`:
```json
{
  "type": "object",
  "properties": {
    "city": {
      "type": "string",
      "description": "(str) The city name to get weather for."
    },
    "units": {
      "type": "string",
      "description": "(str) Temperature units (celsius or fahrenheit)."
    }
  },
  "required": ["city", "units"],
  "additionalProperties": false
}
```

## Built-in Tool Inventory

### Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| Web Search | 10+ | DuckDuckGo, Brave, Serper, SerpAPI, Tavily, Exa, Linkup, SearxNG |
| Web Scraping | 8+ | Firecrawl, Spider, Crawl4AI, Newspaper4k, Trafilatura, Jina, BrightData, Oxylabs |
| Cloud Providers | 12+ | AWS (Lambda, SES, Redshift), Google (BigQuery, Drive, Sheets, Calendar, Maps), Azure integrations |
| Databases | 6+ | Postgres, Neo4j, DuckDB, SQL (generic), Google BigQuery, AWS Redshift |
| Development | 10+ | Python, Shell, Docker, GitHub, Bitbucket, E2B, Daytona |
| Communication | 8+ | Email, Slack, Discord, Telegram, WhatsApp, Twilio, Webex, Zoom |
| Project Management | 6+ | Jira, Linear, ClickUp, Todoist, Notion, Trello |
| Finance | 4+ | YFinance, OpenBB, Financial Datasets, Shopify |
| AI/ML Services | 10+ | OpenAI, DALL-E, Replicate, Fal, ElevenLabs, Cartesia, Desi Vocal, MLX Transcribe, Models Labs, Nano Banana |
| Knowledge/Memory | 4+ | Knowledge (RAG), Memory, Mem0, Zep |
| Data Processing | 6+ | Pandas, CSV Toolkit, Visualization, MoviePy Video, OpenCV, DuckDB |
| APIs | 8+ | API (generic), Apify, Brandfetch, Giphy, Spotify, Reddit, HackerNews, Wikipedia |
| Calendar/Scheduling | 3+ | Google Calendar, Cal.com, Todoist |
| Workflow | 5+ | Airflow, Parallel execution, Workflow orchestration, User control flow, Reasoning |
| Utilities | 6+ | Calculator, Sleep, File operations, File generation, Browser control, Website tools |

### Complete Tool List (Sample)

| Tool Name | Location | Schema Method | Category |
|-----------|----------|---------------|----------|
| DuckDuckGoTools | tools/duckduckgo.py | Introspection | Web Search |
| BraveSearchTools | tools/bravesearch.py | Introspection | Web Search |
| TavilyTools | tools/tavily.py | Introspection | Web Search |
| FirecrawlTools | tools/firecrawl.py | Introspection | Web Scraping |
| SpiderTools | tools/spider.py | Introspection | Web Scraping |
| Crawl4AITools | tools/crawl4ai.py | Introspection | Web Scraping |
| PythonTools | tools/python.py | Introspection | Development |
| ShellTools | tools/shell.py | Introspection | Development |
| GitHubTools | tools/github.py | Introspection | Development |
| PostgresTools | tools/postgres.py | Introspection | Database |
| Neo4jTools | tools/neo4j.py | Introspection | Database |
| DuckDBTools | tools/duckdb.py | Introspection | Database |
| SlackTools | tools/slack.py | Introspection | Communication |
| EmailTools | tools/email.py | Introspection | Communication |
| DiscordTools | tools/discord.py | Introspection | Communication |
| JiraTools | tools/jira.py | Introspection | Project Management |
| LinearTools | tools/linear.py | Introspection | Project Management |
| NotionTools | tools/notion.py | Introspection | Project Management |
| YFinanceTools | tools/yfinance.py | Introspection | Finance |
| OpenBBTools | tools/openbb.py | Introspection | Finance |
| OpenAITools | tools/openai.py | Introspection | AI/ML Services |
| DALLETools | tools/dalle.py | Introspection | AI/ML Services |
| ReplicateTools | tools/replicate.py | Introspection | AI/ML Services |
| KnowledgeTools | tools/knowledge.py | Introspection | Knowledge/Memory |
| MemoryTools | tools/memory.py | Introspection | Knowledge/Memory |
| PandasTools | tools/pandas.py | Introspection | Data Processing |
| CalculatorTools | tools/calculator.py | Introspection | Utilities |
| AWSLambdaTools | tools/aws_lambda.py | Introspection | Cloud Providers |
| GoogleSheetsTools | tools/googlesheets.py | Introspection | Cloud Providers |
| GoogleBigQueryTools | tools/google_bigquery.py | Introspection | Cloud Providers |

**Total Count**: 100+ distinct tools across 117 files in the tools/ directory (30,102 total lines of code)

## Registration & Discovery

### Pattern

Agno uses a **hybrid registration pattern** combining:
1. **Toolkit-based auto-registration** (primary)
2. **Decorator-based declaration** (@tool)
3. **Manual Function creation** (for advanced use cases)

### Toolkit-Based Registration

**Base Toolkit Class** (`tools/toolkit.py:8-283`):

```python
class Toolkit:
    _requires_connect: bool = False  # For connection management (DB, etc.)

    def __init__(
        self,
        name: str = "toolkit",
        tools: Sequence[Union[Callable[..., Any], Function]] = [],
        instructions: Optional[str] = None,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
        requires_confirmation_tools: Optional[list[str]] = None,
        external_execution_required_tools: Optional[list[str]] = None,
        stop_after_tool_call_tools: Optional[List[str]] = None,
        show_result_tools: Optional[List[str]] = None,
        cache_results: bool = False,
        cache_ttl: int = 3600,
        cache_dir: Optional[str] = None,
        auto_register: bool = True,
    ):
        self.name: str = name
        self.tools: Sequence[Union[Callable[..., Any], Function]] = tools
        self.functions: Dict[str, Function] = OrderedDict()

        # Automatically register all methods if auto_register is True
        if auto_register and self.tools:
            self._register_tools()

    def register(self, function: Union[Callable[..., Any], Function], name: Optional[str] = None):
        """Register a function with the toolkit."""
        # Handle Function objects (from @tool decorator)
        if isinstance(function, Function):
            return self._register_decorated_tool(function, name)

        # Handle regular callables
        tool_name = name or function.__name__
        if self.include_tools is not None and tool_name not in self.include_tools:
            return
        if self.exclude_tools is not None and tool_name in self.exclude_tools:
            return

        f = Function(
            name=tool_name,
            entrypoint=function,
            cache_results=self.cache_results,
            cache_dir=self.cache_dir,
            cache_ttl=self.cache_ttl,
            requires_confirmation=tool_name in self.requires_confirmation_tools,
            external_execution=tool_name in self.external_execution_required_tools,
            stop_after_tool_call=tool_name in self.stop_after_tool_call_tools,
            show_result=tool_name in self.show_result_tools,
        )
        self.functions[f.name] = f
```

**Example: CalculatorTools** (`tools/calculator.py:9-26`):

```python
class CalculatorTools(Toolkit):
    def __init__(self, **kwargs):
        tools: List[Callable] = [
            self.add,
            self.subtract,
            self.multiply,
            self.divide,
            self.exponentiate,
            self.factorial,
            self.is_prime,
            self.square_root,
        ]

        # Initialize with auto-registration enabled
        super().__init__(name="calculator", tools=tools, **kwargs)

    def add(self, a: float, b: float) -> str:
        """Add two numbers and return the result."""
        result = a + b
        return json.dumps({"operation": "addition", "result": result})
```

### Decorator-Based Registration

**@tool Decorator** (`tools/decorator.py:86-262`):

```python
@tool
def get_weather(city: str) -> str:
    """Get weather for a city."""
    return f"Weather in {city}: sunny"

# Or with configuration:
@tool(
    name="custom_weather",
    description="Fetch weather data",
    strict=True,
    requires_confirmation=True,
    cache_results=True,
    cache_ttl=1800,
)
async def get_weather_async(city: str) -> str:
    """Get weather for a city."""
    await asyncio.sleep(1)
    return f"Weather in {city}: sunny"
```

**Decorator Implementation**:
- Supports both sync and async functions
- Auto-detects async generators
- Wraps with error handling
- Processes entrypoint to generate schema
- Validates mutually exclusive flags (requires_confirmation, requires_user_input, external_execution)

### Registration Flow

```
1. Define Tool
   ├─→ As Toolkit subclass (collection)
   ├─→ As @tool decorated function (single)
   └─→ As raw callable (manual)

2. Schema Generation
   ├─→ Extract type hints
   ├─→ Parse docstring
   ├─→ Generate JSON Schema
   └─→ Mark required fields

3. Entrypoint Wrapping
   ├─→ Wrap with Pydantic validate_call (unless async gen or has session_state)
   ├─→ Mark as wrapped to avoid double-wrapping
   └─→ Preserve original metadata

4. Registration
   ├─→ Add to toolkit.functions dict
   ├─→ Apply include/exclude filters
   └─→ Merge toolkit-level and decorator-level configs

5. Agent Assignment
   ├─→ Agent receives toolkit or Function list
   ├─→ Functions are copied with agent context
   └─→ Special params (agent, team, run_context) are injected at call time
```

**Dynamic Tool Registration**:
```python
agent = Agent(
    tools=[
        CalculatorTools(),  # Toolkit instance
        get_weather,        # Raw callable
        custom_tool,        # @tool decorated function
    ]
)

# Tools can also be added/removed after creation (though less common)
```

## Execution Flow

### Invocation Pattern

**FunctionCall Model** (`tools/function.py:646-685`):

```python
class FunctionCall(BaseModel):
    function: Function
    arguments: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    call_id: Optional[str] = None
    error: Optional[str] = None

    def execute(self) -> FunctionExecutionResult:
        """Synchronous execution."""
        # 1. Pre-hook
        self._handle_pre_hook()

        # 2. Build arguments
        entrypoint_args = self._build_entrypoint_args()

        # 3. Check cache
        if self.function.cache_results:
            cached_result = self.function._get_cached_result(cache_file)
            if cached_result is not None:
                return FunctionExecutionResult(status="success", result=cached_result)

        # 4. Execute with hooks
        if self.function.tool_hooks is not None:
            execution_chain = self._build_nested_execution_chain(entrypoint_args)
            result = execution_chain(self.function.name, self.function.entrypoint, self.arguments)
        else:
            result = self.function.entrypoint(**entrypoint_args, **self.arguments)

        # 5. Handle generators vs regular results
        if isgenerator(result):
            self.result = result  # Don't cache generators
        else:
            self.result = result
            if self.function.cache_results:
                self.function._save_to_cache(cache_file, self.result)

        # 6. Post-hook
        self._handle_post_hook()

        return FunctionExecutionResult(
            status="success",
            result=self.result,
            updated_session_state=session_state
        )
```

**Argument Building** - Special parameters are injected automatically:

```python
def _build_entrypoint_args(self) -> Dict[str, Any]:
    """Inject context based on function signature."""
    from inspect import signature

    entrypoint_args = {}
    sig = signature(self.function.entrypoint)

    # Inject agent/team/context if function expects them
    if "agent" in sig.parameters:
        entrypoint_args["agent"] = self.function._agent
    if "team" in sig.parameters:
        entrypoint_args["team"] = self.function._team
    if "run_context" in sig.parameters:
        entrypoint_args["run_context"] = self.function._run_context
    if "session_state" in sig.parameters:
        entrypoint_args["session_state"] = self.function._session_state
    if "dependencies" in sig.parameters:
        entrypoint_args["dependencies"] = self.function._dependencies

    # Inject media if function expects them
    if "images" in sig.parameters:
        entrypoint_args["images"] = self.function._images
    # ... similar for videos, audios, files

    return entrypoint_args
```

### Error Handling

| Error Type | Handling | Feedback to LLM |
|------------|----------|-----------------|
| Argument Parsing Error | Caught in `get_function_call()` | `"Error while decoding function arguments: {e}\n\nPlease make sure we can json.loads() the arguments and retry."` |
| Argument Type Error | String normalization ("true"→True, "null"→None) | Automatic correction before execution |
| Invalid JSON Object | Caught before execution | `"Function arguments are not a valid JSON object.\n\n Please fix and retry."` |
| AgentRunException | Caught, error stored in FunctionCall | Exception propagated to agent for control flow |
| RetryAgentRun | Caught, triggers retry loop | Agent re-attempts with error context |
| StopAgentRun | Caught, stops agent execution | Agent terminates gracefully |
| Generic Exception | Logged and stored in FunctionCall.error | Error message fed back to model for self-correction |

**Intelligent Argument Normalization** (`utils/functions.py:50-66`):

```python
# Normalize common LLM mistakes
clean_arguments: Dict[str, Any] = {}
for k, v in _arguments.items():
    if isinstance(v, str):
        _v = v.strip().lower()
        if _v in ("none", "null"):
            clean_arguments[k] = None
        elif _v == "true":
            clean_arguments[k] = True
        elif _v == "false":
            clean_arguments[k] = False
        else:
            clean_arguments[k] = v.strip()
    else:
        clean_arguments[k] = v
```

**Self-Correction Loop** - Errors are fed back to the model:

```python
# From models/base.py:1812-1971
function_call_result = Message(
    role=self.tool_message_role,
    content=str(function_call.error) if function_call.error else str(function_call.result),
    tool_call_id=function_call.call_id,
    tool_name=function_call.function.name,
    tool_args=function_call.arguments,
    tool_call_error=True if function_call.error else None,
)

# This message is appended to conversation, allowing model to correct itself
```

### Retry Mechanisms

**Exception-Based Control Flow** (`exceptions.py:26-56`):

```python
class RetryAgentRun(AgentRunException):
    """Raised when a tool call should be retried."""
    def __init__(
        self,
        exc,
        user_message: Optional[Union[str, Message]] = None,
        agent_message: Optional[Union[str, Message]] = None,
        messages: Optional[List[Union[dict, Message]]] = None,
    ):
        super().__init__(
            exc,
            user_message=user_message,
            agent_message=agent_message,
            messages=messages,
            stop_execution=False  # Don't stop, retry instead
        )

class StopAgentRun(AgentRunException):
    """Raised when agent should stop entirely."""
    def __init__(self, ...):
        super().__init__(
            exc,
            ...,
            stop_execution=True  # Stop execution immediately
        )
```

**Usage Pattern**:
```python
def validate_input(data: str, agent) -> str:
    """Tool that validates input and triggers retry if invalid."""
    if not is_valid(data):
        raise RetryAgentRun(
            "Invalid input format",
            agent_message="The input format is incorrect. Please provide data in JSON format."
        )
    return process(data)
```

**File-Based Caching**:
- Cache key: MD5 hash of `function_name:arguments:kwargs`
- Cache location: `{cache_dir}/functions/{function_name}/{hash}.json`
- Cache format: `{"timestamp": float, "result": Any}`
- Cache validation: Check if `current_time - timestamp <= cache_ttl`
- Cache cleanup: Expired entries removed on next access
- **Not supported for generators** (both sync and async)

## Parallel Execution

### Implementation

Agno supports **full parallel tool execution** using `asyncio.gather` for concurrent async function calls.

**Parallel Execution Pattern** (`models/base.py:2250-2252`):

```python
# Create and run all function calls in parallel
results = await asyncio.gather(
    *(self.arun_function_call(fc) for fc in function_calls_to_run),
    return_exceptions=True
)
```

**Key Features**:

1. **Concurrent Startup**: All tool calls start simultaneously
2. **Independent Execution**: Each tool runs in its own async task
3. **Event Streaming**: Real-time events for tool_call_started and tool_call_completed
4. **Generator Support**: Async generators processed concurrently with event queue
5. **Error Isolation**: `return_exceptions=True` prevents one failure from stopping others

**Async Generator Handling** (`models/base.py:2277-2297`):

```python
async def process_async_generator(result, generator_id):
    """Process each async generator in parallel with real-time streaming."""
    function_call_success, function_call_timer, function_call, function_execution_result = result
    function_call_output = ""

    try:
        async for item in function_call.result:
            # Stream events in real-time
            if isinstance(item, (RunContentEvent, TeamRunContentEvent)):
                function_call_output += item.content or ""
                # Put events in queue for immediate yielding
                await event_queue.put((generator_id, item))
            # ... handle other event types
    except Exception as e:
        async_generator_outputs[generator_id] = (function_call_timer, "", e)
    else:
        async_generator_outputs[generator_id] = (function_call_timer, function_call_output, None)
    finally:
        # Signal completion
        await event_queue.put((generator_id, None))

# Create background tasks for each async generator
tasks = [
    asyncio.create_task(process_async_generator(result, i))
    for i, result in enumerate(async_generator_results)
]
```

**Event Queue Pattern**:
- Each async generator puts events in shared `asyncio.Queue`
- Main loop yields events as they arrive (real-time streaming)
- Generators complete independently
- Final results collected after all tasks finish

**Concurrent Tool Call Example** (`cookbook/03_agents/async/concurrent_tool_calls.py`):

```python
agent = Agent(
    model=OpenAIChat(id="gpt-4"),
    tools=[get_weather, get_activities],  # Two async functions
)

# Both tools called in parallel:
# [1.00s] get_weather started
# [1.00s] get_activities started
# [2.00s] get_weather completed (1s duration)
# [4.00s] get_activities completed (3s duration)
# Total: 4s (not 1+3=4s sequentially)
```

**Limitations**:
- Synchronous tools run sequentially (no parallelism)
- Human-in-the-loop tools (requires_confirmation, requires_user_input, external_execution) are paused and not executed in parallel batch
- Cache not used for generators
- Tool call limit applies across parallel executions

## Code References

### Core Tool Infrastructure
- `tools/function.py:65-144` - Function model definition
- `tools/function.py:186-312` - Function.from_callable schema generation
- `tools/function.py:314-456` - process_entrypoint for schema processing
- `tools/function.py:646-963` - FunctionCall.execute (sync)
- `tools/function.py:1098-1194` - FunctionCall.aexecute (async)
- `tools/toolkit.py:8-283` - Toolkit base class
- `tools/decorator.py:86-262` - @tool decorator

### Schema Generation
- `utils/json_schema.py:118-188` - get_json_schema_for_arg type mapping
- `utils/json_schema.py:190-235` - get_json_schema main function
- `utils/json_schema.py:44-116` - inline_pydantic_schema for model inlining

### Execution Engine
- `models/base.py:1812-1971` - run_function_call (sync)
- `models/base.py:2078-2117` - arun_function_call (single async)
- `models/base.py:2118-2400` - arun_function_calls (parallel async)
- `models/base.py:2250-2252` - asyncio.gather for parallelism
- `models/base.py:2277-2320` - Async generator processing with event queue

### Error Handling
- `exceptions.py:8-24` - AgentRunException base
- `exceptions.py:26-40` - RetryAgentRun for self-correction
- `exceptions.py:42-56` - StopAgentRun for termination
- `utils/functions.py:10-71` - get_function_call with argument parsing

### Example Tools
- `tools/calculator.py` - Simple toolkit example
- `tools/shell.py` - Shell command execution
- `tools/python.py` - Python code execution with sandboxing
- `tools/duckduckgo.py` - Web search toolkit

## Implications for New Framework

### Positive Patterns

1. **Unified Function Model**: Single Function class supports all use cases (raw callable, toolkit, decorator)
   - **Implication**: Avoid fragmentation - one model to rule them all

2. **Automatic Schema Generation**: Introspection + docstring parsing = zero boilerplate
   - **Implication**: Developers write normal Python with type hints, framework does the rest

3. **Context Injection**: Special parameters (agent, session_state, etc.) injected by signature inspection
   - **Implication**: Tools are testable without framework dependencies

4. **Hook System**: Pre/post hooks + nested tool_hooks enable middleware patterns
   - **Implication**: Cross-cutting concerns (logging, validation, metrics) without tool modification

5. **Human-in-the-Loop**: Three distinct modes cover confirmation, user input, external execution
   - **Implication**: Clear separation of concerns for interactive workflows

6. **File-Based Caching**: MD5-keyed JSON cache with TTL reduces duplicate work
   - **Implication**: Simple, debuggable caching without external dependencies

7. **Parallel Execution**: asyncio.gather enables true concurrent tool calls
   - **Implication**: Multi-tool queries complete faster (fetch weather + flights in parallel)

8. **Self-Correction**: Errors fed back to model with structured messages
   - **Implication**: Models learn from mistakes and retry with corrections

9. **Pydantic Integration**: BaseModel + validate_call provide type safety
   - **Implication**: Runtime validation prevents bad arguments from reaching tools

10. **Flexible Registration**: Toolkit (collection) + decorator (single) + manual (advanced)
    - **Implication**: Match pattern to use case complexity

### Considerations

1. **Configuration Overload**: 20+ configuration fields on Function
   - **Risk**: Cognitive overload for developers
   - **Mitigation**: Sensible defaults, clear documentation, builder pattern

2. **Magic Parameter Injection**: Automatic injection of agent, session_state, etc.
   - **Risk**: Not obvious from signature alone what's available
   - **Mitigation**: Explicit documentation, IDE autocomplete support

3. **No Timeout Support**: Tools can run indefinitely
   - **Risk**: Hung tools block agent progress
   - **Mitigation**: Add timeout parameter to Function config

4. **Cache Key Collisions**: MD5 hash of arguments could collide
   - **Risk**: Wrong cached result returned
   - **Mitigation**: Include function version/hash in cache key

5. **String Normalization**: Auto-converting "true" → True
   - **Risk**: May break tools that expect literal string "true"
   - **Mitigation**: Opt-in via config flag

6. **No Parallel Sync Tools**: Synchronous tools run sequentially
   - **Risk**: Slow when multiple sync tools called
   - **Mitigation**: ThreadPoolExecutor for sync tool parallelism

7. **Pydantic Validation Skip**: validate_call skipped for session_state functions
   - **Risk**: Type errors not caught for those tools
   - **Mitigation**: Manual validation or separate session_state from params

8. **Global Tool Registry**: Tools registered per toolkit/agent instance
   - **Risk**: No framework-wide tool discovery
   - **Mitigation**: Central registry for tool sharing across agents

9. **Hook Execution Order**: Nested hooks execute outside-in
   - **Risk**: Not intuitive for middleware patterns
   - **Mitigation**: Clear documentation with execution diagrams

10. **Generator Caching**: Generators not cached
    - **Risk**: Repeated generator calls repeat work
    - **Mitigation**: Cache final output after generator exhaustion

## Anti-Patterns Observed

1. **eval() for Type Restoration**: `field_type=eval(data["field_type"])` in UserInputField.from_dict
   - **Risk**: Arbitrary code execution if data untrusted
   - **Severity**: HIGH
   - **Recommendation**: Use type registry or pickle for serialization

2. **Mutable Default Argument**: `parameters: Dict[str, Any] = Field(default_factory=lambda: ...)`
   - **Risk**: Shared state across instances if factory not used correctly
   - **Severity**: LOW (Pydantic handles this correctly)
   - **Recommendation**: Keep using default_factory

3. **Silent Exception Handling**: Multiple `except Exception as e: log_warning(...); return "Error: {e}"`
   - **Risk**: Tools fail silently, agent gets error string instead of structured error
   - **Severity**: MEDIUM
   - **Recommendation**: Use structured error types, consider raising exceptions

4. **String-Based Error Messages**: Error feedback as plain strings
   - **Risk**: Model must parse error strings to understand failure modes
   - **Severity**: LOW
   - **Recommendation**: Structured error objects with error codes

5. **No Tool Versioning**: Tools have no version field
   - **Risk**: Cache hits on outdated tool implementations
   - **Severity**: MEDIUM
   - **Recommendation**: Add version field to Function, include in cache key

6. **Deep Nesting in Hooks**: Nested hook execution via reduce + closures
   - **Risk**: Stack traces difficult to debug
   - **Severity**: LOW
   - **Recommendation**: Iterative execution with explicit stack

7. **Inconsistent Naming**: `entrypoint` vs `function` vs `callable`
   - **Risk**: Confusion about which term to use
   - **Severity**: LOW
   - **Recommendation**: Pick one term and use consistently

8. **No Rate Limiting**: Tools can be called unlimited times
   - **Risk**: API quota exhaustion, cost explosion
   - **Severity**: MEDIUM
   - **Recommendation**: Add rate limiting to Function config

9. **Session State Passed by Reference**: `session_state` mutated in-place
   - **Risk**: Hard to track state changes, no audit trail
   - **Severity**: MEDIUM
   - **Recommendation**: Return new state or use immutable data structures

10. **No Tool Metrics**: No built-in metrics for tool usage/performance
    - **Risk**: Can't optimize or debug tool performance
    - **Severity**: LOW
    - **Recommendation**: Add metrics collection to Function execution
