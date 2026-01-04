# Tool Interface Analysis: swarm

## Summary
- **Tool Modeling**: Plain Python callables (no base class, no protocol, no decorators)
- **Schema Generation**: Runtime introspection via `inspect.signature()` with hardcoded type mapping
- **Registration Pattern**: Declarative list assignment to `Agent.functions`
- **Error Handling**: Asymmetric - missing tool sends error to LLM (good), execution errors crash agent (bad)
- **Built-in Tools**: 0 built-in tools - framework provides zero tooling infrastructure
- **Parallel Execution**: Supported via OpenAI API (`parallel_tool_calls=True` by default)

## Tool Modeling

### Core Abstraction

Swarm has **no tool abstraction**. Tools are raw Python callables typed as `Callable[[], Union[str, Agent, dict]]`:

```python
# From types.py
AgentFunction = Callable[[], Union[str, "Agent", dict]]

class Agent(BaseModel):
    name: str = "Agent"
    model: str = "gpt-4o"
    instructions: Union[str, Callable[[], str]] = "You are a helpful agent."
    functions: List[AgentFunction] = []
    tool_choice: str = None
    parallel_tool_calls: bool = True
```

**No base class. No protocol. No decorators. No registration ceremony.**

Tools are just functions added to a list:

```python
def get_weather(location: str) -> str:
    """Get the current weather in a given location."""
    return "{'temp':67, 'unit':'F'}"

agent = Agent(
    name="Agent",
    functions=[get_weather],
)
```

### Key Attributes

Tools have **no explicit attributes** - everything is inferred from the function signature:

| Attribute | Derived From | Method | Notes |
|-----------|--------------|--------|-------|
| name | `func.__name__` | Reflection | Function name becomes tool name |
| description | `func.__doc__` | Docstring | Empty string if no docstring |
| parameters | `inspect.signature()` | Introspection | Type annotations required |
| return type | N/A | Not used | Ignored by schema generation |
| required | `param.default == inspect._empty` | Introspection | No default = required |

### Return Value Semantics

Functions can return three types with special handling:

```python
# From core.py handle_function_result()
def handle_function_result(self, result, debug) -> Result:
    match result:
        case Result() as result:
            return result  # Return structured result
        case Agent() as agent:
            return Result(
                value=json.dumps({"assistant": agent.name}),
                agent=agent,  # Trigger agent handoff
            )
        case _:
            return Result(value=str(result))  # Cast to string
```

**Pattern**: Functions returning `Agent` trigger handoffs, `Result` provides context/agent control, everything else stringified.

## Schema Generation

### Method Used

**Automatic runtime introspection** via `inspect.signature()` with hardcoded type mapping:

```python
# From util.py
def function_to_json(func) -> dict:
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
        type(None): "null",
    }

    signature = inspect.signature(func)
    parameters = {}
    for param in signature.parameters.values():
        param_type = type_map.get(param.annotation, "string")
        parameters[param.name] = {"type": param_type}

    required = [
        param.name
        for param in signature.parameters.values()
        if param.default == inspect._empty
    ]

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

**Limitations**:
- **No support for complex types**: `List[str]`, `Optional[str]`, `Literal`, enums all fallback to `"string"`
- **No support for Pydantic models**: Cannot use structured inputs
- **No validation**: Type hints used only for schema generation, not runtime validation
- **No parameter descriptions**: Cannot add per-parameter documentation

### Magic Parameter Injection

**Context variables** are automatically injected if parameter named `context_variables`:

```python
# From core.py handle_tool_calls()
if __CTX_VARS_NAME__ in func.__code__.co_varnames:
    args[__CTX_VARS_NAME__] = context_variables

# Hidden from LLM during schema generation
for tool in tools:
    params = tool["function"]["parameters"]
    params["properties"].pop(__CTX_VARS_NAME__, None)
    if __CTX_VARS_NAME__ in params["required"]:
        params["required"].remove(__CTX_VARS_NAME__)
```

**Pattern**: Framework-controlled state injection hidden from model - good ergonomics but magic behavior.

### Generated Schema Example

```python
def get_weather(location: str, time: str = "now") -> str:
    """Get the current weather in a given location. Location MUST be a city."""
    return json.dumps({"location": location, "temperature": "65", "time": time})

