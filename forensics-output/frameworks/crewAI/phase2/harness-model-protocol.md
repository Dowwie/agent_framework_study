# Harness-Model Protocol Analysis: CrewAI

## Summary
- **Key Finding 1**: Dual-layer architecture - LiteLLM fallback with native SDK priority for OpenAI, Anthropic, Azure, Gemini, Bedrock
- **Key Finding 2**: Factory pattern routing with intelligent provider detection from model strings (prefix-based or constants lookup)
- **Key Finding 3**: Event-driven streaming with queue-based chunk accumulation and partial tool call handling
- **Classification**: Hybrid Gateway + Native Adapter Pattern

## Detailed Analysis

### Message Protocol

**Wire Format Family**: Multi-protocol (OpenAI, Anthropic, Gemini, Bedrock native + LiteLLM universal fallback)

**Providers Supported**:
| Provider | Adapter Location | Strategy |
|----------|-----------------|----------|
| OpenAI | `llms/providers/openai/completion.py` | Native SDK (openai-python) |
| Anthropic | `llms/providers/anthropic/completion.py` | Native SDK (anthropic-python) |
| Azure | `llms/providers/azure/completion.py` | Native SDK (openai-python) |
| Gemini | `llms/providers/gemini/completion.py` | Native SDK (google-generativeai) |
| Bedrock | `llms/providers/bedrock/completion.py` | Native SDK (boto3) |
| Others | `llm.py` (LiteLLM fallback) | Universal gateway (litellm) |

**Abstraction Strategy**: **Factory with Graceful Degradation**

The `LLM.__new__()` factory method (llm.py:L345-419) routes to native providers when available:

```python
def __new__(cls, model: str, is_litellm: bool = False, **kwargs: Any) -> LLM:
    """Factory method that routes to native SDK or falls back to LiteLLM.

    Routing priority:
        1. If 'provider' kwarg is present, use that provider with constants
        2. If only 'model' kwarg, use constants to infer provider
        3. If "/" in model name:
           - Check if prefix is a native provider (openai/anthropic/azure/bedrock/gemini)
           - If yes, validate model against constants
           - If valid, route to native SDK; otherwise route to LiteLLM
    """
    explicit_provider = kwargs.get("provider")

    if explicit_provider:
        provider = explicit_provider
        use_native = True
    elif "/" in model:
        prefix, _, model_part = model.partition("/")
        provider_mapping = {
            "openai": "openai",
            "anthropic": "anthropic",
            "claude": "anthropic",
            # ...
        }
        canonical_provider = provider_mapping.get(prefix.lower())
        if canonical_provider and cls._validate_model_in_constants(model_part, canonical_provider):
            provider = canonical_provider
            use_native = True
        else:
            use_native = False
    else:
        provider = cls._infer_provider_from_model(model)
        use_native = True

    native_class = cls._get_native_provider(provider) if use_native else None
    if native_class and not is_litellm and provider in SUPPORTED_NATIVE_PROVIDERS:
        return native_class(model=model_string, provider=provider, **kwargs)

    # FALLBACK to LiteLLM
    return LiteLLM_instance
```

**Message Type System**:
- **Internal**: `LLMMessage` TypedDict (utilities/types.py:L8-17)
  ```python
  class LLMMessage(TypedDict):
      role: Literal["user", "assistant", "system"]
      content: str | list[dict[str, Any]]
  ```
- **Provider-specific**: Native SDKs use their own types (OpenAI's `ChatCompletionMessageParam`, Anthropic's `MessageParam`)
- **Conversion**: `_format_messages()` in BaseLLM converts strings to LLMMessage list, then providers convert to their native formats

**Provider-Specific Message Formatting**:

LiteLLM backend (`llm.py:L1876-1940`):
```python
def _format_messages_for_provider(self, messages: list[LLMMessage]) -> list[dict[str, str]]:
    # O1 models: system -> assistant
    if "o1" in self.model.lower():
        for msg in messages:
            if msg["role"] == "system":
                msg["role"] = "assistant"

    # Mistral: last message must be user/tool
    if "mistral" in self.model.lower():
        if messages and messages[-1]["role"] == "assistant":
            return [*messages, {"role": "user", "content": "Please continue."}]

    # Anthropic: first message must be user
    if self.is_anthropic:
        if not messages or messages[0]["role"] == "system":
            return [{"role": "user", "content": "."}, *messages]

    return messages
```

