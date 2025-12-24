## Tool Interface Analysis: LangGraph

### Schema Generation
- **Method**: Delegated to LangChain (Pydantic-based)
- **Location**: `libs/prebuilt/langgraph/prebuilt/tool_node.py`
- **Expressiveness**: Rich (Pydantic models, docstrings)

### Core Insight

LangGraph itself **does not define tool schemas**. It delegates to **LangChain's tool abstraction**:

```python
from langchain_core.tools import Tool, StructuredTool
```

LangChain provides:
1. **Tool schema generation** (from functions, Pydantic models, or manual)
2. **Tool invocation** (validation, error handling)
3. **Tool binding** (attach tools to LLM models)

LangGraph provides:
1. **`ToolNode`**: Executor for tool calls from LLM output
2. **Integration**: Seamless use of LangChain tools in graphs

### LangChain Tool Patterns

**Pattern 1: Function with decorator**
```python
from langchain_core.tools import tool

@tool
def search(query: str) -> str:
    """Search the web for information."""
    return search_api.query(query)

# Schema auto-generated from:
# - Function name
# - Docstring (first line = description)
# - Type hints (parameters)
```

**Pattern 2: Pydantic model**
```python
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

class SearchInput(BaseModel):
    query: str = Field(description="The search query")
    max_results: int = Field(default=10, ge=1, le=100, description="Max results")

def search_impl(query: str, max_results: int) -> str:
    return search_api.query(query, limit=max_results)

search_tool = StructuredTool.from_function(
    func=search_impl,
    name="search",
    description="Search the web",
    args_schema=SearchInput
)
```

**Pattern 3: Manual definition**
```python
search_tool = Tool(
    name="search",
    description="Search the web for information",
    func=lambda query: search_api.query(query)
)
```

**LangGraph's role**: Accept any `BaseTool` from LangChain.

### Registration Pattern
- **Type**: Declarative list
- **Dynamic**: No (static at graph compile time)
- **Location**: Passed to agent creation or `ToolNode`

**Example 1: Prebuilt agent**
```python
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool

@tool
def search(query: str) -> str:
    """Search tool"""
    return "results"

@tool
def calculator(expression: str) -> float:
    """Calculator tool"""
    return eval(expression)

# Register tools by passing list
agent = create_react_agent(
    model=llm,
    tools=[search, calculator]  # Declarative registration
)
```

**Example 2: Manual ToolNode**
```python
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, MessagesState

tools = [search, calculator]

builder = StateGraph(MessagesState)
builder.add_node("llm", llm_node)
builder.add_node("tools", ToolNode(tools))  # Tools passed here
builder.add_conditional_edges("llm", should_continue, {"continue": "tools", "end": END})
builder.add_edge("tools", "llm")
```

**Key**: Tools are **immutable after graph compilation** (no dynamic registration).

### ToolNode Implementation

From `libs/prebuilt/langgraph/prebuilt/tool_node.py`:

```python
class ToolNode(RunnableCallable):
    """Executes tools based on tool calls in messages."""

    def __init__(
        self,
        tools: Sequence[BaseTool | Callable],
        *,
        name: str = "tools",
        handle_tool_errors: bool | Callable = True,
    ):
        self.tools_by_name = {tool.name: tool for tool in tools}
        self.handle_tool_errors = handle_tool_errors

    def invoke(self, input: State, config: RunnableConfig) -> dict:
        # Extract tool calls from last message
        tool_calls = input["messages"][-1].tool_calls

        # Execute each tool
        tool_messages = []
        for call in tool_calls:
            tool = self.tools_by_name[call["name"]]
            try:
                output = tool.invoke(call["args"], config)
                tool_messages.append(
                    ToolMessage(content=output, tool_call_id=call["id"])
                )
            except Exception as e:
                if self.handle_tool_errors:
                    # Feed error back to LLM
                    tool_messages.append(
                        ToolMessage(
                            content=str(e),
                            tool_call_id=call["id"],
                            status="error"
                        )
                    )
                else:
                    raise

        return {"messages": tool_messages}
```

**Key features**:
1. **Error handling**: Configurable (swallow vs propagate)
2. **Error feedback**: Errors returned as `ToolMessage` with `status="error"`
3. **Parallel execution**: All tool calls in message executed
4. **Result format**: `ToolMessage` objects appended to message list

### Error Feedback

| Component | Feedback Level | Structured |
|-----------|---------------|------------|
| Tool execution | Detailed (exception message) | Yes (ToolMessage) |
| Argument validation | Detailed (Pydantic errors) | Yes (via LangChain) |
| Tool not found | Detailed (KeyError) | Yes (raised or in message) |

**Error feedback flow**:
1. LLM outputs tool call: `{"name": "search", "args": {"query": "x"}}`
2. ToolNode extracts call from message
3. Validates args via Pydantic (LangChain does this)
4. Executes tool function
5. If error:
   - Option A (handle_tool_errors=True): Return `ToolMessage` with error string
   - Option B (handle_tool_errors=False): Raise exception, stop graph
6. LLM sees error in next invocation:
   ```
   ToolMessage(
       content="Error: Invalid query format. Expected string, got None.",
       status="error"
   )
   ```

**Quality**: Detailed - full exception message visible to LLM.

### Retry Mechanisms
- **Automatic Retry**: No (at tool level)
- **Self-Correction**: Yes (implicit - LLM sees error, tries again)
- **Fallback**: No
- **Backoff**: N/A

**Retry via graph looping**:
```
LLM → ToolNode (error) → LLM (sees error) → ToolNode (retry with different args)
```

**Explicit retry policy**:
- Available at **node level** via `RetryPolicy`
- Applies to entire node, not individual tool calls

