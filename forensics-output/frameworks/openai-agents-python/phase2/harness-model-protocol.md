# Harness-Model Protocol Analysis: OpenAI Agents Python

## Summary
- **Key Finding 1**: Native OpenAI Responses API with fallback Chat Completions adapter - framework is OpenAI-centric with bidirectional translation layers to support other providers via LiteLLM
- **Key Finding 2**: Dual-API architecture enables both server-managed conversations (Responses API) and client-managed (Chat Completions), with automatic protocol conversion between them
- **Key Finding 3**: Sophisticated streaming implementation with full support for partial tool call accumulation, reasoning tokens, and semantic event emission (not just raw chunks)
- **Classification**: OpenAI-native harness with multi-provider abstraction via protocol converters. First-class support for Responses API features (conversation_id, previous_response_id, server-side deduplication) with graceful degradation to Chat Completions.

## Detailed Analysis

### Message Protocol

**Wire Format Family**: OpenAI Responses API (primary) + Chat Completions (fallback)

**Providers Supported**:
- OpenAI (native): `src/agents/models/openai_responses.py`, `src/agents/models/openai_chatcompletions.py`
- LiteLLM (multi-provider): `src/agents/extensions/models/litellm_model.py`
- Custom providers via `ModelProvider` protocol: `src/agents/models/interface.py`

**Abstraction Strategy**: Unified internal message type (OpenAI Responses format) with bidirectional converters

The framework uses OpenAI's `ResponseInputItemParam` and `ResponseOutputItem` types as the **universal internal format**. All message exchanges happen in this format, regardless of the actual LLM provider.

**Internal Message Type** (`src/agents/items.py:65-72`):
```python
TResponseInputItem = ResponseInputItemParam
TResponseOutputItem = ResponseOutputItem
TResponseStreamEvent = ResponseStreamEvent
```

**Three-Layer Architecture**:

1. **Responses API (Native)** - Direct passthrough (`src/agents/models/openai_responses.py:242-344`)
```python
async def _fetch_response(
    self,
    system_instructions: str | None,
    input: str | list[TResponseInputItem],  # Already in Responses format
    ...
) -> Response | AsyncStream[ResponseStreamEvent]:
    list_input = ItemHelpers.input_to_new_input_list(input)

    response = await self._client.responses.create(
        previous_response_id=self._non_null_or_omit(previous_response_id),
        conversation=self._non_null_or_omit(conversation_id),
        instructions=self._non_null_or_omit(system_instructions),
        input=list_input,  # Direct passthrough - no conversion needed
        tools=tools_param,
        ...
    )
```

2. **Chat Completions (Adapter)** - Converts Responses format to Chat Completions (`src/agents/models/openai_chatcompletions.py:235-366`)
```python
async def _fetch_response(
    self,
    system_instructions: str | None,
    input: str | list[TResponseInputItem],  # Responses format
    ...
) -> ChatCompletion | tuple[Response, AsyncStream[ChatCompletionChunk]]:
    # Convert Responses items to Chat Completions messages
    converted_messages = Converter.items_to_messages(input)

    if system_instructions:
        converted_messages.insert(0, {
            "content": system_instructions,
            "role": "system",
        })

    ret = await self._get_client().chat.completions.create(
        model=self.model,
        messages=converted_messages,  # Converted format
        ...
    )

    # For streaming: wrap Chat Completions stream in fake Response object
    response = Response(
        id=FAKE_RESPONSES_ID,
        created_at=time.time(),
        model=self.model,
        object="response",
        output=[],  # Populated by stream handler
        ...
    )
    return response, ret
```

3. **LiteLLM (Multi-Provider)** - Uses Chat Completions converter + custom handling (`src/agents/extensions/models/litellm_model.py:65-250`)
```python
async def _fetch_response(
    self,
    system_instructions: str | None,
    input: str | list[TResponseInputItem],  # Responses format
    ...
):
    # Convert to Chat Completions format
    converted_messages = Converter.items_to_messages(
        input,
        preserve_thinking_blocks=True,  # Anthropic compatibility
        preserve_tool_output_all_content=True  # Image content support
    )

    # LiteLLM routing based on model prefix
    response = await litellm.acompletion(
        model=self.model,  # e.g., "anthropic/claude-3-5-sonnet-20241022"
        messages=converted_messages,
        ...
    )

    # Convert LiteLLM response back to Responses format
    items = Converter.message_to_output_items(
        LitellmConverter.convert_message_to_openai(message)
    )
```

**Key Converter: Responses ↔ Chat Completions** (`src/agents/models/chatcmpl_converter.py:338-632`)

The `Converter.items_to_messages()` method handles complex bidirectional translation:

```python
@classmethod
def items_to_messages(
    cls,
    items: str | Iterable[TResponseInputItem],
    preserve_thinking_blocks: bool = False,  # For Claude extended thinking
    preserve_tool_output_all_content: bool = False,  # For multimodal tools
) -> list[ChatCompletionMessageParam]:
    """
    Convert Responses API items to Chat Completions messages.

    Rules:
    - EasyInputMessage or InputMessage (role=user) => ChatCompletionUserMessageParam
    - EasyInputMessage or InputMessage (role=system) => ChatCompletionSystemMessageParam
    - response_output_message => ChatCompletionAssistantMessageParam
    - tool calls get attached to current assistant message
    - tool outputs => ChatCompletionToolMessageParam
    - reasoning items => extracted thinking blocks (Anthropic)
    """

    result: list[ChatCompletionMessageParam] = []
    current_assistant_msg: ChatCompletionAssistantMessageParam | None = None
    pending_thinking_blocks: list[dict[str, str]] | None = None

    for item in items:
        if easy_msg := cls.maybe_easy_input_message(item):
            # Simple message conversion
            ...
        elif func_call := cls.maybe_function_tool_call(item):
            # Attach tool call to current or new assistant message
            asst = ensure_assistant_message()
            tool_calls.append(ChatCompletionMessageFunctionToolCallParam(
                id=func_call["call_id"],
                type="function",
                function={"name": func_call["name"], "arguments": arguments},
            ))
        elif func_output := cls.maybe_function_tool_call_output(item):
            # Convert to tool result message
            msg: ChatCompletionToolMessageParam = {
                "role": "tool",
                "tool_call_id": func_output["call_id"],
                "content": tool_result_content,
            }
        elif reasoning_item := cls.maybe_reasoning_message(item):
            # Extract thinking blocks for Anthropic extended thinking
            if preserve_thinking_blocks:
                pending_thinking_blocks = reconstructed_thinking_blocks
```

