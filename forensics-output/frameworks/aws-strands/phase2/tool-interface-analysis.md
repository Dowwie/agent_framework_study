# Tool Interface Analysis: AWS Strands

## Summary
- **Key Finding 1**: Dual tool interfaces - class-based (AgentTool ABC) and function-based (@tool decorator)
- **Key Finding 2**: JSON Schema generation from function signatures via introspection
- **Classification**: Hybrid declarative/imperative with schema inference

## Detailed Analysis

### Tool Definition Patterns

#### Pattern 1: Class-Based (AgentTool ABC)

**Location**: `src/strands/types/tools.py:218`

```python
class MyTool(AgentTool):
    @property
    def tool_name(self) -> str:
        return "my_tool"

    @property
    def tool_spec(self) -> ToolSpec:
        return {
            "name": "my_tool",
            "description": "Does something useful",
            "inputSchema": {"type": "object", "properties": {...}},
        }

    @property
    def tool_type(self) -> str:
        return "python"

    async def stream(self, tool_use: ToolUse, invocation_state: dict, **kwargs) -> ToolGenerator:
        # Execute tool logic
        yield {"partial": "result"}
        yield {
            "content": [{"text": "final result"}],
            "status": "success",
            "toolUseId": tool_use["toolUseId"],
        }
```

**Characteristics**:
- Manual schema definition
- Full control over execution
- Streaming support (AsyncGenerator)
- Access to invocation_state
- Hot reload support (optional)

#### Pattern 2: Function-Based (@tool decorator)

**Usage**:
```python
@tool
async def search_web(query: str, max_results: int = 10) -> str:
    """Search the web for information.

    Args:
        query: The search query
        max_results: Maximum number of results (default: 10)

    Returns:
        Search results as text
    """
    # Implementation
    return "search results"
```

**Schema Inference**:
- Name: Function name (`search_web`)
- Description: Docstring first line
- Input schema: Generated from type annotations
- Output schema: Inferred from return type annotation (if supported)
- Parameters: `inspect.signature()` introspection

#### Pattern 3: Module-Based

**Structure**:
```
tools/
├── my_tool.py
│   └── __all__ = ["MyTool"]  # or @tool decorated functions
```

**Loading**: `load_tools_from_module(module, tool_name)`

**Discovery**: Scans for:
1. `AgentTool` subclass instances
2. Functions decorated with `@tool`
3. Respects `__all__` if present

### Schema Generation

#### Function Signature Introspection

**Source**: Inferred from decorator pattern (not visible in sampled code)

**Likely Implementation**:
```python
def generate_schema_from_function(func):
    sig = inspect.signature(func)
    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        if param_name in ["self", "cls", "context"]:
            continue

        param_type = param.annotation
        properties[param_name] = type_to_json_schema(param_type)

        if param.default == inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
```

#### Type Mapping

**Supported Types** (inferred):
- `str` → `{"type": "string"}`
- `int` → `{"type": "integer"}`
- `float` → `{"type": "number"}`
- `bool` → `{"type": "boolean"}`
- `list[T]` → `{"type": "array", "items": {...}}`
- `dict` → `{"type": "object"}`
- `Optional[T]` → Schema for T (not in required)
- `Literal[...]` → `{"enum": [...]}`
- Pydantic models → `model.model_json_schema()`

#### Composition Keywords

**Source**: `tools/tools.py` (referenced as `_COMPOSITION_KEYWORDS`)

**Purpose**: Handle oneOf, anyOf, allOf in schemas

**Normalization**: `normalize_schema()` expands composition keywords for providers that don't support them

### ToolContext (Framework-Provided Data)

**Location**: `src/strands/types/tools.py:128`

```python
@dataclass
class ToolContext(_Interruptible):
    tool_use: ToolUse  # Original request
    agent: Any  # Agent or BidiAgent instance
    invocation_state: dict[str, Any]  # User-provided context

    def _interrupt_id(self, name: str) -> str:
        # Generate unique interrupt ID
        return f"v1:tool_call:{self.tool_use['toolUseId']}:{uuid.uuid5(...)}"
```

**Usage**:
```python
@tool
async def interactive_tool(query: str, context: ToolContext) -> str:
    # Access agent state
    previous_results = context.agent.state.get("results")

    # Access invocation state
    user_id = context.invocation_state["user_id"]

    # Request human input
    user_input = await context.interrupt("Need your approval")

    return f"Processed with {user_input}"
```

**Characteristics**:
- Optional parameter (injected if present in signature)
- Access to agent internals
- Interrupt support (human-in-the-loop)
- Type-safe via dataclass

### Error Feedback

#### ToolResult Status

