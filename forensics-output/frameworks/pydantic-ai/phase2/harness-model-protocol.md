# Harness-Model Protocol Analysis: Pydantic-AI

## Summary
- **Key Finding 1**: Universal internal message format with provider-specific adapters - ModelMessage/ModelRequest/ModelResponse types serve as protocol-agnostic representation
- **Key Finding 2**: Streaming built with delta accumulation pattern via ModelResponsePartsManager - supports partial tool calls and progressive validation
- **Key Finding 3**: Comprehensive multi-provider abstraction (20+ LLMs) via adapter pattern - each provider translates internal messages to native wire format
- **Classification**: **Unified message protocol with provider-specific adapters**

## Detailed Analysis

### Message Protocol

**Wire Format Family**: Hybrid - uses provider-native formats (OpenAI Chat Completions, Anthropic Messages, Gemini Content) via adapters

**Providers Supported**:
- OpenAI-compatible: `/models/openai.py` - OpenAI, Azure, Groq, DeepSeek, Fireworks, GitHub, Grok, Heroku, Moonshot, Ollama, Together, Vercel, LiteLLM, Nebius, OVHCloud, Alibaba
- Anthropic: `/models/anthropic.py` - Anthropic native + Bedrock
- Google: `/models/google.py` - Gemini (GLA + Vertex)
- Groq: `/models/groq.py`
- Cohere: `/models/cohere.py`
- Mistral: `/models/mistral.py`
- OpenRouter: `/models/openrouter.py`
- Bedrock: `/models/bedrock.py` (Converse API)
- HuggingFace: `/models/huggingface.py`
- Cerebras: `/models/cerebras.py`

**Abstraction Strategy**: Thin adapter layer - internal universal types mapped to provider-specific types at request/response boundary

#### Internal Message Type Hierarchy

```python
# Defined in messages.py

# Request parts (sent to model)
ModelRequestPart = SystemPromptPart | UserPromptPart | ToolReturnPart | RetryPromptPart

# Response parts (received from model)
ModelResponsePart = TextPart | ToolCallPart | BuiltinToolCallPart |
                    BuiltinToolReturnPart | ThinkingPart | FilePart

# Message envelope
ModelRequest:
    parts: Sequence[ModelRequestPart]
    timestamp: datetime | None
    instructions: str | None  # System prompt
    kind: Literal['request']
    run_id: str | None
    metadata: dict[str, Any] | None

ModelResponse:
    parts: Sequence[ModelResponsePart]
    usage: RequestUsage
    model_name: str | None
    timestamp: datetime
    kind: Literal['response']
    provider_name: str | None
    provider_url: str | None
    provider_details: dict[str, Any] | None  # Vendor-specific extras
    provider_response_id: str | None
    finish_reason: FinishReason | None
    run_id: str | None
    metadata: dict[str, Any] | None

# Union type
ModelMessage = ModelRequest | ModelResponse
```

**Key Design**: Discriminated unions (`kind` field) enable type-safe message handling. Provider details preserved in `provider_details` dict.

#### Translation Example: Anthropic Adapter

From `/models/anthropic.py:406`:

```python
# Internal -> Anthropic format
system_prompt, anthropic_messages = await self._map_message(
    messages, model_request_parameters, model_settings
)

await self.client.beta.messages.create(
    system=system_prompt or OMIT,
    messages=anthropic_messages,  # list[BetaMessageParam]
    model=self._model_name,
    tools=tools or OMIT,
    # ...
)
```

**Message mapping** (`_map_message` method, line ~700):
- Separates system prompts from messages (Anthropic requires separate `system` param)
- Groups consecutive user/assistant messages
- Translates UserPromptPart → BetaMessageParam(role='user', content=[...])
- Translates ToolReturnPart → tool_result content blocks
- Handles multi-modal content (ImageUrl, DocumentUrl, BinaryContent)
- Applies cache control markers (CachePoint) to specific blocks

#### Translation Example: OpenAI Adapter

From `/models/openai.py`:

OpenAI adapter uses native SDK types directly:
- `ChatCompletionMessageParam` for messages
- `ChatCompletionToolParam` for tool definitions
- `ChatCompletionChunk` for streaming

