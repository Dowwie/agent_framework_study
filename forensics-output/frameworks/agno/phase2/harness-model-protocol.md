# Harness-Model Protocol Analysis: Agno

## Summary
- **Provider-Native Message Types**: Agno uses provider-native APIs directly (OpenAI SDK, Anthropic SDK) without a universal abstraction layer
- **Unified Internal Message Format**: Single `Message` class with `role/content/tool_calls/tool_call_id` maps to all providers via adapter functions
- **Two-Tier Response Processing**: Raw provider responses parsed into `ModelResponse`, then populate internal `Message` objects
- **Stateless API Reconstruction**: Multi-turn tool conversations reconstructed by serializing full message history to provider format
- **Streaming via Iterator Pattern**: Synchronous `Iterator[ModelResponse]` and async `AsyncIterator[ModelResponse]` with delta accumulation
- **Classification**: **Gateway Pattern with Provider-Native SDKs** - thin adapters over official client libraries

## Detailed Analysis

### Message Protocol

**Wire Format Family**: Provider-Native (OpenAI-compatible, Anthropic-native, Gemini-native, etc.)

**Providers Supported**:
- OpenAI (`agno/models/openai/chat.py`, `agno/models/openai/responses.py`)
- Anthropic (`agno/models/anthropic/claude.py`)
- Google Gemini (`agno/models/google/`)
- Azure OpenAI (`agno/models/azure/openai_chat.py`)
- 30+ additional providers (Groq, Cohere, DeepSeek, Mistral, etc.)

**Abstraction Strategy**: **Thin Adapter with Provider SDKs**

Agno does NOT create a unified client abstraction. Instead:
1. Each provider model uses the official SDK (e.g., `openai.OpenAI`, `anthropic.Anthropic`)
2. Message translation happens at call time via `_format_message()` methods
3. Response parsing happens via `_parse_provider_response()` methods

**Core Message Type** (`agno/models/message.py:55-121`):
```python
class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    role: str  # "system", "user", "assistant", "tool"
    content: Optional[Union[List[Any], str]] = None

    # Tool calling
    tool_call_id: Optional[str] = None  # For tool role
    tool_calls: Optional[List[Dict[str, Any]]] = None  # For assistant role

    # Multimodal
    images: Optional[Sequence[Image]] = None
    audio: Optional[Sequence[Audio]] = None
    videos: Optional[Sequence[Video]] = None
    files: Optional[Sequence[File]] = None

    # Reasoning (o1/Claude thinking)
    reasoning_content: Optional[str] = None
    redacted_reasoning_content: Optional[str] = None

    # Provider-specific data preserved for continuity
    provider_data: Optional[Dict[str, Any]] = None

    # Metrics and metadata
    metrics: Metrics = Field(default_factory=Metrics)
    references: Optional[MessageReferences] = None  # RAG references
    citations: Optional[Citations] = None
```

**OpenAI Message Formatting** (`agno/models/openai/chat.py:308-373`):
```python
def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
    tool_result = message.get_content(use_compressed_content=compress_tool_results)

    message_dict: Dict[str, Any] = {
        "role": self.role_map[message.role] if self.role_map else self.default_role_map[message.role],
        "content": tool_result,
        "name": message.name,
        "tool_call_id": message.tool_call_id,
        "tool_calls": message.tool_calls,
    }
    message_dict = {k: v for k, v in message_dict.items() if v is not None}

    # Handle multimodal content
    if (message.images or message.audio):
        message_dict["content"] = [{"type": "text", "text": message.content}]
        if message.images:
            message_dict["content"].extend(images_to_message(images=message.images))
        if message.audio:
            message_dict["content"].extend(audio_to_message(audio=message.audio))

    return message_dict
```