**Reverse Converter: Chat Completions → Responses** (`src/agents/models/chatcmpl_converter.py:96-170`)

```python
@classmethod
def message_to_output_items(cls, message: ChatCompletionMessage) -> list[TResponseOutputItem]:
    items: list[TResponseOutputItem] = []

    # Handle reasoning content (for o1-style models)
    if hasattr(message, "reasoning_content") and message.reasoning_content:
        reasoning_item = ResponseReasoningItem(
            id=FAKE_RESPONSES_ID,
            summary=[Summary(text=message.reasoning_content, type="summary_text")],
            type="reasoning",
        )
        items.append(reasoning_item)

    # Handle regular message content
    message_item = ResponseOutputMessage(
        id=FAKE_RESPONSES_ID,
        content=[ResponseOutputText(text=message.content, type="output_text", ...)],
        role="assistant",
        type="message",
        status="completed",
    )
    items.append(message_item)

    # Handle tool calls
    if message.tool_calls:
        for tool_call in message.tool_calls:
            items.append(ResponseFunctionToolCall(
                id=FAKE_RESPONSES_ID,
                call_id=tool_call.id,
                arguments=tool_call.function.arguments,
                name=tool_call.function.name,
                type="function_call",
            ))
```

**Design Implication**: This architecture allows:
- OpenAI Responses API users get native features (server-side conversation tracking, response chaining)
- Chat Completions API users get compatibility layer with minimal overhead
- Third-party providers (Anthropic, Gemini) work via LiteLLM with extended feature support (thinking blocks, multimodal tool outputs)

### Tool Call Encoding

**Request Method**: OpenAI Function Calling API (native) + hosted tools (Responses-specific)

**Schema Transmission**: Dual-path based on model type

**1. Responses API Path** (`src/agents/models/openai_responses.py:435-542`)

```python
@classmethod
def convert_tools(
    cls,
    tools: list[Tool],
    handoffs: list[Handoff[Any, Any]],
) -> ConvertedTools:
    converted_tools: list[ToolParam] = []

    for tool in tools:
        if isinstance(tool, FunctionTool):
            # User-defined functions
            converted_tool: ToolParam = {
                "name": tool.name,
                "parameters": tool.params_json_schema,  # From function signature
                "strict": tool.strict_json_schema,  # OpenAI strict mode
                "type": "function",
                "description": tool.description,
            }
        elif isinstance(tool, WebSearchTool):
            # Hosted tool (Responses API only)
            converted_tool = {
                "type": "web_search",
                "filters": tool.filters.model_dump(),
                "user_location": tool.user_location,
                "search_context_size": tool.search_context_size,
            }
        elif isinstance(tool, FileSearchTool):
            # Hosted tool (Responses API only)
            converted_tool = {
                "type": "file_search",
                "vector_store_ids": tool.vector_store_ids,
                "max_num_results": tool.max_num_results,
            }
        elif isinstance(tool, ComputerTool):
            # Hosted computer use (Responses API only)
            converted_tool = {
                "type": "computer_use_preview",
                "environment": computer.environment,
                "display_width": computer.dimensions[0],
                "display_height": computer.dimensions[1],
            }

    # Handoffs become function tools
    for handoff in handoffs:
        converted_tools.append({
            "name": handoff.tool_name,
            "parameters": handoff.input_json_schema,
            "strict": handoff.strict_json_schema,
            "type": "function",
            "description": handoff.tool_description,
        })
```

**2. Chat Completions Path** (`src/agents/models/chatcmpl_converter.py:603-631`)

```python
@classmethod
def tool_to_openai(cls, tool: Tool) -> ChatCompletionToolParam:
    if isinstance(tool, FunctionTool):
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.params_json_schema,
                "strict": tool.strict_json_schema,
            },
        }

    # Hosted tools NOT supported
    raise UserError(
        f"Hosted tools are not supported with the ChatCompletions API. "
        f"Got tool type: {type(tool)}"
    )
```

**Schema Generation** (`src/agents/function_schema.py` - not shown but referenced):
- Introspects function signature via `inspect.signature()`
- Extracts type hints and converts to JSON Schema
- Parses docstrings (Google/NumPy style) for parameter descriptions
- Automatically enables `strict: true` mode when compatible with OpenAI strict schemas

**Response Parsing**: Dual-path parsing based on wire format

**Responses API** - Already structured (`src/agents/models/openai_responses.py:152-156`)
```python
return ModelResponse(
    output=response.output,  # List[ResponseOutputItem] - already typed
    usage=usage,
    response_id=response.id,
)
```

**Chat Completions** - Converter extracts tool calls (`src/agents/models/chatcmpl_converter.py:155-169`)
```python
if message.tool_calls:
    for tool_call in message.tool_calls:
        if tool_call.type == "function":
            items.append(
                ResponseFunctionToolCall(
                    id=FAKE_RESPONSES_ID,
                    call_id=tool_call.id,  # Maps to Responses call_id
                    arguments=tool_call.function.arguments,  # JSON string
                    name=tool_call.function.name,
                    type="function_call",
                )
            )
```

**Tool Choice Support**:

| Tool Choice | Responses API | Chat Completions | Notes |
|-------------|---------------|------------------|-------|
| `auto` | ✅ | ✅ | Default behavior |
| `required` | ✅ | ✅ | Force tool use |
| `none` | ✅ | ✅ | Text-only response |
| `"function_name"` | ✅ | ✅ | Force specific tool |
| `"file_search"` | ✅ | ❌ | Responses-only hosted tool |
| `"web_search"` | ✅ | ❌ | Responses-only hosted tool |
| `"computer_use_preview"` | ✅ | ❌ | Responses-only hosted tool |
| `MCPToolChoice` | ✅ | ❌ | Model Context Protocol tool selection |

