# Tool Interface Analysis: Swarm

## Summary
- **Tool Definition**: Plain Python functions
- **Schema Generation**: Automatic via reflection (`inspect.signature`)
- **Registration**: List-based (no decorators)
- **Error Feedback**: Only for missing tools (graceful), not for tool failures
- **Self-Correction**: Supported for missing tools, not for execution errors

## Tool Definition Method

**Approach**: Plain functions, no base class or decorator required

```python
# Example from documentation
def get_weather(location: str) -> str:
    """Get the weather for a location"""
    return f"Weather in {location}: Sunny, 72F"

agent = Agent(
    functions=[get_weather]  # Just add to list
)
```

**Requirements**:
- Must be callable
- Type hints used for schema generation
- Docstring becomes description
- Can return `str`, `Agent`, or `Result`

### Type Alias
```python
# types.py:L11
AgentFunction = Callable[[], Union[str, "Agent", dict]]
```

**Note**: Type alias says `Callable[[],...]` (no parameters), but actual functions DO take parameters. Type alias is incorrect.

## Schema Generation

**Method**: Reflection via `inspect.signature()`

```python
# util.py:L31-87
def function_to_json(func) -> dict:
    signature = inspect.signature(func)

    # Map Python types to JSON schema types
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
        type(None): "null",
    }

    # Extract parameters
    parameters = {}
    for param in signature.parameters.values():
        param_type = type_map.get(param.annotation, "string")
        parameters[param.name] = {"type": param_type}

    # Identify required (no default value)
    required = [
        param.name
        for param in signature.parameters.values()
        if param.default == inspect._empty
    ]

    # Build OpenAI function schema
    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": func.__doc__ or "",
            "parameters": {
                "type": "object",
                "properties": parameters,
                "required": required,
            },
        },
    }
```

### Type Mapping Limitations

**Supported**:
- `str` → "string"
- `int` → "integer"
- `float` → "number"
- `bool` → "boolean"
- `list` → "array"
- `dict` → "object"
- `None` → "null"

**Not supported**:
- `List[str]` (generic types) → Defaults to "string"
- `Optional[int]` → Defaults to "string"
- `Literal["a", "b"]` → Defaults to "string"
- Custom classes → Defaults to "string"
- `Union` types → Defaults to "string"

**Implication**: No support for rich type specifications like Pydantic models or enums.

### Schema Enrichment Missing

**Not generated**:
- Parameter descriptions (OpenAI supports this)
- Enum constraints (e.g., `location` must be one of ["NYC", "LA", "SF"])
- Min/max for numbers
- Pattern validation for strings
- Array item types

**Example of what's missing**:
```python
# Current: Simple schema
{
    "name": "get_weather",
    "parameters": {
        "properties": {"location": {"type": "string"}},
        "required": ["location"]
    }
}

# Could be: Rich schema
{
    "name": "get_weather",
    "description": "Get current weather for a location",
    "parameters": {
        "properties": {
            "location": {
                "type": "string",
                "description": "City name or coordinates",
                "enum": ["NYC", "LA", "SF", "Boston"]  # NOT SUPPORTED
            }
        },
        "required": ["location"]
    }
}
```

## Context Variables Injection

**Magic parameter**: Framework auto-detects and injects

```python
# core.py:L120-121
if __CTX_VARS_NAME__ in func.__code__.co_varnames:
    args[__CTX_VARS_NAME__] = context_variables
```

### Hidden from LLM
```python
# core.py:L52-56
for tool in tools:
    params = tool["function"]["parameters"]
    params["properties"].pop(__CTX_VARS_NAME__, None)  # Remove from schema
    if __CTX_VARS_NAME__ in params["required"]:
        params["required"].remove(__CTX_VARS_NAME__)
```

**Purpose**: Tools can access session state without LLM needing to provide it

**Example**:
```python
def send_email(to: str, message: str, context_variables: dict) -> str:
    user_id = context_variables["user_id"]  # Available, but LLM didn't provide
    # Send email...
```

**Trade-off**:
- ✅ Convenient - tools get context automatically
- ❌ Magic - not obvious from signature
- ❌ Type checking fails - `context_variables` not in schema

## Tool Registration

**Method**: List in Agent constructor

```python
# types.py:L18
class Agent(BaseModel):
    functions: List[AgentFunction] = []

# Usage
agent = Agent(
    name="Assistant",
    functions=[func1, func2, func3]
)
```

**No decorator**: Unlike LangChain's `@tool`, Swarm uses plain functions

### Dynamic Registration
```python
# Agent is Pydantic model, so can update
agent.functions.append(new_function)
```

**Thread safety**: Not safe - Agent is mutable

## Tool Execution

### Lookup
```python
# core.py:L96
function_map = {f.__name__: f for f in functions}
```

**Key**: Function name (string from LLM)
**Collision risk**: If two functions have same `__name__`, last one wins (dict overwrite)

### Invocation
```python
# core.py:L114-122
args = json.loads(tool_call.function.arguments)  # Parse JSON from LLM

func = function_map[name]
if __CTX_VARS_NAME__ in func.__code__.co_varnames:
    args[__CTX_VARS_NAME__] = context_variables

raw_result = function_map[name](**args)  # Direct call, no try/catch
```

**No sandboxing**: Tool runs in main process, same privileges as framework

