# Harness-Model Protocol Analysis: AWS Strands

## Summary
- **Key Finding 1**: Unified Bedrock-native message format with thin adapter layer for each provider
- **Key Finding 2**: Streaming-first architecture with stateful accumulation of partial tool calls
- **Key Finding 3**: Native support for advanced Bedrock features (caching, guardrails, reasoning) with graceful degradation
- **Classification**: Provider-specific adapters wrapping a unified Bedrock TypedDict protocol

## Detailed Analysis

### Message Protocol

**Wire Format Family**: Bedrock-native with provider-specific adapters

**Internal Representation**: TypedDict structures matching AWS Bedrock Converse API

```python
# Core message structure (types/content.py:178)
class Message(TypedDict):
    content: List[ContentBlock]  # Heterogeneous content blocks
    role: Role  # "user" | "assistant"

# Content blocks support multimodal data
class ContentBlock(TypedDict, total=False):
    text: str
    image: ImageContent
    video: VideoContent
    document: DocumentContent
    toolUse: ToolUse
    toolResult: ToolResult
    reasoningContent: ReasoningContentBlock
    guardContent: GuardContent
    citationsContent: CitationsContentBlock
    cachePoint: CachePoint
```

**Key Characteristics**:
- **Heterogeneous content blocks**: Single message can mix text, images, tool calls
- **Tool results use "user" role**: Bedrock convention, not OpenAI's "tool" role
- **Cache points as content blocks**: Inline markers for prompt caching boundaries
- **Reasoning content**: Native extended thinking support (Claude reasoning models)

**Providers Supported**:
| Provider | Adapter Location | Wire Format |
|----------|-----------------|-------------|
| Bedrock | `models/bedrock.py` | Native (no transformation) |
| Anthropic | `models/anthropic.py` | Bedrock → Anthropic Messages API |
| OpenAI | `models/openai.py` | Bedrock → OpenAI Chat Completions |
| Gemini | `models/gemini.py` | Bedrock → Google AI SDK |
| Ollama | `models/ollama.py` | Bedrock → OpenAI-compatible |
| LiteLLM | `models/litellm.py` | Bedrock → LiteLLM universal |
| Mistral | `models/mistral.py` | Bedrock → Mistral API |
| Llama.cpp | `models/llamacpp.py` | Bedrock → llama-cpp-python |

**Abstraction Strategy**: Thin adapter pattern

Each provider implements the `Model` ABC:

```python
# models/model.py:18
class Model(abc.ABC):
    @abc.abstractmethod
    def stream(
        self,
        messages: Messages,
        tool_specs: Optional[list[ToolSpec]] = None,
        system_prompt: Optional[str] = None,
        *,
        tool_choice: ToolChoice | None = None,
        system_prompt_content: list[SystemContentBlock] | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[StreamEvent]:
        """Stream conversation with the model."""
        pass
```

**Transformation Flow**:
1. Agent calls `stream_messages()` with Bedrock-native messages
2. Model adapter transforms to provider-specific format via `format_request()`
3. Provider SDK streams responses
4. Adapter transforms back via `format_chunk()`
5. Unified `StreamEvent` yielded to agent

### Tool Call Encoding

**Request Method**: Function calling API (provider-native)

**Schema Transmission**: JSON Schema in Bedrock format

```python
# types/tools.py:22
class ToolSpec(TypedDict):
    description: str
    inputSchema: JSONSchema  # JSON Schema dict
    name: str
    outputSchema: NotRequired[JSONSchema]  # Optional, filtered for unsupported providers
```

**Anthropic Transformation Example**:

```python
# models/anthropic.py:224
def format_request(self, messages, tool_specs, ...):
    return {
        "tools": [
            {
                "name": tool_spec["name"],
                "description": tool_spec["description"],
                "input_schema": tool_spec["inputSchema"]["json"],  # Extract nested JSON
            }
            for tool_spec in tool_specs or []
        ],
        # ...
    }
```