**Anthropic Message Formatting** (`agno/utils/models/claude.py:227-324`):
```python
def format_messages(messages: List[Message], compress_tool_results: bool = False) -> Tuple[List[Dict], str]:
    chat_messages: List[Dict[str, Union[str, list]]] = []
    system_messages: List[str] = []

    for message in messages:
        if message.role in ("system", "developer"):
            system_messages.append(message.content)  # Extract to system parameter
            continue
        elif message.role == "assistant":
            content = []
            # Add thinking blocks if present
            if message.reasoning_content and message.provider_data:
                content.append(ThinkingBlock(
                    thinking=message.reasoning_content,
                    signature=message.provider_data.get("signature"),
                    type="thinking"
                ))
            # Add text response
            if message.content:
                content.append(TextBlock(text=message.content, type="text"))
            # Add tool calls as ToolUseBlock
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    content.append(ToolUseBlock(
                        id=tool_call["id"],
                        input=json.loads(tool_call["function"]["arguments"]),
                        name=tool_call["function"]["name"],
                        type="tool_use"
                    ))
        elif message.role == "tool":
            content = [{
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": str(message.get_content(use_compressed_content=compress_tool_results))
            }]

        chat_messages.append({"role": ROLE_MAP[message.role], "content": content})

    return chat_messages, " ".join(system_messages)
```

**Key Design Decision**: Agno stores provider data in `Message.provider_data` to preserve continuity across turns:
- OpenAI Responses API: `response_id` for conversation threading (`agno/models/openai/responses.py:286-299`)
- Anthropic thinking: `signature` for extended thinking blocks
- This enables stateful features on stateless APIs

### Tool Call Encoding

**Request Method**: Function Calling API (native provider support)

**Schema Transmission**:

OpenAI format (`agno/models/openai/chat.py:248-262`):
```python
# Tools sent to API
request_params["tools"] = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        }
    }
]
```

Anthropic format (`agno/utils/models/claude.py:327-373`):
```python
# Transformed to Anthropic schema
{
    "name": "search_web",
    "description": "Search the web for information",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"}
        },
        "required": ["query"],
        "additionalProperties": False  # Strict mode enforcement
    },
    "strict": True  # For structured outputs support
}
```

**Tool Choice Support**:

| Provider | auto | none | required | specific_tool | strict |
|----------|------|------|----------|---------------|--------|
| OpenAI | ✓ | ✓ | ✓ | ✓ (via dict) | ✓ (json_schema) |
| Anthropic | ✓ | - | ✓ ("any") | ✓ (via dict) | ✓ (strict:true) |
| Gemini | ✓ | ✓ | ✓ | ✓ | Partial |

**Response Parsing**:

Tool calls stored in OpenAI format internally, regardless of provider:
```python
# OpenAI native format (agno/models/message.py:74)
message.tool_calls = [
    {
        "id": "call_abc123",
        "type": "function",
        "function": {
            "name": "search_web",
            "arguments": '{"query": "weather today"}'
        }
    }
]
```

Anthropic responses converted to this format during parsing:
```python
# Anthropic response processing (agno/models/anthropic/claude.py - inferred)
for tool_use_block in response.content:
    if tool_use_block.type == "tool_use":
        tool_calls.append({
            "id": tool_use_block.id,
            "type": "function",
            "function": {
                "name": tool_use_block.name,
                "arguments": json.dumps(tool_use_block.input)
            }
        })
```

**Tool Result Attribution**:
- Tool messages created with `tool_call_id` matching request (`agno/models/message.py:72`)
- OpenAI: sent as `tool_call_id` in tool role message
- Anthropic: sent as `tool_use_id` in `tool_result` content block

### Streaming Implementation

**Protocol**: Provider-native streaming (OpenAI SSE via SDK, Anthropic SSE via SDK)

**Partial Tool Call Handling**: **Supported with Accumulator Pattern**

Streaming implementation (`agno/models/base.py:1147-1179`):
```python
def process_response_stream(
    self,
    messages: List[Message],
    assistant_message: Message,
    stream_data: MessageData,  # Accumulator
    ...
) -> Iterator[ModelResponse]:
    for response_delta in self._invoke_stream_with_retry(messages=messages, ...):
        for model_response_delta in self._populate_stream_data(
            stream_data=stream_data,
            model_response_delta=response_delta,
        ):
            yield model_response_delta

    # Finalize assistant message after stream completes
    self._populate_assistant_message_from_stream_data(
        assistant_message=assistant_message,
        stream_data=stream_data
    )
```