# Generates:
{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather in a given location. Location MUST be a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "time": {"type": "string"}
            },
            "required": ["location"]
        }
    }
}
```

## Built-in Tool Inventory

### Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| Built-in | 0 | Framework provides zero built-in tools |

**Zero built-in tools.** Swarm is a harness, not a toolkit.

### Example Tools from Demos

The repository includes **example tools** in demos (not part of framework):

| Tool Name | Location | Schema Method | Category |
|-----------|----------|---------------|----------|
| get_weather | examples/basic/function_calling.py | Introspection | Demo |
| transfer_to_spanish_agent | examples/basic/agent_handoff.py | Introspection | Agent Control |
| print_account_details | examples/basic/context_variables.py | Introspection | Demo |
| escalate_to_agent | examples/airline/configs/tools.py | Introspection | Agent Control |
| valid_to_change_flight | examples/airline/configs/tools.py | Introspection | Business Logic |
| change_flight | examples/airline/configs/tools.py | Introspection | Action |
| initiate_refund | examples/airline/configs/tools.py | Introspection | Action |
| initiate_flight_credits | examples/airline/configs/tools.py | Introspection | Action |
| case_resolved | examples/airline/configs/tools.py | Introspection | Control Flow |
| initiate_baggage_search | examples/airline/configs/tools.py | Introspection | Action |
| query_docs | examples/support_bot/customer_service.py | Introspection | RAG |
| send_email | examples/support_bot/customer_service.py | Introspection | Notification |
| submit_ticket | examples/support_bot/customer_service.py | Introspection | Action |
| refund_item | examples/personal_shopper/main.py | Introspection | Action |
| notify_customer | examples/personal_shopper/main.py | Introspection | Notification |
| order_item | examples/personal_shopper/main.py | Introspection | Action |
| process_refund | examples/triage_agent/agents.py | Introspection | Action |
| apply_discount | examples/triage_agent/agents.py | Introspection | Action |
| transfer_back_to_triage | examples/triage_agent/agents.py | Introspection | Agent Control |
| transfer_to_sales | examples/triage_agent/agents.py | Introspection | Agent Control |
| transfer_to_refunds | examples/triage_agent/agents.py | Introspection | Agent Control |

**Pattern Observation**: Agent handoff tools (returning `Agent`) are common pattern for routing/escalation.

## Registration & Discovery

### Pattern

**Declarative list assignment** - tools registered by adding to `Agent.functions` list:

```python
# Pattern 1: Constructor assignment
agent = Agent(
    name="Sales Agent",
    functions=[order_item, notify_customer],
)

# Pattern 2: Post-construction append
def transfer_to_spanish_agent():
    return spanish_agent

english_agent.functions.append(transfer_to_spanish_agent)

# Pattern 3: Direct assignment
triage_agent.functions = [transfer_to_sales, transfer_to_refunds]
```

**No registry. No discovery. No factory. No decorators.**

### Registration Flow

```
1. Define function with type hints and docstring
2. Add to Agent.functions list
3. At runtime, get_chat_completion() converts functions to JSON:
   tools = [function_to_json(f) for f in agent.functions]
4. Schemas passed to OpenAI API
5. Model returns tool calls
6. handle_tool_calls() looks up function by name:
   function_map = {f.__name__: f for f in functions}
```

**Lifecycle**: Functions discovered at agent instantiation, schemas generated per LLM call, execution via name lookup.

## Execution Flow

### Invocation Pattern

```python
# From core.py handle_tool_calls()
def handle_tool_calls(
    self,
    tool_calls: List[ChatCompletionMessageToolCall],
    functions: List[AgentFunction],
    context_variables: dict,
    debug: bool,
) -> Response:
    function_map = {f.__name__: f for f in functions}
    partial_response = Response(messages=[], agent=None, context_variables={})

    for tool_call in tool_calls:
        name = tool_call.function.name

        # Handle missing tool - SEND ERROR TO LLM
        if name not in function_map:
            debug_print(debug, f"Tool {name} not found in function map.")
            partial_response.messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "tool_name": name,
                "content": f"Error: Tool {name} not found.",
            })
            continue

        args = json.loads(tool_call.function.arguments)
        func = function_map[name]

        # Inject context_variables if requested
        if __CTX_VARS_NAME__ in func.__code__.co_varnames:
            args[__CTX_VARS_NAME__] = context_variables

        # Execute - NO TRY/EXCEPT
        raw_result = function_map[name](**args)
        result: Result = self.handle_function_result(raw_result, debug)

        partial_response.messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "tool_name": name,
            "content": result.value,
        })
        partial_response.context_variables.update(result.context_variables)
        if result.agent:
            partial_response.agent = result.agent

    return partial_response
