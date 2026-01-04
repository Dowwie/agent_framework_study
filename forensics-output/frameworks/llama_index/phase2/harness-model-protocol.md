# Harness-Model Protocol Analysis: LlamaIndex

## Summary
- **Key Finding 1**: Universal message abstraction with block-based content (TextBlock, ImageBlock, ToolCallBlock) - provider adapters convert to/from native formats
- **Key Finding 2**: Provider-specific utils handle wire format translation (OpenAI ChatCompletionMessageParam, Anthropic MessageParam) with no unified internal client
- **Key Finding 3**: Streaming accumulates tool calls via delta updates - partial JSON parsing for streaming structured outputs but no explicit partial tool call handling
- **Classification**: Thin adapter layer with universal ChatMessage type - delegates to native SDKs (OpenAI, Anthropic) for actual API calls

## Detailed Analysis

### Message Protocol

**Wire Format Family**: Provider-specific (OpenAI, Anthropic, Gemini) - no unified wire format

**Universal Internal Type**: `ChatMessage` with content blocks

Core message structure (llama-index-core/llama_index/core/base/llms/types.py:538-646):
```python
class ChatMessage(BaseModel):
    role: MessageRole = MessageRole.USER
    additional_kwargs: dict[str, Any] = Field(default_factory=dict)
    blocks: list[ContentBlock] = Field(default_factory=list)

# ContentBlock = Union[TextBlock, ImageBlock, AudioBlock, VideoBlock,
#                      DocumentBlock, ToolCallBlock, ThinkingBlock, CitationBlock, CachePoint]
```

**Content Block Architecture**:
- **TextBlock**: `{"block_type": "text", "text": str}`
- **ImageBlock**: `{"block_type": "image", "image": bytes, "url": str, "image_mimetype": str}`
- **ToolCallBlock**: `{"block_type": "tool_call", "tool_call_id": str, "tool_name": str, "tool_kwargs": dict}`
- **ThinkingBlock**: For reasoning traces (Anthropic extended thinking, O1 models)
- **CitationBlock**: For models with built-in citation support

**Backward compatibility**: Content property getter/setter allows `message.content` (string) for legacy code, but internally uses blocks.

