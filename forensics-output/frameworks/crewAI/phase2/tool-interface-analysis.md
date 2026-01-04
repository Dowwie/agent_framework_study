# Tool Interface Analysis: crewAI

## Summary
- **Tool Modeling**: Dual approach - `BaseTool` abstract class inheritance + `@tool` decorator for functions
- **Schema Generation**: Automatic via `inspect.signature()` with Pydantic model generation (introspection + Pydantic hybrid)
- **Registration Pattern**: Explicit list-based registration with agent/crew initialization
- **Error Handling**: Structured error feedback with retry mechanism (3 attempts), error events, and LLM-assisted recovery
- **Built-in Tools**: 90+ tools across 75+ categories (file operations, web scraping, databases, AI services, enterprise integrations)
- **Parallel Execution**: Full async support with `ainvoke`/`_arun` methods throughout
- **Notable Features**: Usage limits per tool, result-as-answer flag, tool caching, MCP integration, hook system

## Tool Modeling

### Core Abstraction

crewAI uses a dual-approach tool system with two primary patterns:

#### 1. BaseTool - Inheritance-Based Pattern

```python
# lib/crewai/src/crewai/tools/base_tool.py

class EnvVar(BaseModel):
    name: str
    description: str
    required: bool = True
    default: str | None = None

class BaseTool(BaseModel, ABC):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(description="The unique name of the tool...")
    description: str = Field(description="Used to tell the model how/when/why to use the tool.")
    args_schema: type[PydanticBaseModel] = Field(
        default=_ArgsSchemaPlaceholder,
        validate_default=True,
        description="The schema for the arguments that the tool accepts."
    )
    env_vars: list[EnvVar] = Field(default_factory=list)

    # Usage control
    cache_function: Callable[..., bool] = Field(default=lambda _args=None, _result=None: True)
    result_as_answer: bool = Field(default=False)
    max_usage_count: int | None = Field(default=None)
    current_usage_count: int = Field(default=0)

    @abstractmethod
    def _run(self, *args: Any, **kwargs: Any) -> Any:
        """Sync implementation of the tool."""

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        """Async implementation of the tool."""
        raise NotImplementedError(...)
```

#### 2. @tool Decorator - Function-Based Pattern

```python
# lib/crewai/src/crewai/tools/base_tool.py

@tool
def greet(name: str) -> str:
    '''Greet someone.'''
    return f"Hello, {name}!"

# Or with options
@tool("custom_name", result_as_answer=True, max_usage_count=5)
def important_operation(data: str) -> bool:
    '''Critical operation with usage limit.'''
    return process(data)
```

The decorator automatically:
- Extracts function name as tool name
- Uses docstring as description
- Generates Pydantic schema from type annotations
- Creates a `Tool[P, R]` generic instance

### Key Attributes

| Attribute | Type | Purpose |
|-----------|------|---------|
| `name` | `str` | Unique tool identifier shown to LLM |
| `description` | `str` | Natural language description for LLM (auto-enhanced with schema) |
| `args_schema` | `type[BaseModel]` | Pydantic model defining expected arguments |
| `env_vars` | `list[EnvVar]` | Declarative environment variable requirements |
| `cache_function` | `Callable` | Custom logic to determine if result should be cached |
| `result_as_answer` | `bool` | If True, tool output becomes final agent answer (early termination) |
| `max_usage_count` | `int \| None` | Usage limit to prevent cost overruns or infinite loops |
| `current_usage_count` | `int` | Runtime counter tracked automatically |

### Internal Conversion Layer

Tools are converted to `CrewStructuredTool` for execution:

```python
# lib/crewai/src/crewai/tools/structured_tool.py

class CrewStructuredTool:
    def __init__(
        self,
        name: str,
        description: str,
        args_schema: type[BaseModel],
        func: Callable[..., Any],
        result_as_answer: bool = False,
        max_usage_count: int | None = None,
        current_usage_count: int = 0,
    ) -> None:
        self.name = name
        self.description = description
        self.args_schema = args_schema
        self.func = func
        self.result_as_answer = result_as_answer
        self.max_usage_count = max_usage_count
        self.current_usage_count = current_usage_count
        self._original_tool: BaseTool | None = None
        self._validate_function_signature()
```

This internal layer provides:
- Unified execution interface (`invoke`, `ainvoke`)
- Argument parsing and validation
- Usage tracking synchronization with original tool

## Schema Generation

### Method Used: Introspection + Pydantic Model Generation

crewAI uses runtime introspection to automatically generate Pydantic schemas from function signatures:

```python
# lib/crewai/src/crewai/tools/structured_tool.py

@staticmethod
def _create_schema_from_function(name: str, func: Callable) -> type[BaseModel]:
    """Create a Pydantic schema from a function's signature."""
    sig = inspect.signature(func)
    type_hints = get_type_hints(func)

    fields = {}
    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        annotation = type_hints.get(param_name, Any)
        default = ... if param.default == param.empty else param.default

        fields[param_name] = (annotation, Field(default=default))

    schema_name = f"{name.title()}Schema"
    return create_model(schema_name, **fields)
```