**MessageData Accumulator** (`agno/models/base.py:48-68`):
```python
@dataclass
class MessageData:
    response_role: Optional[str] = None
    response_content: Any = ""
    response_reasoning_content: Any = ""
    response_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    response_audio: Optional[Audio] = None
    response_metrics: Optional[Metrics] = None
    response_provider_data: Optional[Dict[str, Any]] = None
```

**OpenAI Streaming Delta Parsing** (inferred from SDK usage):
```python
# OpenAI SDK returns ChatCompletionChunk objects
# Each delta contains:
# - delta.content: incremental text
# - delta.tool_calls: incremental tool call fragments
# - delta.reasoning_content: o1 thinking (if enabled)

# Agno accumulates these in MessageData, then yields ModelResponse deltas
```

**Event Types Emitted** (`agno/models/response.py:12-19`):

| Event | When | Payload |
|-------|------|---------|
| `assistant_response` | Text chunk received | `content`, `reasoning_content` |
| `tool_call_started` | First tool call delta | `tool_calls` (partial) |
| `tool_call_completed` | Tool execution done | `ToolExecution` with result |
| `tool_call_paused` | HITL confirmation needed | `ToolExecution` with pause reason |

**Streaming Response Flow**:
```
1. Agent calls model.response_stream(messages)
2. Model._invoke_stream_with_retry() → Iterator[provider deltas]
3. For each delta:
   - _populate_stream_data() accumulates into MessageData
   - Yield ModelResponse delta with incremental content
4. After stream ends:
   - Finalize assistant_message from accumulated MessageData
   - If tool_calls present, execute tools
   - If tools return results, continue loop
5. Return final ModelResponse
```

### Agentic Primitives

**System Prompt Assembly**:

System prompt not assembled by Model - handled by Agent layer:
```python
# Agent constructs system message (agno/agent/agent.py - inferred)
if agent.system_prompt or agent.instructions or model.system_prompt:
    system_parts = []
    if model.system_prompt:
        system_parts.append(model.system_prompt)
    if agent.system_prompt:
        system_parts.append(agent.system_prompt)
    if agent.instructions:
        system_parts.extend(agent.instructions)

    messages.insert(0, Message(role="system", content="\n\n".join(system_parts)))
```

Models can inject system prompts via `model.system_prompt` field:
```python
# Model-level system prompt (agno/models/base.py:140-141)
system_prompt: Optional[str] = None
instructions: Optional[List[str]] = None
```

**Scratchpad / Working Memory**:

Not implemented at protocol level. Memory managed by Agent:
- `Message.references` stores RAG context per message
- `Message.reasoning_content` stores model thinking (o1, Claude extended thinking)
- Agent accumulates messages in session history
- Compression manager can summarize old messages

**Interrupt / Human-in-the-Loop**:

Tool-level HITL via `ToolExecution` (`agno/models/response.py:21-86`):
```python
@dataclass
class ToolExecution:
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    result: Optional[str] = None

    # HITL control flow
    requires_confirmation: Optional[bool] = None
    confirmed: Optional[bool] = None
    confirmation_note: Optional[str] = None

    requires_user_input: Optional[bool] = None
    user_input_schema: Optional[List[UserInputField]] = None
    answered: Optional[bool] = None

    external_execution_required: Optional[bool] = None

    @property
    def is_paused(self) -> bool:
        return bool(self.requires_confirmation or self.requires_user_input or
                    self.external_execution_required)
```

When tool execution is paused, agent breaks loop and returns `RunRequirement`:
```python
# Agent control loop (agno/models/base.py:677-687)
if function_call_response.event == ModelResponseEvent.tool_call_paused.value:
    if run_response.requirements is None:
        run_response.requirements = []
    run_response.requirements.append(
        RunRequirement(tool_execution=current_tool_execution)
    )
```

