# Harness-Model Protocol Analysis: Google ADK

## Summary
- **Key Finding 1**: Native Gemini types with thin adapters - framework uses `google.genai.types` directly, translating only for non-Gemini providers
- **Key Finding 2**: Sophisticated streaming with partial tool call accumulation - handles streaming function arguments via JSONPath-based partial args
- **Key Finding 3**: Dual execution modes - standard SSE streaming + bidirectional WebSocket (Live API) for voice/realtime use cases
- **Classification**: Gemini-native with adapter pattern for multi-provider support (Anthropic, LiteLLM gateway)

## Detailed Analysis

### Message Protocol

**Wire Format Family**: Gemini-native (`google.genai.types`)

The framework uses Gemini's message protocol as its internal representation, translating only when interfacing with other providers.

**Core Types** (`google.genai.types`):
```python
# Internal message representation
types.Content(
    role="user" | "model" | "assistant",
    parts=[
        types.Part.from_text(text="..."),
        types.Part.from_function_call(name="...", args={...}),
        types.Part.from_function_response(id="...", response={...}),
        types.Part(inline_data=types.Blob(mime_type="...", data=bytes)),
        types.Part(file_data=types.FileData(file_uri="...")),
        types.Part(text="...", thought=True),  # Reasoning traces
    ]
)
```

**Providers Supported**:

| Provider | Adapter Location | Translation Strategy |
|----------|-----------------|----------------------|
| Gemini (native) | `models/google_llm.py` | Direct pass-through, no translation |
| Anthropic | `models/anthropic_llm.py` | Thin adapter: `google.genai.types` ↔ `anthropic.types` |
| LiteLLM | `models/lite_llm.py` | Gateway adapter: translates to OpenAI-compatible format |
| Gemma (local) | `models/gemma_llm.py` | Uses google-genai SDK |

**Abstraction Strategy**: Thin adapters with Gemini-native core

The framework does NOT create a universal internal message type. Instead:
1. All internal APIs use `google.genai.types` directly
2. Provider adapters translate at the boundary (in `generate_content_async`)
3. This creates vendor lock-in but simplifies the core implementation

**Code Example** (Anthropic adapter):
```python
# anthropic_llm.py:154-171
def content_to_message_param(content: types.Content) -> anthropic_types.MessageParam:
    message_block = []
    for part in content.parts or []:
        if _is_image_part(part):
            continue  # Claude doesn't support images in assistant turns
        message_block.append(part_to_message_block(part))

    return {
        "role": to_claude_role(content.role),
        "content": message_block,
    }

def part_to_message_block(part: types.Part) -> Union[...]:
    if part.text:
        return anthropic_types.TextBlockParam(text=part.text, type="text")
    elif part.function_call:
        return anthropic_types.ToolUseBlockParam(
            id=part.function_call.id or "",
            name=part.function_call.name,
            input=part.function_call.args,
            type="tool_use",
        )
    # ... more translations
```

**LiteLLM Complexity** (`lite_llm.py`):
- 1714 lines of translation logic
- Handles 40+ provider quirks (Ollama needs string content, OpenAI needs file_id not inline data)
- Supports file uploads with MIME type inference
- Parses inline JSON tool calls from text responses (for providers without structured tool calls)

### Tool Call Encoding

**Request Method**: Native function calling API (Gemini), translated for other providers

**Schema Transmission** (Gemini):
```python
# llm_request.py:244-274
def append_tools(self, tools: list[BaseTool]) -> None:
    declarations = []
    for tool in tools:
        declaration = tool._get_declaration()  # Returns types.FunctionDeclaration
        declarations.append(declaration)
        self.tools_dict[tool.name] = tool

    # Gemini format: Tool with function_declarations
    self.config.tools.append(
        types.Tool(function_declarations=declarations)
    )
```

**FunctionDeclaration Structure**:
```python
types.FunctionDeclaration(
    name="get_weather",
    description="Get weather for a location",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "location": types.Schema(type=types.Type.STRING, description="City name"),
            "units": types.Schema(type=types.Type.STRING, enum=["C", "F"]),
        },
        required=["location"]
    )
)
```