**OpenAI Transformation Example**:

```python
# models/openai.py:361
def format_request(self, messages, tool_specs, ...):
    return {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool_spec["name"],
                    "description": tool_spec["description"],
                    "parameters": tool_spec["inputSchema"]["json"],  # OpenAI uses "parameters"
                },
            }
            for tool_spec in tool_specs or []
        ],
        # ...
    }
```

**Response Parsing**: Streaming accumulator pattern

```python
# event_loop/streaming.py:192-213
def handle_content_block_delta(event, state):
    if "toolUse" in delta_content:
        # Accumulate partial JSON
        state["current_tool_use"]["input"] += delta_content["toolUse"]["input"]

# event_loop/streaming.py:271-278
def handle_content_block_stop(state):
    # Parse complete JSON at block end
    current_tool_use["input"] = json.loads(current_tool_use["input"])
    tool_use = ToolUse(
        toolUseId=current_tool_use["toolUseId"],
        name=current_tool_use["name"],
        input=current_tool_use["input"],
    )
    content.append({"toolUse": tool_use})
```

**Tool Choice Support**:

| Constraint | Bedrock Format | Anthropic | OpenAI | Notes |
|------------|---------------|-----------|--------|-------|
| Auto | `{"auto": {}}` | `{"type": "auto"}` | `"auto"` | Default behavior |
| Any | `{"any": {}}` | `{"type": "any"}` | `"required"` | Must use a tool |
| Specific | `{"tool": {"name": "X"}}` | `{"type": "tool", "name": "X"}` | `{"type": "function", "function": {"name": "X"}}` | Force specific tool |

**Tool Result Attribution**:

```python
# Bedrock format (types/tools.py:87)
class ToolResult(TypedDict):
    content: list[ToolResultContent]
    status: ToolResultStatus  # "success" | "error"
    toolUseId: str  # Matches ToolUse.toolUseId

# OpenAI transformation (models/openai.py:197)
return {
    "role": "tool",
    "tool_call_id": tool_result["toolUseId"],  # Maps to OpenAI's tool_call_id
    "content": [format_content(c) for c in tool_result["content"]],
}
```

### Streaming Implementation

**Protocol**: Server-Sent Events (SSE) via provider SDKs

**Event Types Emitted**:

| Event Type | Purpose | Emitted When |
|------------|---------|--------------|
| `messageStart` | Conversation turn begins | First chunk from model |
| `contentBlockStart` | New content block (text/tool) | Block boundary |
| `contentBlockDelta` | Incremental content | Each streaming chunk |
| `contentBlockStop` | Block complete | Block boundary |
| `messageStop` | Turn complete | Final chunk |
| `metadata` | Usage/metrics | After message complete |
| `redactContent` | Guardrail redaction | Guardrail triggered |

**Unified StreamEvent TypedDict**:

```python
# types/streaming.py:210
class StreamEvent(TypedDict, total=False):
    contentBlockDelta: ContentBlockDeltaEvent
    contentBlockStart: ContentBlockStartEvent
    contentBlockStop: ContentBlockStopEvent
    messageStart: MessageStartEvent
    messageStop: MessageStopEvent
    metadata: MetadataEvent
    redactContent: RedactContentEvent
    # Exception events
    modelStreamErrorException: ModelStreamErrorEvent
    throttlingException: ExceptionEvent
```

**Partial Tool Call Handling**: Stateful accumulation

```python
# event_loop/streaming.py:380-417
async def process_stream(chunks):
    state = {
        "message": {"role": "assistant", "content": []},
        "text": "",
        "current_tool_use": {},  # Accumulates partial tool JSON
        "reasoningText": "",
        "citationsContent": [],
    }

    async for chunk in chunks:
        if "contentBlockStart" in chunk:
            # Initialize tool use accumulator
            state["current_tool_use"] = handle_content_block_start(...)

        elif "contentBlockDelta" in chunk:
            # Append to accumulator
            state["current_tool_use"]["input"] += delta["toolUse"]["input"]

        elif "contentBlockStop" in chunk:
            # Parse complete JSON, create ToolUse
            state = handle_content_block_stop(state)
```