**Tool Execution Flow** (`src/agents/_run_impl.py:277-300`):
1. Model returns tool calls in response output
2. Framework parses and matches to registered tools
3. Parallel execution via `asyncio.gather()` for all tool calls
4. Results converted to `FunctionCallOutput` format
5. Added to conversation history for next turn

**Tool Output Encoding** (`src/agents/items.py:428-522`):

Supports structured multimodal outputs:
```python
@classmethod
def tool_call_output_item(
    cls, tool_call: ResponseFunctionToolCall, output: Any
) -> FunctionCallOutput:
    """Accepts plain values (stringified) or structured outputs:
    - ToolOutputText → {"type": "input_text", "text": "..."}
    - ToolOutputImage → {"type": "input_image", "image_url": "...", "file_id": "..."}
    - ToolOutputFileContent → {"type": "input_file", "file_data": "...", "filename": "..."}
    """
    converted_output = cls._convert_tool_output(output)

    return {
        "call_id": tool_call.call_id,
        "output": converted_output,  # str | list[ResponseFunctionCallOutputItemParam]
        "type": "function_call_output",
    }
```

### Streaming Implementation

**Protocol**: Server-Sent Events (SSE) via OpenAI SDK's `AsyncStream`

**Partial Tool Call Handling**: ✅ Fully supported with accumulator pattern

**Stream Handler Architecture** (`src/agents/models/chatcmpl_stream_handler.py:81-639`):

The `ChatCmplStreamHandler.handle_stream()` method is a sophisticated state machine that:
1. Accumulates partial chunks into complete items
2. Emits semantic events (not just raw chunks)
3. Handles parallel tool calls with real-time argument streaming
4. Reconstructs Responses API events from Chat Completions chunks

**State Management**:
```python
@dataclass
class StreamingState:
    started: bool = False
    text_content_index_and_output: tuple[int, ResponseOutputText] | None = None
    refusal_content_index_and_output: tuple[int, ResponseOutputRefusal] | None = None
    reasoning_content_index_and_output: tuple[int, ResponseReasoningItem] | None = None
    function_calls: dict[int, ResponseFunctionToolCall] = field(default_factory=dict)

    # Real-time function call streaming
    function_call_streaming: dict[int, bool] = field(default_factory=dict)
    function_call_output_idx: dict[int, int] = field(default_factory=dict)

    # Anthropic extended thinking support
    thinking_text: str = ""
    thinking_signature: str | None = None
```

**Chunk Processing Loop** (`src/agents/models/chatcmpl_stream_handler.py:91-436`):
```python
async for chunk in stream:
    if not state.started:
        state.started = True
        yield ResponseCreatedEvent(response=response, type="response.created", ...)

    delta = chunk.choices[0].delta

    # Handle thinking blocks (Anthropic extended thinking)
    if hasattr(delta, "thinking_blocks") and delta.thinking_blocks:
        for block in delta.thinking_blocks:
            state.thinking_text += block.get("thinking", "")
            if signature := block.get("signature"):
                state.thinking_signature = signature

    # Handle reasoning content (OpenAI o1-style)
    if hasattr(delta, "reasoning_content"):
        if not state.reasoning_content_index_and_output:
            # Emit reasoning item added event
            yield ResponseOutputItemAddedEvent(...)

        yield ResponseReasoningSummaryTextDeltaEvent(
            delta=reasoning_content,
            item_id=FAKE_RESPONSES_ID,
            ...
        )
        state.reasoning_content_index_and_output[1].summary[0].text += reasoning_content

    # Handle regular text content
    if delta.content is not None:
        if not state.text_content_index_and_output:
            # First content chunk - emit item added event
            yield ResponseOutputItemAddedEvent(item=assistant_item, ...)
            yield ResponseContentPartAddedEvent(part=output_text, ...)

        # Emit text delta
        yield ResponseTextDeltaEvent(
            delta=delta.content,
            item_id=FAKE_RESPONSES_ID,
            logprobs=delta_logprobs,
            ...
        )

        # Accumulate text
        state.text_content_index_and_output[1].text += delta.content

    # Handle tool calls with REAL-TIME streaming
    if delta.tool_calls:
        for tc_delta in delta.tool_calls:
            if tc_delta.index not in state.function_calls:
                # New tool call - initialize accumulator
                state.function_calls[tc_delta.index] = ResponseFunctionToolCall(
                    id=FAKE_RESPONSES_ID,
                    arguments="",  # Accumulated incrementally
                    name="",
                    type="function_call",
                    call_id="",
                )

            # Accumulate arguments as they arrive
            state.function_calls[tc_delta.index].arguments += (
                tc_delta.function.arguments or ""
            )

            # Set function name when available
            if tc_delta.function and tc_delta.function.name:
                state.function_calls[tc_delta.index].name = tc_delta.function.name

            # Start streaming as soon as name and call_id are available
            if (
                not state.function_call_streaming[tc_delta.index]
                and function_call.name
                and function_call.call_id
            ):
                state.function_call_streaming[tc_delta.index] = True

                # Emit function call added event
                yield ResponseOutputItemAddedEvent(
                    item=ResponseFunctionToolCall(
                        call_id=function_call.call_id,
                        arguments="",  # Empty at start
                        name=function_call.name,
                        type="function_call",
                    ),
                    ...
                )

            # Stream arguments as they arrive
            if state.function_call_streaming.get(tc_delta.index):
                yield ResponseFunctionCallArgumentsDeltaEvent(
                    delta=tc_delta.function.arguments,
                    item_id=FAKE_RESPONSES_ID,
                    ...
                )
```

