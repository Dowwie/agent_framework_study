# Tool Interface Analysis: google-adk

## Summary
- **Tool Modeling**: BaseTool ABC + FunctionTool wrapper (auto-converts plain functions)
- **Schema Generation**: Pydantic-based automatic introspection from type hints + docstrings
- **Registration Pattern**: Declarative (list in Agent constructor) + Toolset abstraction for dynamic collections
- **Error Handling**: Structured dict returns with 'error' key, validation before execution, LLM feedback loop
- **Built-in Tools**: 40+ tools across 12 categories (search, database, compute, integrations)

## Tool Modeling

### Core Abstraction

google-adk uses a dual-layer tool abstraction:

1. **BaseTool** - Abstract base class for all tools
2. **FunctionTool** - Automatic wrapper that converts plain Python functions to tools

```python
# From: src/google/adk/tools/base_tool.py
class BaseTool(ABC):
    """The base class for all tools."""

    name: str
    description: str
    is_long_running: bool = False
    custom_metadata: Optional[dict[str, Any]] = None

    def _get_declaration(self) -> Optional[types.FunctionDeclaration]:
        """Gets the OpenAPI spec in the form of FunctionDeclaration."""
        return None

    async def run_async(
        self, *, args: dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Runs the tool with the given arguments and context."""
        raise NotImplementedError(f"{type(self)} is not implemented")

    async def process_llm_request(
        self, *, tool_context: ToolContext, llm_request: LlmRequest
    ) -> None:
        """Processes the outgoing LLM request for this tool."""
        llm_request.append_tools([self])
```

```python
# From: src/google/adk/tools/function_tool.py
class FunctionTool(BaseTool):
    """A tool that wraps a user-defined Python function."""

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        require_confirmation: Union[bool, Callable[..., bool]] = False,
    ):
        name = func.__name__
        doc = inspect.cleandoc(func.__doc__)
        super().__init__(name=name, description=doc)
        self.func = func
        self._ignore_params = ['tool_context', 'input_stream']
        self._require_confirmation = require_confirmation
```

### Key Attributes

| Attribute | Type | Purpose |
|-----------|------|---------|
| name | str | Tool identifier sent to LLM |
| description | str | Tool purpose (from docstring) |
| is_long_running | bool | Flag for async operations returning resource IDs |
| custom_metadata | dict | JSON-serializable metadata (tool manifests, etc.) |
| func | Callable | Wrapped function (FunctionTool only) |
| _ignore_params | list[str] | Parameters excluded from schema (tool_context, etc.) |
| _require_confirmation | bool/Callable | HITL approval requirement |

### Design Pattern

**Automatic Function Wrapping** - The framework automatically converts plain functions to FunctionTool instances:

```python
# Usage example from: contributing/samples/built_in_multi_tools/agent.py
def roll_die(sides: int, tool_context: ToolContext) -> int:
    """Roll a die and return the rolled result.

    Args:
        sides: The integer number of sides the die has.

    Returns:
        An integer of the result of rolling the die.
    """
    result = random.randint(1, sides)
    return result

# Direct function registration (auto-wrapped as FunctionTool)
root_agent = Agent(
    tools=[
        roll_die,  # Plain function automatically wrapped
        VertexAiSearchTool(...),  # Explicit BaseTool subclass
    ]
)
```

## Schema Generation

### Method Used

**Pydantic-based introspection** with two implementation paths:

1. **New path (feature flag enabled)**: Full JSON Schema via Pydantic's `create_model` + `model_json_schema()`
2. **Legacy path**: Manual type parsing with fallback to Pydantic TypeAdapter

