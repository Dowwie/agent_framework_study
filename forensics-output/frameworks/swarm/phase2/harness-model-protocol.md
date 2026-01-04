# Harness-Model Protocol Analysis: Swarm

## Summary
- **Key Finding 1**: Complete vendor lock-in - Direct use of OpenAI SDK types throughout, no abstraction layer
- **Key Finding 2**: Wire format is pure OpenAI Chat Completions API with native function calling (no prompt-based tool use)
- **Key Finding 3**: Streaming uses Python generator pattern with manual SSE-style chunk merging but no actual SSE protocol
- **Classification**: Zero-abstraction OpenAI-native framework - educational prototype, not production-ready

## Detailed Analysis

### Message Protocol

**Wire Format Family**: OpenAI-compatible (native, not adapted)

**Providers Supported**: OpenAI only
- Primary client: `openai.OpenAI` (swarm/core.py:8, 29)
- No adapters, no abstraction layer
- Direct dependency on OpenAI SDK types throughout codebase

**Abstraction Strategy**: None - Direct coupling

The framework makes zero attempt to abstract away the provider interface. It directly imports and uses OpenAI SDK types:

```python
# swarm/types.py:1-5
from openai.types.chat import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)

# swarm/core.py:27-30
class Swarm:
    def __init__(self, client=None):
        if not client:
            client = OpenAI()
        self.client = client
```

**Internal Message Format**: Mix of OpenAI types and plain dicts

During execution, messages are stored as plain Python dicts to avoid coupling to OpenAI types (ironically, given the heavy coupling elsewhere):

```python
# swarm/core.py:270-273
message.sender = active_agent.name
history.append(
    json.loads(message.model_dump_json())
)  # to avoid OpenAI types (?)
```

The comment reveals uncertainty about the framework's own design decisions. This suggests the authors recognized the coupling problem but only addressed it partially.

**Message Structure**:
```python
# User messages
{"role": "user", "content": "text"}

# Assistant messages
{
    "role": "assistant",
    "content": "text",
    "sender": "agent_name",  # Custom field, not in OpenAI spec
    "tool_calls": [...]  # Optional
}

# Tool result messages
{
    "role": "tool",
    "tool_call_id": "call_id",
    "tool_name": "function_name",
    "content": "result"
}
```

### Tool Call Encoding

**Request Method**: OpenAI Function Calling API (native)

**Schema Transmission**: OpenAI `tools` parameter format

Tool schemas are auto-generated from Python function signatures and sent directly in the OpenAI format:

```python
# swarm/util.py:31-87
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

# swarm/core.py:50-68
tools = [function_to_json(f) for f in agent.functions]

# Hide context_variables from model
for tool in tools:
    params = tool["function"]["parameters"]
    params["properties"].pop(__CTX_VARS_NAME__, None)
    if __CTX_VARS_NAME__ in params["required"]:
        params["required"].remove(__CTX_VARS_NAME__)

create_params = {
    "model": model_override or agent.model,
    "messages": messages,
    "tools": tools or None,
    "tool_choice": agent.tool_choice,
    "stream": stream,
}

if tools:
    create_params["parallel_tool_calls"] = agent.parallel_tool_calls
```

**Type Mapping Limitations**:

The schema generator only supports basic Python types. Any complex type (generics, Pydantic models, Literal, Optional, Union) defaults to "string":

```python
type_map.get(param.annotation, "string")  # Unknown types become "string"
```

**Supported**: str, int, float, bool, list, dict, None
**Not supported**: List[str], Optional[int], Literal["a", "b"], Pydantic models, enums

**Response Parsing**: Direct use of OpenAI SDK types

```python
# swarm/core.py:268, 280-281
message = completion.choices[0].message
# message is ChatCompletionMessage from OpenAI SDK

partial_response = self.handle_tool_calls(
    message.tool_calls,  # ChatCompletionMessageToolCall[] from OpenAI
    active_agent.functions,
    context_variables,
    debug
)
```

**Tool Choice Support**:

| Feature | Support | Implementation |
|---------|---------|----------------|
| No tool constraint | Yes | `tool_choice=None` (default) |
| Auto (LLM decides) | Yes | Via OpenAI default behavior |
| Required | Yes | `tool_choice="required"` |
| Specific tool | Yes | `tool_choice={"type": "function", "function": {"name": "..."}}` |
| Parallel tool calls | Yes | `parallel_tool_calls=True` (default) |