**End-of-Stream Finalization**:
```python
# Send completion events for all accumulated items
if state.reasoning_content_index_and_output:
    yield ResponseReasoningSummaryPartDoneEvent(...)
    yield ResponseOutputItemDoneEvent(item=reasoning_item, ...)

if state.text_content_index_and_output:
    yield ResponseContentPartDoneEvent(part=text_part, ...)
    yield ResponseOutputItemDoneEvent(item=assistant_msg, ...)

for index, function_call in state.function_calls.items():
    yield ResponseOutputItemDoneEvent(
        item=ResponseFunctionToolCall(
            call_id=function_call.call_id,
            arguments=function_call.arguments,  # Fully accumulated
            name=function_call.name,
            type="function_call",
        ),
        ...
    )

# Final response with usage
final_response = response.model_copy()
final_response.output = outputs  # All accumulated items
final_response.usage = ResponseUsage(...)

yield ResponseCompletedEvent(response=final_response, ...)
```

**Event Types Emitted**:

| Event Type | Description | When Emitted |
|------------|-------------|--------------|
| `response.created` | Stream started | First chunk received |
| `response.output_item.added` | New output item starting | Message/tool call/reasoning begins |
| `response.content_part.added` | New content part starting | Text/refusal content begins |
| `response.output_text.delta` | Text chunk | Each text delta |
| `response.refusal.delta` | Refusal chunk | Each refusal delta |
| `response.reasoning_summary_text.delta` | Reasoning chunk (o1-style) | Each reasoning delta |
| `response.reasoning_text.delta` | Thinking chunk (Anthropic) | Each thinking delta |
| `response.function_call_arguments.delta` | Tool call arguments chunk | Each argument delta |
| `response.content_part.done` | Content part completed | Text/refusal finalized |
| `response.output_item.done` | Output item completed | Message/tool call finalized |
| `response.completed` | Stream finished | Final chunk + usage |

**Streaming Consumer API** (`src/agents/run.py` - referenced):
```python
async def stream_response(
    agent: Agent,
    input: str,
    ...
) -> AsyncIterator[StreamEvent]:
    """
    Stream events are emitted as they occur:
    - Raw model events (e.g., response.output_text.delta)
    - Semantic framework events (e.g., tool_called, tool_result, handoff)
    """
    async for event in runner.stream_response(...):
        if event.type == "response.output_text.delta":
            print(event.delta, end="", flush=True)
        elif event.type == "response.function_call_arguments.delta":
            # Can process partial JSON arguments in real-time
            ...
```

**Partial Tool Call Example**:

Given streaming chunks:
```
Chunk 1: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_abc", "function": {"name": "get_weather"}}]}}]}
Chunk 2: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"ci'}}]}}]}
Chunk 3: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'ty": '}}]}}]}
Chunk 4: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"Tokyo"}'}}]}}]}
```

Handler emits:
```
Event 1: ResponseOutputItemAddedEvent(item=ResponseFunctionToolCall(name="get_weather", call_id="call_abc", arguments=""))
Event 2: ResponseFunctionCallArgumentsDeltaEvent(delta='{"ci')
Event 3: ResponseFunctionCallArgumentsDeltaEvent(delta='ty": ')
Event 4: ResponseFunctionCallArgumentsDeltaEvent(delta='"Tokyo"}')
Event 5: ResponseOutputItemDoneEvent(item=ResponseFunctionToolCall(arguments='{"city": "Tokyo"}'))
```

**Key Insight**: The framework doesn't wait for complete tool calls before emitting events. Consumers can:
- Display tool names immediately (for UX feedback)
- Incrementally parse JSON arguments (for progress indicators)
- Cancel long-running tool invocations early

### Agentic Primitives

#### System Prompt Assembly

**Composition Mechanism**: `instructions` field on `Agent` dataclass

**Static Instructions** (`src/agents/agent.py` - schema):
```python
@dataclass
class Agent(Generic[TContext]):
    instructions: str | Callable[[RunContext, Agent], MaybeAwaitable[str]]
```

**Dynamic Instructions** (evaluated at runtime):
```python
async def dynamic_instructions(context: RunContext, agent: Agent) -> str:
    return f"You are {agent.name}. Current time: {context.current_time}."

agent = Agent(
    name="Assistant",
    instructions=dynamic_instructions,  # Function, not string
)
```

**Injection Point** - Different per model type:

**Responses API** (`src/agents/models/openai_responses.py:318-321`):
```python
response = await self._client.responses.create(
    instructions=self._non_null_or_omit(system_instructions),  # Dedicated parameter
    input=list_input,  # User messages
    ...
)
```

**Chat Completions** (`src/agents/models/openai_chatcompletions.py:248-257`):
```python
converted_messages = Converter.items_to_messages(input)

if system_instructions:
    converted_messages.insert(
        0,
        {
            "content": system_instructions,
            "role": "system",  # Prepended as first message
        },
    )
```

**No Hardcoded System Prompts**: Framework does NOT inject hidden system messages. The `instructions` field is the ONLY system prompt, fully controlled by the user.

**Handoff Context Injection** (`src/agents/handoffs/history.py` - referenced):
When agents hand off to each other, the new agent can receive filtered/transformed conversation history. This is configured via `handoff_input_filter`:

```python
def filter_history(items: list[TResponseInputItem]) -> list[TResponseInputItem]:
    # Only keep last 5 messages
    return items[-5:]

handoff = Handoff(
    target_agent=specialist_agent,
    input_filter=filter_history,
)
```

#### Scratchpad / Working Memory

**Not Implemented** - No explicit scratchpad mechanism. Reasoning happens via:

1. **Reasoning Items** (OpenAI o1-style):
```python
@dataclass
class ReasoningItem(RunItemBase[ResponseReasoningItem]):
    raw_item: ResponseReasoningItem  # Contains summary or full reasoning trace
    type: Literal["reasoning_item"] = "reasoning_item"
```

2. **Extended Thinking** (Anthropic Claude):
Thinking blocks are preserved in `ResponseReasoningItem.content` and `encrypted_content` (for signatures):

```python
# Stream handler extracts thinking
if hasattr(delta, "thinking_blocks") and delta.thinking_blocks:
    for block in delta.thinking_blocks:
        state.thinking_text += block.get("thinking", "")
        if signature := block.get("signature"):
            state.thinking_signature = signature

# Stored in reasoning item
reasoning_item.content = [Content(text=state.thinking_text, type="reasoning_text")]
reasoning_item.encrypted_content = state.thinking_signature
```

These are **model-native** reasoning mechanisms, not framework-injected prompts.