For `BaseTool` subclasses, schema inference happens via validator:

```python
# lib/crewai/src/crewai/tools/base_tool.py

@field_validator("args_schema", mode="before")
@classmethod
def _default_args_schema(cls, v: type[PydanticBaseModel]) -> type[PydanticBaseModel]:
    if v != cls._ArgsSchemaPlaceholder:
        return v

    run_sig = signature(cls._run)
    fields: dict[str, Any] = {}

    for param_name, param in run_sig.parameters.items():
        if param_name in ("self", "return"):
            continue
        if param.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
            continue

        annotation = param.annotation if param.annotation != param.empty else Any

        if param.default is param.empty:
            fields[param_name] = (annotation, ...)
        else:
            fields[param_name] = (annotation, param.default)

    return create_model(f"{cls.__name__}Schema", **fields)
```

### Schema Enhancement for LLM Context

The raw Pydantic schema is enhanced with full JSON schema formatting:

```python
# lib/crewai/src/crewai/tools/base_tool.py

def _generate_description(self) -> None:
    """Generate the tool description with a JSON schema for arguments."""
    schema = generate_model_description(self.args_schema)
    args_json = json.dumps(schema["json_schema"]["schema"], indent=2)
    self.description = (
        f"Tool Name: {self.name}\n"
        f"Tool Arguments: {args_json}\n"
        f"Tool Description: {self.description}"
    )
```

### Schema Utilities (`pydantic_schema_utils.py`)

The framework includes comprehensive schema transformation utilities:

```python
# lib/crewai/src/crewai/utilities/pydantic_schema_utils.py

def generate_model_description(model: type[BaseModel]) -> dict[str, Any]:
    """Generate JSON schema description of a Pydantic model."""
    json_schema = model.model_json_schema(ref_template="#/$defs/{model}")

    # Add additionalProperties: false to all objects
    json_schema = add_key_in_dict_recursively(
        json_schema,
        key="additionalProperties",
        value=False,
        criteria=lambda d: d.get("type") == "object" and "additionalProperties" not in d,
    )

    # Inline all $ref references
    json_schema = resolve_refs(json_schema)

    # OpenAI compatibility transformations
    json_schema.pop("$defs", None)
    json_schema = fix_discriminator_mappings(json_schema)
    json_schema = convert_oneof_to_anyof(json_schema)
    json_schema = ensure_all_properties_required(json_schema)

    return {
        "type": "json_schema",
        "json_schema": {
            "name": model.__name__,
            "strict": True,
            "schema": json_schema,
        },
    }
```

Key transformations:
- **Resolve $refs**: Inline all references to avoid LLM confusion
- **oneOf → anyOf**: OpenAI Structured Outputs compatibility
- **All properties required**: Strict mode enforcement
- **additionalProperties: false**: Prevent schema drift

### Generated Schema Example

For the `FileReadTool`:

```python
class FileReadToolSchema(BaseModel):
    file_path: str = Field(..., description="Mandatory file full path to read the file")
    start_line: int | None = Field(1, description="Line number to start reading from (1-indexed)")
    line_count: int | None = Field(None, description="Number of lines to read. If None, reads the entire file")
```

Generated JSON schema (after enhancement):

```json
{
  "type": "json_schema",
  "json_schema": {
    "name": "FileReadToolSchema",
    "strict": true,
    "schema": {
      "type": "object",
      "properties": {
        "file_path": {
          "type": "string",
          "description": "Mandatory file full path to read the file"
        },
        "start_line": {
          "anyOf": [
            {"type": "integer"},
            {"type": "null"}
          ],
          "default": 1,
          "description": "Line number to start reading from (1-indexed)"
        },
        "line_count": {
          "anyOf": [
            {"type": "integer"},
            {"type": "null"}
          ],
          "default": null,
          "description": "Number of lines to read. If None, reads the entire file"
        }
      },
      "required": ["file_path", "start_line", "line_count"],
      "additionalProperties": false
    }
  }
}
```

## Built-in Tool Inventory

### Categories and Organization

crewAI provides 90+ production-ready tools across 75+ categories. Tools are organized in the `crewai-tools` package:

```
lib/crewai-tools/src/crewai_tools/
├── tools/                    # Tool implementations
│   ├── file_read_tool/
│   ├── serper_dev_tool/
│   ├── brave_search_tool/
│   └── ... (75+ categories)
├── adapters/                 # Third-party integrations
│   ├── mcp_adapter.py       # Model Context Protocol
│   ├── enterprise_adapter.py
│   └── zapier_adapter.py
└── aws/                     # AWS-specific tools
    └── bedrock/
```