```python
# From: src/google/adk/tools/_function_tool_declarations.py
def build_function_declaration_with_json_schema(
    func: Callable[..., Any] | Type[pydantic.BaseModel],
    ignore_params: Optional[list[str]] = None,
) -> types.FunctionDeclaration:
    """Build FunctionDeclaration using Pydantic's JSON schema generation.

    Leverages Pydantic's create_model to dynamically create a model from
    function parameters, then uses model_json_schema() to generate the
    JSON schema.
    """
    description = inspect.cleandoc(func.__doc__) if func.__doc__ else None
    func_name = getattr(func, '__name__', 'Callable')

    declaration = types.FunctionDeclaration(
        name=func_name,
        description=description,
    )

    # Build parameters schema
    parameters_schema = _build_parameters_json_schema(func, ignore_params)
    if parameters_schema:
        declaration.parameters_json_schema = parameters_schema

    # Build response schema
    response_schema = _build_response_json_schema(func)
    if response_schema:
        declaration.response_json_schema = response_schema

    return declaration
```

```python
# From: src/google/adk/tools/_function_tool_declarations.py
def _build_parameters_json_schema(
    func: Callable[..., Any],
    ignore_params: Optional[list[str]] = None,
) -> Optional[dict[str, Any]]:
    """Build JSON schema for function parameters using Pydantic."""
    fields = _get_function_fields(func, ignore_params)
    if not fields:
        return None

    # Create Pydantic model dynamically
    func_name = getattr(func, '__name__', 'Callable')
    model = create_model(
        f'{func_name}Params',
        **fields,  # (type, default) tuples
    )

    return model.model_json_schema()
```

### Type Mapping

The framework uses Pydantic's native JSON Schema generation, which handles:

- **Primitives**: str → string, int → integer, float → number, bool → boolean
- **Collections**: list → array, dict → object, tuple → array
- **Optional**: `Optional[T]` → `anyOf: [{type: T}, {type: null}]` with `nullable: true`
- **Pydantic Models**: Nested JSON schemas with full validation rules
- **Enums**: Enum values extracted as `enum` constraint
- **Union Types**: `anyOf` schemas for multiple type options

### Generated Schema Example

```python
# Input function
def create_user(
    name: str,
    age: int,
    email: Optional[str] = None,
    preferences: UserPreferences = UserPreferences()
) -> dict:
    """Create a new user account."""
    pass

# Generated FunctionDeclaration (simplified)
{
    "name": "create_user",
    "description": "Create a new user account.",
    "parameters_json_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "email": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "nullable": true
            },
            "preferences": {
                "$ref": "#/$defs/UserPreferences"
            }
        },
        "required": ["name", "age"],
        "$defs": {
            "UserPreferences": {
                "type": "object",
                "properties": {
                    "theme": {"type": "string", "default": "light"},
                    "language": {"type": "string", "default": "English"}
                }
            }
        }
    },
    "response_json_schema": {
        "type": "object"
    }
}
```

## Built-in Tool Inventory

### Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| Search & Retrieval | 6 | Google Search, Vertex AI Search, Discovery Engine, Enterprise Search |
| Database | 15 | BigQuery, Bigtable, Spanner (metadata, query, insights) |
| Integration | 8 | OpenAPI, Google APIs, API Hub, Application Integration, MCP |
| Agent Orchestration | 4 | AgentTool, TransferToAgentTool, ExitLoopTool, SetModelResponseTool |
| Memory & Artifacts | 4 | LoadMemoryTool, PreloadMemoryTool, LoadArtifactsTool, URLContextTool |
| Authentication | 2 | AuthenticatedFunctionTool, BaseAuthenticatedTool |
| Human-in-the-Loop | 2 | ToolConfirmation, GetUserChoiceTool |
| Messaging | 2 | PubSub message/subscription tools |
| Computer Use | 1 | Computer interaction toolset |
| Adapters | 3 | LangchainTool, CrewaiTool, GoogleTool |
| Grounding | 1 | GoogleMapsGroundingTool |
| Examples | 1 | ExampleTool (template) |

### Complete Tool List (Representative Sample)