#### Interrupt / Human-in-the-Loop

**Implemented via Guardrails + Tool Callbacks**

**1. Guardrails** (`src/agents/guardrail.py` - referenced):

Input guardrails can halt execution before agent processes input:
```python
class InputGuardrail(Protocol):
    async def guard(self, data: InputGuardrailData) -> InputGuardrailResult:
        """Return ALLOW or BLOCK with optional message."""
```

Output guardrails can halt before returning final output:
```python
class OutputGuardrail(Protocol):
    async def guard(self, data: OutputGuardrailData) -> OutputGuardrailResult:
        """Return ALLOW or BLOCK with optional message."""
```

**Tripwire Pattern**:
```python
# Exceptions raised when guardrails block
class InputGuardrailTripwireTriggered(AgentsException): ...
class OutputGuardrailTripwireTriggered(AgentsException): ...
```

**2. MCP Approval Requests** (Model Context Protocol):

MCP tools can request human approval before execution:
```python
@dataclass
class ToolRunMCPApprovalRequest:
    request_item: McpApprovalRequest  # From model
    mcp_tool: HostedMCPTool
```

**Approval Callback**:
```python
async def approval_callback(request: MCPToolApprovalRequest) -> bool:
    print(f"Approve tool call to {request.tool_name}? (y/n)")
    return input().lower() == 'y'

mcp_tool = HostedMCPTool(
    server_label="github",
    approval_callback=approval_callback,
)
```

**3. Tool Guardrails**:

Per-tool input/output guardrails:
```python
@function_tool(
    tool_input_guardrails=[validate_input],
    tool_output_guardrails=[validate_output],
)
def sensitive_tool(data: str) -> str:
    """Tool with per-invocation guardrails."""
    ...
```

**No Built-In Confirmation UI**: Framework provides hooks, but no default UI for human approval. Applications must implement their own.

#### Conversation State Machine

**States**: Implicit state machine based on response content

**State Transitions** (`src/agents/_run_impl.py` - referenced flow):

```
┌─────────────────────────────────────────────────────────────┐
│  START: Runner.run(agent, input)                            │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  State: INPUT_GUARDRAILS                                     │
│  - Execute input guardrails (parallel or sequential)         │
│  - If BLOCK → raise InputGuardrailTripwireTriggered         │
└────────────────────┬────────────────────────────────────────┘
                     │ ALLOW
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  State: LLM_CALL                                             │
│  - Invoke model.get_response() or stream_response()          │
│  - Receive ModelResponse with output items                   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  State: PROCESS_RESPONSE                                     │
│  - Parse output items (message, tool calls, reasoning)       │
│  - Check output schema if final_output detected             │
└────────────────────┬────────────────────────────────────────┘
                     │
         ┌───────────┴───────────┬──────────────┬──────────────┐
         │                       │              │              │
         ▼                       ▼              ▼              ▼
   ┌──────────┐         ┌──────────────┐  ┌─────────┐  ┌──────────┐
   │ MESSAGE  │         │  TOOL CALLS  │  │ HANDOFF │  │ REFUSAL  │
   │   ONLY   │         │              │  │         │  │          │
   └────┬─────┘         └──────┬───────┘  └────┬────┘  └────┬─────┘
        │                      │               │            │
        ▼                      ▼               ▼            ▼
┌─────────────────┐  ┌──────────────────┐  ┌────────────────────┐
│ OUTPUT_SCHEMA   │  │ EXECUTE_TOOLS    │  │ SWITCH_AGENT       │
│ - Extract final │  │ - Run tools      │  │ - Apply input      │
│   output        │  │ - Guardrails     │  │   filter           │
│ - Guardrails    │  │ - Add results    │  │ - Nest history     │
└────┬────────────┘  └────┬─────────────┘  └────┬───────────────┘
     │                    │                     │
     │ FINAL              │ CONTINUE            │ CONTINUE
     ▼                    ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│  State: OUTPUT_GUARDRAILS (if final output)                 │
│  - Execute output guardrails                                 │
│  - If BLOCK → raise OutputGuardrailTripwireTriggered        │
└────────────────────┬────────────────────────────────────────┘
                     │ ALLOW or CONTINUE
         ┌───────────┴───────────┐
         │                       │
         ▼                       ▼
   ┌──────────┐          ┌──────────────┐
   │  RETURN  │          │ NEXT_TURN    │
   │  RESULT  │          │ (goto        │
   │          │          │  LLM_CALL)   │
   └──────────┘          └──────────────┘
```

**Turn Limit**: Enforced via `max_turns` (default: 10)

**Early Exit Conditions**:
1. **Final Output Detected**: Output schema matched or `tool_use_behavior` returns `is_final_output=True`
2. **Handoff**: Agent switches to new agent
3. **Guardrail Block**: Input/output guardrail triggers tripwire
4. **Max Turns**: Turn counter exceeds limit

**State Persistence**: Not handled by framework core. Applications must use `Session` interface for conversation history:

```python
from agents.memory import SQLiteSession

session = SQLiteSession("conversation.db", session_id="user123")
result = await Runner.run(agent, input, session=session)
```

**Server-Side State** (Responses API only):

```python
# First turn
result1 = await Runner.run(agent, "Hello", run_config=RunConfig(
    conversation_id="conv_abc123",
))

# Subsequent turns - framework auto-chains responses
result2 = await Runner.run(agent, "Follow-up", run_config=RunConfig(
    previous_response_id=result1.response_id,  # Deduplicates history
))
```

The `_ServerConversationTracker` (`src/agents/run.py:130-176` - referenced) tracks which items have been sent to the server to avoid re-transmission.

### Provider Abstraction

**Architecture**: Prefix-based routing via `MultiProvider`

**Provider Registration** (`src/agents/models/multi_provider.py:54-145`):