### Tool Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| **File Operations** | FileReadTool, FileWriterTool, DirectoryReadTool, DirectorySearchTool, FileCompressorTool | Local file system manipulation |
| **Document Processing** | PDFSearchTool, DOCXSearchTool, CSVSearchTool, JSONSearchTool, XMLSearchTool, TXTSearchTool, MDXSearchTool | Structured document parsing |
| **Web Scraping** | ScrapeWebsiteTool, SeleniumScrapingTool, FirecrawlScrapeWebsiteTool, ScrapflyScrapeWebsiteTool, JinaScrapeWebsiteTool, ScrapegraphScrapeTool | HTML extraction |
| **Search Engines** | SerperDevTool, BraveSearchTool, TavilySearchTool, EXASearchTool, LinkupSearchTool | Internet search |
| **Specialized Search** | SerpApiGoogleSearchTool, SerpApiGoogleShoppingTool, SerplyWebSearchTool, SerplyNewsSearchTool, SerplyScholarSearchTool, SerplyJobSearchTool | Vertical-specific search |
| **Browser Automation** | BrowserbaseLoadTool, HyperbrowserLoadTool, StagehandTool, MultiOnTool | Headless browser control |
| **Vector Databases** | QdrantVectorSearchTool, WeaviateVectorSearchTool, MongoDBVectorSearchTool, CouchbaseFTSVectorSearchTool, SingleStoreSearchTool | Semantic search |
| **Cloud Storage** | S3ReaderTool, S3WriterTool | AWS S3 integration |
| **Data Warehouses** | SnowflakeSearchTool, DatabricksQueryTool | SQL query execution |
| **Database Tools** | MySQLSearchTool, NL2SQLTool | SQL generation and execution |
| **AI Services** | DallETool, VisionTool, OCRTool | Image generation/analysis |
| **RAG Tools** | RagTool, BedrockKBRetrieverTool, ContextualAIQueryTool, ContextualAIParseTool, LlamaIndexTool | Retrieval augmented generation |
| **Content Generation** | CodeInterpreterTool, GenerateCrewaiAutomationTool | Code execution and scaffolding |
| **Enterprise** | ComposioTool, ZapierActionTool, EnterpriseActionTool, MergeAgentHandlerTool | SaaS integrations |
| **Research** | ArxivPaperTool, GithubSearchTool | Academic/code search |
| **Evaluation** | PatronusEvalTool, PatronusLocalEvaluatorTool, PatronusPredefinedCriteriaEvalTool | LLM output evaluation |
| **Web Scraping (Advanced)** | ApifyActorsTool, SpiderTool, BrightDataSearchTool, BrightDataWebUnlockerTool, OxylabsUniversalScraperTool | Professional scraping APIs |
| **Agent-to-Agent** | DelegateWorkTool, AskQuestionTool, BedrockInvokeAgentTool, ContextualAICreateAgentTool, InvokeCrewAIAutomationTool | Inter-agent communication |
| **MCP Integration** | MCPServerAdapter | Dynamic tool discovery via Model Context Protocol |

### Complete Tool List (Selected Representative Tools)

| Tool Name | Location | Schema Method | Category |
|-----------|----------|---------------|----------|
| FileReadTool | `tools/file_read_tool/` | Pydantic class + introspection | File I/O |
| SerperDevTool | `tools/serper_dev_tool/` | Pydantic class + introspection | Search |
| ScrapeWebsiteTool | `tools/scrape_website_tool/` | Pydantic class + introspection | Web |
| PDFSearchTool | `tools/pdf_search_tool/` | Pydantic class + introspection | Documents |
| QdrantVectorSearchTool | `tools/qdrant_vector_search_tool/` | Pydantic class + introspection | Vector DB |
| S3ReaderTool | `aws/s3/reader_tool.py` | Pydantic class + introspection | Cloud |
| CodeInterpreterTool | `tools/code_interpreter_tool/` | Pydantic class + introspection | Execution |
| DallETool | `tools/dalle_tool/` | Pydantic class + introspection | AI Services |
| DelegateWorkTool | Core agent tools | Pydantic class | Multi-agent |
| AskQuestionTool | Core agent tools | Pydantic class | Multi-agent |
| MCPServerAdapter | `adapters/mcp_adapter.py` | Dynamic (MCP protocol) | Integration |
| BedrockInvokeAgentTool | `aws/bedrock/agents/` | Pydantic class + introspection | AWS |
| ComposioTool | `tools/composio_tool/` | Pydantic class + introspection | SaaS |
| ZapierActionTool | `adapters/zapier_adapter.py` | Dynamic (API introspection) | Automation |
| PatronusEvalTool | `tools/patronus_eval_tool/` | Pydantic class + introspection | Evaluation |

### Example Tool Implementation