```python
from langgraph.types import RetryPolicy

builder.add_node(
    "tools",
    ToolNode(tools),
    retry_policy=RetryPolicy(max_attempts=3, backoff_factor=2.0)
)
```

### Tool Binding

LangChain models support **tool binding**:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI()
llm_with_tools = llm.bind_tools([search, calculator])

# Model now knows about tools, will output tool calls when appropriate
response = llm_with_tools.invoke(messages)
# response.tool_calls = [{"name": "search", "args": {"query": "..."}}]
```

**Schema transmission**: LangChain converts tool schemas to OpenAI function calling format.

### Tool Validation

**ToolNode** supports validation via `ToolValidator`:

From `libs/prebuilt/langgraph/prebuilt/tool_validator.py`:

```python
class ToolValidator:
    """Validate tool arguments before execution."""

    def validate(self, tool_call: dict) -> dict:
        # Custom validation logic
        # Raise ValidationError if invalid
        # Return modified tool_call if needed
```

**Usage**:
```python
from langgraph.prebuilt import ToolNode, ValidationNode

validator = ToolValidator(...)
tools_node = ToolNode(tools)
validation_node = ValidationNode(validator)

builder.add_node("validate", validation_node)
builder.add_node("tools", tools_node)
builder.add_edge("llm", "validate")
builder.add_conditional_edges("validate", route_on_validation, {
    "valid": "tools",
    "invalid": "llm"  # Send validation errors back to LLM
})
```

### Tool Interceptors (Advanced)

`ToolNode` supports **interceptors** for modifying tool behavior:

```python
def logging_interceptor(tool_call: dict, tool: BaseTool) -> Any:
    print(f"Calling {tool.name} with {tool_call['args']}")
    result = tool.invoke(tool_call["args"])
    print(f"Result: {result}")
    return result

tool_node = ToolNode(tools, interceptor=logging_interceptor)
```

**Use cases**:
- Logging
- Monitoring
- Rate limiting
- Argument transformation

### Tool Result Formatting

**Default**: `ToolMessage` with string content
```python
ToolMessage(content="Search results: ...", tool_call_id="call_123")
```

**Custom formatting**:
```python
def custom_tool_executor(state: State) -> dict:
    tool_calls = state["messages"][-1].tool_calls
    results = []

    for call in tool_calls:
        output = execute_tool(call)

        # Format as structured data
        results.append(ToolMessage(
            content=json.dumps(output),
            tool_call_id=call["id"],
            artifact=output  # Store structured data in artifact
        ))

    return {"messages": results}
```

### Integration with LangChain Tools Ecosystem

LangChain provides 100+ prebuilt tools:
- `DuckDuckGoSearchRun`
- `WikipediaQueryRun`
- `PythonREPLTool`
- `ShellTool`
- etc.

**LangGraph usage**:
```python
from langchain_community.tools import DuckDuckGoSearchRun

search = DuckDuckGoSearchRun()
agent = create_react_agent(llm, tools=[search])
```

**No additional registration** needed - just pass the tool.

### Tool Inventory (Prebuilt Library)

From `libs/prebuilt`:

| Component | Purpose | Schema Method |
|-----------|---------|--------------|
| ToolNode | Execute tool calls | Inherits from LangChain tools |
| ToolValidator | Validate tool args | Custom |
| ValidationNode | Validation wrapper | Custom |

**All schema generation delegated to LangChain**.

### Multi-Tool Calls

**Support**: Yes (parallel execution)

```python
# LLM outputs multiple tool calls
response = llm.invoke(messages)
# response.tool_calls = [
#     {"name": "search", "args": {"query": "x"}},
#     {"name": "calculator", "args": {"expr": "2+2"}}
# ]

# ToolNode executes both
tool_node.invoke(state)
# Returns two ToolMessages
```

**Execution**: Sequential (not truly parallel, but in same step).

### Error Handling Modes

**Mode 1: Handle errors** (default)
```python
ToolNode(tools, handle_tool_errors=True)
```
- Errors converted to ToolMessage
- Graph continues
- LLM sees error, can retry

**Mode 2: Propagate errors**
```python
ToolNode(tools, handle_tool_errors=False)
```
- Errors raised as exceptions
- Graph stops
- Error captured in checkpoint

**Mode 3: Custom handler**
```python
def custom_error_handler(error: Exception) -> str:
    if isinstance(error, RateLimitError):
        return "Rate limit hit. Please retry in 60s."
    return str(error)

ToolNode(tools, handle_tool_errors=custom_error_handler)
```

### Recommendations

**Strengths**:
- Leverages LangChain's rich tool ecosystem
- Declarative tool registration (simple)
- Detailed error feedback to LLM (self-correction)
- Flexible error handling (swallow vs propagate)
- Tool validation support
- Interceptor pattern for extensibility

**Weaknesses**:
- No dynamic tool registration (static at compile time)
- No built-in retry logic at tool level (use node-level retry)
- No fallback chains (user must implement)
- Sequential tool execution (no true parallelism within step)

**Best practices to adopt**:
1. **Delegate to existing tool framework** (don't reinvent LangChain)
2. **Error feedback to LLM** (ToolMessage with error details)
3. **Configurable error handling** (handle vs propagate modes)
4. **Validator pattern** for custom validation logic
5. **Interceptor pattern** for cross-cutting concerns
6. **Declarative tool list** (simple, explicit)

**For new framework**:
- Consider **tool validation** as first-class feature
- Provide **built-in retry** at tool level (optional)
- Support **fallback chains** (tool A fails → try tool B)
- Consider **parallel tool execution** (if tools are independent)
- Keep schema generation **Pydantic-based** (good DX)
