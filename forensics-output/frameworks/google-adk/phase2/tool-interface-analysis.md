# Tool Interface Analysis: Google ADK

## Summary
- **Key Finding 1**: Decorator-based tool creation with automatic schema generation from type hints
- **Key Finding 2**: Native Gemini FunctionDeclaration format (OpenAPI-like)
- **Classification**: Type-introspection with first-class HITL and auth flows

## Detailed Analysis

### Tool Definition Methods

**1. Function Decorator** (Recommended):
```python
from google.adk.tools import function_tool

@function_tool(
    name="search",
    description="Search the web"
)
async def search_web(query: str) -> str:
    """Search for information on the web.

    Args:
        query: The search query

    Returns:
        Search results
    """
    # Implementation
```

**Schema Generation**: Automatic from:
- Function signature (type hints)
- Docstring (parameter descriptions)
- Pydantic models (if used as parameters)

**2. Subclass BaseTool**:
```python
class CustomTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="custom",
            description="Custom tool"
        )

    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters={"type": "object", "properties": {...}}
        )

    async def run_async(self, args: dict, tool_context: ToolContext) -> Any:
        # Implementation
```

**3. Adapter Patterns**:
- `LangChainTool` - Wraps LangChain tools
- `CrewAITool` - Wraps CrewAI tools
- `MCPTool` - Model Context Protocol integration
- `OpenAPITool` - Auto-generated from OpenAPI specs

### Schema Generation

**FunctionDeclaration Format**:
```python
FunctionDeclaration(
    name="tool_name",
    description="Tool description",
    parameters={
        "type": "object",
        "properties": {
            "arg1": {"type": "string", "description": "..."},
            "arg2": {"type": "integer", "description": "..."}
        },
        "required": ["arg1"]
    }
)
```

**Automatic Conversion**:
- Python type hints → JSON Schema types
- Pydantic models → nested object schemas
- Docstrings → parameter descriptions
- Optional[] → non-required parameters

**Special Types**:
- `Annotated[T, Field(description="...")]` - Add descriptions
- `Union[T1, T2]` - anyOf schema
- `list[T]` - array schema
- Pydantic BaseModel - nested object

### Error Handling in Tools

**Tool Execution Error**:
```python
async def run_async(self, args: dict, tool_context: ToolContext) -> Any:
    try:
        result = await do_work(args)
        return result
    except Exception as e:
        # Framework captures exception
        # Returns error in function_response
        raise
```

**Error Propagation**:
- Exceptions serialized to function_response
- LLM sees error message and can retry
- No automatic retry by framework

### Human-in-the-Loop (HITL)

**Tool Confirmation**:
```python
async def run_async(self, args: dict, tool_context: ToolContext) -> Any:
    # Request confirmation
    return ToolConfirmation(
        message="Are you sure you want to delete the file?",
        args=args
    )
```

**Flow**:
1. Tool returns ToolConfirmation
2. Framework generates `adk_request_confirmation` function call
3. User approves/denies
4. Tool execution resumes or cancels

### Authentication Flow (EUC)

**Credential Request**:
```python
async def run_async(self, args: dict, tool_context: ToolContext) -> Any:
    # Request auth if needed
    if not tool_context.credential:
        return RequestAuth(auth_config=AuthConfig(...))

    # Use credential
    api_call(credential=tool_context.credential)
```

**Flow**:
1. Tool requests auth via RequestAuth
2. Framework generates `adk_request_credential` function call
3. User provides credential
4. Tool execution retries with credential

### ToolContext

**Context Available to Tools**:
```python
ToolContext(
    session: Session,              # Access session state
    artifact_service: ArtifactService,  # Save/load files
    credential_service: CredentialService,  # Auth
    invocation_context: InvocationContext,  # Full context
    session_service: SessionService,        # Session management
)
```

**Capabilities**:
- Read/write session state
- Save/load artifacts (files)
- Access agent state
- Modify conversation history

### Tool Registration

**Static Registration**:
```python
LlmAgent(
    name="agent",
    tools=[tool1, tool2, @function_tool decorated functions]
)
```

**Dynamic Registration**:
```python
# Via ToolboxToolset
toolbox = ToolboxToolset(tools=[...])
agent = LlmAgent(name="agent", tools=[toolbox])
```

**Toolset Pattern**:
```python
class BigQueryToolset(BaseToolset):
    def get_tools(self) -> list[BaseTool]:
        return [
            BigQueryMetadataTool(),
            BigQueryQueryTool(),
            BigQueryDataInsightsTool()
        ]
```

### Integration Patterns

**OpenAPI Integration**:
- Auto-generate tools from OpenAPI spec
- Maps paths → tools
- Maps parameters → function args

**MCP Integration**:
- Model Context Protocol support
- MCPTool wraps MCP servers
- Supports stdio, SSE, HTTP transports

**LangChain/CrewAI Integration**:
- Adapters wrap external tools
- Preserves tool metadata
- Async execution support

## Implications for New Framework

### Positive Patterns
- **Decorator ergonomics**: @function_tool is simple and intuitive
- **Automatic schema**: Type introspection reduces boilerplate
- **HITL first-class**: Tool confirmation built into framework
- **Auth flow**: EUC pattern handles OAuth/API keys elegantly
- **Adapter pattern**: Easy integration with other frameworks

### Considerations
- **No streaming tools**: Tools must return complete results (no AsyncGenerator)
- **Sequential execution**: No parallel tool execution
- **No timeout**: Long-running tools can block indefinitely
- **Error handling**: Framework captures but doesn't retry

## Code References
- `tools/base_tool.py:47` - BaseTool ABC
- `tools/base_tool.py:81` - _get_declaration() for schema generation
- `tools/_function_tool_declarations.py` - @function_tool decorator
- `tools/tool_context.py` - ToolContext data structure
- `tools/tool_confirmation.py` - HITL confirmation pattern
- `tools/base_authenticated_tool.py` - Auth flow pattern
- `tools/langchain_tool.py` - LangChain adapter
- `tools/base_toolset.py` - Toolset grouping pattern
- `tools/google_api_tool/google_api_tool.py` - OpenAPI integration

## Anti-Patterns Observed
- **No validation**: Function args not validated before tool execution (trust LLM)
- **No rate limiting**: Tools can be called unlimited times
- **No cost tracking**: No mechanism to track tool usage/costs
- **No caching**: Tool results not cached (duplicate calls waste resources)