Anthropic native (`providers/anthropic/completion.py:L196-269`):
```python
def _format_messages_for_anthropic(self, messages):
    system_message = None
    formatted_messages = []

    for msg in messages:
        if msg["role"] == "system":
            # Extract system messages - Anthropic requires separate system param
            system_message = msg["content"]
        else:
            formatted_messages.append(msg)

    # Anthropic requires first message to be user
    if formatted_messages and formatted_messages[0]["role"] != "user":
        formatted_messages.insert(0, {"role": "user", "content": "..."})

    return formatted_messages, system_message
```

### Tool Call Encoding

**Request Method**: **Native Function Calling APIs** (OpenAI tools, Anthropic tool_use, Gemini function_declarations)

**Schema Transmission**:

OpenAI format (llms/providers/openai/completion.py:L290-340):
```python
def _prepare_completion_params(self, messages, tools):
    params = {
        "model": self.model,
        "messages": messages,
    }

    if tools and not self.is_o1_model:  # o1 doesn't support tools
        # Convert BaseTool to OpenAI tool schema
        openai_tools = []
        for tool in tools:
            tool_obj = tool.get("tool")
            schema = {
                "type": "function",
                "function": {
                    "name": tool_obj.name,
                    "description": tool_obj.description,
                    "parameters": tool_obj.args_schema.model_json_schema(),
                },
            }
            openai_tools.append(schema)
        params["tools"] = openai_tools

    return params
```

Anthropic format (llms/providers/anthropic/completion.py:L300-357):
```python
def _prepare_completion_params(self, formatted_messages, system_message, tools):
    params = {
        "model": self.model,
        "messages": formatted_messages,
        "max_tokens": self.max_tokens,
    }

    if system_message:
        params["system"] = system_message

    if tools:
        # Convert to Anthropic tool schema
        anthropic_tools = []
        for tool in tools:
            tool_obj = tool.get("tool")
            schema = {
                "name": tool_obj.name,
                "description": tool_obj.description,
                "input_schema": tool_obj.args_schema.model_json_schema(),
            }
            anthropic_tools.append(schema)
        params["tools"] = anthropic_tools

    return params
```

**Response Parsing**:

OpenAI (llms/providers/openai/completion.py:L400-450):
```python
def _handle_completion(self, params, available_functions, from_task, from_agent):
    response: ChatCompletion = self.client.chat.completions.create(**params)

    # Track usage
    if response.usage:
        self._track_token_usage_internal(response.usage.model_dump())

    message = response.choices[0].message

    # Check for tool calls
    if message.tool_calls and available_functions:
        tool_call = message.tool_calls[0]
        function_name = tool_call.function.name
        function_args = json.loads(tool_call.function.arguments)

        # Execute tool
        result = self._handle_tool_execution(
            function_name, function_args, available_functions, from_task, from_agent
        )
        if result is not None:
            return result

    # Return text response
    return self._apply_stop_words(message.content or "")
```

Anthropic (llms/providers/anthropic/completion.py:L420-480):
```python
def _handle_completion(self, params, available_functions, from_task, from_agent):
    response: Message = self.client.messages.create(**params)

    # Track usage
    if hasattr(response, "usage"):
        self._track_token_usage_internal({
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
        })

    # Process content blocks
    text_content = []
    for block in response.content:
        if isinstance(block, TextBlock):
            text_content.append(block.text)
        elif isinstance(block, ToolUseBlock):
            # Execute tool
            result = self._handle_tool_execution(
                block.name,
                block.input,
                available_functions,
                from_task,
                from_agent,
            )
            if result is not None:
                return result

    return self._apply_stop_words("".join(text_content))
```

**Tool Choice Support**:
| Provider | Auto | Required | Specific Tool | Parallel Calls |
|----------|------|----------|---------------|----------------|
| OpenAI | ✅ | ✅ (tool_choice="required") | ✅ (tool_choice={"type": "function", "function": {"name": "x"}}) | ✅ |
| Anthropic | ✅ | ✅ (tool_choice={"type": "any"}) | ✅ (tool_choice={"type": "tool", "name": "x"}) | ❌ (sequential) |
| Gemini | ✅ | ❌ | ❌ | ✅ |
| Bedrock | Provider-dependent | Provider-dependent | Provider-dependent | Provider-dependent |