```python
# lib/crewai-tools/src/crewai_tools/tools/serper_dev_tool/serper_dev_tool.py

class SerperDevToolSchema(BaseModel):
    search_query: str = Field(..., description="Mandatory search query you want to use to search the internet")

class SerperDevTool(BaseTool):
    name: str = "Search the internet with Serper"
    description: str = "A tool that can be used to search the internet with a search_query. Supports different search types: 'search' (default), 'news'"
    args_schema: type[BaseModel] = SerperDevToolSchema
    base_url: str = "https://google.serper.dev"
    n_results: int = 10
    save_file: bool = False
    search_type: str = "search"
    country: str | None = ""
    location: str | None = ""
    locale: str | None = ""
    env_vars: list[EnvVar] = Field(
        default_factory=lambda: [
            EnvVar(name="SERPER_API_KEY", description="API key for Serper", required=True),
        ]
    )

    def _run(self, **kwargs: Any) -> FormattedResults:
        search_query = kwargs.get("search_query") or kwargs.get("query")
        search_type = kwargs.get("search_type", self.search_type)

        if not search_query:
            raise ValueError("search_query is required")

        results = self._make_api_request(search_query, search_type)
        formatted_results = self._process_search_results(results, search_type)

        return formatted_results
```

## Registration & Discovery

### Pattern: Explicit List-Based Registration

Tools are registered explicitly when creating agents or crews:

```python
# Agent-level registration
from crewai import Agent
from crewai_tools import FileReadTool, SerperDevTool

researcher = Agent(
    role="Research Analyst",
    goal="Find relevant information",
    tools=[
        FileReadTool(),
        SerperDevTool(n_results=5),
    ]
)

# Crew-level tool sharing
from crewai import Crew

crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, write_task],
    tools=[FileReadTool()]  # Available to all agents
)
```

### Dynamic Discovery via MCP

The MCPServerAdapter enables dynamic tool discovery:

```python
# lib/crewai-tools/src/crewai_tools/adapters/mcp_adapter.py

from mcp import StdioServerParameters

# Connect to MCP server and auto-discover tools
with MCPServerAdapter(
    StdioServerParameters(command="uvx", args=["mcp-server-git"])
) as tools:
    agent = Agent(
        role="Developer",
        tools=tools  # All MCP tools automatically available
    )

# Or filter specific tools
with MCPServerAdapter(
    StdioServerParameters(...),
    "git_status",
    "git_diff"
) as filtered_tools:
    agent = Agent(tools=filtered_tools)
```

### Registration Flow

```
1. Tool Instantiation
   ├─ BaseTool subclass initialization
   ├─ Schema auto-generation (if not provided)
   └─ Description enhancement with JSON schema

2. Agent/Crew Assignment
   ├─ Tools passed to Agent.__init__(tools=[...])
   └─ Or Crew.__init__(tools=[...]) for shared tools

3. Internal Conversion (at execution time)
   ├─ BaseTool.to_structured_tool() called
   ├─ Creates CrewStructuredTool wrapper
   └─ Maintains reference to original tool (_original_tool)

4. Runtime Access
   ├─ Tools available in agent executor
   ├─ Tools indexed by name in tool_name_to_tool_map
   └─ Tools accessible via ToolsHandler
```

### Tool Collection Helper

The `ToolCollection` adapter provides filtering utilities:

```python
# lib/crewai-tools/src/crewai_tools/adapters/tool_collection.py

tools_collection = ToolCollection([tool1, tool2, tool3])
filtered = tools_collection.filter_by_names(["tool1", "tool2"])
```

## Execution Flow

### Invocation Pattern

```python
# lib/crewai/src/crewai/tools/structured_tool.py

def invoke(self, input: str | dict, config: dict | None = None, **kwargs: Any) -> Any:
    """Main method for tool execution."""
    # 1. Parse and validate arguments
    parsed_args = self._parse_args(input)

    # 2. Check usage limits
    if self.has_reached_max_usage_count():
        raise ToolUsageLimitExceededError(
            f"Tool '{self.name}' has reached its maximum usage limit of {self.max_usage_count}."
        )

    # 3. Increment usage counter
    self._increment_usage_count()

    # 4. Execute function (sync or async)
    if inspect.iscoroutinefunction(self.func):
        return asyncio.run(self.func(**parsed_args, **kwargs))

    result = self.func(**parsed_args, **kwargs)

    if asyncio.iscoroutine(result):
        return asyncio.run(result)

    return result

def _parse_args(self, raw_args: str | dict) -> dict:
    """Parse and validate the input arguments against the schema."""
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse arguments as JSON: {e}") from e

    try:
        validated_args = self.args_schema.model_validate(raw_args)
        return validated_args.model_dump()
    except Exception as e:
        raise ValueError(f"Arguments validation failed: {e}") from e
```

### Full Execution Flow (via ToolUsage)