| Tool Name | Location | Schema Method | Category |
|-----------|----------|---------------|----------|
| FunctionTool | tools/function_tool.py | Pydantic introspection | Core |
| GoogleSearchTool | tools/google_search_tool.py | Built-in (no schema) | Search |
| VertexAiSearchTool | tools/vertex_ai_search_tool.py | Manual FunctionDeclaration | Search |
| DiscoveryEngineSearchTool | tools/discovery_engine_search_tool.py | Manual | Search |
| EnterpriseWebSearchTool | tools/enterprise_search_tool.py | Manual | Search |
| BigQueryToolset | tools/bigquery/bigquery_toolset.py | Dynamic toolset | Database |
| get_dataset_info | tools/bigquery/metadata_tool.py | Pydantic introspection | Database |
| get_table_info | tools/bigquery/metadata_tool.py | Pydantic introspection | Database |
| execute_sql | tools/bigquery/query_tool.py | Pydantic introspection | Database |
| ask_data_insights | tools/bigquery/data_insights_tool.py | Pydantic introspection | Database |
| BigtableToolset | tools/bigtable/bigtable_toolset.py | Dynamic toolset | Database |
| SpannerToolset | tools/spanner/spanner_toolset.py | Dynamic toolset | Database |
| OpenAPIToolset | tools/openapi_tool/openapi_spec_parser/openapi_toolset.py | OpenAPI spec parsing | Integration |
| RestApiTool | tools/openapi_tool/openapi_spec_parser/rest_api_tool.py | OpenAPI derived | Integration |
| GoogleAPIToolset | tools/google_api_tool/google_api_toolset.py | Discovery doc parsing | Integration |
| APIHubToolset | tools/apihub_tool/apihub_toolset.py | API registry | Integration |
| MCPToolset | tools/mcp_tool/mcp_toolset.py | MCP protocol | Integration |
| AgentTool | tools/agent_tool.py | Agent as tool | Orchestration |
| TransferToAgentTool | tools/transfer_to_agent_tool.py | Manual | Orchestration |
| ExitLoopTool | tools/exit_loop_tool.py | Manual | Orchestration |
| LoadMemoryTool | tools/load_memory_tool.py | Manual | Memory |
| PreloadMemoryTool | tools/preload_memory_tool.py | Manual | Memory |
| LoadArtifactsTool | tools/load_artifacts_tool.py | Manual | Artifacts |
| LangchainTool | tools/langchain_tool.py | Adapter pattern | Adapter |
| CrewaiTool | tools/crewai_tool.py | Adapter pattern | Adapter |
| AuthenticatedFunctionTool | tools/authenticated_function_tool.py | Pydantic + auth | Auth |
| ComputerUseToolset | tools/computer_use/computer_use_toolset.py | Anthropic-style | Computer |
| PubSubToolset | tools/pubsub/pubsub_toolset.py | Dynamic toolset | Messaging |
| GoogleMapsGroundingTool | tools/google_maps_grounding_tool.py | Built-in (no schema) | Grounding |

### Built-in Tool Count

**Total**: 40+ individual tools across 12 toolsets

**Breakdown**:
- Direct tools: 25+
- Toolset-generated tools: 15+ (BigQuery: 9, Bigtable: 3, Spanner: 5, etc.)
- Adapter tools: 3 (Langchain, CrewAI, Google API)

## Registration & Discovery

### Pattern

**Declarative registration** with automatic FunctionTool wrapping:

```python
# From: contributing/samples/pydantic_argument/agent.py
root_agent = Agent(
    model="gemini-2.5-pro",
    tools=[
        FunctionTool(create_full_user_account),  # Explicit wrapper
        FunctionTool(create_entity_profile),     # Explicit wrapper
    ],
)

# From: contributing/samples/built_in_multi_tools/agent.py
root_agent = Agent(
    tools=[
        roll_die,  # Plain function (auto-wrapped)
        VertexAiSearchTool(...),  # Tool instance
        GoogleSearchTool(...),    # Tool instance
    ],
)
```