### Streaming Implementation

**Protocol**: Native SDK streaming (OpenAI `Stream[ChatCompletionChunk]`, Anthropic `Stream[RawMessageStreamEvent]`)

**Partial Tool Call Handling**: ✅ **Supported with accumulator pattern**

LiteLLM streaming (llm.py:L708-1050):
```python
def _handle_streaming_response(self, params, callbacks, available_functions, from_task, from_agent):
    full_response = ""
    accumulated_tool_args: defaultdict[int, AccumulatedToolArgs] = defaultdict(AccumulatedToolArgs)

    params["stream"] = True
    params["stream_options"] = {"include_usage": True}

    for chunk in litellm.completion(**params):
        choices = chunk.choices
        if choices and len(choices) > 0:
            delta = choices[0].delta

            # Accumulate text content
            if delta.content:
                full_response += delta.content
                crewai_event_bus.emit(
                    self,
                    event=LLMStreamChunkEvent(
                        chunk=delta.content,
                        from_task=from_task,
                        from_agent=from_agent,
                        call_type=LLMCallType.LLM_CALL,
                    ),
                )

            # Accumulate tool calls
            if delta.tool_calls:
                for tool_call in delta.tool_calls:
                    current_tool = accumulated_tool_args[tool_call.index]

                    if tool_call.function.name:
                        current_tool.function.name = tool_call.function.name

                    if tool_call.function.arguments:
                        current_tool.function.arguments += tool_call.function.arguments

                    crewai_event_bus.emit(
                        self,
                        event=LLMStreamChunkEvent(
                            tool_call=tool_call.to_dict(),
                            chunk=tool_call.function.arguments,
                            from_task=from_task,
                            from_agent=from_agent,
                            call_type=LLMCallType.TOOL_CALL,
                        ),
                    )

                    # Try to execute if complete
                    if current_tool.function.name and current_tool.function.arguments:
                        try:
                            json.loads(current_tool.function.arguments)
                            # Tool args are complete, execute immediately
                            return self._handle_tool_call([current_tool], available_functions)
                        except json.JSONDecodeError:
                            continue  # Wait for more chunks

    return full_response
```

OpenAI native streaming (llms/providers/openai/completion.py:L500-600):
```python
def _handle_streaming_completion(self, params, available_functions, from_task, from_agent):
    stream: Stream[ChatCompletionChunk] = self.client.chat.completions.create(**params)

    full_content = ""
    accumulated_tool_calls = {}

    for chunk in stream:
        if not chunk.choices:
            continue

        delta: ChoiceDelta = chunk.choices[0].delta

        # Stream text content
        if delta.content:
            full_content += delta.content
            self._emit_stream_chunk_event(
                chunk=delta.content,
                from_task=from_task,
                from_agent=from_agent,
            )

        # Accumulate tool calls
        if delta.tool_calls:
            for tool_call_delta in delta.tool_calls:
                idx = tool_call_delta.index
                if idx not in accumulated_tool_calls:
                    accumulated_tool_calls[idx] = {
                        "name": "",
                        "arguments": "",
                    }

                if tool_call_delta.function.name:
                    accumulated_tool_calls[idx]["name"] = tool_call_delta.function.name

                if tool_call_delta.function.arguments:
                    accumulated_tool_calls[idx]["arguments"] += tool_call_delta.function.arguments

    # Execute accumulated tool calls
    if accumulated_tool_calls and available_functions:
        for idx, tool_data in accumulated_tool_calls.items():
            result = self._handle_tool_execution(
                tool_data["name"],
                json.loads(tool_data["arguments"]),
                available_functions,
                from_task,
                from_agent,
            )
            if result is not None:
                return result

    return full_content
```

**Event Types Emitted** (events/types/llm_events.py):
| Event | When | Payload |
|-------|------|---------|
| `LLMCallStartedEvent` | Before LLM call | messages, tools, model |
| `LLMCallCompletedEvent` | After successful response | response, call_type (LLM_CALL or TOOL_CALL) |
| `LLMCallFailedEvent` | On error | error message |
| `LLMStreamChunkEvent` | Each streaming chunk | chunk (text or tool args), call_type, tool_call (optional) |