```python
class MultiProvider(ModelProvider):
    """Routes to models based on prefix:
    - "openai/gpt-4o" → OpenAIProvider
    - "litellm/anthropic/claude-3-5-sonnet" → LitellmProvider
    - No prefix → OpenAIProvider (default)
    """

    def __init__(
        self,
        provider_map: MultiProviderMap | None = None,
        openai_api_key: str | None = None,
        openai_base_url: str | None = None,
        ...
    ):
        self.provider_map = provider_map
        self.openai_provider = OpenAIProvider(...)
        self._fallback_providers: dict[str, ModelProvider] = {}

    def get_model(self, model_name: str | None) -> Model:
        prefix, model_name = self._get_prefix_and_model_name(model_name)

        if prefix and self.provider_map:
            return self.provider_map.get_provider(prefix).get_model(model_name)
        else:
            return self._get_fallback_provider(prefix).get_model(model_name)

    def _create_fallback_provider(self, prefix: str) -> ModelProvider:
        if prefix == "litellm":
            from ..extensions.models.litellm_provider import LitellmProvider
            return LitellmProvider()
        else:
            raise UserError(f"Unknown prefix: {prefix}")
```

**Usage**:
```python
# Default OpenAI
result = await Runner.run(agent, "Hello", run_config=RunConfig(
    model="gpt-4o",
))

# Explicit prefix
result = await Runner.run(agent, "Hello", run_config=RunConfig(
    model="litellm/anthropic/claude-3-5-sonnet-20241022",
))
```

**Provider Feature Matrix**:

| Feature | OpenAI Responses | OpenAI Chat Completions | LiteLLM (Multi-Provider) | Custom Provider |
|---------|------------------|------------------------|--------------------------|-----------------|
| **Core Protocol** | ||||
| Function calling | ✅ Native | ✅ Via converter | ✅ Via converter | ⚠️ Implement converter |
| Streaming | ✅ Native SSE | ✅ Via stream handler | ✅ Via stream handler | ⚠️ Implement handler |
| Parallel tool calls | ✅ | ✅ | ✅ | ⚠️ Depends on model |
| Tool choice | ✅ All modes | ✅ auto/required/none/name | ✅ auto/required/none/name | ⚠️ Depends on model |
| **Responses API Features** | ||||
| Server-side conversation tracking | ✅ `conversation_id` | ❌ | ❌ | ❌ |
| Response chaining | ✅ `previous_response_id` | ❌ | ❌ | ❌ |
| Hosted tools (file_search, web_search) | ✅ | ❌ | ❌ | ❌ |
| Computer use | ✅ | ❌ | ❌ | ❌ |
| MCP hosted tools | ✅ | ❌ | ❌ | ❌ |
| Prompt objects | ✅ External config | ❌ | ❌ | ❌ |
| **Advanced Features** | ||||
| Reasoning tokens (o1-style) | ✅ Native | ✅ Native | ✅ Via LiteLLM | ⚠️ Custom handling |
| Extended thinking (Anthropic) | ❌ | ❌ | ✅ Via thinking_blocks | ⚠️ Custom handling |
| Multimodal tool outputs | ✅ | ❌ (text only) | ✅ Via preserve_tool_output_all_content | ⚠️ Custom handling |
| Structured outputs (JSON schema) | ✅ | ✅ | ✅ | ⚠️ Depends on model |
| Logprobs | ✅ | ✅ | ✅ | ⚠️ Depends on model |
| **Observability** | ||||
| Tracing integration | ✅ | ✅ | ✅ | ✅ Via Model interface |
| Usage tracking | ✅ | ✅ | ✅ | ✅ Via Model interface |

**Custom Provider Implementation**:

```python
from agents.models.interface import Model, ModelProvider

class MyCustomModel(Model):
    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],  # Responses format!
        model_settings: ModelSettings,
        tools: list[Tool],
        ...
    ) -> ModelResponse:
        # Convert Responses format → your provider's format
        native_messages = self._convert_to_native(input, system_instructions)

        # Call your provider
        response = await my_provider.complete(
            messages=native_messages,
            tools=self._convert_tools(tools),
            ...
        )

        # Convert back to Responses format
        output_items = self._convert_to_responses_format(response)

        return ModelResponse(
            output=output_items,  # List[ResponseOutputItem]
            usage=Usage(...),
            response_id=None,
        )

    def stream_response(self, ...) -> AsyncIterator[TResponseStreamEvent]:
        # Emit ResponseStreamEvent types
        yield ResponseCreatedEvent(...)
        yield ResponseOutputItemAddedEvent(...)
        yield ResponseTextDeltaEvent(...)
        ...

class MyCustomProvider(ModelProvider):
    def get_model(self, model_name: str | None) -> Model:
        return MyCustomModel(model_name)
```

**Graceful Degradation Strategy**:

1. **OpenAI Responses → Chat Completions**: Framework automatically falls back when:
   - User specifies `use_responses=False` in `OpenAIProvider`
   - Model doesn't support Responses API (auto-detected)

2. **Hosted Tools**: Error raised at model call time
```python
# Chat Completions path
def tool_to_openai(cls, tool: Tool):
    if isinstance(tool, FunctionTool):
        return {...}  # OK

    raise UserError(
        "Hosted tools are not supported with the ChatCompletions API. "
        f"Got tool type: {type(tool)}"
    )
```

3. **Features Not Supported**: Framework checks at runtime
```python
# MCP tool choice
if isinstance(tool_choice, MCPToolChoice):
    raise UserError("MCPToolChoice is not supported for Chat Completions models")
```

**Key Insight**: The framework is **OpenAI-first** but extensible. Non-OpenAI providers work by:
- Accepting Responses API format as input (universal internal type)
- Translating to their native format
- Translating responses back to Responses API format
- LiteLLM extension demonstrates this pattern for 100+ providers

## Code References

### Core Protocol Files
- `src/agents/models/interface.py:36-126` - `Model` and `ModelProvider` protocols
- `src/agents/items.py:1-523` - Universal message types (`TResponseInputItem`, `TResponseOutputItem`)
- `src/agents/models/openai_responses.py:62-543` - Native Responses API implementation
- `src/agents/models/openai_chatcompletions.py:43-378` - Chat Completions adapter

### Message Converters
- `src/agents/models/chatcmpl_converter.py:57-632` - Bidirectional Responses ↔ Chat Completions converter
- `src/agents/models/chatcmpl_converter.py:338-601` - `items_to_messages()` - Complex multi-turn conversation reconstruction
- `src/agents/models/chatcmpl_converter.py:96-170` - `message_to_output_items()` - Chat Completions → Responses