### Registration Flow

```
1. Agent.__init__(tools=[...])
   ↓
2. For each tool in list:
   - If Callable (plain function) → wrap in FunctionTool
   - If BaseTool instance → use directly
   - If BaseToolset instance → call get_tools() at runtime
   ↓
3. Store in agent.tools list
   ↓
4. On LLM request:
   - Call tool.process_llm_request() for each tool
   - Tool adds its FunctionDeclaration to request.config.tools
   ↓
5. LLM receives all tool schemas in request
```

### Toolset Dynamic Discovery

```python
# From: src/google/adk/tools/base_toolset.py
class BaseToolset(ABC):
    @abstractmethod
    async def get_tools(
        self,
        readonly_context: Optional[ReadonlyContext] = None,
    ) -> list[BaseTool]:
        """Return tools based on context (dynamic filtering)."""
        pass

# Example: BigQuery toolset with filtering
# From: src/google/adk/tools/bigquery/bigquery_toolset.py
class BigQueryToolset(BaseToolset):
    async def get_tools(
        self, readonly_context: Optional[ReadonlyContext] = None
    ) -> List[BaseTool]:
        all_tools = [
            GoogleTool(func=func, credentials_config=...)
            for func in [
                metadata_tool.get_dataset_info,
                metadata_tool.get_table_info,
                query_tool.execute_sql,
                # ... 9 total tools
            ]
        ]
        return [
            tool for tool in all_tools
            if self._is_tool_selected(tool, readonly_context)
        ]
```

**Tool Filtering**:
- `tool_filter: List[str]` - Whitelist by tool name
- `tool_filter: ToolPredicate` - Custom callable predicate
- `tool_name_prefix: str` - Namespace isolation

## Execution Flow

### Invocation Pattern

```python
# From: src/google/adk/tools/function_tool.py
async def run_async(
    self, *, args: dict[str, Any], tool_context: ToolContext
) -> Any:
    # 1. Preprocess arguments (Pydantic conversion)
    args_to_call = self._preprocess_args(args)

    # 2. Inject tool_context if function signature requires it
    signature = inspect.signature(self.func)
    if 'tool_context' in signature.parameters:
        args_to_call['tool_context'] = tool_context

    # 3. Filter to valid parameters only
    valid_params = {param for param in signature.parameters}
    args_to_call = {k: v for k, v in args_to_call.items() if k in valid_params}

    # 4. Validate mandatory parameters
    mandatory_args = self._get_mandatory_args()
    missing_mandatory_args = [
        arg for arg in mandatory_args if arg not in args_to_call
    ]

    if missing_mandatory_args:
        error_str = f"""Invoking `{self.name}()` failed as the following mandatory input parameters are not present:
{chr(10).join(missing_mandatory_args)}
You could retry calling this tool, but it is IMPORTANT for you to provide all the mandatory parameters."""
        return {'error': error_str}

    # 5. Human-in-the-loop confirmation check
    if require_confirmation:
        if not tool_context.tool_confirmation:
            tool_context.request_confirmation(hint=...)
            tool_context.actions.skip_summarization = True
            return {
                'error': 'This tool call requires confirmation, please approve or reject.'
            }
        elif not tool_context.tool_confirmation.confirmed:
            return {'error': 'This tool call is rejected.'}

    # 6. Execute function (sync or async)
    return await self._invoke_callable(self.func, args_to_call)
```

### Pydantic Model Conversion