**Queue-Based Streaming Distribution** (utilities/streaming.py:L96-297):
```python
def create_streaming_state(current_task_info, result_holder, use_async=False):
    sync_queue = queue.Queue()
    async_queue = asyncio.Queue() if use_async else None
    loop = asyncio.get_event_loop() if use_async else None

    def stream_handler(_, event):
        if not isinstance(event, LLMStreamChunkEvent):
            return

        chunk = _create_stream_chunk(event, current_task_info)

        if async_queue and loop:
            loop.call_soon_threadsafe(async_queue.put_nowait, chunk)
        else:
            sync_queue.put(chunk)

    crewai_event_bus.register_handler(LLMStreamChunkEvent, stream_handler)

    return StreamingState(
        current_task_info=current_task_info,
        result_holder=result_holder,
        sync_queue=sync_queue,
        async_queue=async_queue,
        loop=loop,
        handler=stream_handler,
    )
```

Consumers can iterate:
```python
# Sync
for chunk in create_chunk_generator(state, run_func, output_holder):
    print(chunk.content)

# Async
async for chunk in create_async_chunk_generator(state, run_coro, output_holder):
    print(chunk.content)
```

### Agentic Primitives

**1. System Prompt Assembly** (utilities/prompts.py - referenced):
- **Pattern**: Multi-part template composition
- **Structure**: Role + Goal + Backstory + Tools + Task + Context + Memory
- **Assembly Location**: `CrewAgentExecutor.__init__` receives pre-assembled `SystemPromptResult`
- **Injection**: System message in message list OR separate `system` parameter (Anthropic)

**2. Scratchpad / Working Memory**:
- **Location**: Message history accumulation in `CrewAgentExecutor.messages`
- **Pattern**: Append-only message list (system → user → assistant → tool → assistant...)
- **Management**: No automatic summarization (unbounded growth until context limit)
- **Eviction**: Reactive truncation via `handle_context_length()` when `LLMContextLengthExceededError` raised

**3. Interrupt / Human-in-the-Loop**:
- **Not observed at protocol layer** - may exist at Crew/Task orchestration level
- LLM clients do not implement confirmation or pause mechanisms
- Event bus could enable external intervention

**4. Conversation State Machine**:
- **Pattern**: ReAct loop (Thought → Action → Observation)
- **Implementation**: `CrewAgentExecutor._invoke_loop()` (crew_agent_executor.py)
  ```python
  while not isinstance(formatted_answer, AgentFinish):
      # 1. Get LLM response
      answer = get_llm_response(...)

      # 2. Parse to AgentAction or AgentFinish
      formatted_answer = process_llm_response(answer, ...)

      # 3. Execute tool if action
      if isinstance(formatted_answer, AgentAction):
          tool_result = execute_tool_and_check_finality(...)
          # 4. Append observation to messages
          self.messages.append(format_message_for_llm(tool_result))

      # 5. Check max iterations
      if has_reached_max_iterations(...):
          formatted_answer = handle_max_iterations_exceeded(...)
  ```

**5. Stop Words**:
- **Implementation**: `BaseLLM._apply_stop_words()` (llms/base_llm.py:L231-272)
- **Pattern**: Post-processing truncation (not sent to API for some providers)
  ```python
  def _apply_stop_words(self, content: str) -> str:
      if not self.stop or not content:
          return content

      earliest_stop_pos = len(content)
      for stop_word in self.stop:
          stop_pos = content.find(stop_word)
          if stop_pos != -1 and stop_pos < earliest_stop_pos:
              earliest_stop_pos = stop_pos

      if earliest_stop_pos < len(content):
          return content[:earliest_stop_pos].strip()

      return content
  ```
- **Provider Support**: Native SDKs may or may not support `stop` param (checked via `supports_stop_words()`)

### Provider Abstraction

**Multi-Provider Support Table**:

| Provider | Native SDK | Fallback | Streaming | Tools | Structured Output | Thinking/Reasoning |
|----------|-----------|----------|-----------|-------|-------------------|-------------------|
| OpenAI | ✅ `openai-python` | ✅ LiteLLM | ✅ SSE | ✅ Function calling | ✅ response_format | ✅ reasoning_effort (o1) |
| Anthropic | ✅ `anthropic-python` | ✅ LiteLLM | ✅ SSE | ✅ Tool use | ⚠️ Via prompt engineering | ✅ Thinking blocks (extended) |
| Azure | ✅ `openai-python` (Azure endpoints) | ✅ LiteLLM | ✅ SSE | ✅ Function calling | ✅ response_format | ✅ (if model supports) |
| Gemini | ✅ `google-generativeai` | ✅ LiteLLM | ✅ | ✅ Function declarations | ⚠️ Limited | ❌ |
| Bedrock | ✅ `boto3` | ✅ LiteLLM | Provider-dependent | Provider-dependent | Provider-dependent | Provider-dependent |
| Others | ❌ | ✅ LiteLLM | Provider-dependent | Provider-dependent | Provider-dependent | ❌ |

**Graceful Degradation Pattern**:

1. **Model Name Parsing**: Extract provider from prefix (`openai/gpt-4` → OpenAI)
2. **Constants Validation**: Check if model exists in `OPENAI_MODELS`, `ANTHROPIC_MODELS`, etc. (llms/constants.py)
3. **Pattern Matching**: If not in constants, use pattern matching (`gpt-*` → OpenAI, `claude-*` → Anthropic)
4. **Native SDK Attempt**: Try to instantiate native provider
5. **LiteLLM Fallback**: If native fails or unavailable, use LiteLLM universal gateway

**Abstraction Boundary**:
- **Unified Interface**: `BaseLLM.call(messages, tools, callbacks, available_functions, from_task, from_agent, response_model)`
- **Provider-Specific**: Each native adapter handles:
  - Message formatting (system separation for Anthropic, role conversion for O1)
  - Tool schema conversion (OpenAI tools vs Anthropic tool_use vs Gemini function_declarations)
  - Response parsing (different content block types)
  - Streaming chunk formats
- **Escape Hatch**: `is_litellm` flag bypasses native routing

**Context Window Handling**:
- **Size Lookup**: `LLM_CONTEXT_WINDOW_SIZES` dict (llm.py:L180-305) with 100+ models
- **Default**: 8192 tokens
- **Usage Ratio**: 85% of max to avoid overflow (llm.py:L308)
- **Exception**: `LLMContextLengthExceededError` raised on overflow, caught by `CrewAgentExecutor`

## Code References

**Core LLM Routing**:
- Factory pattern: `lib/crewai/src/crewai/llm.py:L345-419` (`LLM.__new__`)
- Provider inference: `lib/crewai/src/crewai/llm.py:L501-530` (`_infer_provider_from_model`)
- Provider validation: `lib/crewai/src/crewai/llm.py:L465-499` (`_validate_model_in_constants`)
- Native provider instantiation: `lib/crewai/src/crewai/llm.py:L532-562` (`_get_native_provider`)

**Message Protocol**:
- LLMMessage type: `lib/crewai/src/crewai/utilities/types.py:L8-17`
- LiteLLM message formatting: `lib/crewai/src/crewai/llm.py:L1876-1940`
- Base formatting: `lib/crewai/src/crewai/llms/base_llm.py:L470-494`

**Native Providers**:
- OpenAI: `lib/crewai/src/crewai/llms/providers/openai/completion.py`
- Anthropic: `lib/crewai/src/crewai/llms/providers/anthropic/completion.py`
- Azure: `lib/crewai/src/crewai/llms/providers/azure/completion.py`
- Gemini: `lib/crewai/src/crewai/llms/providers/gemini/completion.py`
- Bedrock: `lib/crewai/src/crewai/llms/providers/bedrock/completion.py`

**Streaming**:
- LiteLLM streaming: `lib/crewai/src/crewai/llm.py:L708-1050` (`_handle_streaming_response`)
- OpenAI streaming: `lib/crewai/src/crewai/llms/providers/openai/completion.py:L500-650`
- Stream utilities: `lib/crewai/src/crewai/utilities/streaming.py`
- Stream events: `lib/crewai/src/crewai/events/types/llm_events.py`

