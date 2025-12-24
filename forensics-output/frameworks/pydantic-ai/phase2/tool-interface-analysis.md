# Tool Interface Analysis: pydantic-ai

## Summary

- **Schema Generation**: Automatic from function signatures + docstrings
- **Validation**: Pydantic TypeAdapter for argument validation
- **Error Feedback**: Structured validation errors sent to model
- **Classification**: **Auto-schema with rich validation feedback**

## Detailed Analysis

### Tool Definition Structure

```python
@dataclass(kw_only=True)
class ToolDefinition:
    name: str  # Tool function name
    description: str  # From docstring
    parameters_json_schema: ObjectJsonSchema  # Generated from signature
    outer_typed_dict_key: str | None = None  # For nested args
    strict: bool | None = None  # OpenAI strict mode support
```

### Schema Generation

**From function signature** + docstring:
```python
def generate_schema(
    func: Callable,
    docstring_format: DocstringFormat = 'auto'
) -> tuple[str, ObjectJsonSchema]:
    # 1. Parse docstring (Google/Numpy/Sphinx/auto-detect)
    # 2. Extract type hints from signature
    # 3. Generate JSON schema via Pydantic TypeAdapter
    # 4. Merge description from docstring into schema
```

**Supported docstring formats**:
- Google-style (default in examples)
- Numpy-style
- Sphinx-style
- Auto-detect

**Example**:
```python
def search_web(query: str, max_results: int = 10) -> list[str]:
    """Search the web for information.

    Args:
        query: The search query string
        max_results: Maximum number of results to return
    """
    ...

# Generates:
{
    "name": "search_web",
    "description": "Search the web for information.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query string"},
            "max_results": {"type": "integer", "default": 10, "description": "Maximum number of results to return"}
        },
        "required": ["query"]
    }
}
```

### Argument Validation

**Pydantic TypeAdapter**:
```python
@dataclass(kw_only=True)
class ToolsetTool:
    args_validator: SchemaValidator | SchemaValidatorProt

# Usage:
try:
    validated_args = tool.args_validator.validate_python(raw_args)
    result = await func(**validated_args)
except ValidationError as e:
    raise ToolRetryError(tool.tool_def.name, e)
```

**Error handling**:
```python
class ToolRetryError(Exception):
    def __init__(self, tool_name: str, validation_error: ValidationError):
        # Format errors for model feedback:
        error_messages = []
        for err in validation_error.errors():
            location = '.'.join(str(loc) for loc in err['loc'])
            error_messages.append(f'{location}: {err["msg"]}')

        message = f'Tool call validation failed for tool {tool_name!r}:\n' + '\n'.join(f'- {msg}' for msg in error_messages)
        super().__init__(message)
```

### Context-Aware Tools

**RunContext injection**:
```python
# Tool with context:
@agent.tool
async def get_user_data(ctx: RunContext[MyDeps], user_id: int) -> dict:
    db = ctx.deps.database
    return await db.fetch_user(user_id)

# Tool without context:
@agent.tool
def format_text(text: str) -> str:
    return text.upper()
```

**Auto-detection**:
```python
def _takes_ctx(func: Callable) -> bool:
    """Check if function's first parameter is RunContext."""
    sig = inspect.signature(func)
    first_param = next(iter(sig.parameters.values()), None)
    if first_param is None:
        return False
    # Check if annotated with RunContext[...]
    return get_origin(first_param.annotation) is RunContext
```

### Tool Preparation

**Dynamic tool availability**:
```python
@agent.tool(prepare=only_if_admin)
async def delete_user(ctx: RunContext[MyDeps], user_id: int):
    ...

async def only_if_admin(ctx: RunContext[MyDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if not ctx.deps.user.is_admin:
        return None  # Hide tool from this run
    return tool_def
```