```python
# From: src/google/adk/tools/function_tool.py
def _preprocess_args(self, args: dict[str, Any]) -> dict[str, Any]:
    """Preprocess and convert function arguments before invocation.

    Handles:
    - Converting JSON dictionaries to Pydantic model instances
    - Optional[PydanticModel] unwrapping
    """
    signature = inspect.signature(self.func)
    converted_args = args.copy()

    for param_name, param in signature.parameters.items():
        if param_name in args and param.annotation != inspect.Parameter.empty:
            target_type = param.annotation

            # Handle Optional[PydanticModel] types
            if get_origin(param.annotation) is Union:
                union_args = get_args(param.annotation)
                non_none_types = [arg for arg in union_args if arg is not type(None)]
                if len(non_none_types) == 1:
                    target_type = non_none_types[0]

            # Convert to Pydantic model if needed
            if inspect.isclass(target_type) and issubclass(
                target_type, pydantic.BaseModel
            ):
                if args[param_name] is None:
                    continue

                if not isinstance(args[param_name], target_type):
                    try:
                        converted_args[param_name] = target_type.model_validate(
                            args[param_name]
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to convert argument '{param_name}': {e}"
                        )

    return converted_args
```

### Error Handling

| Error Type | Handling | Feedback to LLM |
|------------|----------|-----------------|
| Missing mandatory params | Pre-execution validation | `{'error': 'Invoking \`tool()\` failed... provide all mandatory parameters'}` |
| Pydantic validation failure | Logged warning, original value kept | Function receives raw value (may fail) |
| Tool confirmation rejected | Return error before execution | `{'error': 'This tool call is rejected.'}` |
| Tool confirmation pending | Return error, request confirmation | `{'error': 'This tool call requires confirmation...'}` |
| Function execution exception | Propagates to agent (not caught) | Exception becomes LLM context |
| Invalid parameter type | Pydantic validation at boundary | Schema mismatch prevents LLM from generating |

**Error Response Pattern**:
```python
# Consistent error dictionary structure
{
    "error": "Human-readable error message for LLM to understand and retry"
}
```

### Retry Mechanisms

**Built-in retry**: None at tool level (agent-level retry not examined)

**Self-correction via LLM feedback**:
- Missing parameters → LLM receives error message → retries with complete args
- Confirmation rejected → LLM receives rejection → may ask user or try alternative

### Tool Context Injection

```python
# From: src/google/adk/tools/tool_context.py
class ToolContext(CallbackContext):
    """The context of the tool.

    Provides access to:
    - invocation_context: Agent execution context
    - function_call_id: Unique identifier for this tool call
    - event_actions: Side effects (skip_summarization, etc.)
    - tool_confirmation: HITL approval state
    """

    def request_credential(self, auth_config: AuthConfig) -> None:
        """Request OAuth/API credentials via EUC protocol."""
        pass

    def get_auth_response(self, auth_config: AuthConfig) -> AuthCredential:
        """Retrieve user-provided credentials."""
        pass

    def request_confirmation(
        self, *, hint: Optional[str] = None, payload: Optional[Any] = None
    ) -> None:
        """Request HITL approval for tool execution."""
        pass

    async def search_memory(self, query: str) -> SearchMemoryResponse:
        """Search agent's long-term memory."""
        pass
```

## Parallel Execution

**Supported**: Yes, via async/await pattern

**Implementation**: Tools are executed concurrently when LLM requests multiple tool calls in a single turn.

```python
# From: src/google/adk/tools/function_tool.py
async def _invoke_callable(
    self, target: Callable[..., Any], args_to_call: dict[str, Any]
) -> Any:
    """Invokes a callable, handling both sync and async cases."""

    # Check if callable is async
    is_async = inspect.iscoroutinefunction(target) or (
        hasattr(target, '__call__')
        and inspect.iscoroutinefunction(target.__call__)
    )

    if is_async:
        return await target(**args_to_call)  # Await async tools
    else:
        return target(**args_to_call)  # Execute sync tools
```

**Concurrency Pattern**:
- Agent receives multiple FunctionCall requests from LLM
- Creates tasks for each tool via `asyncio.gather()` or similar
- Tools execute concurrently (if async) or in event loop (if sync)
- Results collected and sent back to LLM together

**Note**: Actual parallel execution code likely resides in agent executor (not examined in detail).

## Code References

### Core Files

