# Tool Interface Analysis: Agno

## Summary
- **Key Finding 1**: JSON Schema-based tool definitions with automatic schema generation from Python functions
- **Key Finding 2**: Rich lifecycle hooks - pre/post hooks, tool_hooks, confirmation, user input
- **Key Finding 3**: Intelligent argument parsing - handles string variations of null/true/false
- **Classification**: Declarative tool system with imperative extension points

## Schema Generation
- **Method**: Automatic from Python function signatures + docstrings
- **Library**: docstring_parser + Pydantic type hints
- **Format**: JSON Schema (OpenAI function calling format)
- **Validation**: Pydantic validate_call decorator

## Tool Ergonomics
- **Registration**: Declarative - wrap Python functions with minimal boilerplate
- **Argument Passing**: Type-checked via Pydantic
- **Error Handling**: Errors captured in FunctionCall.error field, retry prompted
- **Context Injection**: Agent, session_state, dependencies, media injected via internal fields

## Detailed Analysis

### Function Schema

**Evidence** (`tools/function.py:65-144`):
```python
class Function(BaseModel):
    """Model for storing functions that can be called by an agent."""

    # Core identity
    name: str
    description: Optional[str] = None
    parameters: Dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []},
        description="JSON Schema object describing function parameters",
    )
    strict: Optional[bool] = None  # Structured outputs mode

    # Behavioral configuration
    instructions: Optional[str] = None
    add_instructions: bool = True
    show_result: bool = False
    stop_after_tool_call: bool = False

    # Lifecycle hooks
    pre_hook: Optional[Callable] = None
    post_hook: Optional[Callable] = None
    tool_hooks: Optional[List[Callable]] = None

    # User interaction
    requires_confirmation: Optional[bool] = None
    requires_user_input: Optional[bool] = None
    user_input_fields: Optional[List[str]] = None
    user_input_schema: Optional[List[UserInputField]] = None

    # Execution control
    external_execution: Optional[bool] = None  # Tool executed outside agent

    # Caching
    cache_results: bool = False
    cache_dir: Optional[str] = None
    cache_ttl: int = 3600

    # The actual function
    entrypoint: Optional[Callable] = None
    skip_entrypoint_processing: bool = False

    # Context injection (internal)
    _agent: Optional[Any] = None
    _run_context: Optional[RunContext] = None
    _session_state: Optional[Dict[str, Any]] = None
    _dependencies: Optional[Dict[str, Any]] = None
    _images, _videos, _audios, _files: Optional[Sequence[Media]] = None
```

**Rich Configuration**: 20+ configuration fields provide extensive control over tool behavior

### Automatic Schema Generation

**Evidence** (`tools/function.py:18-37`):
```python
def get_entrypoint_docstring(entrypoint: Callable) -> str:
    from inspect import getdoc

    docstring = getdoc(entrypoint)
    if not docstring:
        return ""

    parsed_doc = parse(docstring)  # docstring_parser library

    # Combine short and long descriptions
    lines = []
    if parsed_doc.short_description:
        lines.append(parsed_doc.short_description)
    if parsed_doc.long_description:
        lines.extend(parsed_doc.long_description.split("\n"))

    return "\n".join(lines)
```

**Pattern**: Extracts description from docstring automatically
- Uses `docstring_parser` library to parse Google/NumPy/Sphinx style docstrings
- Combines short and long descriptions into tool description
- No manual description needed if docstring present

**Parameter Schema**: Generated from type hints (implementation in separate file)
- Pydantic inspects function signature
- Converts Python types to JSON Schema
- Extracts parameter descriptions from docstring

### Argument Parsing with String Normalization

**Evidence** (`utils/functions.py:50-66`):
```python
clean_arguments: Dict[str, Any] = {}
for k, v in _arguments.items():
    if isinstance(v, str):
        _v = v.strip().lower()
        if _v in ("none", "null"):
            clean_arguments[k] = None  # Convert string "none" to None
        elif _v == "true":
            clean_arguments[k] = True  # Convert string "true" to bool
        elif _v == "false":
            clean_arguments[k] = False  # Convert string "false" to bool
        else:
            clean_arguments[k] = v.strip()  # Trim whitespace
    else:
        clean_arguments[k] = v
```

**Resilient Parsing**: Handles LLM quirks
- Models sometimes return `"true"` instead of `true` in JSON
- Models sometimes return `"null"` instead of `null`
- Framework normalizes these automatically

**Fallback Parsing** (`utils/functions.py:31-36`):
```python
try:
    _arguments = json.loads(arguments)
except Exception:
    import ast
    _arguments = ast.literal_eval(arguments)  # Try Python literals
```

**Double Fallback**: If JSON parsing fails, try Python's `ast.literal_eval`
- Handles cases where model returns Python syntax instead of JSON
- Last-ditch effort before error

### Error Feedback to Model

**Evidence** (`utils/functions.py:38-43, 46-48`):
```python
except Exception as e:
    log_error(f"Unable to decode function arguments:\n{arguments}\nError: {e}")
    function_call.error = (
        f"Error while decoding function arguments: {e}\n\n"
        f"Please make sure we can json.loads() the arguments and retry."
    )
    return function_call

# Later:
if not isinstance(_arguments, dict):
    function_call.error = "Function arguments are not a valid JSON object.\n\n Please fix and retry."
    return function_call
```

**Self-Healing**: Errors are structured as messages to the model
- Error includes guidance on how to fix ("Please make sure we can json.loads()")
- FunctionCall object returned with error field populated
- Model sees error and retries with corrected arguments

This creates a **feedback loop for self-correction**.

### User Input Fields