**Two model variants**:
1. **OpenAIChatModel** - uses Chat Completions API (`/chat/completions`)
2. **OpenAIResponsesModel** - uses Responses API (`/responses`) for multi-turn with builtin tools

**Message assembly** (inferred from imports):
- SystemPromptPart → messages with role='system'
- UserPromptPart → role='user' with content array (text, images, audio, documents)
- ToolReturnPart → role='tool' with tool_call_id matching
- ModelResponse parts → role='assistant' with content/tool_calls

**Provider abstraction pattern**:

```python
# models/__init__.py:549-551
class Model(ABC):
    @abstractmethod
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        raise NotImplementedError()
```

Every provider implements `request()` which:
1. Accepts universal `list[ModelMessage]`
2. Translates to provider-native format
3. Makes HTTP request via provider SDK
4. Parses response back to `ModelResponse`

### Tool Call Encoding

**Request Method**: Function calling API (native to each provider)

**Schema Transmission**:

Via `ModelRequestParameters` (line 522-547):

```python
@dataclass(repr=False, kw_only=True)
class ModelRequestParameters:
    function_tools: list[ToolDefinition] = field(default_factory=list)
    builtin_tools: list[AbstractBuiltinTool] = field(default_factory=list)
    output_mode: OutputMode = 'text'
    output_object: OutputObjectDefinition | None = None
    output_tools: list[ToolDefinition] = field(default_factory=list)
    # ...
```

**ToolDefinition structure** (from `tools.py` via earlier reading):

```python
@dataclass(kw_only=True)
class ToolDefinition:
    name: str
    description: str
    parameters_json_schema: ObjectJsonSchema
    outer_typed_dict_key: str | None = None
    strict: bool | None = None  # OpenAI strict mode
```

**Anthropic tool schema translation** (`_get_tools` method):

```python
def _get_tools(...) -> list[BetaToolUnionParam]:
    tools: list[BetaToolUnionParam] = [
        BetaToolParam(
            name=tool_def.name,
            description=tool_def.description,
            input_schema=tool_def.parameters_json_schema,
        )
        for tool_def in model_request_parameters.function_tools
    ]
```

**OpenAI tool schema** (similar pattern, using `ChatCompletionToolParam`).

**Response Parsing**:

**Anthropic** (`_process_response`, line 521-579):

```python
for item in response.content:
    if isinstance(item, BetaTextBlock):
        items.append(TextPart(content=item.text))
    elif isinstance(item, BetaToolUseBlock):
        items.append(
            ToolCallPart(
                tool_name=item.name,
                args=cast(dict[str, Any], item.input),
                tool_call_id=item.id,
            )
        )
    elif isinstance(item, BetaThinkingBlock):
        items.append(ThinkingPart(content=item.thinking, signature=item.signature))
    # ... other block types
```

**Tool choice support**:

Anthropic `_infer_tool_choice` method (not shown but referenced):
- Supports `any`, `auto`, `tool:<name>`
- Maps to `BetaToolChoiceParam`

OpenAI:
- Supports `none`, `auto`, `required`, specific function
- Maps via `ChatCompletionToolChoiceOptionParam`

**Table of tool encoding by provider**:

| Provider | Tool Schema Format | Tool Call Format | Parallel Calls | Strict Mode |
|----------|-------------------|------------------|----------------|-------------|
| OpenAI | `function.parameters` | `tool_calls[]` with `function.name/arguments` | Yes | Yes (`strict: true`) |
| Anthropic | `input_schema` | `content[].tool_use` with `name/input` | Yes | Yes (`strict: true`) |
| Google | `functionDeclarations` | `functionCall.name/args` | Yes | No |
| Bedrock | Converse `toolSpec` | `toolUse` blocks | Yes | No |

### Streaming Implementation

**Protocol**: SSE (Server-Sent Events) via provider SDKs (`AsyncStream`)

**Partial Tool Call Handling**: Supported via delta accumulation

**Architecture**:

1. **Base class** (`StreamedResponse` in `/models/__init__.py:843-979`):