### Streaming
- `src/agents/models/chatcmpl_stream_handler.py:56-639` - Full streaming state machine
- `src/agents/models/chatcmpl_stream_handler.py:353-436` - Real-time tool call argument streaming
- `src/agents/models/openai_responses.py:158-211` - Native Responses streaming (passthrough)

### Tool Handling
- `src/agents/models/openai_responses.py:435-542` - Responses API tool conversion (hosted + function)
- `src/agents/models/chatcmpl_converter.py:603-631` - Chat Completions tool conversion (function only)
- `src/agents/items.py:428-522` - Tool output encoding (multimodal support)
- `src/agents/function_schema.py` - JSON schema generation from function signatures

### Multi-Provider
- `src/agents/models/multi_provider.py:10-145` - Prefix-based provider routing
- `src/agents/extensions/models/litellm_model.py:65-250` - LiteLLM adapter implementation
- `src/agents/extensions/models/litellm_provider.py:9-24` - LiteLLM provider registration

### Agentic Primitives
- `src/agents/prompts.py:50-77` - System prompt assembly (`PromptUtil.to_model_input()`)
- `src/agents/guardrail.py` - Input/output guardrail protocols
- `src/agents/tool_guardrails.py` - Per-tool guardrails
- `src/agents/_run_impl.py:275-300` - Tool execution flow

## Implications for New Framework

### Positive Patterns

1. **Universal Internal Message Format**
   - Using OpenAI Responses API types as the internal lingua franca is brilliant
   - Enables clean separation: framework logic operates on typed structures, converters handle wire protocol
   - **Adopt**: Define a single canonical message format, even if it's based on one provider's schema

2. **Bidirectional Converters**
   - Separating conversion logic (`chatcmpl_converter.py`) from model clients enables testing and reuse
   - `items_to_messages()` and `message_to_output_items()` are inverse operations
   - **Adopt**: Make converters pure functions with clear input/output contracts

3. **Streaming State Machine**
   - The `ChatCmplStreamHandler` is exceptionally well-designed for handling incremental chunks
   - Real-time tool call argument streaming is a UX win
   - **Adopt**: Don't emit raw chunks; emit semantic events consumers actually care about

4. **Event Sequence Numbers**
   - Every stream event has a `sequence_number` for ordering/deduplication
   - Enables replay and event sourcing
   - **Adopt**: Make streaming events replayable and ordered

5. **Fake IDs for Chat Completions**
   - Using `FAKE_RESPONSES_ID` constant when converting Chat Completions → Responses format
   - Avoids generating random IDs that break determinism
   - **Adopt**: Use stable sentinel values for synthetic data

6. **Graceful Feature Detection**
   - Framework checks `hasattr(delta, "reasoning_content")` instead of crashing on unknown fields
   - Supports OpenAI o1 reasoning, Anthropic thinking blocks, LiteLLM extensions
   - **Adopt**: Design for forward compatibility with unknown model features

7. **Prefix-Based Provider Routing**
   - `"litellm/anthropic/claude-3-5-sonnet"` is intuitive and composable
   - Avoids global configuration
   - **Adopt**: Encode provider selection in model identifiers, not separate config

8. **Tool Output Multimodality**
   - `ToolOutputImage`, `ToolOutputFileContent` structures enable rich tool responses
   - Most frameworks only support text
   - **Adopt**: Design tool output schema for structured/multimodal data from day 1

### Considerations

1. **OpenAI Lock-In**
   - Framework's internal types ARE OpenAI's types (not abstractions)
   - Tight coupling to `openai` Python SDK
   - **Consideration**: For Elixir framework, define protocol-agnostic types even if based on OpenAI schema

2. **Converter Complexity**
   - `items_to_messages()` is 262 lines with complex state management
   - Handles 8 different item types, thinking blocks, tool call accumulation
   - **Consideration**: Budget significant engineering effort for converters; they're harder than they look

3. **Hosted Tools Fallback**
   - No graceful degradation when using file_search with Chat Completions API
   - Raises `UserError` at call time, not configuration time
   - **Consideration**: Validate feature compatibility early, not during execution

4. **Responses API Assumptions**
   - Many features (conversation_id, prompt objects) only work with OpenAI
   - No abstraction for "server-managed state" vs "client-managed state"
   - **Consideration**: Design abstractions that work across stateful and stateless APIs

5. **LiteLLM Dependency**
   - Multi-provider support requires LiteLLM (optional dependency)
   - Adds maintenance burden and version compatibility issues
   - **Consideration**: For Elixir, implement converters directly for key providers (Anthropic, Gemini)

6. **Streaming Event Explosion**
   - 12+ different event types in streaming API
   - Consumers must handle all of them or ignore most
   - **Consideration**: Provide high-level event types (e.g., "content_delta") alongside low-level ones

7. **No Built-In Retry Logic**
   - Framework doesn't retry failed LLM calls
   - Applications must implement exponential backoff
   - **Consideration**: Add retry decorator for model calls with configurable policy

8. **Session Interface is Custom**
   - Not compatible with LangChain's `BaseChatMessageHistory`
   - Ecosystem fragmentation
   - **Consideration**: Align with community standards where possible

## Anti-Patterns Observed

### 1. Type Confusion: Dict vs Pydantic Model

**Problem**: Internal message types are TypedDicts in the OpenAI SDK, but framework sometimes treats them as Pydantic models

**Example** (`src/agents/items.py:134-143`):
```python
def to_input_item(self) -> TResponseInputItem:
    if isinstance(self.raw_item, dict):
        return self.raw_item  # type: ignore
    elif isinstance(self.raw_item, BaseModel):
        return self.raw_item.model_dump(exclude_unset=True)  # type: ignore
```

**Why It's Bad**: Runtime type checks in hot path; violates static typing guarantees

**Better Approach**: Pick one type system (Pydantic or TypedDict) and stick to it

---

### 2. Sentinel Object for Missing Values