**Providers Supported**:
| Provider | Location | Wire Format |
|----------|----------|-------------|
| OpenAI | llama-index-llms-openai/base.py | ChatCompletionMessageParam |
| Anthropic | llama-index-llms-anthropic/base.py | MessageParam |
| Bedrock Converse | llama-index-llms-bedrock-converse/base.py | Bedrock Converse API |
| Azure OpenAI | llama-index-llms-azure-openai/base.py | OpenAI-compatible |
| Gemini | llama-index-llms-gemini/base.py | Gemini native |
| 50+ others | llama-index-integrations/llms/* | Various |

**Abstraction Strategy**: Thin adapter per provider - each integration implements conversion utils

### Tool Call Encoding

**Request Method**: Native function calling API (OpenAI tools, Anthropic tool_use)

**Schema Transmission** (OpenAI example):

Tools converted to OpenAI format via Pydantic (llama-index-core/llama_index/core/tools/types.py:76-90):
```python
def to_openai_tool(self) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": self.name,
            "description": self.description,
            "parameters": self.get_parameters_dict(),  # Pydantic model_json_schema()
        },
    }
```

**OpenAI Message Encoding** (llama-index-llms-openai/utils.py:348-518):

Tool calls sent in message blocks:
```python
# LlamaIndex ChatMessage -> OpenAI message dict
def to_openai_message_dict(message: ChatMessage) -> ChatCompletionMessageParam:
    content = []
    for block in message.blocks:
        if isinstance(block, TextBlock):
            content.append({"type": "text", "text": block.text})
        elif isinstance(block, ImageBlock):
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mimetype};base64,{img_str}"}
            })
        elif isinstance(block, ToolCallBlock):
            # Tool calls embedded in content or message.additional_kwargs
            content.append({
                "type": "text",
                "text": "",
                "tool_calls": [{
                    "type": "function",
                    "function": {
                        "name": block.tool_name,
                        "arguments": block.tool_kwargs
                    },
                    "id": block.tool_call_id
                }]
            })
```

**Anthropic Message Encoding** (llama-index-llms-anthropic/utils.py:186-300):

System prompt separated from messages:
```python
def messages_to_anthropic_messages(
    messages: Sequence[ChatMessage], cache_idx: Optional[int] = None
) -> Tuple[Sequence[MessageParam], str]:
    anthropic_messages = []
    system_prompt = []

    for message in messages:
        if message.role == MessageRole.SYSTEM:
            system_prompt.extend(blocks_to_anthropic_blocks(message.blocks))
        elif message.role == MessageRole.TOOL:
            # Tool results as special content type
            content = ToolResultBlockParam(
                tool_use_id=message.additional_kwargs["tool_call_id"],
                type="tool_result",
                content=blocks_to_anthropic_blocks(message.blocks)
            )
            anthropic_messages.append(MessageParam(role="user", content=[content]))
```

**Response Parsing**:

Streaming accumulates deltas (llama-index-llms-openai/base.py:524-591):
```python
def _stream_chat(self, messages: Sequence[ChatMessage], **kwargs) -> ChatResponseGen:
    content = ""
    tool_calls: List[ChoiceDeltaToolCall] = []

    for response in client.chat.completions.create(..., stream=True):
        delta = response.choices[0].delta
        content += delta.content or ""

        # Accumulate tool calls via update_tool_calls helper
        if delta.tool_calls:
            tool_calls = update_tool_calls(tool_calls, delta.tool_calls)
            for tool_call in tool_calls:
                blocks.append(ToolCallBlock(
                    tool_call_id=tool_call.id,
                    tool_kwargs=tool_call.function.arguments,  # May be partial JSON
                    tool_name=tool_call.function.name
                ))

        yield ChatResponse(message=ChatMessage(role=role, blocks=blocks), delta=content_delta)
```

**Tool Choice Support**:

| Provider | auto | required | any | none | specific tool |
|----------|------|----------|-----|------|---------------|
| OpenAI | Yes | Yes | N/A | Yes | Yes (tool_choice={"type": "function", "function": {"name": "..."}}) |
| Anthropic | Yes | Yes | Yes | N/A | Yes (tool_choice={"type": "tool", "name": "..."}) |

Resolved via provider utils (llama-index-llms-openai/utils.py):
```python
def resolve_tool_choice(
    tool_choice: Union[str, dict] = "auto"
) -> Union[str, dict]:
    # Maps "auto", "none", "required", specific tool name
    # to provider-specific format
```

### Streaming Implementation

**Protocol**: SSE (Server-Sent Events) via native provider SDKs

OpenAI uses httpx streaming under the hood:
```python
client = SyncOpenAI(api_key=..., http_client=httpx.Client())
for chunk in client.chat.completions.create(..., stream=True):
    # yields ChatCompletionChunk objects
```

**Partial Tool Call Handling**:

OpenAI accumulates tool call deltas (llama-index-llms-openai/utils.py has update_tool_calls):
```python
def update_tool_calls(
    tool_calls: List[ChoiceDeltaToolCall],
    new_tool_calls: Optional[List[ChoiceDeltaToolCall]],
) -> List[ChoiceDeltaToolCall]:
    """Accumulate tool call deltas across streaming chunks."""
    # Merges deltas by index, appending arguments strings
```

**Challenges**:
- Partial JSON in `tool_kwargs` may be invalid until final chunk
- No explicit JSON validation during streaming (consumer must parse final accumulated result)
- Structured output streaming uses `parse_partial_json` helper for progressive parsing

**Event Types Emitted**:

Streaming yields `ChatResponse` objects with `delta` field:
```python
class ChatResponse(BaseModel):
    message: ChatMessage  # Accumulated message so far
    delta: Optional[str] = None  # New text in this chunk
    raw: Optional[Any] = None  # Provider's raw response
    logprobs: Optional[List[List[LogProb]]] = None
```

For structured outputs, stream events are `Model` instances (partial Pydantic models).

Instrumentation events (llama-index-core/llama_index/core/instrumentation/events/llm.py):
- `LLMPredictStartEvent`
- `LLMPredictEndEvent`
- `LLMStructuredPredictStartEvent`
- `LLMStructuredPredictInProgressEvent` (streaming)
- `LLMStructuredPredictEndEvent`

### Agentic Primitives

**System Prompt Assembly** (llama-index-core/llama_index/core/llms/llm.py:295-302):

System prompt injected at message preparation:
```python
def _extend_messages(self, messages: List[ChatMessage]) -> List[ChatMessage]:
    """Add system prompt to chat message list."""
    if self.system_prompt:
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=self.system_prompt),
            *messages,
        ]
    return messages
```

**Provider-Specific Handling**:
- OpenAI O1 models: system role converted to "developer" role
- Anthropic: system prompt passed as separate parameter to API (not in messages array)

**Scratchpad / Working Memory**:

Not built into message protocol - implemented at agent layer via ChatMemoryBuffer (separate analysis). Memory returns `List[ChatMessage]` that gets prepended to new user messages.

**Interrupt / Human-in-the-Loop**:

No message-level primitive for interrupts. Implemented at workflow layer:
- Agents can emit events requesting human input
- Workflow pauses execution and waits for external input
- Not part of the message protocol itself

**Conversation State Machine**:

Messages are stateless - sequence must be explicitly maintained by caller. No built-in conversation ID or session tracking at protocol level.

**Tool Results**:

Tool results sent back as TOOL role messages (OpenAI) or USER role with ToolResultBlockParam (Anthropic):
```python
# OpenAI
ChatMessage(
    role=MessageRole.TOOL,
    content=tool_output.content,
    additional_kwargs={"tool_call_id": tool_call.tool_call_id}
)

# Anthropic - tool results sent as USER messages
MessageParam(
    role="user",
    content=[ToolResultBlockParam(
        tool_use_id=tool_call_id,
        type="tool_result",
        content=[TextBlockParam(text=result)]
    )]
)
```

### Provider Abstraction

**Multi-LLM Support Mechanism**: Inheritance from `BaseLLM` + provider-specific adapters

Base interface (llama-index-core/llama_index/core/base/llms/base.py:25-292):
```python
class BaseLLM(BaseComponent, DispatcherSpanMixin):
    @abstractmethod
    def chat(self, messages: Sequence[ChatMessage], **kwargs) -> ChatResponse: ...

    @abstractmethod
    def stream_chat(self, messages: Sequence[ChatMessage], **kwargs) -> ChatResponseGen: ...

    @abstractmethod
    async def achat(self, messages: Sequence[ChatMessage], **kwargs) -> ChatResponse: ...

    @abstractmethod
    async def astream_chat(self, messages: Sequence[ChatMessage], **kwargs) -> ChatResponseAsyncGen: ...

    def convert_chat_messages(self, messages: Sequence[ChatMessage]) -> List[Any]:
        """Override to convert to provider-specific format."""
```

**Provider Feature Matrix**:

| Provider | Function Calling | Streaming | Vision | Audio | Thinking | Caching |
|----------|-----------------|-----------|--------|-------|----------|---------|
| OpenAI | Yes (gpt-4+) | Yes | Yes (gpt-4o) | Yes (gpt-4o-audio) | Yes (O1) | No |
| Anthropic | Yes (Claude 3+) | Yes | Yes | No | Yes (extended thinking) | Yes (prompt caching) |
| Bedrock Converse | Yes | Yes | Yes | No | Yes | No |
| Gemini | Yes | Yes | Yes | Yes | No | Yes |
| Azure OpenAI | Yes | Yes | Yes | No | No | No |

**Graceful Degradation Examples**:

1. **Non-function-calling models** (llama-index-core/llama_index/core/llms/llm.py:778-851):
   - Falls back to ReAct text prompting
   - `predict_and_call` creates ReActAgent internally
   - Tool calls parsed from text responses

2. **O1 models without function calling**:
   - `O1_MODELS_WITHOUT_FUNCTION_CALLING` set excludes o1-preview, o1-mini
   - System prompts converted to USER role
   - Temperature forced to 1.0

3. **Missing features**:
   - If provider doesn't support streaming structured outputs, raises NotImplementedError
   - If audio not supported, raises ValueError during streaming

**Provider Detection** (llama-index-llms-openai/utils.py:324-345):
```python
def is_function_calling_model(model: str) -> bool:
    # Default to True for unknown models (assume modern)
    if model not in ALL_AVAILABLE_MODELS:
        return True

    is_chat = is_chat_model(model)
    is_old = "0314" in model or "0301" in model
    is_o1_beta = model in O1_MODELS_WITHOUT_FUNCTION_CALLING

    return is_chat and not is_old and not is_o1_beta
```

**Metadata Reporting** (llama-index-core/llama_index/core/base/llms/types.py:702-747):
```python
class LLMMetadata(BaseModel):
    context_window: int = DEFAULT_CONTEXT_WINDOW  # 3900
    num_output: int = DEFAULT_NUM_OUTPUTS  # 256
    is_chat_model: bool = False
    is_function_calling_model: bool = False
    model_name: str = "unknown"
    system_role: MessageRole = MessageRole.SYSTEM  # Or USER for O1
```

## Code References

### Core Types
- `llama-index-core/llama_index/core/base/llms/types.py:39` - MessageRole enum
- `llama-index-core/llama_index/core/base/llms/types.py:52-536` - ContentBlock types (TextBlock, ImageBlock, ToolCallBlock, etc.)
- `llama-index-core/llama_index/core/base/llms/types.py:538` - ChatMessage
- `llama-index-core/llama_index/core/base/llms/types.py:657` - ChatResponse
- `llama-index-core/llama_index/core/base/llms/types.py:702` - LLMMetadata

### Base LLM Interface
- `llama-index-core/llama_index/core/base/llms/base.py:25` - BaseLLM abstract class
- `llama-index-core/llama_index/core/llms/llm.py:163` - LLM class (adds system_prompt, messages_to_prompt)
- `llama-index-core/llama_index/core/llms/function_calling.py:24` - FunctionCallingLLM

### OpenAI Integration
- `llama-index-llms-openai/llama_index/llms/openai/base.py:138` - OpenAI class
- `llama-index-llms-openai/llama_index/llms/openai/base.py:524` - _stream_chat implementation
- `llama-index-llms-openai/llama_index/llms/openai/utils.py:348` - to_openai_message_dict
- `llama-index-llms-openai/llama_index/llms/openai/utils.py:287` - openai_modelname_to_contextsize

### Anthropic Integration
- `llama-index-llms-anthropic/llama_index/llms/anthropic/base.py:109` - Anthropic class
- `llama-index-llms-anthropic/llama_index/llms/anthropic/utils.py:303` - messages_to_anthropic_messages
- `llama-index-llms-anthropic/llama_index/llms/anthropic/utils.py:186` - blocks_to_anthropic_blocks

### Tool Interface
- `llama-index-core/llama_index/core/tools/types.py:22` - ToolMetadata
- `llama-index-core/llama_index/core/tools/types.py:76` - to_openai_tool
- `llama-index-core/llama_index/core/llms/llm.py:70` - ToolSelection

## Implications for New Framework

### Positive Patterns

1. **Block-based content representation**
   - Unified internal format for multimodal content
   - Clean separation between internal representation and wire format
   - Easy to add new content types (citations, thinking, cache points)
   - Discriminated unions via Pydantic enable type-safe parsing

2. **Backward compatibility via property accessor**
   - `message.content` returns concatenated text from TextBlocks
   - Setter creates single TextBlock
   - Allows gradual migration from string-based to block-based APIs

3. **Provider-specific utils, not forced abstraction**
   - Each provider has optimal wire format (no lowest-common-denominator)
   - Can leverage provider-specific features (Anthropic caching, OpenAI audio)
   - Utils are pure functions, easy to test

4. **Metadata-driven capability detection**
   - `is_function_calling_model`, `is_chat_model` flags
   - Context window sizes in lookup tables
   - System role customization per provider

5. **Streaming delta accumulation pattern**
   - Generators yield incremental ChatResponse with growing message
   - Delta field shows what's new
   - Consumer can display progressive updates or wait for final result

### Considerations

1. **No universal internal LLM client**
   - Each provider brings its own SDK (openai, anthropic, google-generativeai)
   - Increases dependency footprint
   - But: leverages vendor SDKs' retry logic, error handling, auth

2. **Partial JSON in streaming tool calls**
   - `tool_kwargs` field may contain incomplete JSON during streaming
   - No validation until final chunk
   - Consumers must handle parse errors

3. **No conversation ID or session tracking**
   - Messages are stateless
   - Caller must maintain conversation history
   - Multi-turn tool conversations require explicit message sequencing

4. **Provider-specific system prompt handling**
   - OpenAI: injected as SYSTEM message at start of messages array
   - Anthropic: separate `system` parameter in API call
   - O1 models: system becomes "developer" role
   - Abstraction leaks to caller for edge cases

5. **Additional_kwargs as escape hatch**
   - Non-standard fields go into `additional_kwargs` dict
   - Enables provider-specific features but breaks type safety
   - Tool results use this for `tool_call_id`

6. **Streaming structured outputs use partial JSON parsing**
   - Progressive parsing via `parse_partial_json` helper
   - May emit invalid intermediate states
   - No schema validation during streaming

## Anti-Patterns Observed

1. **In-place mutation of message blocks during streaming**
   ```python
   # Updates tool_calls list in place
   tool_calls = update_tool_calls(tool_calls, delta.tool_calls)
   ```
   - Violates immutability
   - Should create new list

2. **No explicit tool_call_id matching validation**
   - Anthropic utils update blocks by matching `tool_call_id`
   - No verification that tool result `tool_call_id` matches a prior tool call
   - Could accept mismatched IDs silently

3. **Silent feature degradation**
   - Non-function-calling models fall back to ReAct without warning
   - User may not realize they're getting text-based tool calling
   - Should log or raise error if requested feature unsupported

4. **String-based model detection**
   ```python
   if "0314" in model or "0301" in model:  # Old model detection
   ```
   - Fragile, could match false positives
   - Better: explicit set of old models

5. **No standardized error taxonomy**
   - OpenAI errors: `openai.APIError`, `openai.RateLimitError`
   - Anthropic errors: `anthropic.APIError`
   - Each provider has different error hierarchy
   - Caller must catch multiple exception types

6. **Dual sync/async clients as PrivateAttr**
   ```python
   _client: Optional[SyncOpenAI] = PrivateAttr()
   _aclient: Optional[AsyncOpenAI] = PrivateAttr()
   ```
   - Doubles client overhead
   - Lost during serialization
   - Should use async-only with sync wrappers

7. **No streaming event protocol**
   - Streaming yields response objects
   - No typed event stream (start, progress, tool_call, complete)
   - Makes it harder to build UIs that react to specific events

## Recommendations for New Framework

### Adopt These Patterns
1. Block-based content representation with discriminated unions
2. Provider-specific utils for wire format translation
3. Metadata-driven capability detection
4. Backward compatibility via property accessors
5. Streaming delta accumulation with progressive responses

### Avoid These Issues
1. Use immutable updates for streaming accumulators
2. Add explicit tool_call_id validation
3. Log warnings for feature degradation
4. Create unified error taxonomy (ProviderError base class)
5. Async-first with sync wrappers, not dual clients
6. Define typed streaming event protocol

### Specific Improvements
1. **Add conversation session tracking** - Optional `conversation_id` field in messages
2. **Validate partial tool calls** - Check JSON schema during streaming if possible
3. **Structured streaming events** - `StreamStartEvent`, `TextDeltaEvent`, `ToolCallEvent`, `StreamEndEvent`
4. **Provider capability registry** - Declarative feature matrix instead of runtime detection
5. **Standardized additional_kwargs** - Define well-known keys (`tool_call_id`, `cache_control`) with types
6. **Tool call attribution matrix** - Verify tool results match prior tool calls in conversation
7. **Progressive JSON schema validation** - Validate partial structures against schema during streaming

### Architecture Recommendations

For a new framework, consider:

1. **Two-tier message system**:
   - Internal universal format (similar to ChatMessage with blocks)
   - Provider adapters translate to/from wire formats
   - Keep adapters as pure functions in utils modules

2. **Typed streaming protocol**:
   ```python
   @dataclass
   class StreamEvent:
       type: Literal["start", "delta", "tool_call", "end"]

   @dataclass
   class TextDeltaEvent(StreamEvent):
       delta: str
       accumulated: str

   @dataclass
   class ToolCallEvent(StreamEvent):
       tool_call_id: str
       tool_name: str
       tool_kwargs: dict  # Partial or complete
       is_complete: bool
   ```

3. **Capability-based provider selection**:
   ```python
   @dataclass
   class ProviderCapabilities:
       function_calling: bool
       streaming: bool
       vision: bool
       thinking: bool

   class Provider(Protocol):
       capabilities: ProviderCapabilities
       def chat(self, messages: List[Message]) -> Response: ...
   ```

4. **Unified error handling**:
   ```python
   class ProviderError(Exception):
       provider: str
       error_code: str
       retryable: bool

   class RateLimitError(ProviderError):
       retry_after: Optional[float]
   ```

5. **Conversation state tracking**:
   - Attach `conversation_id` to messages
   - Validate message sequencing (no orphaned tool results)
   - Detect cycles in tool call chains
