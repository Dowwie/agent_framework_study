# Tool Interface Analysis: LlamaIndex

## Summary
- **Key Finding 1**: Dual tool definition - manual via ToolMetadata or automatic via FunctionTool.from_defaults()
- **Key Finding 2**: Pydantic schema generation for OpenAI function calling via model_json_schema()
- **Key Finding 3**: Error feedback via ToolOutput.is_error flag, enabling LLM self-correction
- **Classification**: Reflection-based schema generation with error-as-data pattern

## Detailed Analysis

### Tool Definition

**Methods**: Class-based (BaseTool) or function-based (FunctionTool)

**Class-Based** (tools/types.py:L155-214):
```python
class BaseTool(DispatcherSpanMixin):
    @property
    @abstractmethod
    def metadata(self) -> ToolMetadata:
        pass

    @abstractmethod
    def __call__(self, input: Any) -> ToolOutput:
        pass
```

**Function-Based** (via FunctionTool):
```python
@tool  # Decorator (hypothetical - actual is FunctionTool.from_defaults)
def search(query: str) -> str:
    '''Search the web for information.'''
    # implementation
    return results
```

**Auto-Conversion** (base_agent.py:L172-198):
```python
@field_validator("tools", mode="before")
def validate_tools(cls, v: Optional[Sequence[Union[BaseTool, Callable]]]):
    validated_tools: List[BaseTool] = []
    for tool in v:
        if not isinstance(tool, BaseTool):
            validated_tools.append(FunctionTool.from_defaults(tool))  # Auto-wrap
        else:
            validated_tools.append(tool)
    return validated_tools
```

Any callable is automatically wrapped in FunctionTool, reducing friction.

### Tool Metadata

**ToolMetadata dataclass** (tools/types.py:L22-90):
```python
@dataclass
class ToolMetadata:
    description: str
    name: Optional[str] = None
    fn_schema: Optional[Type[BaseModel]] = DefaultToolFnSchema
    return_direct: bool = False
```

**Fields**:
- `description`: Human-readable description (shown to LLM)
- `name`: Tool identifier (defaults to function name)
- `fn_schema`: Pydantic model defining parameters
- `return_direct`: If True, return tool output as final answer (no LLM processing)

### Schema Generation

**Approach**: Reflection on Pydantic models

**OpenAI Tool Schema** (tools/types.py:L76-90):
```python
def to_openai_tool(self, skip_length_check: bool = False) -> Dict[str, Any]:
    if not skip_length_check and len(self.description) > 1024:
        raise ValueError("Tool description exceeds maximum length of 1024 characters.")

    return {
        "type": "function",
        "function": {
            "name": self.name,
            "description": self.description,
            "parameters": self.get_parameters_dict(),
        },
    }
```

**Parameter Schema Generation** (tools/types.py:L29-45):
```python
def get_parameters_dict(self) -> dict:
    if self.fn_schema is None:
        parameters = {
            "type": "object",
            "properties": {
                "input": {"title": "input query string", "type": "string"},
            },
            "required": ["input"],
        }
    else:
        parameters = self.fn_schema.model_json_schema()  # Pydantic V2
        parameters = {
            k: v
            for k, v in parameters.items()
            if k in ["type", "properties", "required", "definitions", "$defs"]
        }
    return parameters
```

**How It Works**:
1. Define Pydantic model with tool parameters
2. Pydantic generates JSON Schema via `model_json_schema()`
3. Filter to OpenAI-compatible fields
4. Return as dict

**Example**:
```python
class SearchInput(BaseModel):
    query: str = Field(description="The search query")
    limit: int = Field(default=10, description="Max results")

metadata = ToolMetadata(
    name="search",
    description="Search the web",
    fn_schema=SearchInput
)

# Generates:
{
    "type": "function",
    "function": {
        "name": "search",
        "description": "Search the web",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "limit": {"type": "integer", "default": 10, "description": "Max results"}
            },
            "required": ["query"]
        }
    }
}
```

### Error Feedback Mechanism

**ToolOutput with Error State** (tools/types.py:L93-153):
```python
class ToolOutput(BaseModel):
    blocks: List[ContentBlock]
    tool_name: str
    raw_input: Dict[str, Any]
    raw_output: Any
    is_error: bool = False  # Error flag

    _exception: Optional[Exception] = PrivateAttr(default=None)

    @property
    def exception(self) -> Optional[Exception]:
        return self._exception
```

**Self-Correction Flow**:
1. Tool execution fails
2. Tool returns `ToolOutput(is_error=True, content=error_message)`
3. Error message added to reasoning as ObservationReasoningStep
4. LLM sees error in next prompt
5. LLM adjusts and retries (different tool or different input)