**Response Parsing**:
- **Gemini**: Native `types.Part.function_call` objects with structured `args` dict
- **Anthropic**: `anthropic_types.ToolUseBlock` → `types.Part.from_function_call`
- **LiteLLM**: Fallback JSON parser for providers that return tool calls in text:

```python
# lite_llm.py:775-814
def _parse_tool_calls_from_text(text_block: str):
    """Extracts inline JSON tool calls from LiteLLM text responses."""
    tool_calls = []
    cursor = 0
    while cursor < len(text_block):
        brace_index = text_block.find("{", cursor)
        if brace_index == -1:
            break
        try:
            candidate, end = _JSON_DECODER.raw_decode(text_block, brace_index)
        except json.JSONDecodeError:
            cursor = brace_index + 1
            continue

        tool_call = _build_tool_call_from_json_dict(candidate, index=len(tool_calls))
        if tool_call:
            tool_calls.append(tool_call)
        cursor = end

    return tool_calls, remainder
```

**Tool Choice Support**:

| Feature | Gemini | Anthropic | LiteLLM |
|---------|--------|-----------|---------|
| Auto (default) | ✅ | ✅ | ✅ |
| Required | ✅ | ✅ | ✅ |
| None (disable) | ✅ | ✅ | ✅ |
| Specific tool | ✅ | ❌ | Varies by provider |
| Parallel calls | ✅ | ✅ | ✅ |
| Tool call ID | ✅ | ✅ | ✅ (generated if missing) |

**Parallel Tool Calls**:
- Supported in message format (multiple `function_call` parts in single response)
- BUT framework executes sequentially (no `asyncio.gather`) - anti-pattern noted in main report

### Streaming Implementation

**Protocol**: SSE for unidirectional, WebSocket for bidirectional (Live API)

**Two Streaming Modes**:

1. **SSE Streaming** (`generate_content_stream`):
   - Server-Sent Events
   - Unidirectional: model → client
   - Used for standard chat interactions
   - Implements `StreamingResponseAggregator` for partial accumulation

2. **Live API** (`connect` → `BaseLlmConnection`):
   - WebSocket bidirectional
   - Used for voice interactions, real-time interruptions
   - Supports audio caching, transparent session resumption
   - `GeminiLlmConnection` implements send/receive interface

**Partial Tool Call Handling**: Advanced JSONPath-based accumulation

```python
# streaming_utils.py:178-211
def _process_streaming_function_call(self, fc: types.FunctionCall):
    """Process a streaming function call with partialArgs."""
    if fc.name:
        self._current_fc_name = fc.name
    if fc.id:
        self._current_fc_id = fc.id

    # Process each partial argument
    for partial_arg in getattr(fc, 'partial_args', []):
        json_path = partial_arg.json_path  # e.g., "$.location.latitude"
        value, has_value = self._get_value_from_partial_arg(partial_arg, json_path)

        if has_value:
            self._set_value_by_json_path(json_path, value)  # Build nested dict

    # Check if function call is complete
    fc_will_continue = getattr(fc, 'will_continue', False)
    if not fc_will_continue:
        # Flush accumulated args to parts sequence
        self._flush_function_call_to_sequence()
```

This allows streaming tool arguments as they're generated:
```
Chunk 1: name="get_weather", partial_args=[{json_path: "$.location", string_value: "San"}]
Chunk 2: partial_args=[{json_path: "$.location", string_value: " Francisco"}]
Chunk 3: partial_args=[{json_path: "$.units", string_value: "C"}], will_continue=False
→ Final: FunctionCall(name="get_weather", args={"location": "San Francisco", "units": "C"})
```

**Event Types Emitted**:

| Event Type | Partial? | Content | When |
|------------|----------|---------|------|
| `LlmResponse(partial=True)` | Yes | Text chunks | During streaming |
| `LlmResponse(partial=True)` | Yes | Thought chunks | Reasoning streaming |
| `LlmResponse(partial=True)` | Yes | Function call partial | Tool call streaming |
| `LlmResponse(partial=True)` | Yes | Audio/image chunks | Multimodal streaming |
| `LlmResponse(partial=False)` | No | Aggregated content | Final turn complete |