However, parallel tool calls are executed **sequentially** despite the flag:

```python
# swarm/core.py:100-136
for tool_call in tool_calls:  # Sequential loop, not parallel
    name = tool_call.function.name
    # ...
    raw_result = function_map[name](**args)
```

**Tool Invocation Flow**:

1. LLM returns tool calls in `message.tool_calls`
2. Framework builds function map: `{f.__name__: f for f in functions}`
3. For each tool call:
   - Parse arguments: `json.loads(tool_call.function.arguments)` (no try/catch)
   - Inject context if needed: `args["context_variables"] = context_variables`
   - Execute directly: `function_map[name](**args)` (no try/catch)
   - Convert result to string
   - Append to history as tool message

**Error Handling**:

| Error Type | Handling | Impact |
|------------|----------|--------|
| Missing tool | Graceful | Sends error to LLM for self-correction |
| Invalid JSON args | None | Crashes entire agent run |
| Tool execution error | None | Crashes entire agent run |
| Type mismatch | None | Python raises TypeError, crashes |

Only missing tools are handled gracefully:

```python
# swarm/core.py:103-113
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

### Streaming Implementation

**Protocol**: Python Generator (not SSE, not WebSocket)

The framework uses Python's generator pattern, not an actual network streaming protocol. When `stream=True`, the `run()` method returns a generator that yields chunks:

```python
# swarm/core.py:242-251
def run(..., stream: bool = False, ...) -> Response:
    if stream:
        return self.run_and_stream(...)  # Returns generator
    # else: synchronous execution
```

**Streaming Flow**:

```python
# swarm/core.py:139-229
def run_and_stream(...):
    while len(history) - init_len < max_turns:
        message = {
            "content": "",
            "sender": agent.name,
            "role": "assistant",
            "tool_calls": defaultdict(lambda: {...})  # Accumulator
        }

        # Get OpenAI streaming completion
        completion = self.get_chat_completion(..., stream=True, ...)

        yield {"delim": "start"}

        for chunk in completion:  # OpenAI SDK stream chunks
            delta = json.loads(chunk.choices[0].delta.json())
            if delta["role"] == "assistant":
                delta["sender"] = active_agent.name
            yield delta  # Forward chunk to consumer
            delta.pop("role", None)
            delta.pop("sender", None)
            merge_chunk(message, delta)  # Accumulate

        yield {"delim": "end"}

        # Continue with tool execution...

    yield {"response": Response(...)}  # Final result
```

**Partial Tool Call Handling**: Supported via accumulator pattern

The framework correctly handles partial tool calls by accumulating chunks:

```python
# swarm/util.py:21-28
def merge_chunk(final_response: dict, delta: dict) -> None:
    delta.pop("role", None)
    merge_fields(final_response, delta)

    tool_calls = delta.get("tool_calls")
    if tool_calls and len(tool_calls) > 0:
        index = tool_calls[0].pop("index")
        merge_fields(final_response["tool_calls"][index], tool_calls[0])

def merge_fields(target, source):
    for key, value in source.items():
        if isinstance(value, str):
            target[key] += value  # String concatenation for partial content
        elif value is not None and isinstance(value, dict):
            merge_fields(target[key], value)  # Recursive merge
```

**Event Types Emitted**:

| Event | Structure | Purpose |
|-------|-----------|---------|
| Delimiter start | `{"delim": "start"}` | Mark beginning of LLM response |
| Content delta | `{"content": "text"}` | Partial text from LLM |
| Tool call delta | `{"tool_calls": [...]}` | Partial tool call (name, args) |
| Sender info | `{"sender": "agent_name"}` | Identify active agent |
| Delimiter end | `{"delim": "end"}` | Mark end of LLM response |
| Final response | `{"response": Response(...)}` | Complete run result |

**Consumer Pattern**:

```python
# swarm/repl/repl.py:6-34
def process_and_print_streaming_response(response):
    content = ""
    last_sender = ""

    for chunk in response:
        if "sender" in chunk:
            last_sender = chunk["sender"]

        if "content" in chunk and chunk["content"] is not None:
            if not content and last_sender:
                print(f"{last_sender}:", end=" ", flush=True)
                last_sender = ""
            print(chunk["content"], end="", flush=True)
            content += chunk["content"]

        if "tool_calls" in chunk and chunk["tool_calls"] is not None:
            for tool_call in chunk["tool_calls"]:
                f = tool_call["function"]
                name = f["name"]
                if not name:
                    continue
                print(f"{last_sender}: {name}()")

        if "delim" in chunk and chunk["delim"] == "end" and content:
            print()  # End of response message
            content = ""

        if "response" in chunk:
            return chunk["response"]
