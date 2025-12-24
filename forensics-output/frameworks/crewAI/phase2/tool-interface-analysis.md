# Tool Interface Analysis: crewAI

## Summary
- **Tool Definition**: Decorator-based (@tool) or class inheritance (BaseTool)
- **Schema Generation**: Automatic via function introspection or manual Pydantic schema
- **Error Feedback**: Tool errors returned to LLM for self-correction
- **Tool Usage Tracking**: Per-tool usage counts and limits

## Detailed Analysis

### Tool Definition Methods

**Method 1: Decorator** (base_tool.py - implied):
```python
@tool
def search_web(query: str, limit: int = 10) -> list[str]:
    \"\"\"Search the web for information.\"\"\"
    return results
```
- Function signature → automatic Pydantic schema
- Docstring → tool description
- Type hints → argument validation

**Method 2: Class Inheritance** (base_tool.py:L54):
```python
class BaseTool(BaseModel, ABC):
    name: str = Field(description="Unique name...")
    description: str = Field(description="How/when/why to use...")
    args_schema: type[PydanticBaseModel] = Field(default=_ArgsSchemaPlaceholder)

    @abstractmethod
    def _run(self, **kwargs) -> Any:
        pass
```

**Tool Registration**:
- Agent.tools: `list[Any]` (agent/core.py, base_agent.py:L74)
- Parsed via `parse_tools()` utility (agent/core.py:L68)
- Converted to `CrewStructuredTool` for execution

**MCP Tools** (agent/core.py:L50-60):
```python
mcps: list[MCPServerConfig] | None = Field(default=None)
# Model Context Protocol - dynamic tool discovery
```
- Tools loaded from external MCP servers
- HTTP, SSE, stdio transports supported

### Schema Generation

**Approach**: **Reflection + Manual**

**Automatic (Decorator)**:
- Uses `inspect.signature()` to extract parameters (base_tool.py:L6)
- Type hints → Pydantic field types
- Default values preserved
- Example: `query: str` → `{"type": "string"}` in JSON schema

**Manual (Class)**:
```python
class CustomTool(BaseTool):
    args_schema: type[PydanticBaseModel] = CustomArgsModel

    def _run(self, **kwargs) -> Any:
        validated_args = self.args_schema(**kwargs)
```

**Schema Access**:
- `BaseTool.args_schema` - Pydantic model for arguments
- Auto-generated or explicitly provided
- Validated before tool execution

**Description Generation** (base_tool.py:L28):
```python
from crewai.utilities.pydantic_schema_utils import generate_model_description
```
- Extracts descriptions from Pydantic field metadata
- Formats for LLM consumption

### Error Feedback Loop

**Tool Error Handling** (crew_agent_executor.py:L279):
```python
except OutputParserError as e:
    formatted_answer = handle_output_parser_exception(
        e=e, printer=self._printer, i18n=self._i18n,
        messages=self.messages, llm=self.llm, callbacks=self.callbacks
    )
    # Error message fed back to LLM
```

**Self-Correction Flow**:
1. Tool execution fails (invalid args, runtime error)
2. Error converted to observation message
3. Appended to message history
4. LLM receives error in next iteration
5. LLM can retry with corrected arguments

**Tool Result** (crew_agent_executor.py:L47-49):
```python
from crewai.utilities.tool_utils import execute_tool_and_check_finality
# Returns ToolResult with success/error status
```

**Feedback Format**:
- Error observations likely formatted as:
  - "Tool 'search_web' failed: Invalid argument 'limit': must be positive"
- LLM prompted to analyze error and retry

### Tools Found in Codebase

**AgentTools** (crew.py:L82, agent/core.py:L64):
```python
from crewai.tools.agent_tools.agent_tools import AgentTools
```
- Delegation tools (ask_question, delegate_work)
- Auto-generated for multi-agent coordination

**Platform Tools** (base_agent.py:L95):
```python
apps: list[PlatformAppOrAction] | None = None
# Enterprise app integrations: Slack, GitHub, Gmail, etc.
```

**CodeInterpreterTool** (agent/core.py:L81):
```python
from crewai_tools import CodeInterpreterTool
```
- Code execution capability (separate package)

**Tool Handler** (base_agent.py:L81):
```python
tools_handler: ToolsHandler
# Manages tool lifecycle and caching
```

### Tool Lifecycle

**Preparation** (agent/core.py:L29):
```python
from crewai.agent.utils import prepare_tools
# Converts tools to executable format
```

**Caching** (base_tool.py:L80-83):
```python
cache_function: Callable[..., bool] = Field(
    default=lambda _args=None, _result=None: True,
    description="Determine if tool should be cached..."
)
```

**Usage Limits** (base_tool.py:L88-95):
```python
max_usage_count: int | None = Field(default=None)
current_usage_count: int = Field(default=0)
```
- Enforced before tool execution
- Prevents runaway tool costs

**Result Finality** (base_tool.py:L84-87):
```python
result_as_answer: bool = Field(
    default=False,
    description="Flag if tool should be final agent answer"
)
```
- Allows tool result to terminate agent loop immediately

### Environment Variables

**Tool Env Vars** (base_tool.py:L47-51):
```python
class EnvVar(BaseModel):
    name: str
    description: str
    required: bool = True
    default: str | None = None

env_vars: list[EnvVar] = Field(default_factory=list)
```
- Declarative env var requirements
- Validated before tool execution

## Implications for New Framework

**Adopt**:
1. **Decorator-based tool creation** - low ceremony, ergonomic
2. **Automatic schema generation** - reduces boilerplate
3. **Error feedback to LLM** - enables self-correction
4. **Usage limits per tool** - prevents cost overruns
5. **Result-as-answer flag** - early termination for definitive results
6. **Declarative env vars** - clear dependencies, validation
7. **MCP integration** - dynamic tool discovery

**Avoid**:
1. **String-or-function-or-class tools** (`list[Any]`) - defeats type checking
2. **Manual schema for simple tools** - unnecessary boilerplate
3. **Global tool registry** - prefer explicit dependency injection

**Improve**:
1. Type tool lists properly: `tools: list[BaseTool]` instead of `list[Any]`
2. Add tool versioning for compatibility
3. Implement tool namespaces to avoid name collisions
4. Add structured error types instead of string messages
5. Support async tools natively (separate _arun method)
6. Add tool composition (pipelines)
7. Implement tool marketplace/discovery

## Code References

- BaseTool: `lib/crewai/src/crewai/tools/base_tool.py:L54`
- Tool decorator: `lib/crewai/src/crewai/tools/base_tool.py` (imports)
- Schema generation: `lib/crewai/src/crewai/utilities/pydantic_schema_utils.py` (referenced)
- Tool execution: `lib/crewai/src/crewai/utilities/tool_utils.py` (execute_tool_and_check_finality)
- Error handling: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L279`
- Tool preparation: `lib/crewai/src/crewai/agent/utils.py` (prepare_tools)
- MCP integration: `lib/crewai/src/crewai/agent/core.py:L50-60`
- AgentTools: `lib/crewai/src/crewai/tools/agent_tools/agent_tools.py`
- EnvVar: `lib/crewai/src/crewai/tools/base_tool.py:L47`

## Anti-Patterns Observed

1. **Untyped tool lists**: `tools: list[Any]` - no compile-time validation
2. **Mixed tool types**: Strings, functions, classes all accepted - runtime parsing required
3. **No tool versioning**: Breaking changes to tools could fail silently
4. **Global tool names**: No namespacing, risk of collisions
5. **Synchronous-only**: No native async tool support (bolt-on via wrappers)