**Progressive SSE Streaming Feature** (feature flag):
```python
# streaming_utils.py:258-289
if is_feature_enabled(FeatureName.PROGRESSIVE_SSE_STREAMING):
    # Accumulate parts while preserving order
    for part in llm_response.content.parts:
        if part.text:
            if self._current_text_buffer and part.thought != self._current_text_is_thought:
                self._flush_text_buffer_to_sequence()  # Type changed
            self._current_text_buffer += part.text
        elif part.function_call:
            self._process_function_call_part(part)  # Handle streaming args
        else:
            self._flush_text_buffer_to_sequence()
            self._parts_sequence.append(part)  # Preserve order

    llm_response.partial = True
    yield llm_response
```

**Streaming Flow**:
```
1. Call api_client.aio.models.generate_content_stream(...)
2. AsyncGenerator yields types.GenerateContentResponse chunks
3. StreamingResponseAggregator.process_response():
   - Yields partial LlmResponse for each chunk
   - Accumulates text/tool calls internally
4. aggregator.close():
   - Returns final LlmResponse(partial=False) with all accumulated content
```

### Agentic Primitives

**System Prompt Assembly** (`flows/llm_flows/instructions.py`):

```python
# instructions.py:59-106
async def run_async(invocation_context, llm_request):
    # 1. Global instructions (deprecated, use plugin instead)
    if root_agent.global_instruction:
        si = await inject_session_state(root_agent.global_instruction, ctx)
        llm_request.append_instructions([si])

    # 2. Static instruction (multimodal content)
    if agent.static_instruction:
        static_content = _transformers.t_content(agent.static_instruction)
        llm_request.append_instructions(static_content)

    # 3. Dynamic instruction
    if agent.instruction and not agent.static_instruction:
        si = await inject_session_state(agent.instruction, ctx)
        llm_request.append_instructions([si])  # Add to system_instruction
    elif agent.instruction and agent.static_instruction:
        si = await inject_session_state(agent.instruction, ctx)
        # Add as user message (since system_instruction already has static)
        llm_request.contents.append(
            types.Content(role='user', parts=[types.Part(text=si)])
        )
```

**System Instruction Construction**:
```python
# llm_request.py:102-242
def append_instructions(self, instructions: Union[list[str], types.Content]):
    if isinstance(instructions, types.Content):
        # Extract text parts, convert non-text parts to user content with references
        for part in instructions.parts:
            if part.text:
                text_parts.append(part.text)
            elif part.inline_data:
                reference_id = f"inline_data_{non_text_count}"
                text_parts.append(f"[Reference to inline binary data: {reference_id}]")
                user_contents.append(
                    types.Content(role="user", parts=[
                        types.Part.from_text(f"Referenced inline data: {reference_id}"),
                        types.Part(inline_data=part.inline_data)
                    ])
                )

        # Concatenate to system_instruction
        new_text = "\n\n".join(text_parts)
        if not self.config.system_instruction:
            self.config.system_instruction = new_text
        else:
            self.config.system_instruction += "\n\n" + new_text

        # Append referenced content to contents
        self.contents.extend(user_contents)
```

**Scratchpad / Working Memory**:
- **Session State**: Full conversation history stored in `Session.events`
- **Agent State**: Per-agent key-value store in `Session.agent_states[agent_name]`
- **Thought Streaming**: `types.Part(text="...", thought=True)` for reasoning traces
- **Context Caching**: Static instructions/tools cached with TTL (Gemini context cache)

**Interrupt / Human-in-the-Loop**:

1. **Tool Confirmation** (`tools/tool_confirmation.py`):
```python
async def run_async(self, args, tool_context):
    # Request confirmation from user
    return ToolConfirmation(
        message="Are you sure you want to delete the file?",
        args=args
    )
# Framework generates adk_request_confirmation function call
# User approves/denies → tool execution resumes/cancels
```