- `src/google/adk/tools/base_tool.py:47-213` - BaseTool abstract class
- `src/google/adk/tools/function_tool.py:38-286` - FunctionTool wrapper
- `src/google/adk/tools/_function_tool_declarations.py:164-231` - Pydantic schema builder
- `src/google/adk/tools/_automatic_function_calling_util.py:197-468` - Legacy schema builder
- `src/google/adk/tools/base_toolset.py:62-207` - Toolset abstraction
- `src/google/adk/tools/tool_context.py:33-107` - Tool execution context
- `src/google/adk/tools/tool_confirmation.py:28-46` - HITL confirmation model

### Built-in Tools

- `src/google/adk/tools/google_search_tool.py` - Built-in Google Search
- `src/google/adk/tools/vertex_ai_search_tool.py` - Vertex AI Search
- `src/google/adk/tools/bigquery/bigquery_toolset.py:38-102` - BigQuery toolset
- `src/google/adk/tools/openapi_tool/openapi_spec_parser/openapi_toolset.py:43-100` - OpenAPI toolset
- `src/google/adk/tools/langchain_tool.py:32-181` - LangChain adapter
- `src/google/adk/tools/crewai_tool.py:38-159` - CrewAI adapter

### Sample Implementations

- `contributing/samples/pydantic_argument/agent.py:50-183` - Pydantic model arguments
- `contributing/samples/built_in_multi_tools/agent.py:31-66` - Multi-tool agent
- `contributing/samples/adk_answering_agent/tools.py:27-231` - GitHub integration tools

## Implications for New Framework

### Positive Patterns

1. **Automatic Function Wrapping**: Zero-boilerplate tool creation - plain functions become tools automatically
   - **Adoption**: Use `@tool` decorator or auto-detection in Agent constructor
   - **Benefit**: Developers don't need to subclass or write adapters for simple tools

2. **Pydantic Schema Generation**: Leverage existing type validation library instead of custom JSON Schema builders
   - **Adoption**: Use `pydantic.TypeAdapter` + `model_json_schema()` for all schema generation
   - **Benefit**: Consistent validation, automatic nested model support, excellent IDE integration

3. **Tool Context Injection**: Provide rich execution context (state, auth, memory) via reserved parameter
   - **Adoption**: Inject `tool_context: ToolContext` automatically if function signature includes it
   - **Benefit**: Tools can access agent state, request auth, etc. without globals or singletons

4. **Toolset Abstraction**: Group related tools with dynamic filtering based on runtime context
   - **Adoption**: Implement `BaseToolset` protocol for DB integrations (BigQuery-style)
   - **Benefit**: Expose 10+ tools from a single import, enable/disable based on permissions

5. **Human-in-the-Loop Protocol**: First-class confirmation workflow via `request_confirmation()`
   - **Adoption**: Add `require_confirmation` parameter to tool definitions
   - **Benefit**: Built-in approval gates for sensitive operations (delete, send email, etc.)

6. **Adapter Pattern**: Seamless integration with LangChain/CrewAI tools via wrapper classes
   - **Adoption**: Create `LangchainTool`, `CrewaiTool` adapters for ecosystem compatibility
   - **Benefit**: Tap into existing tool ecosystems without reimplementation

7. **Error Dictionary Pattern**: Consistent `{'error': 'message'}` return value for LLM feedback
   - **Adoption**: Standardize on this pattern for all tool errors
   - **Benefit**: LLM can self-correct via natural language error messages

8. **Long-running Tool Flag**: Explicit `is_long_running` attribute for async operations
   - **Adoption**: Use this pattern for tools that return job IDs before completion
   - **Benefit**: Agent can poll or wait for results appropriately

### Considerations

1. **No Explicit Retry Logic**: Tools don't handle retries internally - relies on LLM self-correction
   - **Decision**: Implement exponential backoff at agent level, not tool level
   - **Rationale**: Keep tools simple, let orchestrator handle retry policy