**Conversation State Machine**:

Implicit state machine via control loop (`agno/models/base.py:594-738`):
```
State: GENERATE_RESPONSE
  → Generate assistant message
  → If tool_calls: State = EXECUTE_TOOLS
  → Else: State = DONE

State: EXECUTE_TOOLS
  → Execute function calls
  → If stop_after_tool_call: State = DONE
  → If requires_confirmation: State = PAUSED (break loop, return requirements)
  → If requires_user_input: State = PAUSED
  → Else: State = GENERATE_RESPONSE (continue loop)

State: PAUSED
  → Return RunOutput with requirements
  → User provides confirmation/input
  → Resume: State = GENERATE_RESPONSE

State: DONE
  → Return final ModelResponse
```

**Tool Call Limits**:
```python
# Prevents infinite loops (agno/models/base.py:551)
tool_call_limit: Optional[int] = None  # Default: unlimited

# Enforced during execution
if tool_call_limit and function_call_count >= tool_call_limit:
    break
```

### Provider Abstraction

**Abstraction Table**:

| Provider | Model Class | SDK Used | Streaming | Structured Output | Reasoning | Notes |
|----------|-------------|----------|-----------|-------------------|-----------|-------|
| OpenAI | `OpenAIChat` | `openai.OpenAI` | ✓ | ✓ (native json_schema) | ✓ (o1 models) | Chat Completions API |
| OpenAI | `OpenAIResponses` | `openai.OpenAI` | ✓ | ✓ | ✓ (o3/o4/gpt-5) | Responses API with reasoning |
| Anthropic | `Claude` | `anthropic.Anthropic` | ✓ | ✓ (4.5+, strict mode) | ✓ (extended thinking) | Messages API with beta features |
| Google | `Gemini` | `google.genai` | ✓ | Partial | ✗ | Gemini API |
| Azure OpenAI | `AzureOpenAIChat` | `openai.AzureOpenAI` | ✓ | ✓ | ✓ | Azure-hosted OpenAI |
| Groq | `Groq` | `openai.OpenAI` | ✓ | ✓ | ✗ | OpenAI-compatible |
| DeepSeek | `DeepSeek` | `openai.OpenAI` | ✓ | ✓ | ✓ (R1 models) | OpenAI-compatible |
| Cohere | `CohereChat` | `cohere.Client` | ✓ | ✗ | ✗ | Cohere API |
| LiteLLM | `LiteLLM` | `litellm` | ✓ | Partial | Depends | Gateway to 100+ providers |

**Graceful Degradation Examples**:

1. **Unsupported Structured Outputs** (`agno/models/anthropic/claude.py:186-199`):
```python
def _supports_structured_outputs(self) -> bool:
    # Blacklist for legacy models
    if self.id in self.NON_STRUCTURED_OUTPUT_MODELS:
        return False

    # If user tries to use structured outputs with unsupported model
    if response_format and not self._supports_structured_outputs():
        log_warning(
            f"Model '{self.id}' does not support structured outputs. "
            "Structured output features will not be available."
        )
        return None  # Don't send output_format parameter
```

2. **Unsupported Thinking** (`agno/models/anthropic/claude.py:236-250`):
```python
def _validate_thinking_support(self) -> None:
    if self.thinking and self.id in self.NON_THINKING_MODELS:
        raise ValueError(
            f"Model '{self.id}' does not support extended thinking.\n"
            f"The following models do NOT support thinking:\n  - {non_thinking_models}\n"
        )
```

3. **Provider-Specific Tool Fields** (`agno/models/openai/chat.py:251-257`):
```python
# Some OpenAI-like providers don't support custom tool fields
if self.provider in ["AIMLAPI", "Fireworks", "Nvidia"]:
    for tool in tools:
        if tool.get("type") == "function":
            # Remove Agno-specific fields
            if tool["function"].get("requires_confirmation") is not None:
                del tool["function"]["requires_confirmation"]
            if tool["function"].get("external_execution") is not None:
                del tool["function"]["external_execution"]
```