**Tool Execution**:
- Base tool execution: `lib/crewai/src/crewai/llms/base_llm.py:L372-468` (`_handle_tool_execution`)
- LiteLLM tool handling: `lib/crewai/src/crewai/llm.py:L1497-1584`
- Tool accumulation: `lib/crewai/src/crewai/llm.py:L1006-1050` (`_handle_streaming_tool_calls`)

**Agentic Primitives**:
- Stop words: `lib/crewai/src/crewai/llms/base_llm.py:L231-272` (`_apply_stop_words`)
- Agent executor: `lib/crewai/src/crewai/agents/crew_agent_executor.py`
- Context handling: `lib/crewai/src/crewai/utilities/agent_utils.py` (handle_context_length)

**Events & Hooks**:
- Event bus: `lib/crewai/src/crewai/events/event_bus.py`
- LLM hooks: `lib/crewai/src/crewai/hooks/llm_hooks.py`
- Before/after hooks: `lib/crewai/src/crewai/llms/base_llm.py:L590-719`

## Implications for New Framework

### Positive Patterns

1. **Factory-Based Provider Routing**: Enables transparent multi-provider support without caller awareness
   - Model string determines provider: `"gpt-4"` → OpenAI, `"claude-3-5-sonnet"` → Anthropic
   - Explicit override: `LLM(model="gpt-4", provider="azure")` routes to Azure
   - Pattern matching allows new models without code changes

2. **Native SDK Priority with Universal Fallback**: Best of both worlds
   - Use native SDKs for optimal features (structured outputs, thinking blocks, latest APIs)
   - Fall back to LiteLLM for 100+ other providers without custom adapters
   - No vendor lock-in - swap providers by changing model string

3. **Queue-Based Streaming Distribution**: Clean separation of concerns
   - Event bus emits chunks, queue accumulates, generators yield
   - Supports both sync (threading.Queue) and async (asyncio.Queue) consumers
   - Single LLM call can stream to multiple consumers