```python
# lib/crewai/src/crewai/tools/tool_usage.py

def use(self, calling: ToolCalling, tool_string: str) -> str:
    # 1. Error handling for parsing failures
    if isinstance(calling, ToolUsageError):
        error = calling.message
        if self.agent and self.agent.verbose:
            self._printer.print(content=f"\n\n{error}\n", color="red")
        if self.task:
            self.task.increment_tools_errors()
        return error

    # 2. Tool selection (fuzzy matching)
    try:
        tool = self._select_tool(calling.tool_name)
    except Exception as e:
        error = getattr(e, "message", str(e))
        if self.task:
            self.task.increment_tools_errors()
        return error

    # 3. Check for repeated usage (infinite loop protection)
    if self._check_tool_repeated_usage(calling=calling):
        result = self._i18n.errors("task_repeated_usage").format(tool_names=self.tools_names)
        return self._format_result(result=result)

    # 4. Emit start event
    crewai_event_bus.emit(self, ToolUsageStartedEvent(...))

    # 5. Check cache
    from_cache = False
    result = None
    if self.tools_handler and self.tools_handler.cache:
        result = self.tools_handler.cache.read(tool=calling.tool_name, input=input_str)
        from_cache = result is not None

    # 6. Check usage limits
    usage_limit_error = self._check_usage_limit(available_tool, tool.name)
    if usage_limit_error:
        return self._format_result(result=usage_limit_error)

    # 7. Execute before hooks
    hook_context = ToolCallHookContext(...)
    before_hooks = get_before_tool_call_hooks()
    for hook in before_hooks:
        result = hook(hook_context)
        if result is False:
            return ToolResult("Tool execution blocked by hook", False)

    # 8. Execute tool
    if result is None:
        try:
            arguments = self._add_fingerprint_metadata(calling.arguments)
            result = tool.invoke(input=arguments)
        except Exception as e:
            self._run_attempts += 1
            if self._run_attempts > self._max_parsing_attempts:
                error = ToolUsageError(f"\n{error_message}.\nMoving on then...")
                return error
            # Retry
            return self.use(calling=calling, tool_string=tool_string)

    # 9. Cache result (if applicable)
    if self.tools_handler:
        should_cache = True
        if hasattr(available_tool, "cache_function") and available_tool.cache_function:
            should_cache = available_tool.cache_function(calling.arguments, result)
        self.tools_handler.on_tool_use(calling=calling, output=result, should_cache=should_cache)

    # 10. Execute after hooks
    after_hooks = get_after_tool_call_hooks()
    modified_result = result
    for after_hook in after_hooks:
        hook_result = after_hook(hook_context)
        if hook_result is not None:
            modified_result = hook_result

    # 11. Emit finish event
    crewai_event_bus.emit(self, ToolUsageFinishedEvent(...))

    # 12. Track usage and return
    self.agent.tools_results.append({
        "result": result,
        "tool_name": tool.name,
        "tool_args": calling.arguments,
    })

    return result
```

### Error Handling

| Error Type | Handling | Feedback to LLM |
|------------|----------|-----------------|
| **Tool Selection Error** | Fuzzy matching with SequenceMatcher (>85% similarity threshold) | `"Action '{tool_name}' doesn't exist, these are the only available Actions: {tools_description}"` |
| **Argument Parsing Error** | Multi-stage parsing: JSON → Python literal → JSON5 → JSON repair | `"Tool input must be a valid dictionary in JSON or Python literal format"` |
| **Argument Validation Error** | Pydantic validation with detailed error messages | `"Arguments validation failed: {pydantic_error}"` |
| **Tool Execution Error** | Retry with max 3 attempts (2 for GPT-4+ models) | `"Error: {error}.\nMoving on then. {format_reminder}"` |
| **Usage Limit Exceeded** | Hard stop with error message | `"Tool '{tool_name}' has reached its maximum usage limit of {max_count} times and cannot be used anymore."` |
| **Repeated Usage** | Single warning then allow | `"You seem to be repeating the same tool usage. Try a different approach."` |
| **Hook Blocked** | Return blocking message | `"Tool execution blocked by hook. Tool: {tool_name}"` |

### Retry Mechanisms

```python
# lib/crewai/src/crewai/tools/tool_usage.py

self._run_attempts: int = 1
self._max_parsing_attempts: int = 3  # Default
self._remember_format_after_usages: int = 3

# Adjusted for larger models
if self.function_calling_llm and self.function_calling_llm.model in OPENAI_BIGGER_MODELS:
    self._max_parsing_attempts = 2  # Fewer retries for smarter models
    self._remember_format_after_usages = 4
```

**Retry Logic**:
1. On tool execution error, increment `_run_attempts`
2. If `_run_attempts > _max_parsing_attempts`, return error to LLM with format reminder
3. Otherwise, recursively call `use()` again (with same arguments)
4. After every N successful tool uses, remind LLM of available tools and format