```

**Streaming Characteristics**:

- Uses OpenAI SDK's native streaming (SSE under the hood, but abstracted away)
- Chunks are immediately yielded (no buffering)
- Tool execution is NOT streamed (tools run after LLM completes)
- Consumer must accumulate chunks to reconstruct full message
- No backpressure mechanism
- No error events in stream (errors raise exceptions)

### Agentic Primitives

#### System Prompt Assembly

**Method**: Dynamic evaluation at each turn

```python
# swarm/core.py:41-47
context_variables = defaultdict(str, context_variables)
instructions = (
    agent.instructions(context_variables)
    if callable(agent.instructions)
    else agent.instructions
)
messages = [{"role": "system", "content": instructions}] + history
```

**Features**:
- Supports static strings: `instructions="You are a helpful agent."`
- Supports dynamic functions: `instructions=lambda ctx: f"You are {ctx['user_name']}'s assistant"`
- Re-evaluated every turn (allows context-aware prompting)
- System message always prepended to history

**Example from types.py**:

```python
# swarm/types.py:14-21
class Agent(BaseModel):
    name: str = "Agent"
    model: str = "gpt-4o"
    instructions: Union[str, Callable[[], str]] = "You are a helpful agent."
    functions: List[AgentFunction] = []
    tool_choice: str = None
    parallel_tool_calls: bool = True
```

#### Scratchpad / Working Memory

**Not implemented** - No explicit scratchpad or chain-of-thought mechanism

The framework relies on the LLM's native reasoning within the context window. There is no:
- Explicit scratchpad field
- Forced chain-of-thought prompting
- Reasoning trace storage

However, the full conversation history acts as an implicit scratchpad:
- All messages preserved in history (until context overflow)
- Tool results visible to LLM in subsequent turns
- Agent handoff messages become part of history

#### Interrupt / Human-in-the-Loop

**Not implemented** - No built-in HITL mechanism

The framework provides no native support for:
- Approval workflows before tool execution
- Mid-run interrupts
- Human confirmation requests

However, HITL can be implemented externally:

```python
# Hypothetical HITL pattern (not built-in)
response = client.run(agent=agent, messages=messages, execute_tools=False)

for message in response.messages:
    if message.get("tool_calls"):
        for tool_call in message["tool_calls"]:
            print(f"Agent wants to call {tool_call['function']['name']}")
            if input("Approve? (y/n): ") == 'y':
                # Execute tools manually
                pass
```

The `execute_tools` parameter (swarm/core.py:147, 240) allows disabling automatic tool execution, but there's no built-in confirmation UI.

#### Conversation State Machine

**Implicit state machine** in the run loop:

```
[Get LLM Response]
    → [Check for tool calls]
        → If no tool calls: END
        → If tool calls: [Execute tools] → [Check max_turns] → [Get LLM Response]
```

**States**:
1. **Waiting for LLM** - Calling `client.chat.completions.create()`
2. **Processing tool calls** - Executing tools, accumulating results
3. **Agent handoff** - Switching active agent if tool returned Agent
4. **Terminal** - No more tool calls or max_turns reached

**Termination conditions**:
- LLM doesn't request tool calls: `if not message.tool_calls` (core.py:275)
- Max turns reached: `while len(history) - init_len < max_turns` (core.py:257)
- `execute_tools=False` parameter set (core.py:275)

**No explicit state tracking** - state is implicit in loop variables.

### Provider Abstraction

**Zero abstraction** - Framework is OpenAI-only

| Provider | Support | Adapter Location | Notes |
|----------|---------|------------------|-------|
| OpenAI | Native | swarm/core.py:8, 29 | Direct OpenAI SDK usage |
| Anthropic | No | N/A | Would require forking framework |
| Google Gemini | No | N/A | Would require forking framework |
| Azure OpenAI | Possible | N/A | Could pass Azure client to `Swarm(client=azure_client)` |
| Local models | No | N/A | No OpenAI-compatible server support |

**Theoretical multi-provider support**:

The only abstraction point is the client injection:

```python
# swarm/core.py:27-30
class Swarm:
    def __init__(self, client=None):
        if not client:
            client = OpenAI()
        self.client = client