**Evidence** (`tools/function.py:106-111`):
```python
# If True, the function will require user input before execution
requires_user_input: Optional[bool] = None
# List of fields that the user will provide as input
user_input_fields: Optional[List[str]] = None
# This is set during parsing, not by the user
user_input_schema: Optional[List[UserInputField]] = None
```

**Pattern**: Some tool arguments provided by user, not model
- Model calls tool with partial arguments
- Framework pauses execution
- User fills in remaining fields (e.g., credit card number, password)
- Execution resumes

**Schema** (`tools/function.py:40-62`):
```python
@dataclass
class UserInputField:
    name: str
    field_type: Type
    description: Optional[str] = None
    value: Optional[Any] = None
```

**Security Benefit**: Sensitive data never exposed to model

### Confirmation Workflow

**Evidence** (`tools/function.py:103-104`):
```python
# If True, the function will require confirmation before execution
requires_confirmation: Optional[bool] = None
```

**Pattern**: Human-in-the-loop for destructive operations
- Model decides to call tool
- Framework shows user what will happen
- User confirms/rejects
- If rejected, model sees rejection and tries alternative

### External Execution

**Evidence** (`tools/function.py:113-114`):
```python
# If True, the function will be executed outside the agent's control.
external_execution: Optional[bool] = None
```

**Pattern**: Tool call delegated to external system
- Agent generates tool call specification
- External system executes it
- External system returns result
- Agent continues with result

**Use Case**: Long-running tools (batch jobs, human approval workflows)

### Tool Hooks

**Evidence** (`tools/function.py:94-101`):
```python
# Hook that runs before the function is executed.
pre_hook: Optional[Callable] = None
# Hook that runs after the function is executed, regardless of success/failure.
post_hook: Optional[Callable] = None

# A list of hooks to run around tool calls.
tool_hooks: Optional[List[Callable]] = None
```

**Extension Points**: Inject behavior before/after tool execution
- Pre-hook: Logging, validation, rate limiting
- Post-hook: Cleanup, metrics, notification
- Tool_hooks: More general hook list

**Hook Signature**: Can accept FunctionCall instance as parameter

### Caching

**Evidence** (`tools/function.py:116-119`):
```python
# Caching configuration
cache_results: bool = False
cache_dir: Optional[str] = None
cache_ttl: int = 3600  # seconds
```

**Pattern**: File-based caching of tool results
- Deterministic tools can cache results
- TTL-based expiration
- Reduces redundant API calls/computation

**Implementation** (`utils/functions.py:74-100`):
```python
def cache_result(enable_cache: bool = True, cache_dir: Optional[str] = None, cache_ttl: int = 3600):
    """Decorator factory that creates a file-based caching decorator."""
    # Uses filesystem cache with TTL
```

### Context Injection via Internal Fields

**Evidence** (`tools/function.py:121-137`):
```python
# --*-- FOR INTERNAL USE ONLY --*--
_agent: Optional[Any] = None
_run_context: Optional[RunContext] = None
_session_state: Optional[Dict[str, Any]] = None
_dependencies: Optional[Dict[str, Any]] = None
_images, _videos, _audios, _files: Optional[Sequence[Media]] = None
```

**Pattern**: Framework populates internal fields before execution
- Tools can access agent configuration
- Tools can access session state
- Tools can access user-provided dependencies
- Tools can access media from conversation

**No Explicit Parameters**: Context injected without cluttering function signature

### Stop After Tool Call

**Evidence** (`tools/function.py:91-92`):
```python
# If True, the agent will stop after the function call.
stop_after_tool_call: bool = False
```

**Pattern**: Tool call ends agent run
- Useful for handoff tools (escalate_to_human)
- Agent calls tool, then exits
- External system takes over

## Implications for New Framework

1. **JSON Schema with auto-generation is ideal** - Balances flexibility and ergonomics
2. **Intelligent argument parsing is essential** - LLMs make formatting mistakes; normalize them
3. **Error feedback loop works** - Returning errors as messages enables self-correction
4. **User input fields are powerful** - Separate model-provided from user-provided args
5. **Confirmation for destructive operations** - Critical for production systems
6. **Hooks provide extensibility** - Don't bake every feature in; expose hooks
7. **Caching reduces cost** - Deterministic tools should cache results
8. **Context injection beats explicit parameters** - Cleaner function signatures

## Anti-Patterns Observed

1. **Too many configuration fields** - 20+ fields on Function is overwhelming; consider builder pattern
2. **Internal fields prefixed with underscore** - Pydantic model shouldn't have "private" fields; use separate context object
3. **tool_hooks AND pre_hook/post_hook** - Redundant; unify hook system
4. **Eval in deserialization** - `eval(data["field_type"])` in UserInputField.from_dict (line 59) is dangerous
5. **No tool timeout** - Tools can hang indefinitely
6. **No parallel tool execution** - Tools run sequentially
7. **Cache uses filesystem** - Should support pluggable cache backends (Redis, etc.)

## Code References
- `libs/agno/agno/tools/function.py:65-144` - Function schema with extensive configuration
- `libs/agno/agno/tools/function.py:18-37` - Automatic description extraction from docstrings
- `libs/agno/agno/tools/function.py:40-62` - UserInputField for user-provided arguments
- `libs/agno/agno/utils/functions.py:10-71` - FunctionCall parsing with argument normalization
- `libs/agno/agno/utils/functions.py:50-66` - String normalization for null/true/false
- `libs/agno/agno/utils/functions.py:31-36` - Double fallback parsing (JSON then ast.literal_eval)
- `libs/agno/agno/utils/functions.py:38-48` - Error feedback messages for self-correction
- `libs/agno/agno/utils/functions.py:74-100` - File-based caching decorator