### Integration with Agent Executor

```python
# lib/crewai/src/crewai/agents/crew_agent_executor.py

# Within agent execution loop
if isinstance(formatted_answer, AgentAction):
    # Execute tool
    tool_result = execute_tool_and_check_finality(
        agent_action=formatted_answer,
        tools=self.tools,
        i18n=self._i18n,
        tools_handler=self.tools_handler,
        task=self.task,
        agent=self.agent,
        function_calling_llm=self.function_calling_llm,
        crew=self.crew,
    )

    # Handle result
    formatted_answer = self._handle_agent_action(formatted_answer, tool_result)

    # If tool result should be final answer
    if tool_result.result_as_answer:
        return AgentFinish(output=tool_result.result)
```

## Parallel Execution

### Async Support Throughout Stack

crewAI provides comprehensive async support:

```python
# 1. Tool Level - BaseTool
async def _arun(self, *args: Any, **kwargs: Any) -> Any:
    """Async implementation of the tool."""
    raise NotImplementedError(...)

async def arun(self, *args: Any, **kwargs: Any) -> Any:
    """Execute the tool asynchronously."""
    result = await self._arun(*args, **kwargs)
    self.current_usage_count += 1
    return result

# 2. Structured Tool Level
async def ainvoke(self, input: str | dict, config: dict | None = None, **kwargs: Any) -> Any:
    """Asynchronously invoke the tool."""
    parsed_args = self._parse_args(input)

    if self.has_reached_max_usage_count():
        raise ToolUsageLimitExceededError(...)

    self._increment_usage_count()

    try:
        if inspect.iscoroutinefunction(self.func):
            return await self.func(**parsed_args, **kwargs)
        # Run sync functions in thread pool
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.func(**parsed_args, **kwargs)
        )
    except Exception:
        raise

# 3. Tool Usage Level
async def ause(self, calling: ToolCalling, tool_string: str) -> str:
    """Execute a tool asynchronously."""
    # ... (same logic as sync version)
    result = await tool.ainvoke(input=arguments)
    return result

# 4. Agent Executor Level
async def ainvoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
    """Execute the agent asynchronously with given inputs."""
    formatted_answer = await self._ainvoke_loop()
    return {"output": formatted_answer.output}

async def _ainvoke_loop(self) -> AgentFinish:
    """Execute agent loop asynchronously until completion."""
    while not isinstance(formatted_answer, AgentFinish):
        # Async LLM call
        answer = await aget_llm_response(...)

        # Async tool execution
        if isinstance(formatted_answer, AgentAction):
            tool_result = await aexecute_tool_and_check_finality(...)
```

### Hybrid Execution Strategy

crewAI handles both sync and async functions gracefully:

```python
# Sync function in async context
if inspect.iscoroutinefunction(self.func):
    return await self.func(**parsed_args)
else:
    # Run sync function in thread pool executor
    return await asyncio.get_event_loop().run_in_executor(
        None, lambda: self.func(**parsed_args)
    )

# Async function in sync context
result = self.func(*args, **kwargs)
if asyncio.iscoroutine(result):
    result = asyncio.run(result)
```

### Parallel Tool Execution

The `ParallelSearchTool` demonstrates parallel execution pattern:

```python
# lib/crewai-tools/src/crewai_tools/tools/parallel_tools/parallel_search_tool.py

class ParallelSearchTool(BaseTool):
    """Execute multiple search queries in parallel."""

    def _run(self, queries: list[str]) -> list[dict]:
        # Execute searches concurrently
        tasks = [self._search(query) for query in queries]
        results = asyncio.gather(*tasks)
        return results
```

## Code References

### Core Tool Files
- `/repos/crewAI/lib/crewai/src/crewai/tools/base_tool.py` (lines 1-553) - Base tool abstraction and @tool decorator
- `/repos/crewAI/lib/crewai/src/crewai/tools/structured_tool.py` (lines 1-301) - Internal execution wrapper
- `/repos/crewAI/lib/crewai/src/crewai/tools/tool_usage.py` (lines 1-962) - Tool execution orchestration

### Schema Generation
- `/repos/crewAI/lib/crewai/src/crewai/utilities/pydantic_schema_utils.py` (lines 1-246) - Schema transformations
- `/repos/crewAI/lib/crewai/src/crewai/tools/base_tool.py` (lines 97-138) - Auto-schema generation from `_run` signature
- `/repos/crewAI/lib/crewai/src/crewai/tools/structured_tool.py` (lines 125-163) - Schema creation from functions

### Execution Flow
- `/repos/crewAI/lib/crewai/src/crewai/utilities/tool_utils.py` (lines 161-294) - `execute_tool_and_check_finality`
- `/repos/crewAI/lib/crewai/src/crewai/agents/crew_agent_executor.py` (lines 259-271, 412-424) - Agent executor integration
- `/repos/crewAI/lib/crewai/src/crewai/tools/tool_usage.py` (lines 408-597) - `_use` method

