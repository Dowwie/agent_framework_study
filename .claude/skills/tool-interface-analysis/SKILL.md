---
name: tool-interface-analysis
description: Analyze tool registration, schema generation, and error feedback mechanisms in agent frameworks. Use when (1) understanding how tools are defined and registered, (2) evaluating schema generation approaches (introspection vs manual), (3) tracing error feedback loops to the LLM, (4) assessing retry and self-correction mechanisms, or (5) comparing tool interfaces across frameworks.
---

# Tool Interface Analysis

Analyzes tool registration, schema generation, and error feedback.

## Process

1. **Analyze schema generation** — How tools become LLM-readable
2. **Document registration** — How tools are made available
3. **Trace error feedback** — How failures reach the LLM
4. **Identify retry mechanisms** — Self-correction patterns

## Schema Generation Methods

### Introspection-Based (Automatic)

```python
import inspect

def generate_schema(func):
    sig = inspect.signature(func)
    doc = inspect.getdoc(func) or ""
    
    schema = {
        "name": func.__name__,
        "description": doc.split("\n")[0],
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
    
    for name, param in sig.parameters.items():
        prop = {"type": python_type_to_json(param.annotation)}
        if param.default is inspect.Parameter.empty:
            schema["parameters"]["required"].append(name)
        schema["parameters"]["properties"][name] = prop
    
    return schema
```

**Pros**: DRY, always in sync with code
**Cons**: Limited expressiveness, relies on annotations

### Pydantic-Based (Semi-Automatic)

```python
from pydantic import BaseModel, Field

class SearchInput(BaseModel):
    """Search the web for information."""
    query: str = Field(description="The search query")
    max_results: int = Field(default=10, ge=1, le=100)

# Schema generated from model
schema = SearchInput.model_json_schema()
```

**Pros**: Rich validation, good descriptions
**Cons**: More boilerplate, class per tool

### Decorator-Based

```python
@tool(
    name="search",
    description="Search the web",
    parameters={
        "query": {"type": "string", "description": "Search query"},
        "max_results": {"type": "integer", "default": 10}
    }
)
def search(query: str, max_results: int = 10) -> list[str]:
    ...
```

**Pros**: Explicit, flexible
**Cons**: Can drift from implementation

### Manual Definition

```python
TOOLS = [
    {
        "name": "search",
        "description": "Search the web for information",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                }
            },
            "required": ["query"]
        }
    }
]
```

**Pros**: Full control
**Cons**: Maintenance burden, drift risk

## Registration Patterns

### Declarative List

```python
agent = Agent(
    tools=[search_tool, calculator_tool, weather_tool]
)
```

**Characteristics**: Explicit, static, easy to understand

### Registry Pattern

```python
TOOL_REGISTRY = {}

def register_tool(name: str):
    def decorator(func):
        TOOL_REGISTRY[name] = func
        return func
    return decorator

@register_tool("search")
def search(query: str): ...

# Agent uses registry
agent = Agent(tools=TOOL_REGISTRY)
```

**Characteristics**: Dynamic, plugin-friendly, implicit

### Discovery-Based

```python
import importlib
import pkgutil

def discover_tools(package):
    tools = []
    for module_info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        for name, obj in inspect.getmembers(module):
            if hasattr(obj, '__tool__'):
                tools.append(obj)
    return tools
```

**Characteristics**: Automatic, magic, harder to trace

### Factory Pattern

```python
class ToolFactory:
    @classmethod
    def create(cls, config: ToolConfig) -> Tool:
        tool_class = cls._registry.get(config.type)
        return tool_class(**config.params)
```

**Characteristics**: Configurable, testable, more complex

## Error Feedback Analysis

### Feedback Quality Levels

| Level | What LLM Sees | Example |
|-------|--------------|---------|
| Silent | Nothing | Error swallowed |
| Basic | Exception type | "Error: ValueError" |
| Message | Exception message | "Error: Invalid date format" |
| Detailed | Full context | "Error parsing date 'tomorrow': expected YYYY-MM-DD format" |
| Structured | Type + message + hints | `{error: "...", suggestion: "try format YYYY-MM-DD"}` |

### Implementation Patterns

**Silent (Bad)**
```python
def run_tool(self, tool, args):
    try:
        return tool.execute(args)
    except Exception:
        return None  # Error lost!
```

**Basic**
```python
def run_tool(self, tool, args):
    try:
        return tool.execute(args)
    except Exception as e:
        return f"Error: {type(e).__name__}"
```

**Detailed**
```python
def run_tool(self, tool, args):
    try:
        return ToolResult(success=True, output=tool.execute(args))
    except Exception as e:
        return ToolResult(
            success=False,
            error=str(e),
            error_type=type(e).__name__,
            traceback=traceback.format_exc(),
            suggestion=self._get_suggestion(e)
        )
```

### Feedback Loop Integration

```python
def agent_step(self):
    action = self.llm.generate(self.prompt)
    
    if action.type == "tool_call":
        result = self.run_tool(action.tool, action.args)
        
        # Feed result back for next iteration
        if result.success:
            self.add_observation(f"Tool result: {result.output}")
        else:
            self.add_observation(
                f"Tool error: {result.error}\n"
                f"Suggestion: {result.suggestion}"
            )
```

## Retry Mechanisms

### Simple Retry

```python
def run_with_retry(self, tool, args, max_retries=3):
    for i in range(max_retries):
        result = self.run_tool(tool, args)
        if result.success:
            return result
        time.sleep(2 ** i)  # Exponential backoff
    return result  # Return last failure
```

### LLM-Guided Retry

```python
def run_with_self_correction(self, tool, args, max_retries=3):
    for i in range(max_retries):
        result = self.run_tool(tool, args)
        if result.success:
            return result
        
        # Ask LLM to fix the error
        correction_prompt = f"""
        Tool {tool.name} failed with error: {result.error}
        Original args: {args}
        
        Please provide corrected arguments.
        """
        corrected = self.llm.generate(correction_prompt)
        args = parse_args(corrected)
    
    return result
```

### Fallback Chain

```python
def run_with_fallback(self, primary_tool, fallback_tool, args):
    result = self.run_tool(primary_tool, args)
    if result.success:
        return result
    
    # Try fallback
    return self.run_tool(fallback_tool, args)
```

## Output Template

```markdown
## Tool Interface Analysis: [Framework Name]

### Schema Generation
- **Method**: [Introspection/Pydantic/Decorator/Manual]
- **Location**: `path/to/tools.py`
- **Expressiveness**: [Basic/Rich]

### Registration Pattern
- **Type**: [Declarative/Registry/Discovery/Factory]
- **Dynamic**: [Yes/No]
- **Location**: `path/to/agent.py`

### Error Feedback

| Component | Feedback Level | Structured |
|-----------|---------------|------------|
| Tool execution | Detailed | Yes |
| Argument parsing | Basic | No |
| Validation | Message | No |

### Retry Mechanisms
- **Automatic Retry**: [Yes/No, N attempts]
- **Self-Correction**: [Yes/No]
- **Fallback**: [Yes/No]
- **Backoff**: [None/Linear/Exponential]

### Tool Inventory

| Tool | Schema Method | Error Handling |
|------|--------------|----------------|
| search | Pydantic | Detailed + retry |
| calculator | Decorator | Basic |
| file_write | Manual | Silent ⚠️ |
```

## Integration

- **Prerequisite**: `codebase-mapping` to identify tool files
- **Feeds into**: `comparative-matrix` for interface decisions
- **Related**: `resilience-analysis` for error handling patterns