### Result Handling
```python
# core.py:L71-87
def handle_function_result(self, result, debug) -> Result:
    match result:
        case Result() as result:
            return result  # Already wrapped

        case Agent() as agent:
            # Tool requested agent handoff
            return Result(
                value=json.dumps({"assistant": agent.name}),
                agent=agent,
            )

        case _:
            # String or dict or unknown
            try:
                return Result(value=str(result))
            except Exception as e:
                error_message = f"Failed to cast response to string: {result}..."
                debug_print(debug, error_message)
                raise TypeError(error_message)
```

**Pattern matching** (Python 3.10+):
1. If already `Result`, use as-is
2. If `Agent`, wrap in Result and trigger handoff
3. Else, convert to string (or fail)

## Error Feedback to LLM

### Missing Tool (Graceful)
```python
# core.py:L103-113
if name not in function_map:
    debug_print(debug, f"Tool {name} not found in function map.")
    partial_response.messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "tool_name": name,
            "content": f"Error: Tool {name} not found.",
        }
    )
    continue  # Don't crash, send error to LLM
```

**Feedback**: Error message sent as tool result
**LLM sees**: "Error: Tool {name} not found."
**Self-correction**: LLM can retry with different tool or ask user

### Tool Execution Error (Not Handled)
```python
# core.py:L122
raw_result = function_map[name](**args)  # No try/catch
```

**If tool raises exception**:
- Exception propagates up
- Entire `run()` fails
- LLM never sees the error
- No opportunity for self-correction

**Missing pattern**:
```python
# Should be
try:
    raw_result = function_map[name](**args)
except Exception as e:
    # Send error to LLM for self-correction
    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": f"Error: {str(e)}"
    }
```

### Argument Parsing Error
```python
# core.py:L114
args = json.loads(tool_call.function.arguments)  # No try/catch
```

**If LLM provides invalid JSON**: `json.loads()` raises `JSONDecodeError` → Agent crashes

**No validation**: Framework doesn't check if LLM-provided args match schema

## Self-Correction Support

### Supported: Missing Tool
```
LLM calls non-existent tool
    → Framework sends error message to LLM
        → LLM sees error in next turn
            → LLM can try different tool or ask user
```

**Example conversation**:
```
Assistant: I'll check the weather <calls get_weather>
Framework: Error: Tool get_weather not found.
Assistant: I apologize, I don't have access to a weather tool. Let me...
```

### Not Supported: Tool Failures
```
LLM calls tool with invalid args
    → Tool raises exception
        → Agent crashes
            → Conversation terminated
                → No recovery
```

**Should be**:
```
Assistant: <calls get_weather(location=12345)>  // Invalid type
Framework: Error: Expected string, got int
Assistant: Let me correct that <calls get_weather(location="NYC")>
```

## Tool Discovery

**None**: LLM only knows tools from Agent.functions

**No runtime discovery**:
- Can't list available tools
- Can't search for tools
- Can't load tools dynamically

**Agent switching enables "discovery"**:
- Agent A has tools [X, Y]
- Agent A calls tool Z that returns Agent B
- Agent B has tools [Z, W]
- LLM now has access to Z, W (and loses X, Y unless they overlap)

## Implications for New Framework

### Adopt
1. **Plain function interface** - No ceremony, easy adoption
2. **Automatic schema generation** - DX improvement, reduces boilerplate
3. **Graceful missing tool handling** - Send error to LLM for self-correction
4. **Agent handoff via tool return** - Elegant way to switch capabilities

### Critical Improvements
1. **Wrap tool execution in try/catch** - Send errors to LLM, don't crash
2. **Support rich type hints** - Pydantic models, Literal, Optional, etc.
3. **Add parameter descriptions** - Extract from docstrings or type metadata
4. **Add schema validation** - Check LLM args match schema before calling
5. **Sandbox tool execution** - Subprocess or container isolation
6. **Add tool registry** - Decorator-based registration like `@tool`
7. **Tool timeout** - Prevent hung tools

### Anti-Patterns Observed
1. **No tool execution error handling** - Single tool error crashes agent
2. **Limited type support** - Only basic types, no generics or custom types
3. **Magic parameter injection** - `context_variables` is implicit
4. **No schema validation** - Trust LLM to provide correct args
5. **Name collision risk** - Dict keyed by function name only

## Advanced Tool Patterns Missing

**Not supported**:
- Tool chaining (output of tool A → input to tool B)
- Tool dependencies (tool B requires tool A to run first)
- Tool permissions (some tools only for certain users)
- Tool versioning (v1 vs v2 of same tool)
- Tool namespaces (avoid name collisions)
- Tool deprecation warnings
- Async tool execution
- Streaming tool results

## Code References

- `swarm/types.py:11` - AgentFunction type alias
- `swarm/types.py:18` - Function list in Agent
- `swarm/util.py:31-87` - function_to_json schema generation
- `swarm/core.py:50` - Schema generation call
- `swarm/core.py:52-56` - Context variables hidden from schema
- `swarm/core.py:71-87` - Result type handling (pattern match)
- `swarm/core.py:96` - Function map creation
- `swarm/core.py:103-113` - Missing tool error feedback
- `swarm/core.py:114` - Argument parsing (no error handling)
- `swarm/core.py:120-122` - Context injection and execution (no error handling)