```python
@dataclass
class StreamedResponse(ABC):
    model_request_parameters: ModelRequestParameters
    _parts_manager: ModelResponsePartsManager = field(default_factory=ModelResponsePartsManager)
    _event_iterator: AsyncIterator[ModelResponseStreamEvent] | None = None
    _usage: RequestUsage = field(default_factory=RequestUsage)

    def __aiter__(self) -> AsyncIterator[ModelResponseStreamEvent]:
        # Wraps _get_event_iterator with part_end events
        ...

    @abstractmethod
    async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
        # Provider-specific implementation
        raise NotImplementedError()
```

2. **Parts Manager** (referenced as `_parts_manager`):

Accumulates deltas into complete parts. Not shown in detail but pattern evident from usage:
- Maintains list of `ModelResponsePart`
- Applies deltas (TextPartDelta, ToolCallPartDelta, ThinkingPartDelta)
- Returns complete parts via `get_parts()`

3. **Event Types** (`messages.py:1787-1872`):

```python
ModelResponseStreamEvent = (
    PartStartEvent |      # New part begins
    PartDeltaEvent |      # Incremental update to part
    PartEndEvent |        # Part complete
    FinalResultEvent      # Output validation matched
)

@dataclass
class PartStartEvent:
    index: int
    part: ModelResponsePart
    previous_part_kind: Literal[...] | None

@dataclass
class PartDeltaEvent:
    index: int
    delta: ModelResponsePartDelta

@dataclass
class PartEndEvent:
    index: int
    part: ModelResponsePart
    next_part_kind: Literal[...] | None
```

4. **Delta Types** (`messages.py:1489-1778`):

```python
@dataclass
class TextPartDelta:
    content_delta: str

    def apply(self, part: ModelResponsePart) -> TextPart:
        return replace(part, content=part.content + self.content_delta)

@dataclass
class ToolCallPartDelta:
    tool_name_delta: str | None
    args_delta: str | dict[str, Any] | None  # Incremental JSON or dict
    tool_call_id: str | None

    def apply(self, part: ToolCallPart | ToolCallPartDelta) -> ToolCallPart:
        # Accumulates tool name and arguments
        # Handles JSON string concatenation OR dict merging
        ...
```

**Critical pattern**: `ToolCallPartDelta.apply()` can apply to another delta OR a part, enabling flexible accumulation.

5. **Provider-Specific Streaming**:

**Anthropic** (`AnthropicStreamedResponse._get_event_iterator`):

```python
async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
    async for event in self._response:
        if isinstance(event, BetaRawContentBlockStartEvent):
            # Map to PartStartEvent with initial part
            ...
        elif isinstance(event, BetaRawContentBlockDeltaEvent):
            if isinstance(event.delta, BetaTextDelta):
                yield PartDeltaEvent(index=event.index, delta=TextPartDelta(content_delta=event.delta.text))
            elif isinstance(event.delta, BetaInputJSONDelta):
                yield PartDeltaEvent(index=event.index, delta=ToolCallPartDelta(args_delta=event.delta.partial_json))
            # ... other delta types
```

**Event Subscription**:

Consumers iterate the stream:

```python
async for event in streamed_response:
    if isinstance(event, PartStartEvent):
        # New part started
    elif isinstance(event, PartDeltaEvent):
        # Incremental update
    elif isinstance(event, FinalResultEvent):
        # Output validated, can return early
```

**Event Types Emitted**:

| Event | Description | Provider Support |
|-------|-------------|------------------|
| `PartStartEvent` | New part (text, tool call, thinking) begins | All streaming providers |
| `PartDeltaEvent` | Incremental content/args delta | All streaming providers |
| `PartEndEvent` | Part complete, next part kind hinted | All streaming providers |
| `FinalResultEvent` | Response matches output schema | Framework-level (all providers) |

**Validation During Streaming**:

From `StreamedResponse.__aiter__` (line 866-878):

```python
async for event in iterator:
    yield event
    if (final_result_event := _get_final_result_event(event, self.model_request_parameters)) is not None:
        self.final_result_event = final_result_event
        yield final_result_event
        break  # Early termination when output validated
```

Enables **streaming validation** - stop consuming stream once valid output detected.

### Agentic Primitives

#### System Prompt Assembly

**Dynamic System Prompts**:

Agents support callable system prompts re-evaluated per step:

```python
# From agent.py (inferred from architecture)
@agent.system_prompt
async def dynamic_prompt(ctx: RunContext[DepsT]) -> str:
    # Re-executed before each model request
    return f"Current time: {ctx.deps.current_time}"
```

**Assembly Process**:

1. System prompts collected from decorators
2. Merged into `ModelRequest.instructions`
3. Provider adapters handle placement:
   - **Anthropic**: Separate `system` parameter
   - **OpenAI**: `role='system'` messages
   - **Google**: `systemInstruction` field

**Model.\_get_instructions** (line 791-840):

```python
@staticmethod
def _get_instructions(messages: Sequence[ModelMessage], model_request_parameters: ModelRequestParameters | None = None) -> str | None:
    # Extracts instructions from last ModelRequest
    # Handles special case: mock requests for result tools
    # Appends prompted_output_instructions if needed
    ...
```

#### Scratchpad / Working Memory

**No dedicated scratchpad** - working memory is flat message history.

From memory-orchestration analysis:
- Single `message_history: list[ModelMessage]` in `GraphAgentState`
- No built-in short-term/long-term separation
- Users implement via history processors

**History processors** allow memory transformation:

```python
async def limit_context(ctx: RunContext, messages: list[ModelMessage]) -> list[ModelMessage]:
    # Keep only last 10 messages
    return messages[-10:]

agent = Agent('openai:gpt-5', history_processors=[limit_context])
```

#### Interrupt / Human-in-the-Loop

**No built-in HITL primitive** in the harness-model protocol layer.

HITL would be implemented at graph execution level (not visible in model protocol analysis).

Agents support pause/resume via graph state machine, but this is orthogonal to model protocol.

#### Conversation State Machine

**Graph-based execution** (from `/pydantic_ai/_agent_graph.py`):

```
UserPromptNode → ModelRequestNode → CallToolsNode → (loop or End)
```

**State tracking**:
- `GraphAgentState.message_history` maintains conversation
- `new_message_index` tracks messages added this run
- Usage tracking via `RunUsage` accumulated across turns

**Multi-turn reconstruction**:

Stateless APIs reconstructed via:
1. Full `message_history` passed to model each turn
2. History processors filter/transform before request
3. Response appended to history
4. Tool results added as new messages

**Example flow**:

```
Turn 1: [UserPromptPart("What's the weather?")]
        → [ModelResponse(ToolCallPart("get_weather"))]
        → [ToolReturnPart(content="72°F")]

Turn 2: [UserPromptPart, ModelResponse(ToolCallPart), ToolReturnPart]  # Full history
        → [ModelResponse(TextPart("It's 72°F"))]
```

### Provider Abstraction

**Profile System** (`profiles/`):

Each provider has `ModelProfile` defining capabilities:

```python
@dataclass
class ModelProfile:
    supports_tools: bool
    supports_json_schema_output: bool
    supports_image_output: bool
    default_structured_output_mode: OutputMode
    native_output_requires_schema_in_instructions: bool
    json_schema_transformer: type[JsonSchemaTransformer] | None
    supported_builtin_tools: frozenset[type[AbstractBuiltinTool]]
    prompted_output_template: str
```

**Provider table**:

| Provider | Tools | Native Structured | Image Output | Builtin Tools | Streaming |
|----------|-------|-------------------|--------------|---------------|-----------|
| OpenAI | ✓ | ✓ | ✓ (DALL-E) | FileSearch, WebSearch, CodeExec, Computer, MCP | ✓ |
| Anthropic | ✓ | ✓ | ✗ | WebSearch, CodeExec, WebFetch, Memory, MCP | ✓ |
| Google | ✓ | ✓ | ✗ | CodeExec | ✓ |
| Bedrock | ✓ | ✗ | ✗ | - | ✓ |
| Groq | ✓ | ✓ | ✗ | - | ✓ |
| Cohere | ✓ | ✗ | ✗ | - | ✓ |
| Mistral | ✓ | ✗ | ✗ | - | ✓ |

**Graceful degradation**:

`prepare_request()` method (line 634-700):

```python
def prepare_request(self, model_settings, model_request_parameters):
    # ...
    if params.output_mode == 'native' and not self.profile.supports_json_schema_output:
        raise UserError('Native structured output is not supported by this model.')
    if params.output_mode == 'tool' and not self.profile.supports_tools:
        raise UserError('Tool output is not supported by this model.')
    if params.allow_image_output and not self.profile.supports_image_output:
        raise UserError('Image output is not supported by this model.')
```