4. **Partial Tool Call Accumulation**: Enables streaming tool execution
   - Accumulate tool name and arguments across chunks
   - Execute as soon as JSON is complete (don't wait for full stream)
   - Emit tool call progress events for UI feedback

5. **Unified Event Bus**: Observability without coupling
   - All LLM calls emit lifecycle events (started, chunk, completed, failed)
   - Tool execution events (started, finished, error)
   - Consumers subscribe to events without modifying LLM code

6. **Provider-Agnostic Tool Execution**: Abstract away tool calling differences
   - `_handle_tool_execution()` works same for all providers
   - Providers convert their tool responses to common format
   - Tool result fed back to conversation regardless of provider

7. **Context Window Lookup Table**: Explicit model-specific limits
   - No guessing at context sizes
   - 85% usage ratio prevents overflow
   - Graceful degradation on context exceeded (summarization or error)

### Considerations

1. **Message Formatting Fragmentation**: Each provider needs custom logic
   - O1: system → assistant conversion
   - Anthropic: separate system parameter, first message must be user
   - Mistral: last message must be user
   - Solution: Centralize in provider adapters, not scattered

2. **Tool Schema Conversion Duplication**: Every provider reimplements Pydantic → native schema
   - OpenAI: `parameters: tool.args_schema.model_json_schema()`
   - Anthropic: `input_schema: tool.args_schema.model_json_schema()`
   - Gemini: `parameters: tool.args_schema.model_json_schema()`
   - Solution: Create `ToolSchemaConverter` with provider-specific methods

3. **Streaming Event Granularity**: No structured metadata on chunks
   - `LLMStreamChunkEvent` has `chunk` (string) but limited context
   - No token-level metadata (logprobs, finish_reason per chunk)
   - Solution: Enrich event with provider-specific metadata

4. **No Multi-Turn Tool Conversations**: Sequential tool calls only
   - Accumulate all tool results, then send back in one message
   - Can't do: Tool A → Tool B → Tool C in parallel
   - Anthropic limitation (no parallel tools) applied to all providers

5. **Stop Words Post-Processing**: Applied after response, not during
   - Provider may not support stop sequences (LiteLLM limitation)
   - Post-processing wastes tokens on content after stop word
   - Solution: Pass to provider API when supported, post-process as fallback

6. **No Token Budgets Per Message**: Context management is reactive
   - Wait for `LLMContextLengthExceededError`, then handle
   - No proactive "will this fit?" check before LLM call
   - Solution: Add `estimate_tokens(messages)` and pre-check

## Anti-Patterns Observed

1. **Factory Returns Different Types**: `LLM.__new__()` may return `OpenAICompletion`, `AnthropicCompletion`, or `LLM` (LiteLLM)
   - Type checkers can't infer return type
   - `cast(Self, native_class(...))` hides the real type
   - **Fix**: Return union type OR use separate factory function

2. **Dual Code Paths for Streaming**: `_handle_streaming_response` and `_ahandle_streaming_response` have 90% duplicate logic
   - Sync and async versions manually kept in sync
   - Bug in one version may not be fixed in the other
   - **Fix**: Write async-first, wrap in `asyncio.run()` for sync

3. **In-Place Message Mutation**: `_format_messages_for_provider()` may modify input messages
   - `msg["role"] = "assistant"` mutates caller's data structure
   - Hard to debug when messages change unexpectedly
   - **Fix**: Copy messages before modification, return new list

4. **String-Based Error Detection**: `"Unsupported parameter" in str(e) and "'stop'" in str(e)`
   - Brittle - error message changes break detection
   - Re-raises and retries based on text matching
   - **Fix**: Catch specific exception types, use error codes

5. **Global State in LiteLLM**: `litellm.drop_params = True`, `litellm.callbacks = ...`
   - Modifying global library state affects all instances
   - Thread-safety concerns
   - **Fix**: Use per-instance configuration if library supports

6. **No Request/Response Logging**: Only events, no raw API payloads
   - Can't debug "what exactly was sent to OpenAI?"
   - No replay/mock capability for testing
   - **Fix**: Add optional request/response interceptor (they have httpx interceptor but not used for logging)

7. **Tool Call ID Not Tracked**: Streaming accumulates by index, not tool_call_id
   - May break if providers change indexing behavior
   - Can't correlate tool result with specific call in multi-tool scenarios
   - **Fix**: Use `tool_call.id` as accumulator key

8. **No Partial Response Recovery**: If streaming fails mid-stream, lose all accumulated chunks
   - Exception in chunk processing discards `full_response`
   - Only fallback is complete re-call (expensive)
   - **Fix**: Store chunks in durable buffer, return partial on error

9. **Context Window Size Hardcoded**: 100+ model entries in dict, no auto-update
   - New models require code changes
   - GPT-4.1/4.2 sizes may be wrong (rapidly changing)
   - **Fix**: Fetch from provider API OR pattern-match with defaults

10. **System Message Handling Inconsistent**: Different providers extract system differently
    - LiteLLM: Keeps in message list, may convert role
    - Anthropic: Extracts to separate `system` parameter
    - OpenAI: Keeps in message list as-is
    - **Fix**: Unified `SystemMessage` type that all providers understand

## Positive Patterns to Adopt

1. **Event-Driven Architecture**: Emit lifecycle events for all LLM operations - enables observability without tight coupling
2. **Native SDK + Universal Fallback**: Combine best-of-class native integrations with broad compatibility via gateway
3. **Accumulator Pattern for Streaming Tools**: Execute tools as soon as args are complete, don't wait for full stream
4. **Provider-Agnostic Tool Interface**: Abstract tool execution so business logic doesn't care about OpenAI vs Anthropic formats
5. **Factory Pattern for Provider Selection**: Model string determines provider, no explicit routing needed in application code

## Recommendations

1. **Structured Metadata Events**: Include token counts, finish_reason, model version in chunk events
2. **Proactive Context Management**: Check token estimates before LLM call, not reactive error handling
3. **Tool Call ID Correlation**: Use provider's tool_call_id for result matching, not array indices
4. **Immutable Message Formatting**: Always return new message list, never mutate input
5. **Type-Safe Provider Return**: Use protocol/interface for common methods, avoid runtime type checks
6. **Async-First Streaming**: Write async implementation, provide sync wrapper to avoid duplication
7. **Request/Response Logging**: Add optional middleware to capture raw API payloads for debugging
8. **Dynamic Context Window Lookup**: Fetch from provider API or use conservative defaults for unknown models
9. **Unified System Message Handling**: Create abstraction that works across all providers (e.g., `system` field + auto-conversion)
10. **Partial Response Resilience**: Store chunks in recoverable buffer, return partial results on streaming errors