2. **Live Request Interruption** (bidirectional streaming):
```python
# base_llm_flow.py:239-267
async def _send_to_model(llm_connection, invocation_context):
    while True:
        live_request = await live_request_queue.get()
        if live_request.activity_start:
            await llm_connection.send_realtime(types.ActivityStart())
        elif live_request.blob:
            await llm_connection.send_realtime(live_request.blob)  # User speaking
        # Model can be interrupted mid-generation
```

**Conversation State Machine**:
```
Preprocessors → LLM Call → Response Processing → Postprocessors
     ↓              ↓                ↓                  ↓
Instructions   Streaming      Function Calls    Agent Transfer
Tools          Accumulation   Sequential Exec   State Update
Caching        Partial Events Tool Results      Session Save
```

**Processor Pipeline** (`flows/llm_flows/_base_llm_processor.py`):
```python
# Request processors (run before LLM call)
- InstructionsProcessor: Assemble system prompt
- FunctionProcessor: Add tool declarations
- ContentsProcessor: Build conversation history from session
- ContextCacheProcessor: Manage Gemini context cache
- OutputSchemaProcessor: Set structured output schema

# Response processors (run after LLM call)
- Custom processors via agent callbacks
```

### Provider Abstraction

**Provider Feature Matrix**:

| Feature | Gemini | Anthropic | LiteLLM | Notes |
|---------|--------|-----------|---------|-------|
| Function Calling | ✅ Native | ✅ Via adapter | ✅ Via gateway | Anthropic uses tool_use blocks |
| Streaming | ✅ SSE + WS | ✅ SSE only | ✅ SSE | LiteLLM streaming incomplete for some providers |
| Parallel Tool Calls | ✅ | ✅ | ✅ | Framework executes sequentially anyway |
| Tool Call IDs | ✅ | ✅ | ✅ Generated | LiteLLM generates UUIDs if missing |
| Multimodal Input | ✅ Full | ⚠️ User only | ✅ Varies | Claude rejects images in assistant turns |
| Multimodal Output | ✅ Images/audio | ❌ | ❌ | Gemini 2.5 Flash Image only |
| Thought Streaming | ✅ Native | ❌ | ⚠️ Via reasoning | o1/o3 reasoning mapped to thoughts |
| Context Caching | ✅ Native | ❌ | ⚠️ OpenAI only | Vertex AI context cache |
| Structured Output | ✅ response_schema | ❌ | ⚠️ Provider-specific | LiteLLM translates to json_schema |
| Code Execution | ✅ Native | ❌ | ❌ | Gemini code execution sandbox |
| Grounding/Search | ✅ Native | ❌ | ❌ | Google Search integration |
| Live/Realtime API | ✅ Native | ❌ | ❌ | Bidirectional WebSocket |

**Graceful Degradation Examples**:

1. **Anthropic - No images in assistant turns**:
```python
# anthropic_llm.py:154-164
def content_to_message_param(content: types.Content):
    for part in content.parts or []:
        if content.role != "user" and _is_image_part(part):
            logger.warning("Image data not supported in Claude for assistant turns.")
            continue  # Skip image part
```

2. **LiteLLM - Ollama content flattening**:
```python
# lite_llm.py:641-679
def _flatten_ollama_content(content):
    """Ollama's chat endpoint rejects arrays for content."""
    if isinstance(content, str):
        return content

    text_parts = []
    for block in content:
        if block.get("type") == "text":
            text_parts.append(block["text"])

    return "\n".join(text_parts)  # Flatten to string
```

3. **Gemini API vs Vertex AI**:
```python
# google_llm.py:422-440
async def _preprocess_request(self, llm_request):
    if self._api_backend == GoogleLLMVariant.GEMINI_API:
        # API Key auth doesn't support labels or display_name
        llm_request.config.labels = None
        for content in llm_request.contents:
            for part in content.parts:
                if part.inline_data:
                    part.inline_data.display_name = None  # Remove display_name
```

**Provider Selection**:
```python
# Registry pattern in base classes
class BaseLlm(BaseModel):
    @classmethod
    def supported_models(cls) -> list[str]:
        return []  # Regex patterns

# Gemini
Gemini.supported_models() → [r'gemini-.*', r'model-optimizer-.*', ...]

# Anthropic
AnthropicLlm.supported_models() → [r"claude-3-.*", r"claude-.*-4.*"]

# LiteLLM
LiteLlm.supported_models() → [r"openai/.*", r"groq/.*", r"anthropic/.*"]
```