**Fails fast** rather than silently degrading.

### System Prompt Handling

**Injection point**: `Model._get_instructions()` method extracts from message history.

**Provider-specific handling**:

**Anthropic**:
```python
# Separate system parameter
system_prompt, anthropic_messages = await self._map_message(messages, ...)
await client.beta.messages.create(
    system=system_prompt or OMIT,
    messages=anthropic_messages,
    ...
)
```

**OpenAI**: System prompts added as `role='system'` messages.

**Google**: Uses `systemInstruction` parameter (inferred).

**Dynamic re-evaluation**: System prompt functions called per-request by graph execution, result stored in `ModelRequest.instructions`.

## Code References

**Core Protocol**:
- `/pydantic_ai_slim/pydantic_ai/models/__init__.py:549` - `Model` ABC
- `/pydantic_ai_slim/pydantic_ai/messages.py:987-1018` - `ModelRequest`
- `/pydantic_ai_slim/pydantic_ai/messages.py:1223-1476` - `ModelResponse`
- `/pydantic_ai_slim/pydantic_ai/messages.py:1479` - `ModelMessage` union

**Streaming**:
- `/pydantic_ai_slim/pydantic_ai/models/__init__.py:843` - `StreamedResponse` ABC
- `/pydantic_ai_slim/pydantic_ai/messages.py:1489` - `TextPartDelta`
- `/pydantic_ai_slim/pydantic_ai/messages.py:1635` - `ToolCallPartDelta`
- `/pydantic_ai_slim/pydantic_ai/messages.py:1869` - `ModelResponseStreamEvent`

**Adapters**:
- `/pydantic_ai_slim/pydantic_ai/models/openai.py` - OpenAI adapter
- `/pydantic_ai_slim/pydantic_ai/models/anthropic.py:406` - Message mapping
- `/pydantic_ai_slim/pydantic_ai/models/anthropic.py:521` - Response processing

**Tool Interface**:
- `/pydantic_ai_slim/pydantic_ai/models/__init__.py:522` - `ModelRequestParameters`
- `/pydantic_ai_slim/pydantic_ai/tools.py` - `ToolDefinition`

**Profiles**:
- `/pydantic_ai_slim/pydantic_ai/profiles/__init__.py` - `ModelProfile`

## Implications for New Framework

### Positive Patterns

1. **Universal Message Type**: Single `ModelMessage` union enables provider-agnostic code
   - **Adopt**: Define protocol-neutral message types with discriminated unions
   - **Benefit**: Tool logic, history management, validation all provider-independent

2. **Streaming Delta Pattern**: Explicit delta types with `apply()` methods
   - **Adopt**: TextDelta, ToolCallDelta with accumulation logic
   - **Benefit**: Clean progressive rendering, partial tool call support
   - **Implementation**: Parts manager tracks state, deltas are pure transforms

3. **Profile-Based Capability Detection**: `ModelProfile` declares what each provider supports
   - **Adopt**: Fail-fast validation before request
   - **Benefit**: Clear error messages, prevents invalid configurations
   - **Extension**: Could enable automatic fallback strategies

4. **Thin Adapter Layer**: Adapters only translate at boundary, no business logic
   - **Adopt**: Keep adapters focused on format translation
   - **Benefit**: Easy to add new providers, maintains clear separation

5. **Provider Details Preservation**: `provider_details` dict captures vendor-specific extras
   - **Adopt**: Don't lose information during normalization
   - **Benefit**: Debugging, provider-specific features accessible

6. **Streaming Validation**: Early termination when output matches schema
   - **Adopt**: Progressive validation during streaming
   - **Benefit**: Faster responses, reduced token usage

### Considerations

1. **Multi-Provider Testing Complexity**: 20+ providers means extensive compatibility testing
   - **Consider**: Start with 2-3 core providers (OpenAI, Anthropic, local)
   - **Trade-off**: Broad support vs. maintenance burden

2. **Provider-Specific Settings**: Each provider has unique parameters (`openai_*`, `anthropic_*`)
   - **Adopt**: Namespaced settings prevent collisions
   - **Implementation**: `ModelSettings` typed dict with optional provider-prefixed keys