**Backpressure Support**: Native via AsyncGenerator

```python
# models/model.py:77
async def stream(...) -> AsyncIterable[StreamEvent]:
    """AsyncIterable allows consumer to control flow."""

# Agent consumption (event_loop/event_loop.py:341)
async for event in stream_messages(...):
    yield event  # Backpressure propagates upstream
```

**Provider-Specific Streaming Examples**:

**Anthropic**:
```python
# models/anthropic.py:400-407
async with self.client.messages.stream(**request) as stream:
    async for event in stream:
        if event.type in AnthropicModel.EVENT_TYPES:
            yield self.format_chunk(event.model_dump())

    # Usage comes after stream completes
    yield self.format_chunk({"type": "metadata", "usage": usage.model_dump()})
```

**OpenAI**:
```python
# models/openai.py:535-586
async for event in response:
    if choice.delta.content:
        yield format_chunk({"chunk_type": "content_delta", "data": choice.delta.content})

    # Accumulate tool calls by index
    for tool_call in choice.delta.tool_calls or []:
        tool_calls.setdefault(tool_call.index, []).append(tool_call)

    if choice.finish_reason:
        break

# Emit accumulated tool calls after text complete
for tool_deltas in tool_calls.values():
    yield format_chunk({"chunk_type": "content_start", "data_type": "tool", ...})
    for tool_delta in tool_deltas:
        yield format_chunk({"chunk_type": "content_delta", "data_type": "tool", ...})
```

**Error Handling in Streams**:

```python
# models/anthropic.py:409-416
except anthropic.RateLimitError as error:
    raise ModelThrottledException(str(error)) from error

except anthropic.BadRequestError as error:
    if any(overflow_message in str(error).lower() for overflow_message in OVERFLOW_MESSAGES):
        raise ContextWindowOverflowException(str(error)) from error
    raise error
```

### Agentic Primitives

#### System Prompt Assembly

**Multi-format support**: String or structured content blocks

```python
# agent/agent.py:794-816
def _initialize_system_prompt(
    self, system_prompt: str | list[SystemContentBlock] | None
) -> tuple[str | None, list[SystemContentBlock] | None]:
    """Maps input to both string and content block representations."""
    if isinstance(system_prompt, str):
        return system_prompt, [{"text": system_prompt}]
    elif isinstance(system_prompt, list):
        # Concatenate text blocks for backwards compatibility
        text_parts = [block["text"] for block in system_prompt if "text" in block]
        system_prompt_str = "\n".join(text_parts) if text_parts else None
        return system_prompt_str, system_prompt
    else:
        return None, None
```

**Transmission to model**:

```python
# event_loop/event_loop.py:341-348
async for event in stream_messages(
    agent.model,
    agent.system_prompt,  # Backwards-compatible string
    agent.messages,
    tool_specs,
    system_prompt_content=agent._system_prompt_content,  # Authoritative blocks
):
```

**Provider handling**:

- **Bedrock**: Native support for `SystemContentBlock[]` with cache points
- **Anthropic**: Supports cache_control on system blocks
- **OpenAI**: Converts to system role messages (no caching)

```python
# models/openai.py:245-254
def _format_system_messages(system_prompt, system_prompt_content):
    # Backwards compatibility: string → content blocks
    if system_prompt and system_prompt_content is None:
        system_prompt_content = [{"text": system_prompt}]

    # TODO: Handle caching blocks (not supported by OpenAI)
    return [
        {"role": "system", "content": content["text"]}
        for content in system_prompt_content or []
        if "text" in content
    ]
```

#### Scratchpad / Working Memory

**No explicit scratchpad**: Working memory = full conversation history