**Multi-LLM Support Strategy**:
- Uses Gemini types internally (tight coupling)
- Thin adapters for each provider translate at boundaries
- LiteLLM acts as universal gateway (40+ providers via single adapter)
- No unified abstraction layer - accepts vendor lock-in for simplicity

## Code References

**Core Protocol Files**:
- `models/llm_request.py:49-285` - Request wrapper with Gemini types
- `models/llm_response.py:28-201` - Response wrapper, converts GenerateContentResponse
- `models/base_llm.py:32-206` - LLM interface, AsyncGenerator[LlmResponse]

**Provider Implementations**:
- `models/google_llm.py:82-593` - Gemini integration (native, no translation)
- `models/anthropic_llm.py:50-349` - Anthropic adapter (types translation)
- `models/lite_llm.py:1-1714` - LiteLLM gateway (comprehensive provider support)

**Streaming Infrastructure**:
- `utils/streaming_utils.py:28-382` - StreamingResponseAggregator with JSONPath partial args
- `models/gemini_llm_connection.py` - Bidirectional WebSocket for Live API
- `flows/llm_flows/base_llm_flow.py:283-361` - receive_from_model event loop

**System Prompt Assembly**:
- `flows/llm_flows/instructions.py:34-113` - InstructionsProcessor
- `utils/instructions_utils.py` - State injection helpers
- `llm_request.py:102-242` - append_instructions with multimodal handling

**Tool Integration**:
- `llm_request.py:244-274` - append_tools to FunctionDeclaration
- `tools/base_tool.py:81-120` - _get_declaration() schema generation
- `tools/tool_confirmation.py` - HITL confirmation pattern

## Implications for New Framework

### Positive Patterns

1. **Streaming Accumulator Pattern**:
   - `StreamingResponseAggregator` cleanly separates partial/final responses
   - JSONPath-based partial args allow streaming complex nested arguments
   - Progressive SSE feature flag enables order-preserving accumulation
   - **Adopt**: Build similar aggregator with clear partial=True/False semantics

2. **Dual Execution Modes**:
   - SSE for standard chat, WebSocket for realtime voice
   - Same agent code works in both modes
   - LiveRequestQueue for interruptions during streaming
   - **Adopt**: Design for both unidirectional and bidirectional use cases from start

3. **Event-Driven Architecture**:
   - AsyncGenerator[Event, None] streaming abstraction
   - Clean separation: LlmResponse → Event → Session storage
   - Easy to add observers for telemetry/logging
   - **Adopt**: Use event stream as primary abstraction, not raw LLM responses

4. **Multimodal System Instructions**:
   - `append_instructions` handles both text and binary content
   - Non-text parts become user messages with references in system prompt
   - Elegant solution to system-instruction-only-text constraint
   - **Adopt**: Support rich instructions without API limitations

5. **Context Caching Integration**:
   - Automatic fingerprinting of static content (tools + instructions)
   - TTL-based cache management
   - Transparent to agent developers
   - **Adopt**: Build caching as first-class primitive

### Considerations

1. **Vendor Lock-In**:
   - Using `google.genai.types` throughout creates tight Gemini coupling
   - Changing primary provider would require massive refactor
   - **Decision**: Create provider-agnostic internal types OR accept lock-in for simplicity
   - **Recommendation**: Define minimal internal protocol, adapt all providers (including Gemini)

2. **Adapter Complexity**:
   - LiteLLM adapter is 1714 lines (40% of total model code)
   - Each provider has unique quirks requiring special handling
   - **Challenge**: Keep adapters maintainable as providers evolve
   - **Recommendation**: Isolate provider-specific code, comprehensive integration tests

3. **Streaming Partial Tool Calls**:
   - Advanced feature but requires complex accumulator logic
   - JSONPath parsing adds cognitive overhead
   - Many providers don't support streaming tool args
   - **Decision**: Implement basic streaming first, add partial args as enhancement
   - **Recommendation**: Feature flag partial tool call streaming