3. **Tool Call ID Management**: Different providers handle differently
   - **Pattern**: Framework generates IDs if provider doesn't supply them
   - **Code**: `_generate_tool_call_id()` fallback
   - **Ensure**: Consistent matching between call and result

4. **Builtin Tool Abstraction**: Providers have incompatible builtin tools
   - **Pydantic-AI approach**: Abstract tool types, provider-specific translation
   - **Example**: `WebSearchTool` → OpenAI's `web_search` vs Anthropic's `BetaWebSearchTool`
   - **Complexity**: Each builtin tool needs adapter for each provider

5. **Thinking/Reasoning Blocks**: New primitive (Claude extended thinking, o1 reasoning)
   - **Adopt**: First-class `ThinkingPart` type
   - **Translation**: Map to vendor thinking blocks (Anthropic signature, OpenAI encrypted_content)
   - **Forward-compatible**: Design for models with multi-stage reasoning

## Anti-Patterns Observed

**None major** - well-designed protocol abstraction.

**Minor observations**:

1. **Stateful StreamedResponse**: `_parts_manager`, `_event_iterator` are mutable
   - **Risk**: If reused across requests (unlikely given contextmanager usage)
   - **Mitigation**: Created per-stream, not reused
   - **Not critical**: Well-contained within class

2. **ABC vs Protocol**: Uses `ABC` for `Model` when `Protocol` would work
   - **Observation**: Consistent with framework choice (see main report)
   - **Not protocol-specific issue**: Framework-wide pattern

3. **Provider Details as Dict**: Untyped `dict[str, Any]`
   - **Risk**: No validation of vendor-specific fields
   - **Trade-off**: Flexibility vs. type safety
   - **Acceptable**: Vendor fields too diverse to unify

## Notable Innovations

1. **Delta Application to Deltas**: `ToolCallPartDelta.apply()` can apply to another delta
   - **Enables**: Flexible delta accumulation without parts manager coupling
   - **Use case**: Provider emits multiple deltas before part starts

2. **Part End Events**: Framework wraps provider streams to emit `PartEndEvent`
   - **Benefit**: UI can render complete parts, know what's next
   - **Pattern**: `iterator_with_part_end()` in `StreamedResponse.__aiter__`

3. **Cache Control Markers**: `CachePoint` objects in message content
   - **Translation**: Anthropic `cache_control` blocks, ignored by providers without caching
   - **Flexible**: Users place markers, adapters translate per provider semantics

4. **History Processors**: User-defined message transformations before each request
   - **Applied**: Transparently in `_map_message`
   - **Use cases**: Truncation, summarization, PII filtering
   - **Clean extension point**: Decoupled from protocol

5. **Bidirectional Provider Details**: Preserved from response, can be sent back in subsequent requests
   - **Example**: Anthropic `container_id` for multi-turn sessions
   - **Pattern**: Check history for provider-specific state, reuse if present

## Streaming Protocol Deep Dive

**SSE vs WebSocket**: Uses SSE (AsyncStream from provider SDKs)

**Partial Tool Call Accumulation**:

**Anthropic example** (from streaming code):
```python
# Event 1: Block starts
BetaRawContentBlockStartEvent(index=0, content_block=BetaToolUseBlock(id="call_123", name="search", input={}))
→ PartStartEvent(index=0, part=ToolCallPart(tool_name="search", args={}, tool_call_id="call_123"))

# Event 2: First delta
BetaRawContentBlockDeltaEvent(index=0, delta=BetaInputJSONDelta(partial_json='{"query": "wea'))
→ PartDeltaEvent(index=0, delta=ToolCallPartDelta(args_delta='{"query": "wea'))

# Event 3: Second delta
BetaRawContentBlockDeltaEvent(index=0, delta=BetaInputJSONDelta(partial_json='ther"}'))
→ PartDeltaEvent(index=0, delta=ToolCallPartDelta(args_delta='ther"}'))

# Event 4: Block stops
BetaRawContentBlockStopEvent(index=0)
→ PartEndEvent(index=0, part=ToolCallPart(tool_name="search", args='{"query": "weather"}', tool_call_id="call_123"))
```