- Messages stored in `agent.messages: List[Message]`
- No separate reasoning buffer
- Extended thinking via `reasoningContent` blocks (inline with response)

```python
# types/content.py:52
class ReasoningContentBlock(TypedDict, total=False):
    reasoningText: ReasoningTextBlock  # Model's internal reasoning
    redactedContent: bytes  # Encrypted safety redactions
```

#### Interrupt / Human-in-the-Loop

**Interrupt mechanism**: Async coordination via `_InterruptState`

```python
# interrupt/_interrupt_state.py (inferred)
class _InterruptState:
    activated: bool
    context: dict[str, Any]  # Contains "tool_use_message"

# event_loop/event_loop.py:144-146
if agent._interrupt_state.activated:
    stop_reason = "tool_use"
    message = agent._interrupt_state.context["tool_use_message"]
```

**Tool-level interrupt support**:

```python
# types/tools.py:128
@dataclass
class ToolContext(_Interruptible):
    tool_use: ToolUse
    agent: Any
    invocation_state: dict[str, Any]

    # Inherited from _Interruptible
    async def interrupt(self, prompt: str) -> str:
        """Request human input during tool execution."""
```

**Usage pattern**:

```python
@tool
async def interactive_tool(query: str, context: ToolContext) -> str:
    # Request human approval
    user_input = await context.interrupt("Proceed with deletion? (yes/no)")
    if user_input.lower() != "yes":
        return "Operation cancelled"
    # Continue execution
```

#### Conversation State Machine

**State transitions**:

```
┌─────────────┐
│ User Input  │
└─────┬───────┘
      │
      ▼
┌─────────────────┐
│ Model Inference │◄─────┐
└─────┬───────────┘      │
      │                  │
      ▼                  │
  ┌───────┐              │
  │ Stop? │──yes──► End  │
  └───┬───┘              │
      │no                │
      ▼                  │
┌──────────────┐         │
│ Tool Execute │─────────┘
└──────────────┘  (recurse)
```

**Implementation**:

```python
# event_loop/event_loop.py:179-195
if stop_reason == "tool_use":
    # Execute tools, then recurse
    tool_events = _handle_tool_execution(...)
    async for tool_event in tool_events:
        yield tool_event
    return  # Recursion continues in _handle_tool_execution

# End the cycle
yield EventLoopStopEvent(stop_reason, message, metrics, state)
```

**Recursion pattern**:

```python
# event_loop/event_loop.py:247-283
async def recurse_event_loop(agent, invocation_state, ...):
    """Recursive call after tool execution."""
    events = event_loop_cycle(agent, invocation_state, ...)
    async for event in events:
        yield event
```

**Risk**: Unbounded recursion (no max depth limit) → stack overflow on deep tool chains

### Provider Abstraction

**Architecture**: Adapter pattern with unified interface

```
┌──────────┐
│  Agent   │
└────┬─────┘
     │
     ▼
┌─────────────────┐
│ Model ABC       │ ◄── Unified interface
│ - stream()      │
│ - update_config│
└────┬────────────┘
     │
     ├─► BedrockModel     (native)
     ├─► AnthropicModel   (adapter)
     ├─► OpenAIModel      (adapter)
     ├─► GeminiModel      (adapter)
     └─► LiteLLMModel     (universal gateway)
```

**Provider Feature Matrix**:

| Feature | Bedrock | Anthropic | OpenAI | Gemini | LiteLLM | Notes |
|---------|---------|-----------|--------|--------|---------|-------|
| Function Calling | ✅ | ✅ | ✅ | ✅ | ✅ | Universal support |
| Streaming | ✅ | ✅ | ✅ | ✅ | ✅ | SSE-based |
| Prompt Caching | ✅ | ✅ | ❌ | ❌ | Varies | Bedrock/Anthropic only |
| Extended Thinking | ✅ | ✅ | ✅ | ❌ | Varies | `reasoningContent` |
| Guardrails | ✅ | ❌ | ❌ | ❌ | ❌ | Bedrock-native feature |
| Vision (images) | ✅ | ✅ | ✅ | ✅ | ✅ | Base64 encoding |
| Documents | ✅ | ✅ | ✅ | ❌ | Varies | PDF/text as base64 |
| Citations | ✅ | Partial | ❌ | ❌ | ❌ | Bedrock RAG feature |
| Structured Output | ✅ | Via tools | Native API | Via tools | Varies | Different mechanisms |