4. **Model-Specific Requirements** (`agno/models/openai/responses.py:248-260`):
```python
# Deep research models require web_search_preview tool
if "deep-research" in self.id:
    if tools is None:
        tools = []

    has_web_search = any(tool.get("type") == "web_search_preview" for tool in tools)

    if not has_web_search:
        web_search_tool = {"type": "web_search_preview"}
        tools.insert(0, web_search_tool)
        log_debug(f"Added web_search_preview tool for deep research model")
```

**Multi-LLM Support Strategy**:
- Each provider has dedicated model class
- Common interface via `Model` ABC (`agno/models/base.py:115`)
- Abstract methods: `invoke()`, `ainvoke()`, `invoke_stream()`, `ainvoke_stream()`
- Adapters translate to/from provider formats at boundaries
- No universal client - uses official SDKs directly

## Code References

### Core Protocol Files
- `/Users/dgordon/my_projects/agent_framework_study/repos/agno/libs/agno/agno/models/base.py:115-1400` - Model ABC and response processing
- `/Users/dgordon/my_projects/agent_framework_study/repos/agno/libs/agno/agno/models/message.py:55-454` - Message type definition
- `/Users/dgordon/my_projects/agent_framework_study/repos/agno/libs/agno/agno/models/response.py:1-202` - ModelResponse and events

### Provider Implementations
- `/Users/dgordon/my_projects/agent_framework_study/repos/agno/libs/agno/agno/models/openai/chat.py:1-800+` - OpenAI Chat Completions
- `/Users/dgordon/my_projects/agent_framework_study/repos/agno/libs/agno/agno/models/openai/responses.py:1-500+` - OpenAI Responses API
- `/Users/dgordon/my_projects/agent_framework_study/repos/agno/libs/agno/agno/models/anthropic/claude.py:1-1000+` - Anthropic Claude
- `/Users/dgordon/my_projects/agent_framework_study/repos/agno/libs/agno/agno/utils/models/claude.py:1-374` - Anthropic message formatting

### Streaming & Tool Execution
- `/Users/dgordon/my_projects/agent_framework_study/repos/agno/libs/agno/agno/models/base.py:1147-1350` - Streaming response processing
- `/Users/dgordon/my_projects/agent_framework_study/repos/agno/libs/agno/agno/models/base.py:594-738` - Non-streaming tool execution loop
- `/Users/dgordon/my_projects/agent_framework_study/repos/agno/libs/agno/agno/models/response.py:21-86` - ToolExecution with HITL

## Implications for New Framework

### Positive Patterns

1. **Provider-Native SDKs** - Don't build a universal client. Use official SDKs and translate at boundaries. This ensures:
   - Latest provider features immediately available
   - Official error handling and retry logic
   - Native type checking via provider SDK types
   - Reduced maintenance burden

2. **OpenAI-Compatible Tool Call Format** - Storing all tool calls in OpenAI's `{id, type, function: {name, arguments}}` format internally, even for Anthropic:
   - Single code path for tool execution
   - Easy to add new providers (just translate to OpenAI format)
   - Familiar format for developers

3. **MessageData Accumulator** - Separate delta accumulation (`MessageData`) from finalized message (`Message`):
   - Clean separation of streaming state vs. final state
   - Prevents partial message pollution
   - Enables replay/caching of streams

4. **Provider Data Preservation** - `Message.provider_data` field stores provider-specific continuation data:
   - Enables stateful features on stateless APIs (OpenAI Responses `response_id`)
   - Preserves extended thinking signatures (Anthropic)
   - Future-proof for new provider features

5. **Agentic Tool Execution** - `ToolExecution` dataclass with HITL fields:
   - Clean separation of tool call request vs. execution status
   - `is_paused` property simplifies control flow
   - `requires_confirmation` / `requires_user_input` enables fine-grained HITL

6. **Retry with Guidance** - `RetryableModelProviderError` with `retry_guidance_message`:
   - Model can self-correct known errors (e.g., "invalid JSON")
   - Reduces wasted retries
   - Configurable retry limit