4. **No Parallel Tool Execution**:
   - Framework supports parallel tool calls in protocol but executes sequentially
   - Missed optimization opportunity
   - **Fix**: Use `asyncio.gather` for independent tool calls
   - **Recommendation**: Build parallel execution from start

5. **Error Handling in Adapters**:
   - Errors from providers wrapped but not categorized
   - No retry logic (must be added at higher level)
   - **Improvement**: Define error taxonomy (transient/permanent, retryable/fatal)
   - **Recommendation**: Adapter errors map to framework error types

6. **Tool Call ID Attribution**:
   - All providers support tool_call_id for response correlation
   - LiteLLM generates UUIDs if provider doesn't provide ID
   - **Good Practice**: Always generate IDs for traceability
   - **Recommendation**: Enforce ID generation at framework level

## Anti-Patterns Observed

1. **Tight Gemini Coupling**:
   - `arbitrary_types_allowed=True` everywhere to mix Pydantic with google.genai types
   - No abstraction layer between framework and provider types
   - **Lesson**: Define provider-agnostic internal message protocol

2. **Sequential Tool Execution**:
   - Supports parallel tool calls in protocol but doesn't execute in parallel
   - Performance bottleneck for independent operations
   - **Lesson**: If protocol supports it, implementation should too

3. **No Max Iterations**:
   - Control loop can run indefinitely
   - No token budget enforcement
   - **Lesson**: Always add safety limits

4. **Inconsistent Streaming**:
   - Feature flag for progressive vs non-progressive streaming
   - Two different accumulation strategies in same codebase
   - **Lesson**: Pick one streaming model and stick with it

5. **Provider-Specific Workarounds Scattered**:
   - Ollama flattening, OpenAI file_id, Azure MIME type handling
   - Not centralized in provider adapter
   - **Lesson**: Keep provider quirks isolated to adapter, not in shared code

6. **No Streaming Timeout**:
   - Streaming can hang indefinitely if provider stops sending events
   - No client-side timeout enforcement
   - **Lesson**: Add timeout to streaming async generators

7. **Complex Type Conversions**:
   - Multiple places convert between Gemini Schema, OpenAPI, JSON Schema
   - Error-prone enum conversions (TYPE.STRING → "string")
   - **Lesson**: Centralize schema conversion logic

## Recommendations for New Framework

1. **Provider Abstraction**:
   - Define minimal internal message protocol (don't use provider types directly)
   - Create provider interface with clear contracts
   - Build adapters for all providers (including "native" one)
   - Use feature detection, not provider detection

2. **Streaming Design**:
   - AsyncGenerator with clear partial/final semantics
   - Single accumulator pattern (not multiple modes)
   - Support streaming tool arguments via delta protocol
   - Timeout enforcement at generator level

3. **System Prompt Assembly**:
   - Support multimodal instructions (images, files in system prompt)
   - State injection via template variables
   - Clear precedence: global → static → dynamic
   - Plugin architecture for instruction processors

4. **Tool Call Protocol**:
   - Always generate/enforce tool_call_id
   - Support parallel execution (asyncio.gather)
   - Graceful degradation for providers without structured tool calls
   - Unified error handling for tool execution

5. **Error Taxonomy**:
   ```python
   class ProviderError:
       category: Literal["auth", "rate_limit", "model_error", "network", "timeout"]
       retryable: bool
       provider_code: str
       framework_message: str
   ```

6. **Feature Detection**:
   ```python
   class ProviderCapabilities:
       streaming: bool
       tool_calls: bool
       parallel_tools: bool
       streaming_tool_args: bool
       multimodal_input: list[str]  # ["image", "audio", "video"]
       multimodal_output: list[str]
       context_caching: bool
       structured_output: bool
   ```

7. **Avoid Tight Coupling**:
   - No `arbitrary_types_allowed=True` (use proper typing)
   - Provider types stay in adapter modules
   - Internal types are framework-owned
   - Clear boundaries between core and provider code