```

**Flow**:
1. Build name-to-function map
2. For each tool call:
   - Look up function by name
   - Parse JSON arguments
   - Inject context_variables if function signature includes it
   - **Execute with no error handling**
   - Normalize result via `handle_function_result()`
   - Append tool response message
   - Update context variables and active agent

### Error Handling

**Asymmetric error handling** - graceful for missing tools, fail-fast for execution errors:

| Error Type | Handling | Feedback to LLM | Recovery |
|------------|----------|-----------------|----------|
| Tool not found | Graceful | `"Error: Tool {name} not found."` | LLM can self-correct |
| Invalid arguments | **Crash** | None | Agent dies |
| Execution error | **Crash** | None | Agent dies |
| Type coercion failure | **Crash** | Error logged to debug | Agent dies |

```python
# GOOD: Missing tool sends error to LLM
if name not in function_map:
    partial_response.messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": f"Error: Tool {name} not found.",
    })
    continue

# BAD: No try/except around execution
raw_result = function_map[name](**args)

# BAD: Type coercion crashes agent
try:
    return Result(value=str(result))
except Exception as e:
    error_message = f"Failed to cast response to string: {result}..."
    raise TypeError(error_message)
```

**Design Decision**: Fail-fast philosophy - execution errors indicate bugs, not recoverable conditions.

### Retry Mechanisms

**None.** Framework provides:
- No retry logic
- No circuit breakers
- No timeout handling
- No validation before execution

**Rationale**: 293-line educational framework - error handling is application responsibility.

## Parallel Execution

**Supported via OpenAI API delegation**:

```python
# From core.py get_chat_completion()
create_params = {
    "model": model_override or agent.model,
    "messages": messages,
    "tools": tools or None,
    "tool_choice": agent.tool_choice,
    "stream": stream,
}

if tools:
    create_params["parallel_tool_calls"] = agent.parallel_tool_calls  # Default: True

# From types.py
class Agent(BaseModel):
    parallel_tool_calls: bool = True
```

**Implementation**:
- Parallel execution **delegated to OpenAI API**
- Framework receives multiple tool calls in single response
- Tools executed **sequentially in for loop** (no asyncio, no threads)
- Results accumulated and sent back together

```python
# Sequential execution despite parallel_tool_calls=True
for tool_call in tool_calls:
    raw_result = function_map[name](**args)  # Synchronous execution
    partial_response.messages.append(...)