```

This allows passing a custom client, but:
1. Client must match OpenAI SDK interface exactly
2. Message types must be OpenAI types (ChatCompletionMessage, etc.)
3. Tool call format must match OpenAI's function calling API
4. No adapter layer to translate between formats

**Vendor lock-in points**:

```python
# swarm/types.py:1-5
from openai.types.chat import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)

# swarm/core.py:268
message = completion.choices[0].message  # Expects OpenAI response structure

# swarm/core.py:280-281
partial_response = self.handle_tool_calls(
    message.tool_calls,  # Expects OpenAI ChatCompletionMessageToolCall[]
    ...
)
```

**No message translation layer** - Framework assumes OpenAI message format throughout.

### Context Variables (Hidden State Channel)

A unique pattern in Swarm is the `context_variables` mechanism for passing state to tools without exposing it to the LLM:

```python
# swarm/core.py:23
__CTX_VARS_NAME__ = "context_variables"

# Tool function with context access
def send_email(to: str, message: str, context_variables: dict) -> str:
    user_id = context_variables["user_id"]  # Available, LLM didn't provide
    api_key = context_variables["api_key"]  # Sensitive data hidden from LLM
    # Send email...

# Framework auto-detects and injects
# swarm/core.py:120-121
if __CTX_VARS_NAME__ in func.__code__.co_varnames:
    args[__CTX_VARS_NAME__] = context_variables
```

This is removed from tool schemas before sending to LLM:

```python
# swarm/core.py:52-56
for tool in tools:
    params = tool["function"]["parameters"]
    params["properties"].pop(__CTX_VARS_NAME__, None)
    if __CTX_VARS_NAME__ in params["required"]:
        params["required"].remove(__CTX_VARS_NAME__)
```

**Use cases**:
- Session state (user_id, session_token)
- API credentials (keys, passwords)
- Database connections
- Configuration objects

**Persistence**: Tools can update context_variables for future tools:

```python
# swarm/core.py:133
partial_response.context_variables.update(result.context_variables)
```

## Code References

**Core protocol files**:
- swarm/core.py:27-30 - Swarm client initialization
- swarm/core.py:32-69 - `get_chat_completion()` - LLM request construction
- swarm/core.py:89-137 - `handle_tool_calls()` - Tool execution
- swarm/core.py:139-229 - `run_and_stream()` - Streaming implementation
- swarm/core.py:231-292 - `run()` - Main execution loop

**Type definitions**:
- swarm/types.py:1-5 - OpenAI type imports (vendor coupling)
- swarm/types.py:14-21 - Agent configuration
- swarm/types.py:23-27 - Response structure
- swarm/types.py:29-42 - Result type for tool returns

**Schema generation**:
- swarm/util.py:31-87 - `function_to_json()` - Tool schema generator
- swarm/util.py:13-23 - `merge_chunk()` - Streaming accumulator

**Streaming utilities**:
- swarm/repl/repl.py:6-34 - Stream consumer example

**Testing/Mocking**:
- tests/mock_client.py:44-68 - Mock OpenAI client (shows coupling)

## Implications for New Framework

### Positive Patterns

1. **Dynamic instruction evaluation** - Allows context-aware system prompts
   ```python
   instructions=lambda ctx: f"You are {ctx['user_name']}'s assistant"
   ```

2. **Graceful missing tool handling** - Sends error to LLM instead of crashing
   ```python
   if name not in function_map:
       return {"role": "tool", "content": f"Error: Tool {name} not found."}
   ```

3. **Context variables pattern** - Hidden state channel for sensitive data
   ```python
   # LLM can't see API keys, but tools can access them
   context_variables={"api_key": "secret"}
   ```

4. **Deep copy isolation** - Prevent caller state mutation
   ```python
   history = copy.deepcopy(messages)  # Immutability at API boundary
   ```

5. **Streaming chunk accumulator** - Correctly handles partial tool calls
   ```python
   # merge_chunk() properly concatenates partial strings and nested objects
   ```

6. **Tool-based agent handoff** - Elegant multi-agent pattern
   ```python
   def transfer_to_sales() -> Agent:
       return sales_agent
   ```

### Considerations

1. **Abstraction layer required** - Cannot support multiple providers without fundamental refactor

2. **Type system improvements needed** - Support Pydantic models, Literal, Optional, etc.

3. **Comprehensive error handling** - Wrap tool execution, handle malformed JSON, validate schemas

4. **Token management critical** - Unbounded history will crash on long conversations

5. **Async support essential** - Blocking I/O on every API call prevents high-concurrency use

6. **Streaming protocol decision** - Choose between:
   - Python generators (like Swarm) - simple but Python-only
   - SSE - standard, works across languages/networks
   - WebSocket - bidirectional, more complex

7. **Provider abstraction strategy**:
   - Option A: Universal message type (translate all providers to common format)
   - Option B: Provider-native types with adapter layer
   - Option C: Protocol-based (structural typing, any matching interface)

## Anti-Patterns Observed

### 1. Zero Abstraction / Complete Vendor Lock-In

**Issue**: Direct OpenAI SDK types used throughout, no abstraction layer

```python
# swarm/types.py:1-5
from openai.types.chat import ChatCompletionMessage  # Direct coupling
from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall

# Impossible to support other providers without forking
```

**Impact**: Cannot support Anthropic, Gemini, local models, etc. without complete rewrite

**Fix**: Create provider protocol:
```python
class LLMProvider(Protocol):
    def chat_completion(self, messages: List[Message], tools: List[Tool]) -> Response:
        ...

    def stream_completion(self, ...) -> Iterator[Chunk]:
        ...
```

### 2. No Tool Execution Error Handling

**Issue**: Single tool exception crashes entire agent run

```python
# swarm/core.py:114, 122
args = json.loads(tool_call.function.arguments)  # No try/catch - JSONDecodeError crashes
raw_result = function_map[name](**args)  # No try/catch - tool errors crash
```

**Impact**: Production fragility, no LLM self-correction opportunity

**Fix**: Wrap in try/except, send errors to LLM:
```python
try:
    args = json.loads(tool_call.function.arguments)
    raw_result = function_map[name](**args)
except json.JSONDecodeError as e:
    content = f"Error: Invalid JSON arguments - {str(e)}"
except Exception as e:
    content = f"Error executing {name}: {str(e)}"
finally:
    return {"role": "tool", "tool_call_id": tool_call.id, "content": content}
```

### 3. Limited Type Support in Schema Generation

**Issue**: Only basic types supported (str, int, float, bool, list, dict)

```python
# swarm/util.py:43-51, 63
type_map = {str: "string", int: "integer", ...}
param_type = type_map.get(param.annotation, "string")  # Unknown → "string"
```

**Impact**: No support for List[str], Optional[int], Pydantic models, enums

**Fix**: Implement full JSON Schema generation:
```python
def annotation_to_json_schema(annotation):
    if hasattr(annotation, "__origin__"):  # Generic type
        if annotation.__origin__ is list:
            return {"type": "array", "items": annotation_to_json_schema(annotation.__args__[0])}
        elif annotation.__origin__ is Union:
            # Handle Optional, Union
            ...
    elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
        # Pydantic model - use model_json_schema()
        return annotation.model_json_schema()
```

### 4. Sequential Tool Execution Despite Parallel Flag

**Issue**: `parallel_tool_calls=True` sent to API, but tools run sequentially

```python
# swarm/core.py:67
create_params["parallel_tool_calls"] = agent.parallel_tool_calls

# swarm/core.py:100
for tool_call in tool_calls:  # Sequential loop!
    raw_result = function_map[name](**args)