7. **Compression Checkpoints** - `CompressionManager.should_compress()` called before each API call:
   - Prevents context overflow proactively
   - Configurable compression threshold
   - Transparent to model (just sees compressed messages)

### Considerations

1. **No Universal Message Type** - Each provider uses own SDK types internally:
   - **Risk**: Provider-specific bugs leak into core logic
   - **Mitigation**: Translate at boundaries, never expose provider types to Agent
   - **For New Framework**: Consider a truly universal internal type that maps to all providers

2. **Dual Sync/Async Code Paths** - Separate `invoke()` and `ainvoke()` implementations:
   - **Risk**: Code duplication, maintenance burden
   - **Current**: Agno has 128 sync + 56 async methods
   - **For New Framework**: Async-first with thin sync wrappers (`asyncio.run()`)

3. **Tool Call Limit Only** - No per-tool timeout, no parallel execution:
   - **Risk**: Single slow tool blocks entire agent
   - **For New Framework**: Add per-tool timeout and concurrency limits

4. **Manual Serialization** - `Message.to_dict()` / `from_dict()` with 200+ lines of boilerplate:
   - **Risk**: Error-prone, hard to maintain
   - **For New Framework**: Use Pydantic V2 exclusively for automatic serialization

5. **Reasoning Content Handling** - Separate `reasoning_content` and `redacted_reasoning_content`:
   - **Good**: Preserves full thinking for analysis
   - **Issue**: Not clear when to use which (o1 vs Claude extended thinking)
   - **For New Framework**: Unified reasoning API with provider-agnostic access

6. **Beta Feature Explosion** - Anthropic beta features require manual header management:
   - `betas` list must include "structured-outputs-2025-11-13", "code-execution-2025-08-25", etc.
   - **Risk**: Hard to track which betas are required for which features
   - **For New Framework**: Hide beta complexity behind feature flags

## Anti-Patterns Observed

1. **Mutable MessageData** - `MessageData` is modified during streaming without locks:
   ```python
   @dataclass
   class MessageData:  # Should be frozen=True
       response_content: Any = ""  # Mutated during stream
   ```
   **Fix**: Use `@dataclass(frozen=True)` or explicit locks

2. **Silent Tool Field Removal** - Provider-specific tool fields silently deleted:
   ```python
   if self.provider in ["AIMLAPI", "Fireworks", "Nvidia"]:
       del tool["function"]["requires_confirmation"]  # No warning!
   ```
   **Fix**: Log warning when features are disabled

3. **String-Based Event Types** - `event: str = "AssistantResponse"` instead of enum:
   ```python
   model_response.event = "tool_call_paused"  # Typo-prone
   ```
   **Fix**: Use `event: ModelResponseEvent` (already defined but not enforced)

4. **No Structured Logging** - Metrics scattered across multiple fields:
   ```python
   message.metrics.input_tokens = ...
   message.metrics.output_tokens = ...
   message.metrics.duration = ...
   # No unified logging format
   ```
   **Fix**: Emit structured events (JSON) for observability platforms

5. **Global HTTP Clients** - Shared `httpx.Client` across all models:
   ```python
   client_params["http_client"] = get_default_sync_client()  # Singleton
   ```
   **Risk**: Connection pool exhaustion, no per-model rate limiting
   **Fix**: Per-model clients with configurable connection limits

6. **Exception-Based Control Flow** - `AgentRunException` used for retry logic:
   ```python
   raise RetryAgentRun(user_message="Please try again")  # Control flow via exception
   ```
   **Risk**: Obscures actual control flow, harder to debug
   **Fix**: Return `Result[ModelResponse, Error]` types

7. **No Circuit Breaker** - Retries without circuit breaker pattern:
   ```python
   for attempt in range(self.retries + 1):
       try:
           return self.invoke(**kwargs)
       except ModelProviderError:
           sleep(delay)  # No circuit breaker
   ```
   **Fix**: Implement circuit breaker to prevent cascading failures
