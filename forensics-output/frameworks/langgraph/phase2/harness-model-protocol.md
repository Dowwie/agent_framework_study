# Harness-Model Protocol Analysis: LangGraph

## Summary
- **Key Finding 1**: LangGraph delegates ALL LLM interaction to LangChain Core - it has zero native protocol handling
- **Key Finding 2**: Framework is provider-agnostic by design - tool calling, streaming, and message formatting are LangChain's responsibility
- **Key Finding 3**: State-based architecture with message reducers - framework orchestrates execution, not prompts
- **Classification**: **Delegated Abstraction** - LangGraph is a graph execution engine that outsources model protocol concerns entirely to LangChain

## Detailed Analysis

### Message Protocol

**Wire Format Family**: Delegated to LangChain Core (supports OpenAI-compatible, Anthropic-native, Gemini-native, etc.)

**Providers Supported**: Any provider supported by LangChain
- LangChain abstracts: `langchain-openai`, `langchain-anthropic`, `langchain-google-genai`, `langchain-fireworks`, etc.
- LangGraph imports: `langchain_core.language_models.BaseChatModel`
- Location: `/libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:13-17`

**Abstraction Strategy**: Complete delegation - LangGraph never touches wire protocol

**Architecture**:
```python
# LangGraph only knows about LangChain's abstraction
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage

# User provides ANY LangChain-compatible model
model = ChatOpenAI()  # or ChatAnthropic(), ChatGoogleGenerativeAI(), etc.

# LangGraph invokes via LangChain's Runnable protocol
response = model.invoke(messages, config)  # LangChain handles wire format
```

**Message Type System**: LangChain's native types
```python
# From langchain_core.messages
- BaseMessage (abstract)
  - AIMessage (assistant responses, tool calls)
  - HumanMessage (user inputs)
  - SystemMessage (system prompts)
  - ToolMessage (tool execution results)
  - RemoveMessage (state eviction marker)
```

**State Representation**: Append-only message list with custom reducer
```python
# libs/langgraph/langgraph/graph/message.py:307-308
class MessagesState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]

# add_messages reducer handles:
# - Message deduplication by ID
# - Message updates (same ID overwrites)
# - Message removal (RemoveMessage marker)
# - Format conversion (optional OpenAI format)
```

**No Native Protocol Handling**: LangGraph has ZERO code for:
- JSON schema generation for tools
- Tool call request/response formatting
- Provider-specific message serialization
- Token counting or context window management

### Tool Call Encoding

**Request Method**: Delegated to LangChain's `bind_tools()` API

**Schema Transmission**: LangChain converts Pydantic schemas to provider formats
```python
# libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:572-577
if _should_bind_tools(model, tool_classes, num_builtin=len(llm_builtin_tools)):
    model = cast(BaseChatModel, model).bind_tools(
        tool_classes + llm_builtin_tools
    )

# LangChain's bind_tools() handles:
# - Converting Pydantic models to JSON Schema
# - Translating schemas to provider format (OpenAI function calling, Anthropic tools, etc.)
# - Attaching schemas to model configuration
```

**Tool Call Detection**: Check `AIMessage.tool_calls` attribute
```python
# libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:824
last_message = messages[-1]
if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
    return END  # No tool calls, finish
else:
    return "tools"  # Execute tools
```

**Tool Call Structure**: LangChain's standardized format
```python
# AIMessage.tool_calls is a list of dicts:
[
    {
        "name": "search",
        "args": {"query": "weather"},
        "id": "call_abc123",
        "type": "tool_call"
    }
]
# Provider-agnostic - LangChain handles parsing from provider-specific formats
```

**Response Parsing**: Automatic via LangChain
```python
# libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:666-668
response = cast(AIMessage, dynamic_model.invoke(model_input, config))

# LangChain's invoke():
# 1. Sends request in provider format
# 2. Receives provider-specific response
# 3. Parses tool calls into standardized AIMessage.tool_calls
# 4. Returns AIMessage with tool_calls populated
```