**Batch preparation**:
```python
agent = Agent('openai:gpt-4o', prepare_tools=customize_all_tools)

async def customize_all_tools(ctx: RunContext, tool_defs: list[ToolDefinition]) -> list[ToolDefinition] | None:
    # Enable strict mode for OpenAI
    if ctx.model.system == 'openai':
        return [replace(t, strict=True) for t in tool_defs]
    return tool_defs
```

### Tool Execution Flow

1. **Model returns tool call**:
   ```python
   ToolCallPart(
       tool_call_id="call_123",
       tool_name="search_web",
       args={"query": "weather"}  # JSON object or JSON string
   )
   ```

2. **Validate arguments**:
   ```python
   validated_args = tool.args_validator.validate_python(tool_call.args_as_dict())
   ```

3. **Call tool function**:
   ```python
   if is_async_callable(func):
       result = await func(ctx, **validated_args)  # or just **validated_args
   else:
       result = await run_in_executor(func, ctx, **validated_args)
   ```

4. **Handle result/errors**:
   ```python
   try:
       result = await execute_tool(...)
       return ToolReturnPart(tool_call_id=call_id, content=result)
   except ModelRetry as e:
       return RetryPromptPart(tool_call_id=call_id, content=str(e))
   except Exception as e:
       # Log and raise or return error
   ```

### Error Feedback to Model

**Validation errors**:
```python
# Tool validation fails -> ToolRetryError
# ToolRetryError caught -> RetryPromptPart added to next request
# Model sees error and can self-correct
```

**Example error message to model**:
```
Tool call validation failed for tool 'search_web':
- max_results: value must be less than or equal to 100
```

**ModelRetry exception**:
```python
@agent.tool
def risky_operation(value: int) -> str:
    if value < 0:
        raise ModelRetry("Value must be positive. Please try again with a positive number.")
    return f"Success: {value}"
```

### Builtin Tools

**Special handling**:
```python
class AbstractBuiltinTool(ABC):
    @abstractmethod
    async def run_builtin_tool(
        self, args: dict[str, Any], run_context: RunContext[Any]
    ) -> Any: ...
```

**Used for**:
- MCP (Model Context Protocol) integration
- Provider-specific features

**Execution**:
- Interleaved with response parts
- Model can mix text + builtin tool calls
- Results appear as `BuiltinToolReturnPart`

## Code References

- `pydantic_ai_slim/pydantic_ai/tools.py:146` - ToolDefinition dataclass
- `pydantic_ai_slim/pydantic_ai/_function_schema.py` - Schema generation from functions
- `pydantic_ai_slim/pydantic_ai/toolsets/abstract.py:38` - ToolsetTool with validator
- `pydantic_ai_slim/pydantic_ai/exceptions.py:188` - ToolRetryError formatting

## Implications for New Framework

1. **Adopt**: Auto-schema from function signatures
   - Excellent DX - just write normal functions
   - Docstring integration for descriptions
   - Pydantic for validation

2. **Adopt**: Rich validation error feedback
   - Don't silently fail
   - Give model the validation errors
   - Enables self-correction

3. **Adopt**: Context-aware tools via injection
   - Clean API - `ctx: RunContext[DepsT]`
   - Auto-detection of context parameter
   - Type-safe dependency access

4. **Adopt**: Prepare functions for dynamic tools
   - Per-tool preparation
   - Batch preparation for all tools
   - Enables conditional tool availability

5. **Consider**: Builtin tool protocol
   - Useful for provider-specific features
   - Adds complexity
   - Only if needed for MCP or similar

## Anti-Patterns Observed

None - excellent tool interface design.

## Notable Patterns Worth Adopting

1. **args_as_dict() method**:
   - Handles both JSON string and dict
   - Centralized parsing logic
   - Clean API for tool managers

2. **Strict mode support**:
   - OpenAI's strict schema validation
   - Per-tool configuration
   - Opt-in for better reliability

3. **Sync tool wrapping**:
   - `run_in_executor` for sync tools
   - Transparent to users
   - No forced async rewrite

4. **ToolRetryError with formatted message**:
   - Pydantic errors are verbose
   - Framework formats them nicely
   - Model-friendly error messages