**Problem**: Uses `_MISSING_ATTR_SENTINEL = object()` to distinguish missing dict keys from `None` values

**Example** (`src/agents/items.py:76-132`):
```python
_MISSING_ATTR_SENTINEL = object()

def __getattribute__(self, name: str) -> Any:
    value = data.get(attr_name, _MISSING_ATTR_SENTINEL)
    if value is _MISSING_ATTR_SENTINEL:
        return object.__getattribute__(self, attr_name)
```

**Why It's Bad**: Magic value pattern; hard to debug; breaks type safety

**Better Approach**: Use `Optional[T]` explicitly or dataclass fields with `field(default=None)`

---

### 3. Weak References for Agent Cleanup

**Problem**: `RunItem` stores weak references to agents to prevent memory leaks

**Example** (`src/agents/items.py:91-132`):
```python
_agent_ref: weakref.ReferenceType[Agent[Any]] | None = field(init=False, repr=False)

def release_agent(self) -> None:
    """Release the strong reference to the agent while keeping a weak reference."""
    self._agent_ref = weakref.ref(agent)
    self.__dict__["agent"] = None
```

**Why It's Bad**:
- Complex manual memory management in Python
- Weak references can cause unpredictable behavior if agent GC'd mid-run
- Leaks abstraction (callers must know to call `release_agent()`)

**Better Approach**: Store agent ID instead of agent object; look up in registry when needed

---

### 4. Fake IDs Throughout

**Problem**: Uses `FAKE_RESPONSES_ID` constant when converting Chat Completions to Responses format

**Example** (`src/agents/models/fake_id.py` - referenced):
```python
FAKE_RESPONSES_ID = "fake-responses-id"
```

**Why It's Bad**:
- Violates OpenAI API contract (IDs should be unique)
- Breaks event correlation if multiple items have same ID
- Confuses consumers who expect unique IDs

**Better Approach**: Generate deterministic IDs (e.g., hash of content + timestamp + sequence)

---

### 5. Dynamic Attribute Access for Provider Detection

**Problem**: Uses `hasattr()` to detect provider-specific features at runtime

**Example** (`src/agents/models/chatcmpl_stream_handler.py:111-122`):
```python
if hasattr(delta, "thinking_blocks") and delta.thinking_blocks:
    # Anthropic-specific handling
    ...

if hasattr(delta, "reasoning_content"):
    # OpenAI o1-specific handling
    ...
```

**Why It's Bad**:
- No static type checking
- Fragile to provider schema changes
- Hidden dependencies on provider implementation details

**Better Approach**: Define provider-specific message subclasses; use polymorphism

---

### 6. Tool Call Streaming Fallback

**Problem**: Two code paths for tool call streaming - real-time and batch

**Example** (`src/agents/models/chatcmpl_stream_handler.py:499-563`):
```python
for index, function_call in state.function_calls.items():
    if state.function_call_streaming.get(index, False):
        # Streamed path - already emitted events
        yield ResponseOutputItemDoneEvent(...)
    else:
        # Fallback path - emit all events at once
        yield ResponseOutputItemAddedEvent(...)
        yield ResponseFunctionCallArgumentsDeltaEvent(...)
        yield ResponseOutputItemDoneEvent(...)
```

**Why It's Bad**:
- Complexity: maintains two parallel paths for same functionality
- Consumers see different event patterns depending on provider behavior
- Fallback path emits "delta" event with full arguments (not a delta)

**Better Approach**: Always use accumulator pattern; emit synthetic deltas if provider doesn't stream

---

### 7. Mutable State in Stream Handler

**Problem**: `StreamingState` dataclass is mutated throughout stream processing

**Example** (`src/agents/models/chatcmpl_stream_handler.py:56-69`):
```python
@dataclass
class StreamingState:
    function_calls: dict[int, ResponseFunctionToolCall] = field(default_factory=dict)
    function_call_streaming: dict[int, bool] = field(default_factory=dict)
    thinking_text: str = ""  # Mutated in loop
```

**Why It's Bad**:
- Hard to test (stateful objects)
- Difficult to parallelize
- No clear state machine (transitions not explicit)

**Better Approach**: Immutable state; return new state from each transition

---

### 8. Error Messages Without Context

**Problem**: User errors don't include the problematic value

**Example** (`src/agents/models/chatcmpl_converter.py:284-286`):
```python
if "image_url" not in casted_image_param or not casted_image_param["image_url"]:
    raise UserError(
        f"Only image URLs are supported for input_image {casted_image_param}"
    )
```

**Why It's Bad**: Error message dumps entire object; doesn't explain what's wrong

**Better Approach**:
```python
raise UserError(
    f"input_image missing required 'image_url' field. "
    f"Got keys: {list(casted_image_param.keys())}"
)
```

---

### 9. Silent Feature Degradation

**Problem**: Framework silently downgrades features when switching providers

**Example**: Using web_search tool with Chat Completions raises error at **runtime**:
```python
def tool_to_openai(cls, tool: Tool):
    raise UserError(
        f"Hosted tools are not supported with the ChatCompletions API. Got tool type: {type(tool)}"
    )
```

**Why It's Bad**:
- Fails late (after agent starts running)
- No validation at agent construction time
- User discovers incompatibility mid-conversation

**Better Approach**: Validate tool/model compatibility when agent is created:
```python
@dataclass
class Agent:
    def __post_init__(self):
        if self.model_uses_chat_completions() and self.has_hosted_tools():
            raise ValueError("Hosted tools require Responses API. Use gpt-4o or enable use_responses=True")
```

---

### 10. Global Header Overrides

**Problem**: Uses `ContextVar` for header overrides

**Example** (`src/agents/models/openai_responses.py:57-59`):
```python
_HEADERS_OVERRIDE: ContextVar[dict[str, str] | None] = ContextVar(
    "openai_responses_headers_override", default=None
)
```

**Why It's Bad**:
- Thread-local state; breaks in async environments
- Hidden global configuration
- Difficult to test (need context manager setup)

**Better Approach**: Pass headers explicitly through model configuration:
```python
model_settings = ModelSettings(
    extra_headers={"X-Custom-Header": "value"}
)
```