```

**Impact**: Misleading configuration, missed performance optimization

**Fix**: Use async execution:
```python
async def execute_tools_parallel(tool_calls, function_map):
    tasks = [execute_tool(tc, function_map) for tc in tool_calls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
```

### 5. Magic Parameter Injection

**Issue**: `context_variables` detection via introspection is implicit

```python
# swarm/core.py:120-121
if __CTX_VARS_NAME__ in func.__code__.co_varnames:
    args[__CTX_VARS_NAME__] = context_variables
```

**Impact**: Not obvious from function signature, confuses static analysis

**Fix**: Use decorator or explicit type annotation:
```python
@inject_context
def send_email(to: str, message: str) -> str:
    ctx = get_context()  # Explicit access
    ...

# Or: use type hints
def send_email(to: str, message: str, ctx: Annotated[dict, InjectedContext]) -> str:
    ...
```

### 6. No Schema Validation Before Tool Execution

**Issue**: Framework trusts LLM to provide correct arguments

```python
# swarm/core.py:114, 122
args = json.loads(tool_call.function.arguments)
raw_result = function_map[name](**args)  # No validation
```

**Impact**: Type errors crash instead of gracefully handling

**Fix**: Validate against schema before calling:
```python
schema = tool_schemas[name]
try:
    validate_json(args, schema)
    result = function_map[name](**args)
except ValidationError as e:
    return {"role": "tool", "content": f"Validation error: {e}"}
```

### 7. Unbounded Memory Growth

**Issue**: History grows indefinitely, no token counting or truncation

```python
# swarm/core.py:196, 218, 271
history.append(message)  # Always append, never truncate
history.extend(partial_response.messages)
```

**Impact**: Long conversations hit context limits and crash

**Fix**: Implement token budget with automatic truncation:
```python
def enforce_token_budget(history, max_tokens):
    current = count_tokens(history)
    while current > max_tokens and len(history) > 1:
        history.pop(1)  # Keep system message, remove oldest
        current = count_tokens(history)
    return history
```

### 8. Comment Reveals Design Uncertainty

**Issue**: Comment suggests authors unsure of serialization strategy

```python
# swarm/core.py:272-273
history.append(
    json.loads(message.model_dump_json())
)  # to avoid OpenAI types (?)
```

The `(?)` reveals uncertainty. If avoiding OpenAI types is the goal, why import them as framework types in types.py?

**Impact**: Indicates lack of clear architectural vision for provider abstraction

**Fix**: Make a clear decision:
- Option A: Use OpenAI types everywhere (accept lock-in)
- Option B: Define framework types, translate at boundaries
- Option C: Use protocol-based approach (structural typing)

### 9. No Async Support

**Issue**: Fully synchronous, blocks on every API call

```python
# swarm/core.py:27-30
def __init__(self, client=None):
    if not client:
        client = OpenAI()  # Sync client, not AsyncOpenAI
```

**Impact**: Cannot scale to high-concurrency scenarios

**Fix**: Provide async variants:
```python
class AsyncSwarm:
    def __init__(self, client=None):
        if not client:
            client = AsyncOpenAI()

    async def run(self, agent, messages, ...):
        completion = await self.client.chat.completions.create(...)
        ...
```

### 10. No Provider Feature Detection

**Issue**: Assumes all features available (tool_choice, parallel_tool_calls, streaming)

```python
# swarm/core.py:58-68
create_params = {
    "model": model_override or agent.model,
    "messages": messages,
    "tools": tools or None,
    "tool_choice": agent.tool_choice,  # Not all models support this
    "stream": stream,
}

if tools:
    create_params["parallel_tool_calls"] = agent.parallel_tool_calls
```

**Impact**: Would fail with providers/models that don't support these features

**Fix**: Implement feature detection:
```python
class ProviderCapabilities:
    supports_tool_choice: bool
    supports_parallel_tools: bool
    supports_streaming: bool
    max_context_tokens: int

def build_request(agent, history, capabilities):
    params = {"model": agent.model, "messages": history}
    if capabilities.supports_tool_choice:
        params["tool_choice"] = agent.tool_choice
    # etc.
```

## Summary

Swarm's harness-model protocol is **intentionally simple and OpenAI-native**. It's designed as an educational framework to demonstrate agent patterns, not as a production-ready multi-provider abstraction layer.

**Strengths**:
- Clean, readable code (380 lines)
- Correct streaming implementation with chunk accumulation
- Graceful missing tool handling
- Elegant context variables pattern
- Dynamic instruction evaluation

**Critical Weaknesses for Production**:
- Complete vendor lock-in to OpenAI
- No error resilience (tool errors crash agent)
- No token management (unbounded growth)
- No async support (blocking I/O)
- Limited type support (only basic types)
- No schema validation

**For a new production framework**, adopt the positive patterns (dynamic instructions, context variables, graceful missing tools) while addressing the anti-patterns with:
1. Provider abstraction layer (protocol-based or adapter pattern)
2. Comprehensive error handling (try/catch around all external calls)
3. Token budget enforcement (automatic truncation/summarization)
4. Async support (AsyncOpenAI, asyncio.gather for parallel tools)
5. Rich type system (Pydantic models, full JSON Schema)
6. Schema validation before tool execution
7. Feature detection and graceful degradation