**Graceful Degradation Examples**:

1. **Prompt Caching (OpenAI)**:
```python
# models/openai.py:249
# TODO: Handle caching blocks https://github.com/strands-agents/sdk-python/issues/1140
return [
    {"role": "system", "content": content["text"]}
    for content in system_prompt_content or []
    if "text" in content  # Ignore cache points
]
```

2. **Reasoning Content (OpenAI)**:
```python
# models/openai.py:273
if any("reasoningContent" in content for content in contents):
    logger.warning(
        "reasoningContent is not supported in multi-turn conversations with Chat Completions API."
    )
# Continue processing, stripping reasoning blocks
```

3. **Tool Result Status (Bedrock auto-detection)**:
```python
# models/bedrock.py:47-49
_MODELS_INCLUDE_STATUS = ["anthropic.claude"]

# Conditionally include status based on model ID
if should_include_status(model_id):
    tool_result["status"] = status
```

**Multi-LLM Support Strategy**:

1. **Internal normalization**: All messages use Bedrock format
2. **Adapter transformation**: Each provider maps to/from Bedrock
3. **Feature detection**: Check provider capabilities, warn on unsupported features
4. **Universal gateway option**: LiteLLM for 100+ providers via single adapter

```python
# models/litellm.py (wrapper around litellm library)
class LiteLLMModel(Model):
    """Universal model provider using LiteLLM gateway."""
    # Delegates to litellm.acompletion() with OpenAI-compatible API
```

## Code References

### Core Protocol
- `src/strands/types/content.py:178-192` - Message and ContentBlock types
- `src/strands/types/streaming.py:210-239` - StreamEvent union type
- `src/strands/types/tools.py:22-65` - ToolSpec, ToolUse, ToolResult
- `src/strands/models/model.py:18-101` - Model ABC interface

### Provider Adapters
- `src/strands/models/bedrock.py:56-200` - BedrockModel (native)
- `src/strands/models/anthropic.py:30-466` - AnthropicModel adapter
- `src/strands/models/openai.py:40-665` - OpenAIModel adapter
- `src/strands/models/gemini.py` - GeminiModel adapter
- `src/strands/models/litellm.py` - LiteLLMModel universal gateway

### Streaming Pipeline
- `src/strands/event_loop/streaming.py:365-418` - process_stream() accumulator
- `src/strands/event_loop/streaming.py:420-449` - stream_messages() orchestrator
- `src/strands/event_loop/streaming.py:192-251` - Partial tool call handling

### System Prompt
- `src/strands/agent/agent.py:794-816` - _initialize_system_prompt()
- `src/strands/event_loop/event_loop.py:341-348` - System prompt injection

### Interrupt Mechanism
- `src/strands/types/tools.py:128-150` - ToolContext with interrupt support
- `src/strands/event_loop/event_loop.py:144-146` - Interrupt state check

## Implications for New Framework

### Positive Patterns

1. **Unified internal format reduces coupling**: Single message type = fewer conversions
2. **Streaming-first with backpressure**: AsyncGenerator enables flow control
3. **Stateful accumulation of partial tool calls**: Handles streaming JSON correctly
4. **TypedDict for API boundaries**: Lightweight, matches provider schemas exactly
5. **Graceful degradation warnings**: Log unsupported features instead of failing
6. **Tool result status field**: Explicit error handling ("success" | "error")
7. **Multi-format system prompt support**: String (simple) + blocks (advanced)
8. **Provider-agnostic tool schemas**: JSON Schema as universal format
9. **Interrupt-aware execution**: Human-in-the-loop as first-class primitive
10. **Exception hierarchy for recovery**: Throttling vs overflow vs max tokens