**Parts manager** (not shown in detail) concatenates `'{"query": "wea' + 'ther"}'` → `'{"query": "weather"}'`.

**Critical**: Deltas are strings for JSON, final parse happens when complete.

**OpenAI streaming** (inferred from imports):
- `ChatCompletionChunk` with `delta.tool_calls[].function.arguments`
- Similar accumulation pattern

**Multi-part responses**:

Index-based tracking:
```python
# Two parts in one response (text + tool call)
PartStartEvent(index=0, part=TextPart("Let me check..."))
PartDeltaEvent(index=0, delta=TextPartDelta(content_delta="..."))
PartEndEvent(index=0, part=TextPart("Let me check..."))
PartStartEvent(index=1, part=ToolCallPart(...))
PartEndEvent(index=1, part=ToolCallPart(...))
```

**FinalResultEvent injection**: Framework layer, not provider
- Checks each event against output schema
- Emits when match found
- Enables early termination

## Multi-Turn Conversation Reconstruction

**Problem**: Stateless model APIs need full history each turn.

**Solution**: Framework maintains `message_history: list[ModelMessage]`.

**Request assembly**:

1. Graph collects messages from previous turns
2. History processors transform (e.g., truncate)
3. Adapter translates all messages to provider format
4. Single request contains full context

**Tool result attribution**:

Ensured via `tool_call_id`:

```python
# Turn 1 response
ModelResponse(parts=[ToolCallPart(tool_name="search", tool_call_id="call_abc")])

# Turn 2 request includes
ModelRequest(parts=[
    ToolReturnPart(tool_name="search", tool_call_id="call_abc", content="Results...")
])
```

**Provider translation**:

**OpenAI**:
```json
{"role": "assistant", "tool_calls": [{"id": "call_abc", "function": {"name": "search", ...}}]}
{"role": "tool", "tool_call_id": "call_abc", "content": "Results..."}
```

**Anthropic**:
```python
BetaMessageParam(role='assistant', content=[BetaToolUseBlock(id="call_abc", name="search", ...)])
BetaMessageParam(role='user', content=[BetaToolResultBlockParam(tool_use_id="call_abc", content="Results...")])
```

**ID matching enforced** by provider APIs (error if mismatch).

## Provider-Specific Features

**OpenAI Unique**:
- `reasoning_effort` for o1 models
- `prediction` for predictive outputs
- `service_tier` selection
- `prompt_cache_key` for extended caching
- Computer use tool (Responses API)
- Image generation (DALL-E integration)

**Anthropic Unique**:
- Extended thinking (`BetaThinkingBlock` with signature)
- `container` for stateful multi-turn
- Prompt caching with TTL control
- Memory tool

**Google Unique**:
- Video input support (`VideoUrl`)
- Different thinking format (`thought_signature`)

**Handled via**:
1. Provider-specific settings (`OpenAIChatModelSettings`, `AnthropicModelSettings`)
2. Conditional translation in adapters
3. Provider details preserved in responses

## Testing Implications

**VCR cassettes**: Test fixtures record/replay HTTP interactions

**Test models**: `TestModel` for deterministic testing without API calls

**Multi-provider coverage**: Each adapter needs tests against real APIs (recorded)

**Streaming tests**: Must validate delta accumulation, partial tool calls

**From CLAUDE.md**:
- VCR cassettes in `tests/cassettes/`
- Example: `tests/models/test_anthropic.py` for Anthropic adapter

## Summary of Protocol Flow

**Request path**:
```
User code
  ↓ ModelMessage[]
Agent graph
  ↓ ModelMessage[] + ModelRequestParameters
Model.request()
  ↓ Adapter translation
Provider SDK
  ↓ HTTP (OpenAI Chat, Anthropic Messages, etc.)
LLM API
```

**Response path**:
```
LLM API
  ↓ HTTP response (JSON or SSE)
Provider SDK
  ↓ Provider-native types (BetaMessage, ChatCompletion, etc.)
Adapter parsing
  ↓ ModelResponse with normalized parts
Agent graph
  ↓ ModelResponse in history, tool execution
User code
```

**Key invariant**: Internal `ModelMessage` types never touch wire, adapters isolate protocol details.