### Built-in Tools
- `/repos/crewAI/lib/crewai-tools/src/crewai_tools/__init__.py` (lines 1-295) - Tool exports (90+ tools)
- `/repos/crewAI/lib/crewai-tools/src/crewai_tools/tools/file_read_tool/file_read_tool.py` - Example tool implementation
- `/repos/crewAI/lib/crewai-tools/src/crewai_tools/tools/serper_dev_tool/serper_dev_tool.py` - Complex tool with API integration

### MCP Integration
- `/repos/crewAI/lib/crewai-tools/src/crewai_tools/adapters/mcp_adapter.py` (lines 1-164) - Dynamic tool discovery

### Agent Tools (Multi-Agent)
- `/repos/crewAI/lib/crewai/src/crewai/tools/agent_tools/delegate_work_tool.py` - Inter-agent delegation
- `/repos/crewAI/lib/crewai/src/crewai/tools/agent_tools/ask_question_tool.py` - Inter-agent questions

## Implications for New Framework

### Positive Patterns

1. **Dual Tool Definition Strategy**
   - **Pattern**: Support both `@tool` decorator (function-first) AND `BaseTool` inheritance (class-first)
   - **Benefit**: Developers choose based on complexity:
     - Simple tools: `@tool` decorator with type hints
     - Complex tools: `BaseTool` subclass with custom logic
   - **Implementation**: Both converge to same internal representation

2. **Automatic Schema Generation from Introspection**
   - **Pattern**: Use `inspect.signature()` + `get_type_hints()` to auto-generate Pydantic schemas
   - **Benefit**: Zero boilerplate - just add type hints and docstring
   - **Example**:
     ```python
     @tool
     def search(query: str, limit: int = 10) -> list[str]:
         '''Search the web.'''
         # Schema generated automatically from signature
     ```

3. **Usage Limits and Cost Control**
   - **Pattern**: `max_usage_count` attribute per tool
   - **Benefit**: Prevent infinite loops and cost overruns in production
   - **Use Cases**:
     - Expensive API calls (e.g., image generation)
     - Breaking circular reasoning patterns
     - Budget enforcement

4. **Result-as-Answer Flag**
   - **Pattern**: `result_as_answer=True` allows tool to terminate agent execution
   - **Benefit**: Short-circuit for deterministic answers (e.g., calculator tool)
   - **Example**: Math tool immediately returns result without further LLM reasoning