### Considerations

1. **Bedrock-centric design may limit non-AWS adoption**: Internal format assumes Bedrock features
2. **Manual adapter maintenance burden**: Each provider requires custom mapping logic
3. **Feature parity challenges**: Caching/guardrails/reasoning not universal
4. **No runtime validation**: TypedDict doesn't validate at runtime (unlike Pydantic)
5. **Tool results as "user" role is confusing**: Bedrock convention differs from OpenAI
6. **Unbounded recursion risk**: No max depth on tool loops
7. **Adapter complexity grows with features**: Citations, guardrails, reasoning all need per-provider handling
8. **No provider capability negotiation**: Framework assumes features, logs warnings on mismatch
9. **LiteLLM dependency for broad support**: Universal gateway adds indirection
10. **Message normalization done in-place**: Mutates messages before sending (blank text, tool names)

## Anti-Patterns Observed

### 1. In-Place Message Mutation
**Issue**: `_normalize_messages()` modifies messages before sending to model

```python
# event_loop/streaming.py:44-102
def _normalize_messages(messages: Messages) -> Messages:
    for message in messages:
        # Modifies content in place
        content[:] = [item for item in content if ...]
```

**Risk**: State corruption in async contexts, hard to debug

**Fix**: Functional updates (return new list)

### 2. No Runtime Validation
**Issue**: TypedDict doesn't validate structure at runtime

```python
# types/content.py:74
class ContentBlock(TypedDict, total=False):
    text: str
    toolUse: ToolUse
    # No validation that only one field is present
```

**Risk**: Invalid messages passed to providers

**Fix**: Use Pydantic models with validators

### 3. Hardcoded Provider Feature Detection
**Issue**: String matching on model IDs for feature support

```python
# models/bedrock.py:47
_MODELS_INCLUDE_STATUS = ["anthropic.claude"]

# Later: string matching
if any(model_pattern in model_id for model_pattern in _MODELS_INCLUDE_STATUS):
```

**Risk**: Brittle, requires updates for new models

**Fix**: Provider capability metadata system

### 4. Silent Feature Stripping
**Issue**: Unsupported features removed without user awareness in some cases

```python
# models/openai.py:249
# TODO: Handle caching blocks
return [
    {"role": "system", "content": content["text"]}
    for content in system_prompt_content or []
    if "text" in content  # Silently drops cache points
]
```

**Risk**: User expects caching, doesn't get it

**Fix**: Explicit error or warning on feature mismatch

### 5. Exception Hierarchy Overuse
**Issue**: Multiple exception types for similar scenarios

```python
# types/exceptions.py (inferred)
- ContextWindowOverflowException
- MaxTokensReachedException
- ModelThrottledException
- EventLoopException
```

**Risk**: Callers must catch many exception types

**Fix**: Unified error type with error codes

### 6. No Structured Error Codes
**Issue**: Error messages are plain text

```python
# models/anthropic.py:413
raise ContextWindowOverflowException(str(error)) from error
```

**Risk**: Hard to programmatically handle specific errors

**Fix**: Add error codes to exception types

### 7. Adapter Duplication
**Issue**: Similar transformation logic repeated across adapters

```python
# models/anthropic.py:99 + models/openai.py:116
def _format_request_message_content(content):
    if "image" in content:
        # Base64 encoding logic duplicated
```

**Risk**: Inconsistency, maintenance burden

**Fix**: Shared transformation utilities

### 8. Lack of Provider Abstraction for Advanced Features
**Issue**: No unified API for guardrails, caching, reasoning

```python
# Bedrock has guardrail_id config, others don't
# Anthropic has cache_control, OpenAI doesn't
# No common interface for these features
```

**Risk**: Framework features tied to specific providers

**Fix**: Feature plugins with provider-specific implementations