2. **Schema Generation Complexity**: Two code paths (new Pydantic vs legacy manual) create maintenance burden
   - **Decision**: Choose one approach (Pydantic) and deprecate legacy path
   - **Rationale**: Pydantic is more maintainable and leverages community-tested code

3. **Sync/Async Mixing**: Tools can be sync or async, framework handles both
   - **Decision**: Strongly prefer async-only in new framework for simplicity
   - **Rationale**: Sync functions block event loop, harder to reason about concurrency

4. **Tool Confirmation State Management**: Requires round-trip to user, complex state tracking
   - **Decision**: Implement as agent plugin rather than core tool feature
   - **Rationale**: HITL is not needed for most tools, should be opt-in

5. **BaseTool as ABC not Protocol**: Inheritance-based design limits flexibility
   - **Decision**: Use Protocol (structural typing) instead of ABC in new framework
   - **Rationale**: Tools from external libs can satisfy interface without inheritance

6. **No Built-in Sandbox**: Tools execute with full process permissions
   - **Decision**: Add optional sandboxing layer (Docker, gVisor, etc.)
   - **Rationale**: Security-critical for user-provided tools or untrusted code execution

7. **OpenAPI Toolset Complexity**: 100+ LOC just for parsing OpenAPI specs
   - **Decision**: Keep but simplify - focus on common OpenAPI patterns
   - **Rationale**: OpenAPI integration is table stakes, but can be more opinionated

## Anti-Patterns Observed

1. **Dual Schema Generation Paths**: Pydantic-based (new) + manual parsing (legacy) coexist
   - **Issue**: Code duplication, feature flag complexity, harder to test
   - **Fix**: Deprecate legacy path, migrate all tools to Pydantic schemas

2. **Ignored Parameters List**: `_ignore_params = ['tool_context', 'input_stream']` is fragile
   - **Issue**: Magic strings, easy to forget when adding new reserved params
   - **Fix**: Use function signature inspection to auto-detect reserved params

3. **Silent Pydantic Conversion Failures**: Logs warning but passes unconverted value
   - **Issue**: Function may receive dict instead of Pydantic model, fails at runtime
   - **Fix**: Return error dict immediately on conversion failure, let LLM retry

4. **Error Handling Inconsistency**: Some tools return `{'error': ...}`, others raise exceptions
   - **Issue**: Agent must handle both patterns, LLM feedback is inconsistent
   - **Fix**: Standardize on error dict pattern, catch exceptions at agent boundary

5. **Tool Name Collision Risk**: No namespace enforcement, `tool_name_prefix` is optional
   - **Issue**: Two toolsets with same tool name will conflict
   - **Fix**: Enforce namespacing via toolset prefix, or use fully qualified names

6. **Built-in Tool Special Cases**: GoogleSearch bypasses normal tool registration
   - **Issue**: Inconsistent tool lifecycle, harder to test/mock
   - **Fix**: Make built-in tools follow same interface as custom tools

7. **Heavy Use of Optional**: Many parameters are `Optional[T]` with `None` defaults
   - **Issue**: LLM may omit important parameters, unclear which are truly optional
   - **Fix**: Use explicit defaults (`default="value"`) instead of `Optional` where possible

8. **No Tool Versioning**: Tool schemas can change without version tracking
   - **Issue**: Breaking changes affect deployed agents, hard to roll back
   - **Fix**: Add `version` field to tool metadata, support multiple versions

9. **Toolset Filtering Complexity**: Three filter types (list, predicate, None) with different semantics
   - **Issue**: Confusing API, easy to misconfigure
   - **Fix**: Simplify to single filter type (predicate) or use builder pattern

10. **Missing Parameter Descriptions**: Schema generation ignores docstring parameter docs
    - **Issue**: LLM doesn't understand parameter purpose, makes poor choices
    - **Fix**: Parse Google-style or Numpy-style docstrings to extract param descriptions