5. **Custom Cache Control**
   - **Pattern**: `cache_function` callback to determine cacheability per invocation
   - **Benefit**: Fine-grained control (e.g., don't cache time-sensitive queries)
   - **Example**:
     ```python
     cache_function=lambda args, result: "real-time" not in args.get("query", "")
     ```

6. **Structured Error Feedback to LLM**
   - **Pattern**: Convert exceptions to natural language observations with format reminders
   - **Benefit**: LLM can self-correct rather than failing completely
   - **Example**: `"Tool 'search_web' failed. Try using 'browse_url' instead. Available tools: ..."`

7. **Hook System for Tool Execution**
   - **Pattern**: `before_tool_call` and `after_tool_call` hooks
   - **Benefit**:
     - Add logging/monitoring without modifying tools
     - Implement security policies (block certain calls)
     - Transform results (e.g., sanitize sensitive data)
   - **Example**:
     ```python
     def security_check(context: ToolCallHookContext) -> bool:
         if context.tool_name == "execute_code" and not approved(context.tool_input):
             return False  # Block execution
         return True
     ```

8. **MCP Integration for Dynamic Discovery**
   - **Pattern**: Model Context Protocol adapter for runtime tool registration
   - **Benefit**: Connect to external tool servers without code changes
   - **Example**:
     ```python
     with MCPServerAdapter(StdioServerParameters(command="uvx", args=["mcp-server-git"])) as tools:
         agent = Agent(tools=tools)  # Git tools automatically available
     ```

9. **Declarative Environment Variables**
   - **Pattern**: `env_vars` field declares required environment variables
   - **Benefit**: Clear documentation + validation at tool initialization
   - **Example**:
     ```python
     env_vars=[
         EnvVar(name="SERPER_API_KEY", description="API key for Serper", required=True),
     ]
     ```

10. **Comprehensive Async Support**
    - **Pattern**: Parallel sync/async APIs throughout (`run`/`arun`, `invoke`/`ainvoke`)
    - **Benefit**: Works in both sync and async contexts with automatic adaptation
    - **Implementation**: Thread pool executor for sync functions in async context

### Considerations

1. **Schema Coupling to Description**
   - **Issue**: `_generate_description()` mutates `description` to include full JSON schema
   - **Impact**: Description becomes verbose and couples presentation to schema
   - **Alternative**: Keep schema separate; let LLM access via structured format

2. **Retry Logic Complexity**
   - **Issue**: Recursive `use()` calls with attempt counter can be hard to debug
   - **Impact**: Stack traces become deep; state management across retries
   - **Alternative**: Iterative retry loop with explicit state machine

3. **Fuzzy Tool Name Matching**
   - **Issue**: SequenceMatcher allows >85% similarity (e.g., "search_web" matches "search_website")
   - **Impact**: Can lead to wrong tool selection
   - **Alternative**: Strict matching + LLM-based correction suggestion

4. **Global Hooks**
   - **Issue**: `get_before_tool_call_hooks()` returns global hooks (not scoped to crew/agent)
   - **Impact**: Hooks affect all agents in the process
   - **Alternative**: Hooks scoped to crew/agent instances

5. **Tool Conversion Overhead**
   - **Issue**: BaseTool → CrewStructuredTool conversion happens at execution time
   - **Impact**: Extra layer of indirection; dual usage counter tracking
   - **Alternative**: Single unified tool representation

6. **Error Event Complexity**
   - **Issue**: 5+ different error event types (ToolSelectionError, ToolUsageError, ToolValidateInputError, etc.)
   - **Impact**: Complex event handling; listeners need to handle many types
   - **Alternative**: Single ToolErrorEvent with error_type discriminator

7. **Cache Key Generation**
   - **Issue**: Cache key is JSON-serialized arguments (order-dependent)
   - **Impact**: `{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` are different cache keys
   - **Alternative**: Canonicalize argument order before serialization

8. **Fingerprint Metadata Injection**
   - **Issue**: Security metadata automatically added to all tool arguments
   - **Impact**: Tools receive unexpected `security_context` parameter
   - **Alternative**: Pass metadata via separate channel (e.g., execution context)

## Anti-Patterns Observed

1. **Mutable Schema Enhancement**
   ```python
   def _generate_description(self) -> None:
       # Mutates self.description in-place
       self.description = f"Tool Name: {self.name}\nTool Arguments: {args_json}\nTool Description: {self.description}"
   ```
   - **Issue**: Original description is lost; hard to separate user-facing description from LLM context
   - **Better**: Store enhanced description separately (e.g., `llm_description` vs `description`)

2. **Exception-Driven Control Flow**
   ```python
   try:
       return self._original_tool_calling(tool_string, raise_error=True)
   except Exception:
       if self.function_calling_llm:
           return self._function_calling(tool_string)
       return self._original_tool_calling(tool_string)
   ```
   - **Issue**: Using exceptions for normal logic flow (fallback to LLM-based parsing)
   - **Better**: Check preconditions first, reserve exceptions for actual errors

3. **Recursive Retry with Hidden State**
   ```python
   except Exception as e:
       self._run_attempts += 1
       if self._run_attempts > self._max_parsing_attempts:
           return error
       return self.use(calling=calling, tool_string=tool_string)  # Recursive call
   ```
   - **Issue**: State mutation in exception handler; deep call stack on repeated failures
   - **Better**: Iterative retry loop with explicit state tracking

4. **Global Mutable State for Hooks**
   ```python
   before_hooks = get_before_tool_call_hooks()  # Returns global list
   ```
   - **Issue**: Hooks registered in one part of code affect all agents globally
   - **Better**: Hooks scoped to agent/crew instances

5. **Implicit Conversion in Properties**
   ```python
   @property
   def use_stop_words(self) -> bool:
       return self.llm.supports_stop_words() if self.llm else False
   ```
   - **Issue**: Property performs complex logic (method call + conditional)
   - **Better**: Make it a regular method to signal computation

6. **Broad Exception Catching**
   ```python
   except Exception as e:
       # Handle all exceptions the same way
   ```
   - **Issue**: Catches and suppresses unexpected errors (e.g., KeyboardInterrupt, SystemExit)
   - **Better**: Catch specific exceptions (ToolUsageError, ValidationError, etc.)

7. **Dual Usage Counter Tracking**
   ```python
   def _increment_usage_count(self) -> None:
       self.current_usage_count += 1
       if self._original_tool is not None:
           self._original_tool.current_usage_count = self.current_usage_count
   ```
   - **Issue**: Must synchronize counters between CrewStructuredTool and BaseTool
   - **Better**: Single source of truth (either wrapper or original)

8. **JSON Schema Transformations for LLM Compatibility**
   ```python
   json_schema = convert_oneof_to_anyof(json_schema)
   json_schema = ensure_all_properties_required(json_schema)
   ```
   - **Issue**: Pydantic schema doesn't match actual Python types (optional fields marked required)
   - **Better**: Generate schemas that match actual validation rules; use LLM-specific formatting only at serialization boundary