**Tool Execution**: ToolNode handles invocation
```python
# libs/prebuilt/langgraph/prebuilt/tool_node.py:610-700
class ToolNode(RunnableCallable):
    def invoke(self, input, config):
        # Extract tool calls from last AIMessage
        tool_calls = input["messages"][-1].tool_calls

        # Execute each tool
        for call in tool_calls:
            tool = self.tools_by_name[call["name"]]
            output = tool.invoke(call["args"], config)

            # Return ToolMessage with result
            tool_messages.append(
                ToolMessage(
                    content=output,
                    tool_call_id=call["id"]
                )
            )
```

**Tool Choice Support**: Provider-dependent via LangChain
- LangChain models support `tool_choice` parameter
- LangGraph doesn't enforce or validate tool choice
- Example: `model.bind_tools(tools, tool_choice="auto")`

**Validation Strategy**: Multi-layered
1. **Schema validation**: Pydantic (via LangChain's tool decorator)
2. **Argument injection filtering**: ToolNode removes injected args from error messages
```python
# libs/prebuilt/langgraph/prebuilt/tool_node.py:500-553
def _filter_validation_errors(validation_error, injected_args):
    # Only show errors for LLM-controlled arguments
    # Hide errors for state/store/runtime injected by framework
    filtered_errors = [
        error for error in validation_error.errors()
        if error["loc"][0] not in injected_arg_names
    ]
```

**Tool Call Attribution**: Strict ID matching
```python
# libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:238-266
def _validate_chat_history(messages):
    all_tool_calls = [tc for msg in messages if isinstance(msg, AIMessage) for tc in msg.tool_calls]
    tool_call_ids_with_results = {msg.tool_call_id for msg in messages if isinstance(msg, ToolMessage)}

    # Ensure every tool call has a corresponding ToolMessage
    tool_calls_without_results = [
        tc for tc in all_tool_calls if tc["id"] not in tool_call_ids_with_results
    ]
    if tool_calls_without_results:
        raise ValueError("Every tool call MUST have a corresponding ToolMessage")
```

### Streaming Implementation

**Protocol**: Delegated to LangChain's streaming + LangGraph's multi-mode streaming

**Stream Modes** (from `libs/langgraph/langgraph/types.py:91-100`):
```python
StreamMode = Literal[
    "values",      # Emit full state after each step
    "updates",     # Emit only node outputs (deltas)
    "checkpoints", # Emit checkpoint metadata
    "tasks",       # Emit task execution info
    "debug",       # Emit detailed execution traces
    "messages",    # Emit BaseMessage objects as they're generated
    "custom"       # User-defined events via StreamWriter
]
```

**Message Streaming** (LLM token streaming):
```python
# libs/langgraph/langgraph/pregel/_messages.py:29-172
class StreamMessagesHandler(BaseCallbackHandler):
    """Callback handler for stream_mode=messages

    Collects messages from:
    1. LLM streaming chunks (on_llm_new_token)
    2. Node outputs (on_chain_end)
    """

    def on_llm_new_token(self, token, *, chunk, run_id, **kwargs):
        # LangChain's streaming API provides chunks
        if isinstance(chunk, ChatGenerationChunk):
            self._emit(meta, chunk.message)

    def on_llm_end(self, response, *, run_id, **kwargs):
        # Final message after streaming completes
        if isinstance(gen, ChatGeneration):
            self._emit(meta, gen.message, dedupe=True)
```

**Partial Tool Call Handling**: LangChain's responsibility
- LangGraph receives complete `AIMessage.tool_calls` from LangChain
- LangChain's streaming parsers accumulate partial tool calls
- LangGraph sees final, complete tool calls only

**Event Types Emitted**:

| Mode | Event Structure | When Emitted | Content |
|------|-----------------|--------------|---------|
| `values` | `{node_name: state}` | After each step | Full state snapshot |
| `updates` | `{node_name: update}` | After each node | Node output delta |
| `messages` | `(namespace, "messages", (message, metadata))` | During LLM streaming + node completion | BaseMessage objects |
| `checkpoints` | `(namespace, "checkpoints", metadata)` | After each step | Checkpoint metadata |
| `debug` | `(namespace, "debug", task_info)` | Task start/end | Execution traces |
| `custom` | `(namespace, "custom", data)` | User-defined | User data via StreamWriter |

**Streaming Architecture**:
```
User Invokes graph.stream(input, stream_mode=["values", "messages"])
    │
    ├─> LangGraph Pregel Loop
    │   ├─> Execute Node (calls LLM via LangChain)
    │   │   └─> LangChain streams tokens → StreamMessagesHandler → emit chunks
    │   │
    │   ├─> Node completes → emit "updates" event
    │   ├─> State updated → emit "values" event
    │   └─> Checkpoint saved → emit "checkpoints" event
    │
    └─> User receives iterator of events
```

**Deduplication**: Message streaming uses ID-based deduplication
```python
# libs/langgraph/langgraph/pregel/_messages.py:77-84
def _emit(self, meta, message, *, dedupe=False):
    if dedupe and message.id in self.seen:
        return  # Skip if already emitted
    else:
        if message.id is None:
            message.id = str(uuid4())
        self.seen.add(message.id)
        self.stream((meta[0], "messages", (message, meta[1])))
```

**No Server-Sent Events (SSE)**: LangGraph uses Python iterators
- Stream returns `Iterator[dict]` or `AsyncIterator[dict]`
- SSE conversion is SDK/deployment layer responsibility
- Example: LangGraph Cloud wraps iterators in SSE protocol

### Agentic Primitives

#### System Prompt Assembly

**Method**: User-defined prompt injection
```python
# libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:132-165
def _get_prompt_runnable(prompt):
    if prompt is None:
        # No system prompt - just pass messages
        return lambda state: state["messages"]
    elif isinstance(prompt, str):
        # String → SystemMessage at beginning
        return lambda state: [SystemMessage(content=prompt)] + state["messages"]
    elif isinstance(prompt, SystemMessage):
        # SystemMessage → prepend to messages
        return lambda state: [prompt] + state["messages"]
    elif callable(prompt):
        # Callable → user assembles prompt dynamically
        return prompt
```

**Dynamic System Prompts**:
```python
# User can provide callable that reads state
def dynamic_prompt(state):
    user_prefs = state.get("user_preferences", {})
    system_msg = f"You are a {user_prefs['tone']} assistant."
    return [SystemMessage(content=system_msg)] + state["messages"]

agent = create_react_agent(model, tools, prompt=dynamic_prompt)
```

**No Template Engine**: LangGraph doesn't provide prompt templating
- Users must use string formatting, Jinja2, or LangChain's PromptTemplate
- Framework is prompt-agnostic - just passes messages to LLM

#### Scratchpad / Working Memory

**Implementation**: State channels (user-defined)
```python
# User adds scratchpad field to state schema
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    scratchpad: Annotated[list[str], lambda x, y: x + [y]]  # Append-only

def thinking_node(state):
    thought = llm.invoke("Analyze the problem...")
    return {"scratchpad": [thought.content]}

def acting_node(state):
    thoughts = "\n".join(state["scratchpad"])
    prompt = f"Based on: {thoughts}\nTake action:"
    return {"messages": [llm.invoke(prompt)]}
```

**Persistence**: Scratchpad is part of checkpointed state
- Automatically saved after each step
- Resumable across sessions
- User responsible for eviction/summarization

#### Interrupt / Human-in-the-Loop

**Built-in HITL Support**:
```python
# libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:436-442
agent = create_react_agent(
    model, tools,
    interrupt_before=["tools"],  # Pause before tool execution
    interrupt_after=["agent"]     # Pause after LLM response
)

# Execution pauses, saves checkpoint, returns control
result = graph.invoke(input, config={"thread_id": "123"})

# User reviews, modifies state if needed
graph.update_state(config, {"messages": [HumanMessage("Actually...")]})

# Resume from checkpoint
graph.invoke(None, config={"thread_id": "123"})
```

**Interrupt Mechanism** (from checkpoint system):
1. Node marked for interrupt executes
2. State checkpointed immediately after
3. Graph execution stops, returns current state
4. User can inspect, modify, or approve state
5. `invoke(None)` resumes from checkpoint

**Approval Patterns**:
```python
# Pattern: Require approval for specific tools
def should_interrupt(state):
    last_msg = state["messages"][-1]
    if isinstance(last_msg, AIMessage):
        dangerous_tools = {"delete_file", "send_email"}
        return any(tc["name"] in dangerous_tools for tc in last_msg.tool_calls)
    return False

# Implemented via interrupt_before + dynamic routing
```

#### Conversation State Machine

**State Management**: Channel-based with custom reducers
```python
# libs/langgraph/langgraph/graph/message.py:61-244
def add_messages(left, right):
    """Reducer for message lists
    - Append new messages
    - Update existing messages by ID
    - Remove messages with RemoveMessage marker
    - Optional format conversion to OpenAI format
    """
    # Merge by ID, handle RemoveMessage
    merged = left.copy()
    for m in right:
        if existing_idx := merged_by_id.get(m.id):
            if isinstance(m, RemoveMessage):
                ids_to_remove.add(m.id)
            else:
                merged[existing_idx] = m
        else:
            merged.append(m)
    return [m for m in merged if m.id not in ids_to_remove]
```

**State Reconstruction**: Automatic via checkpoints
```python
# Multi-turn conversation reconstructed from checkpoint
config = {"configurable": {"thread_id": "user-123"}}

# Turn 1
graph.invoke({"messages": [("user", "Hello")]}, config)

# Turn 2 - checkpoint automatically loads previous messages
graph.invoke({"messages": [("user", "What's the weather?")]}, config)

# State now contains full history:
# [HumanMessage("Hello"), AIMessage("Hi!"), HumanMessage("What's the weather?"), ...]
```

**No Automatic Truncation**: User must implement
```python
# Example: Truncate in pre-model hook
def truncate_messages(state):
    messages = state["messages"]
    # Keep system + last 10 messages
    truncated = [messages[0]] + messages[-10:]
    return {"llm_input_messages": truncated}

agent = create_react_agent(
    model, tools,
    pre_model_hook=truncate_messages
)
```

### Provider Abstraction

**Abstraction Layer**: LangChain Core's `BaseChatModel`

**Provider Support Matrix**:

| Provider | LangChain Package | Tool Calling | Streaming | Structured Output |
|----------|-------------------|--------------|-----------|-------------------|
| OpenAI | `langchain-openai` | Yes (native) | Yes | Yes |
| Anthropic | `langchain-anthropic` | Yes (native) | Yes | Yes |
| Google (Gemini) | `langchain-google-genai` | Yes (native) | Yes | Yes |
| Cohere | `langchain-cohere` | Yes (native) | Yes | Limited |
| Fireworks | `langchain-fireworks` | Yes (OpenAI-compatible) | Yes | Yes |
| Together | `langchain-together` | Yes (OpenAI-compatible) | Yes | Yes |
| Ollama | `langchain-ollama` | Yes (limited) | Yes | Limited |
| AWS Bedrock | `langchain-aws` | Yes (varies) | Yes | Varies |
| Azure OpenAI | `langchain-openai` | Yes (same as OpenAI) | Yes | Yes |

**Model Selection**: Static or dynamic
```python
# Static - compile time
model = ChatOpenAI(model="gpt-4")
agent = create_react_agent(model, tools)

# Dynamic - runtime selection
def select_model(state, runtime):
    if state["complexity"] > 8:
        return ChatOpenAI(model="gpt-4").bind_tools(tools)
    else:
        return ChatOpenAI(model="gpt-3.5-turbo").bind_tools(tools)

agent = create_react_agent(select_model, tools)
```

**String-based Model Init** (via LangChain):
```python
# libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:558-569
if isinstance(model, str):
    from langchain.chat_models import init_chat_model
    model = init_chat_model(model)  # "openai:gpt-4" → ChatOpenAI(model="gpt-4")

agent = create_react_agent("anthropic:claude-3-5-sonnet-latest", tools)
```

**Feature Detection**: LangChain's responsibility
- LangGraph assumes model supports `.invoke()` and `.bind_tools()`
- If provider doesn't support tools, LangChain raises `NotImplementedError`
- No graceful degradation - user must handle unsupported features

**Structured Output**: Via LangChain's `with_structured_output()`
```python
# libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:750-755
model_with_structured_output = _get_model(resolved_model).with_structured_output(
    structured_response_schema
)
response = model_with_structured_output.invoke(messages, config)

# LangChain handles:
# - Schema → provider format (JSON mode, function calling, etc.)
# - Response parsing → Pydantic model
```

**No Universal Message Type**: Framework uses LangChain's types
- LangGraph doesn't define its own message protocol
- All messages are `langchain_core.messages.BaseMessage` subclasses
- Provider-specific attributes preserved in `additional_kwargs`

## Code References

**Key Files**:
- `/libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py` - ReAct agent (LangChain integration)
- `/libs/prebuilt/langgraph/prebuilt/tool_node.py` - Tool execution
- `/libs/langgraph/langgraph/graph/message.py` - Message state management
- `/libs/langgraph/langgraph/pregel/_messages.py` - Message streaming handler
- `/libs/langgraph/langgraph/pregel/protocol.py` - Streaming protocol
- `/libs/langgraph/langgraph/types.py` - Core types (StreamMode, etc.)

**Critical Integration Points**:
- Line 666: `response = cast(AIMessage, dynamic_model.invoke(model_input, config))` - LLM invocation
- Line 575: `model = model.bind_tools(tool_classes + llm_builtin_tools)` - Tool binding
- Line 238: `_validate_chat_history()` - Tool call attribution validation
- Line 144: `on_llm_new_token()` - Streaming chunk handler
- Line 61: `add_messages()` - Message reducer logic

## Implications for New Framework

### Positive Patterns

1. **Separation of Concerns**
   - Graph orchestration decoupled from LLM protocol
   - Clean abstraction boundary: framework ≠ prompt assembly
   - Enables swapping LLM libraries without touching execution engine

2. **State-Based Architecture**
   - Messages as first-class state (not transient)
   - Custom reducers enable flexible merge strategies
   - Checkpoint persistence enables long-running workflows

3. **Multi-Mode Streaming**
   - Different stream modes for different use cases
   - `values` for full state, `updates` for deltas, `messages` for tokens
   - Composable - can enable multiple modes simultaneously

4. **ID-Based Message Tracking**
   - Deduplication via message IDs
   - Tool call attribution enforcement
   - State updates by ID (not position)

5. **Dynamic Model Selection**
   - Runtime model switching based on state
   - Per-request provider selection
   - Cost optimization (GPT-3.5 vs GPT-4 based on complexity)

6. **Interrupt Mechanism**
   - Built-in HITL support via checkpoints
   - Pause at any node, resume later
   - State modification during pause

### Considerations

1. **Heavy LangChain Dependency**
   - Cannot use without LangChain Core
   - LangChain updates can break LangGraph
   - Vendor lock-in to LangChain's abstractions

2. **No Native Protocol Handling**
   - Cannot optimize for specific providers
   - Cannot implement custom streaming parsers
   - Relies on LangChain's feature parity

3. **Limited Error Context**
   - LLM errors bubble through LangChain
   - Framework doesn't know provider-specific error codes
   - Cannot implement provider-aware retry logic

4. **No Built-in Observability**
   - Streaming provides events, but no tracing
   - Must integrate external observability (LangSmith, etc.)
   - No built-in token usage tracking

5. **Prompt Assembly is User Code**
   - No helpers for common patterns (few-shot, RAG, etc.)
   - User must implement token counting
   - No automatic context window management

## Anti-Patterns Observed

1. **No Provider Feature Detection**
   ```python
   # Framework assumes all providers support all features
   # No check if model supports tool calling before bind_tools()
   # User gets runtime error instead of compile-time validation
   ```
   **Impact**: Poor UX when using limited providers (Ollama, local models)

2. **Synchronous Validation in create_react_agent**
   ```python
   # Line 238: _validate_chat_history() in hot path
   # Iterates all messages on every invocation
   # O(n²) complexity for multi-turn conversations
   ```
   **Impact**: Performance degrades with long conversations

3. **No Automatic Memory Management**
   ```python
   # MessagesState grows unbounded
   # User must manually truncate/summarize
   # Easy to exceed context windows
   ```
   **Impact**: Production footgun - conversations crash after N turns

4. **Static Tool Registration**
   ```python
   # Tools must be known at graph compile time
   # Cannot add tools dynamically during execution
   # Recompile graph to add new tools
   ```
   **Impact**: Limited flexibility for tool discovery/loading

5. **No Circuit Breakers**
   ```python
   # Retry logic at node level only
   # No rate limiting or backoff for LLM APIs
   # No detection of repeated failures
   ```
   **Impact**: Vulnerable to cost runaway, API abuse

6. **Weak Type Safety for Dynamic Models**
   ```python
   # Dynamic model selection returns Any
   # No static type checking for tool binding
   # Runtime errors if model doesn't support tools
   ```
   **Impact**: Type safety lost for advanced features

## Recommendations for New Framework

**Must Have**:

1. **Provider Abstraction Layer**
   - Define own message protocol (don't delegate entirely)
   - Adapters for OpenAI, Anthropic, etc.
   - Feature matrix per provider (tool calling, streaming, vision)
   - Graceful degradation for unsupported features

2. **Native Tool Protocol**
   - Standard tool definition format (Pydantic-based)
   - Automatic schema → provider format conversion
   - Tool call parsing for all supported providers
   - Validation and error handling

3. **Built-in Streaming**
   - Token-level streaming for supported providers
   - Partial tool call accumulation
   - Multiple stream modes (values, updates, messages)
   - Backpressure handling

4. **Message State Management**
   - ID-based message tracking
   - Custom reducers for merge strategies
   - Automatic truncation helpers (token-aware)
   - Optional summarization

5. **HITL Support**
   - Interrupt before/after nodes
   - State inspection and modification
   - Approval workflows
   - Checkpoint-based resumption

**Should Have**:

1. **Memory Management Helpers**
   - Token counting utilities
   - Sliding window implementation
   - Automatic summarization (LLM-based)
   - Context budget allocation

2. **Provider Feature Detection**
   - Compile-time validation of provider capabilities
   - Runtime fallbacks for unsupported features
   - Clear error messages when features unavailable

3. **Observability Integration**
   - Token usage tracking (per-provider)
   - Latency metrics
   - Cost estimation
   - LLM call traces

4. **Prompt Assembly Utilities**
   - Few-shot example injection
   - RAG context insertion
   - System prompt templating
   - Dynamic prompt composition

**Avoid**:

1. **Total Delegation**
   - Own the protocol abstraction, don't outsource entirely
   - Direct control enables optimization and debugging

2. **Unbounded State Growth**
   - Provide default eviction policies
   - Warn when state exceeds thresholds

3. **Synchronous Validation in Hot Path**
   - Validate at node boundaries, not every invocation
   - Cache validation results

4. **Static-Only Configuration**
   - Support both compile-time and runtime configuration
   - Dynamic tool registration, model selection

**Key Insight**: LangGraph's delegation strategy works because it focuses on **graph orchestration**, not **agent intelligence**. A new framework that aims to provide higher-level agent abstractions should own the protocol layer to enable:
- Provider-specific optimizations
- Better error handling and retries
- Built-in observability
- Automatic memory management
- Graceful degradation

The sweet spot is **thin provider adapters** (like LangChain) with **rich framework utilities** (unlike LangGraph).