**Type** (types/tools.py:L87):
```python
class ToolResult(TypedDict):
    content: list[ToolResultContent]
    status: ToolResultStatus  # "success" | "error"
    toolUseId: str
```

**Error Handling**:
```python
try:
    result = execute_tool(tool_use)
    return {
        "content": [{"text": str(result)}],
        "status": "success",
        "toolUseId": tool_use["toolUseId"],
    }
except Exception as e:
    return {
        "content": [{"text": f"Error: {str(e)}"}],
        "status": "error",
        "toolUseId": tool_use["toolUseId"],
    }
```

**Model Feedback**:
- Error status passed back to model
- Error message in content (plain text)
- Model can retry with different parameters
- No structured error codes

### Tool Validation

#### Input Validation

**Pre-execution** (inferred from `validate_and_prepare_tools()`):
1. Check tool exists in registry
2. Validate input against inputSchema (JSON Schema)
3. Coerce types if needed

**Runtime**:
- Function signature validation (via Python runtime)
- Pydantic model validation (if used in parameters)

#### Output Validation

**No built-in output validation**:
- `outputSchema` field exists in ToolSpec (optional)
- Not all providers support it
- No runtime validation against outputSchema

**Workaround**: Use structured output models

### Tool Execution Models

#### Sequential (default)
```python
for tool_use in tool_uses:
    result = await tool.stream(tool_use, invocation_state)
    async for event in result:
        yield event
```

#### Concurrent (ConcurrentToolExecutor)
```python
tasks = [tool.stream(tu, invocation_state) for tu in tool_uses]
async for result in asyncio.as_completed(tasks):
    async for event in result:
        yield event
```

**Ordering**:
- Sequential: Deterministic (order of tool_uses)
- Concurrent: Non-deterministic (completion order)

### Dynamic Tool Loading

#### Hot Reload (ToolWatcher)

**Mechanism**:
- File system watcher monitors `./tools/` directory
- On change: Reload module, update registry
- Old tool instances replaced

**Limitations**:
- Only works for tools with `supports_hot_reload = True`
- No version migration for in-flight tool calls
- Potential for stale references

#### Runtime Registration

**API**:
```python
agent.tool_registry.register_tool(new_tool)
agent.tool_registry.process_tools(["./path/to/tool.py"])
```

**Use Cases**:
- A/B testing tools
- User-defined tools (SaaS)
- Dynamic capability expansion

### Tool Composition

#### No Built-in Composition

**Observed Patterns**:
- Tools are atomic (no sub-tool calls)
- No tool pipelines
- No tool delegation

**Workaround**: Implement in tool logic
```python
@tool
async def composite_tool(query: str, context: ToolContext) -> str:
    # Manually call other tools
    results1 = await context.agent.tool.search(query)
    results2 = await context.agent.tool.summarize(results1)
    return results2
```

### Streaming Tool Results

#### Incremental Updates

**Pattern** (types/tools.py:L183):
```python
ToolGenerator = AsyncGenerator[Any, None]
```

**Usage**:
```python
async def stream(...) -> ToolGenerator:
    yield {"status": "started"}
    yield {"progress": 0.5}
    yield {"progress": 1.0}
    yield {
        "content": [{"text": "final result"}],
        "status": "success",
        "toolUseId": tool_use["toolUseId"],
    }
```

**Last Yield Must Be ToolResult**:
- All previous yields are intermediate events
- Final yield = ToolResult (appended to messages)

## Code References
- `src/strands/types/tools.py:22-37` - ToolSpec TypedDict
- `src/strands/types/tools.py:52-65` - ToolUse request format
- `src/strands/types/tools.py:87-99` - ToolResult with status
- `src/strands/types/tools.py:128-160` - ToolContext for framework data
- `src/strands/types/tools.py:218-307` - AgentTool ABC interface
- `src/strands/tools/registry.py:44-150` - Tool loading strategies

## Implications for New Framework
- **Adopt**: Dual interface (class + decorator) for flexibility
- **Adopt**: JSON Schema generation from type annotations
- **Adopt**: ToolContext for framework-provided data
- **Adopt**: Streaming tool results (incremental progress)
- **Adopt**: Error status in ToolResult (errors as data)
- **Reconsider**: Add output validation against outputSchema
- **Reconsider**: Add structured error codes (not just text)
- **Reconsider**: Add tool composition primitives
- **Add**: Tool dependency graph for parallel execution

## Anti-Patterns Observed
- **No Output Validation**: outputSchema not enforced at runtime
- **Unstructured Errors**: Error messages are plain text (no error codes)
- **Hot Reload Risks**: No migration path for in-flight calls
- **ToolContext Coupling**: Tools access agent internals (breaks encapsulation)
- **Non-Deterministic Concurrent Execution**: Completion order not guaranteed