**Example**:
```
Agent: Action: search, Action Input: {"query": "weather"}
Tool: ToolOutput(is_error=True, content="API key not configured")
Agent: Observation: API key not configured
LLM: Thought: I cannot use search. I'll ask the user directly.
     Answer: I don't have access to weather data. Could you tell me your location?
```

**No Forced Retry**: Unlike traditional retry logic, the LLM decides whether to retry or use a different approach.

### Adapter Patterns

**LangChain Bridge** (tools/types.py:L185-213):
```python
def to_langchain_tool(self, **langchain_tool_kwargs: Any) -> "Tool":
    from llama_index.core.bridge.langchain import Tool

    langchain_tool_kwargs = self._process_langchain_tool_kwargs(langchain_tool_kwargs)
    return Tool.from_function(
        func=self.__call__,
        **langchain_tool_kwargs,
    )
```

Allows using LlamaIndex tools in LangChain agents.

**Async Adapter** (tools/types.py:L240-266):
```python
class BaseToolAsyncAdapter(AsyncBaseTool):
    def __init__(self, tool: BaseTool):
        self.base_tool = tool

    def call(self, input: Any) -> ToolOutput:
        return self.base_tool(input)

    async def acall(self, input: Any) -> ToolOutput:
        return await asyncio.to_thread(self.call, input)

def adapt_to_async_tool(tool: BaseTool) -> AsyncBaseTool:
    if isinstance(tool, AsyncBaseTool):
        return tool
    else:
        return BaseToolAsyncAdapter(tool)
```

Automatically wraps sync tools for async execution.

### Reserved Names and Validation

**Reserved Tool Name** (base_agent.py:L193-196):
```python
for tool in validated_tools:
    if tool.metadata.name == "handoff":
        raise ValueError("'handoff' is a reserved tool name. Please use a different name.")
```

"handoff" is reserved for multi-agent delegation (multi_agent_workflow.py).

**Description Length Limit** (tools/types.py:L78-81):
```python
if not skip_length_check and len(self.description) > 1024:
    raise ValueError("Tool description exceeds maximum length of 1024 characters.")
```

OpenAI enforces a 1024 character limit on tool descriptions.

## Code References

- `llama-index-core/llama_index/core/tools/types.py:22` — ToolMetadata dataclass
- `llama-index-core/llama_index/core/tools/types.py:93` — ToolOutput with is_error
- `llama-index-core/llama_index/core/tools/types.py:29` — Schema generation
- `llama-index-core/llama_index/core/tools/types.py:155` — BaseTool interface
- `llama-index-core/llama_index/core/tools/types.py:240` — Async adapter
- `llama-index-core/llama_index/core/agent/workflow/base_agent.py:172` — Auto-conversion validator

## Implications for New Framework

1. **Auto-conversion of callables**: The validator pattern (converting functions → FunctionTool) reduces friction. Users can pass plain functions and they "just work."

2. **Pydantic for schema generation**: Using Pydantic models for tool parameters provides type safety, validation, and automatic JSON Schema generation. No manual schema writing.

3. **Error-as-data pattern**: Returning `is_error=True` instead of raising exceptions enables LLM-driven error recovery without hand-coded retry logic.

4. **Adapter pattern for ecosystem bridges**: Providing `to_langchain_tool()` makes the framework interoperable rather than siloed.

5. **Async adapters for backward compatibility**: Wrapping sync tools with `asyncio.to_thread()` enables async workflows without forcing all tools to be async.

6. **Reserved names validation**: Validating at initialization (not runtime) prevents conflicts and provides clear error messages.

## Anti-Patterns Observed

1. **dataclass for ToolMetadata**: Using `@dataclass` instead of Pydantic means no validation, no JSON serialization support. Should be `BaseModel`.

2. **PrivateAttr for exceptions**: Storing exceptions in `_exception` means they're lost during serialization. Either make errors first-class or don't store exceptions.

3. **String-based tool names**: Using strings for tool identification is error-prone (typos). Consider typed identifiers or enums.

4. **No tool versioning**: Tools have no version field. If a tool's behavior changes, agents using old prompts will break.

5. **Description length check is optional**: `skip_length_check` parameter allows bypassing the OpenAI limit, leading to runtime errors during tool registration.

6. **No tool timeout configuration**: Tools run with no timeout. A long-running or hung tool blocks the agent indefinitely.

7. **Manual filtering of JSON Schema fields**: The `k in ["type", "properties", ...]` filtering is brittle. Should use Pydantic's JSON Schema export options.

## Recommendations

- Use Pydantic BaseModel for ToolMetadata (not dataclass)
- Add tool version field for schema evolution
- Enforce description length limit (remove skip_length_check)
- Add per-tool timeout configuration
- Make tool IDs typed (enum or literal) rather than strings
- Serialize exceptions properly (custom serializer)
- Add tool execution metrics (duration, success rate)
- Use Pydantic's JSON Schema configuration instead of manual filtering