```

**Pattern**: API handles parallelization, framework executes sequentially - assumes tools are fast.

## Code References

### Core Files
- `/repos/swarm/swarm/types.py:11` - `AgentFunction` type alias
- `/repos/swarm/swarm/types.py:14-21` - `Agent` class definition
- `/repos/swarm/swarm/util.py:31-87` - `function_to_json()` schema generation
- `/repos/swarm/swarm/core.py:50` - Schema generation call site
- `/repos/swarm/swarm/core.py:89-137` - `handle_tool_calls()` execution logic
- `/repos/swarm/swarm/core.py:71-87` - `handle_function_result()` return value handling

### Context Variable Injection
- `/repos/swarm/swarm/core.py:23` - `__CTX_VARS_NAME__ = "context_variables"`
- `/repos/swarm/swarm/core.py:52-56` - Hide context_variables from model
- `/repos/swarm/swarm/core.py:120-121` - Inject context_variables if requested

### Examples
- `/repos/swarm/examples/basic/function_calling.py` - Simplest tool example
- `/repos/swarm/examples/basic/agent_handoff.py` - Agent return pattern
- `/repos/swarm/examples/basic/context_variables.py` - Context injection
- `/repos/swarm/examples/airline/configs/tools.py` - Business logic tools
- `/repos/swarm/examples/support_bot/customer_service.py` - RAG + action tools

## Implications for New Framework

### Positive Patterns

1. **Minimal Ceremony**: Plain functions with type hints - zero boilerplate
   - **Implication**: Maximize developer ergonomics by reducing friction

2. **Docstring as Description**: Reuses existing Python idioms
   - **Implication**: Leverage standard practices over custom metadata

3. **Magic Parameter Injection**: `context_variables` auto-injected but hidden from LLM
   - **Implication**: Framework state can be transparently available without polluting schemas

4. **Agent Return Pattern**: Tools returning `Agent` trigger handoffs
   - **Implication**: Elegant routing/escalation without special tool types

5. **Graceful Missing Tool Handling**: Sends error to LLM for self-correction
   - **Implication**: Enables model-driven error recovery

6. **Result Type Flexibility**: `Result` object provides optional control over context/agent
   - **Implication**: Simple tools return strings, complex tools return structured results

### Considerations

1. **Limited Type Support**: Only 7 primitive types, no complex types
   - **Trade-off**: Simple implementation vs. expressive schemas
   - **Solution**: Use Pydantic for schema generation to support complex types

2. **No Validation**: Type hints used only for schema, not runtime checks
   - **Risk**: Runtime type errors crash agent
   - **Solution**: Add Pydantic validation layer or structured error handling

3. **No Parameter Descriptions**: Cannot document individual parameters
   - **Limitation**: Model only sees function docstring
   - **Solution**: Support per-parameter descriptions via decorator or Pydantic

4. **No Error Recovery**: Execution errors crash agent
   - **Philosophy**: Fail-fast for prototyping
   - **Solution**: Add configurable error handling (strict vs. graceful modes)

5. **Sequential Execution**: No true parallelization despite `parallel_tool_calls=True`
   - **Impact**: Long-running tools block other calls
   - **Solution**: Use asyncio for concurrent execution

6. **No Telemetry**: No hooks for observability
   - **Gap**: Cannot track tool usage, errors, latency
   - **Solution**: Add structured logging and tracing hooks

## Anti-Patterns Observed

### 1. Silent Type Fallback

```python
param_type = type_map.get(param.annotation, "string")
```

**Issue**: Unknown types silently fallback to `"string"` - no warning, no error.

**Risk**: Complex types like `List[str]` become `"string"`, causing runtime failures.

**Better Approach**: Raise error or log warning for unsupported types.

### 2. No Execution Error Handling

```python
raw_result = function_map[name](**args)  # Can raise any exception
```

**Issue**: Any error in tool execution crashes entire agent.

**Risk**: One bad tool call terminates conversation.

**Better Approach**: Wrap in try/except, send error to LLM, allow recovery.

### 3. Magic Constants

```python
__CTX_VARS_NAME__ = "context_variables"
if __CTX_VARS_NAME__ in func.__code__.co_varnames:
    args[__CTX_VARS_NAME__] = context_variables
```

**Issue**: Magic string checked at runtime via introspection.

**Risk**: Typos in parameter name cause silent failures.

**Better Approach**: Use decorator or explicit registration for injected parameters.

### 4. No Schema Caching

```python
# From core.py - called on EVERY LLM request
tools = [function_to_json(f) for f in agent.functions]
```

**Issue**: Schema regenerated on every completion call via introspection.

**Performance**: Unnecessary overhead for static function signatures.

**Better Approach**: Cache schemas at agent construction, invalidate on function list change.

### 5. No Timeout Protection

```python
raw_result = function_map[name](**args)  # No timeout, can block forever
```

**Issue**: Long-running or hung tools block agent indefinitely.

**Risk**: Network calls, external APIs, infinite loops freeze agent.

**Better Approach**: Add configurable timeouts with graceful degradation.

## Design Philosophy

**Swarm is intentionally minimal** - 293 lines of core code, zero built-in tools, minimal abstractions.

**Strengths**:
- Extremely low barrier to entry
- Easy to understand and modify
- Maximum flexibility - bring your own tools

**Weaknesses**:
- No production-ready error handling
- No observability
- No complex type support
- No validation layer

**Target Audience**: Prototyping and education, not production systems.

**Lesson for New Framework**: Start with Swarm's ergonomics (plain functions, minimal ceremony), add production-grade features (validation, error recovery, observability) as opt-in layers.
