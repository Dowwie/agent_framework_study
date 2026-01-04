# Harness-Model Protocol Analysis: MetaGPT

## Summary
- **Key Finding 1**: MetaGPT uses a thin provider adapter pattern with OpenAI-format as the internal lingua franca - all providers translate to/from OpenAI's message structure (`{"role": "...", "content": "..."}`)
- **Key Finding 2**: Tool calling is limited to OpenAI function calling API (`aask_code`) - no unified tool interface across providers, tools are framework-level constructs registered separately from LLM calls
- **Key Finding 3**: Streaming is provider-aware but manual - each provider implements its own chunk accumulation logic with reasoning content extraction, no universal streaming abstraction
- **Classification**: **OpenAI-Centric Multi-Provider** - extends OpenAI patterns to other providers rather than creating provider-agnostic abstractions

## Detailed Analysis

### Message Protocol

**Wire Format Family**: OpenAI-compatible (universal internal format)

**Providers Supported**:
- OpenAI (`openai_api.py`) - native OpenAI SDK
- Anthropic (`anthropic_api.py`) - Claude via native SDK
- Google Gemini (`google_gemini_api.py`) - Gemini via native SDK
- Azure OpenAI (`azure_openai_api.py`)
- Ollama, Fireworks, Moonshot, Mistral, Yi, DeepSeek, etc. (all via `openai_api.py` using OpenAI-compatible endpoints)

**Abstraction Strategy**: Thin adapter with registry pattern

The framework uses a **provider registry** (`llm_provider_registry.py`) where each provider class registers itself via decorator:

```python
# metagpt/provider/llm_provider_registry.py
@register_provider([LLMType.OPENAI, LLMType.FIREWORKS, LLMType.OPEN_LLM, ...])
class OpenAILLM(BaseLLM):
    # OpenAI implementation
    pass

@register_provider([LLMType.ANTHROPIC, LLMType.CLAUDE])
class AnthropicLLM(BaseLLM):
    # Anthropic implementation
    pass

# Registry lookup
def create_llm_instance(config: LLMConfig) -> BaseLLM:
    llm = LLM_REGISTRY.get_provider(config.api_type)(config)
    return llm
```

**Internal Message Format**: All providers normalize to OpenAI format internally. `BaseLLM.format_msg()` converts framework `Message` objects to dicts:

```python
# metagpt/provider/base_llm.py:94-116
def format_msg(self, messages: Union[str, "Message", list[dict], ...]) -> list[dict]:
    processed_messages = []
    for msg in messages:
        if isinstance(msg, str):
            processed_messages.append({"role": "user", "content": msg})
        elif isinstance(msg, dict):
            assert set(msg.keys()) == set(["role", "content"])
            processed_messages.append(msg)
        elif isinstance(msg, Message):
            images = msg.metadata.get(IMAGES)
            processed_msg = self._user_msg(msg=msg.content, images=images) if images else msg.to_dict()
            processed_messages.append(processed_msg)
    return processed_messages
```

Framework `Message` schema (`schema.py:232-334`):
```python
class Message(BaseModel):
    id: str
    content: str  # natural language
    instruct_content: Optional[BaseModel]  # structured output
    role: str = "user"  # system / user / assistant
    cause_by: str  # which Action produced this
    sent_from: str  # sender address
    send_to: set[str]  # recipient addresses
    metadata: Dict[str, Any]  # images, etc.

    def to_dict(self) -> dict:
        """Return OpenAI format: {"role": "...", "content": "..."}"""
        return {"role": self.role, "content": self.content}
```

**Provider-Specific Translation**:

Gemini overrides format methods to use its `parts` structure:
```python
# metagpt/provider/google_gemini_api.py:64-99
class GeminiLLM(BaseLLM):
    def _user_msg(self, msg: str, images=None) -> dict[str, str]:
        return {"role": "user", "parts": [msg]}

    def _assistant_msg(self, msg: str) -> dict[str, str]:
        return {"role": "model", "parts": [msg]}

    def format_msg(self, messages: ...) -> list[dict]:
        # Convert to {"role": "user|model", "parts": [...]}
        processed_messages = []
        for msg in messages:
            if isinstance(msg, Message):
                processed_messages.append({
                    "role": "user" if msg.role == "user" else "model",
                    "parts": [msg.content]
                })
        return processed_messages
```

Anthropic extracts system prompt from first message:
```python
# metagpt/provider/anthropic_api.py:24-38
def _const_kwargs(self, messages: list[dict], stream: bool = False) -> dict:
    kwargs = {"model": self.model, "messages": messages, ...}
    if self.use_system_prompt:
        if messages[0]["role"] == "system":
            kwargs["messages"] = messages[1:]
            kwargs["system"] = messages[0]["content"]  # Anthropic expects separate system param
    return kwargs
```

### Tool Call Encoding

**Request Method**: OpenAI Function Calling API (limited to OpenAI provider only)

**Schema Transmission**: Tools are registered separately in `ToolRegistry`, NOT passed to LLM providers. The only tool-related LLM call is `aask_code` which uses a hardcoded function schema:

```python
# metagpt/provider/constant.py:3-26
GENERAL_FUNCTION_SCHEMA = {
    "name": "execute",
    "description": "Executes code on the user's machine...",
    "parameters": {
        "type": "object",
        "properties": {
            "language": {"type": "string", "enum": ["python", "R", "shell", ...]},
            "code": {"type": "string", "description": "The code to execute"}
        },
        "required": ["language", "code"]
    }
}

# metagpt/provider/openai_api.py:189-203
async def aask_code(self, messages: list[dict], timeout=..., **kwargs) -> dict:
    if "tools" not in kwargs:
        configs = {"tools": [{"type": "function", "function": GENERAL_FUNCTION_SCHEMA}]}
        kwargs.update(configs)
    rsp = await self._achat_completion_function(messages, **kwargs)
    return self.get_choice_function_arguments(rsp)
    # Returns: {'language': 'python', 'code': "print('Hello, World!')"}
```

**Tool Registry**: Tools are framework-level constructs, registered via decorator but NOT integrated with LLM function calling:

```python
# metagpt/tools/tool_registry.py:94-118
@register_tool(tags: list[str] = None, schema_path: str = "", **kwargs)
def decorator(cls):
    file_path = inspect.getfile(cls)
    source_code = inspect.getsource(cls)

    TOOL_REGISTRY.register_tool(
        tool_name=cls.__name__,
        tool_path=file_path,
        tool_code=source_code,
        tags=tags,
        tool_source_object=cls,
        **kwargs
    )
    return cls
```

Tools are used by roles like `DataInterpreter` for **tool recommendation** (BM25 search over tool descriptions), not for LLM function calling:

```python
# metagpt/roles/di/data_interpreter.py:114-122
if self.tool_recommender:
    context = self.working_memory.get()[-1].content
    plan = self.planner.plan if self.use_plan else None
    tool_info = await self.tool_recommender.get_recommended_tool_info(context=context, plan=plan)
else:
    tool_info = ""

# Tool info is injected into prompt as text, not as function schema
code, cause_by = await self._write_code(counter, plan_status, tool_info)
```

**Response Parsing**: Only implemented for OpenAI function calling in `aask_code`:

```python
# metagpt/provider/openai_api.py:230-263
def get_choice_function_arguments(self, rsp: ChatCompletion) -> dict:
    message = rsp.choices[0].message
    if message.tool_calls and message.tool_calls[0].function:
        return json.loads(message.tool_calls[0].function.arguments, strict=False)
    elif message.content and message.content.startswith("```"):
        # Fallback: parse code blocks from content
        code = CodeParser.parse_code(text=message.content)
        return {"language": "python", "code": code}
    else:
        raise Exception(f"Failed to parse {rsp}")
```

**Tool Choice Support**:

| Provider | Function Calling | Parallel Calls | Tool Choice | Notes |
|----------|------------------|----------------|-------------|-------|
| OpenAI | ✅ Yes (native) | ❓ Not tested | ✅ Via `tools` param | Only provider with tool integration |
| Anthropic | ❌ No | - | - | No tool implementation |
| Gemini | ❌ No | - | - | No tool implementation |
| Others | ❌ No | - | - | OpenAI-compatible providers could support it |

**Critical Gap**: Tools are decoupled from LLM interface. The framework has a rich tool registry system but doesn't transmit tool schemas to LLMs (except the hardcoded `execute` function). Tool usage is prompt-based, not function-calling-based.

### Streaming Implementation

**Protocol**: SSE-like (Server-Sent Events) via AsyncStream from native SDKs

**Partial Tool Call Handling**: Not applicable (no streaming tool calls implemented)

**Event Types Emitted**:

Each provider implements streaming independently with different event structures:

**OpenAI Streaming** (`openai_api.py:92-136`):
```python
async def _achat_completion_stream(self, messages: list[dict], timeout=...) -> str:
    response: AsyncStream[ChatCompletionChunk] = await self.aclient.chat.completions.create(
        **self._cons_kwargs(messages, timeout=...), stream=True
    )
    usage = None
    collected_messages = []
    collected_reasoning_messages = []

    async for chunk in response:
        choice0 = chunk.choices[0]
        choice_delta = choice0.delta

        # Extract reasoning content (for DeepSeek)
        if hasattr(choice_delta, "reasoning_content") and choice_delta.reasoning_content:
            collected_reasoning_messages.append(choice_delta.reasoning_content)
            continue

        chunk_message = choice_delta.content or ""
        log_llm_stream(chunk_message)  # Print to console
        collected_messages.append(chunk_message)

        # Extract usage from various positions (provider-specific)
        if chunk.usage:  # Fireworks
            usage = CompletionUsage(**chunk.usage)
        elif choice0.usage:  # Moonshot
            usage = CompletionUsage(**choice0.usage)

    full_reply_content = "".join(collected_messages)
    if collected_reasoning_messages:
        self.reasoning_content = "".join(collected_reasoning_messages)
    return full_reply_content
```

**Anthropic Streaming** (`anthropic_api.py:60-86`):
```python
async def _achat_completion_stream(self, messages: list[dict], timeout=...) -> str:
    stream = await self.aclient.messages.create(**self._const_kwargs(messages, stream=True))
    collected_content = []
    collected_reasoning_content = []
    usage = Usage(input_tokens=0, output_tokens=0)

    async for event in stream:
        event_type = event.type

        if event_type == "message_start":
            usage.input_tokens = event.message.usage.input_tokens
        elif event_type == "content_block_delta":
            delta_type = event.delta.type
            if delta_type == "thinking_delta":  # Extended Thinking
                collected_reasoning_content.append(event.delta.thinking)
            elif delta_type == "text_delta":
                content = event.delta.text
                log_llm_stream(content)
                collected_content.append(content)
        elif event_type == "message_delta":
            usage.output_tokens = event.usage.output_tokens

    full_content = "".join(collected_content)
    if collected_reasoning_content:
        self.reasoning_content = "".join(collected_reasoning_content)
    return full_content
```

**Gemini Streaming** (`google_gemini_api.py:139-157`):
```python
async def _achat_completion_stream(self, messages: list[dict], timeout=...) -> str:
    resp = await self.llm.generate_content_async(**self._const_kwargs(messages, stream=True))
    collected_content = []

    async for chunk in resp:
        try:
            content = chunk.text
        except Exception as e:
            logger.warning(f"errors: {e}\n{BlockedPromptException(str(chunk))}")
            raise BlockedPromptException(str(chunk))
        log_llm_stream(content)
        collected_content.append(content)

    full_content = "".join(collected_content)
    usage = await self.aget_usage(messages, full_content)
    self._update_costs(usage)
    return full_content
```

**Streaming Event Table**:

| Provider | Event Source | Chunk Format | Reasoning/Thinking | Usage Info |
|----------|--------------|--------------|-------------------|------------|
| OpenAI | `AsyncStream[ChatCompletionChunk]` | `chunk.choices[0].delta.content` | `delta.reasoning_content` (DeepSeek) | In final chunk or separate chunk |
| Anthropic | Native `messages.stream()` | `event.delta.text` | `event.delta.thinking` (Extended Thinking) | `message_start` + `message_delta` |
| Gemini | `generate_content_async(..., stream=True)` | `chunk.text` | Not supported | Manual token counting |

**Streaming Output**: All streaming goes through `log_llm_stream()` which prints directly to console:
```python
# metagpt/logs.py (inferred from usage)
def log_llm_stream(content):
    print(content, end="")  # Synchronous console print
```

No structured event emission for application-level consumption - streaming is for human observation only.

### Agentic Primitives

#### System Prompt Assembly

**Dual-layer composition**: Role-level prefix + Action-level prefix

```python
# metagpt/roles/role.py:51-52
PREFIX_TEMPLATE = """You are a {profile}, named {name}, your goal is {goal}. """
CONSTRAINT_TEMPLATE = "the constraint is {constraints}. "

# metagpt/provider/base_llm.py:179-210
async def aask(self, msg: ..., system_msgs: Optional[list[str]] = None, ...) -> str:
    if system_msgs:
        message = self._system_msgs(system_msgs)  # User-provided system messages
    else:
        message = [self._default_system_msg()]  # Default: "You are a helpful assistant."

    if not self.use_system_prompt:  # For models like o1
        message = []

    if isinstance(msg, str):
        message.append(self._user_msg(msg, images=images))
    else:
        message.extend(msg)

    rsp = await self.acompletion_text(message, stream=stream, timeout=...)
    return rsp
```

Action classes can override system prompt:
```python
# metagpt/actions/action.py:85-91
def set_prefix(self, prefix):
    self.prefix = prefix
    self.llm.system_prompt = prefix
    if self.node:
        self.node.llm = self.llm
    return self
```

#### Scratchpad / Working Memory

**Implementation**: Role-level `working_memory` (separate from main memory)

```python
# metagpt/roles/role.py:92-102
class RoleContext(BaseModel):
    env: BaseEnvironment = Field(default=None, exclude=True)
    msg_buffer: MessageQueue = Field(default_factory=MessageQueue)
    memory: Memory = Field(default_factory=Memory)
    working_memory: Memory = Field(default_factory=Memory)  # For planning/temporary state
    state: int = Field(default=-1)  # Current action index
    # ...
```

Used in `DataInterpreter` for ReAct-style reasoning:
```python
# metagpt/roles/di/data_interpreter.py:65-84
async def _think(self) -> bool:
    context = self.working_memory.get()  # Get current working context

    if not context:
        self.working_memory.add(self.get_memories()[0])  # Add user requirement
        self._set_state(0)
        return True

    prompt = REACT_THINK_PROMPT.format(user_requirement=..., context=context)
    rsp = await self.llm.aask(prompt)
    rsp_dict = json.loads(CodeParser.parse_code(text=rsp))

    self.working_memory.add(Message(content=rsp_dict["thoughts"], role="assistant"))
    need_action = rsp_dict["state"]
    return need_action
```

#### Interrupt / Human-in-the-Loop

**Limited implementation**: `HumanProvider` exists but not systematically integrated

```python
# metagpt/provider/human_provider.py (referenced in imports)
class HumanProvider(BaseLLM):
    # Prompts human for responses instead of calling LLM
    pass
```

Commented-out review mechanism in `DataInterpreter`:
```python
# metagpt/roles/di/data_interpreter.py:142-146
# if not success and counter >= max_retry:
#     logger.info("coding failed!")
#     review, _ = await self.planner.ask_review(auto_run=False, trigger=ReviewConst.CODE_REVIEW_TRIGGER)
#     if ReviewConst.CHANGE_WORDS[0] in review:
#         counter = 0  # redo the task again with help of human suggestions
```

No systematic HITL support - appears to be planned but not fully implemented.

#### Conversation State Machine

**Three execution modes** (`RoleReactMode`):

1. **REACT** - LLM-driven state selection:
```python
# metagpt/roles/role.py:54-69
STATE_TEMPLATE = """Here are your conversation records...
Your previous state: {previous_state}
Now choose one of the following stages: {states}
Just answer a number between 0-{n_states}...
If you think you have completed your goal, return -1.
"""

async def _think(self) -> bool:
    # LLM selects next action index
    prompt = self._fill_prompt_template(STATE_TEMPLATE)
    rsp = await self.llm.aask(prompt)
    state_num = extract_state_value_from_output(rsp)
    self._set_state(state_num)
    return state_num != -1  # -1 means done
```

2. **BY_ORDER** - Sequential FSM (execute actions in order):
```python
# metagpt/roles/role.py:353-357
async def _react(self) -> Message:
    if self.rc.react_mode == RoleReactMode.BY_ORDER:
        rsp = await self._act_by_order()
```

3. **PLAN_AND_ACT** - Planner-driven task decomposition:
```python
# metagpt/roles/role.py:472-496
async def _plan_and_act(self) -> Message:
    if not self.planner.plan.tasks:
        await self.planner.update_plan(goal=...)

    current_task = self.planner.get_current_task()
    task_result = await self._act_on_task(current_task)
    self.planner.update_task_result(task_result)
    return rsp
```

### Provider Abstraction

**Multi-Provider Support Table**:

| Provider | API Type | System Prompt | Streaming | Function Calling | Multimodal | Reasoning Mode |
|----------|----------|---------------|-----------|------------------|------------|----------------|
| OpenAI | Native SDK | ✅ Yes | ✅ Yes | ✅ `aask_code` only | ✅ GPT-4V | ✅ o1-series detection |
| Anthropic | Native SDK | ✅ Separate param | ✅ Yes | ❌ No | ✅ Via content array | ✅ Extended Thinking |
| Gemini | Native SDK | ❌ No | ✅ Yes | ❌ No | ❌ Not shown | ❌ No |
| Azure OpenAI | OpenAI SDK | ✅ Yes | ✅ Yes | ✅ Same as OpenAI | ✅ Same as OpenAI | ✅ Same as OpenAI |
| Fireworks | OpenAI SDK | ✅ Yes | ✅ Yes | ✅ Potential | ❌ No | ❌ No |
| Moonshot | OpenAI SDK | ✅ Yes | ✅ Yes | ✅ Potential | ❌ No | ❌ No |
| DeepSeek | OpenAI SDK | ✅ Yes | ✅ Yes | ✅ Potential | ❌ No | ✅ reasoning_content |
| Ollama | OpenAI SDK | ✅ Yes | ✅ Yes | ❌ Unknown | ❌ No | ❌ No |

**Abstraction Quality**:

**Strong**:
- ✅ Message format normalization (all providers → OpenAI dict format)
- ✅ Registry pattern for provider discovery
- ✅ Cost tracking abstraction (`CostManager` per provider)
- ✅ Retry logic in `BaseLLM` (tenacity decorators)
- ✅ Timeout handling unified
- ✅ Message compression (token-aware truncation in `BaseLLM.compress_messages`)

**Weak**:
- ❌ Tool calling is OpenAI-specific, not abstracted
- ❌ Streaming events are provider-specific (no unified event types)
- ❌ Reasoning/thinking content extraction is ad-hoc per provider
- ❌ System prompt handling differs (Anthropic needs separate param, Gemini doesn't support it)
- ❌ No graceful degradation when provider lacks features (just omits the feature)

**Provider-Specific Workarounds**:

```python
# metagpt/provider/openai_api.py:148-151
if "o1-" in self.model:
    # OpenAI o1 doesn't support temperature or max_tokens
    kwargs["temperature"] = 1
    kwargs.pop("max_tokens")

# metagpt/provider/anthropic_api.py:36-37
if self.config.reasoning:
    kwargs["thinking"] = {"type": "enabled", "budget_tokens": self.config.reasoning_max_token}

# metagpt/provider/google_gemini_api.py:49
def __init__(self, config: LLMConfig):
    self.use_system_prompt = False  # Gemini has no system prompt via API
```

## Code References

**Core LLM Interface**:
- `metagpt/provider/base_llm.py:35-413` - BaseLLM abstract class
- `metagpt/provider/llm_provider_registry.py:12-48` - Provider registry
- `metagpt/llm.py:15-20` - Factory function

**Provider Implementations**:
- `metagpt/provider/openai_api.py:43-328` - OpenAI + OpenAI-compatible providers
- `metagpt/provider/anthropic_api.py:14-87` - Anthropic/Claude
- `metagpt/provider/google_gemini_api.py:42-165` - Google Gemini

**Message Types**:
- `metagpt/schema.py:232-357` - Message class with routing metadata
- `metagpt/provider/base_llm.py:94-116` - Message format conversion

**Tool System**:
- `metagpt/tools/tool_registry.py:27-128` - Tool registration
- `metagpt/provider/constant.py:3-26` - Hardcoded function schema
- `metagpt/provider/openai_api.py:189-263` - Function calling implementation

**Streaming**:
- `metagpt/provider/openai_api.py:92-136` - OpenAI streaming
- `metagpt/provider/anthropic_api.py:60-86` - Anthropic streaming
- `metagpt/provider/google_gemini_api.py:139-157` - Gemini streaming

**Context Management**:
- `metagpt/context_mixin.py:17-102` - Context/config/LLM injection
- `metagpt/context.py:58-100` - Global context object
- `metagpt/roles/role.py:92-112` - Role context with working memory

**Agentic Primitives**:
- `metagpt/roles/role.py:51-79` - System prompt templates
- `metagpt/roles/role.py:359-379` - REACT state selection
- `metagpt/roles/di/data_interpreter.py:65-84` - Working memory usage

## Implications for New Framework

### Positive Patterns

1. **Provider Registry Pattern**: Decorator-based registration makes adding new providers straightforward:
   ```python
   @register_provider([LLMType.NEW_PROVIDER])
   class NewProviderLLM(BaseLLM):
       # Implement abstract methods
   ```

2. **Message Normalization**: Converting everything to OpenAI format internally simplifies the framework's mental model - actions/roles don't need to know about provider differences.

3. **Cost Tracking Abstraction**: Per-provider cost managers (`CostManager`, `FireworksCostManager`, `TokenCostManager`) allow flexible pricing models without polluting the LLM interface.

4. **Retry Logic in Base Class**: Tenacity decorators in `BaseLLM` handle retries transparently:
   ```python
   @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(min=1, max=60), ...)
   async def acompletion_text(self, messages, stream=False, timeout=...) -> str:
   ```

5. **Message Compression**: Token-aware message truncation (`compress_messages`) prevents context overflow:
   - PRE_CUT_BY_TOKEN: Keep earliest messages
   - POST_CUT_BY_TOKEN: Keep latest messages
   - Always preserve system messages

6. **Reasoning Content Separation**: Dedicated `reasoning_content` property to store chain-of-thought from models that support it (DeepSeek, Anthropic Extended Thinking).

### Considerations

1. **Tool Calling Gap**: Tools exist at framework level but don't integrate with LLM function calling. Consider:
   - Extend tool registry to generate provider-specific schemas (OpenAI `tools`, Anthropic `tools`, Gemini `function_declarations`)
   - Implement tool result feedback loop (tool call → execute → send result as next message)
   - Handle parallel tool calls (multiple tool_calls in single response)

2. **Streaming Fragmentation**: Each provider has custom streaming logic. Consider:
   - Define universal streaming events: `ChunkEvent`, `ReasoningEvent`, `ToolCallEvent`, `UsageEvent`, `ErrorEvent`
   - Implement adapter layer that translates provider events to universal events
   - Support async generators for application-level consumption (not just console printing)

3. **System Prompt Inconsistency**: Different providers handle system messages differently:
   - OpenAI: First message with `role="system"`
   - Anthropic: Separate `system` parameter, expects `messages` to start with `user`
   - Gemini: No system prompt support
   - **Solution**: Normalize in `BaseLLM.aask()` - detect provider capabilities and transform accordingly

4. **No Graceful Degradation**: When a provider lacks a feature (e.g., Gemini doesn't support system prompts), the framework silently omits it. Consider:
   - Feature capability matrix per provider
   - Automatic workarounds (e.g., prepend system prompt to first user message for Gemini)
   - Warnings when requested features are unavailable

5. **Message Compression Heuristics**: Token counting is provider-specific but defaults to crude heuristic (`len(msg["content"]) * 0.5`). Consider:
   - Require providers to implement accurate token counting (use tiktoken for OpenAI, provider APIs for others)
   - Make compression strategy configurable per role/action
   - Support semantic compression (summarize old messages instead of truncating)

6. **Streaming as Presentation Only**: Current streaming only prints to console. For production:
   - Return async generators from `acompletion_text(..., stream=True)`
   - Emit structured events (text chunks, tool calls, reasoning, finish_reason)
   - Allow multiple subscribers (logging, UI updates, metrics)

7. **Reasoning Mode Detection**: Framework detects o1 models and disables temperature/max_tokens, detects DeepSeek reasoning content. Consider:
   - Explicit configuration flag: `llm_config.reasoning = True` (already exists)
   - Automatic detection based on model name pattern matching
   - Reasoning budget enforcement (stop generation if reasoning exceeds budget)

## Anti-Patterns Observed

1. **Tool Calling Half-Implemented**: Tools are registered with rich schemas but never passed to LLMs (except hardcoded `execute` function). The framework has all the pieces but doesn't connect them.

2. **Streaming Prints to Console**: `log_llm_stream(content)` prints directly instead of emitting events. This makes streaming unusable for programmatic consumption (APIs, UIs, logging pipelines).

3. **Provider-Specific Event Parsing**: Each provider has custom logic to extract usage, reasoning content, finish_reason from chunks. This logic should be in provider adapters, not duplicated in base streaming implementations.

4. **Silent Feature Gaps**: When Gemini doesn't support system prompts, the framework silently drops them. Users get different behavior across providers without warnings.

5. **String-Based Model Detection**: Special cases like `if "o1-" in self.model` are fragile. Use provider capabilities registry instead:
   ```python
   PROVIDER_CAPABILITIES = {
       "o1-preview": {"supports_temperature": False, "supports_max_tokens": False},
       "claude-3-opus": {"extended_thinking": True},
   }
   ```

6. **No Parallel Tool Calls**: OpenAI supports returning multiple `tool_calls` in one response. Framework only handles single function call in `get_choice_function_arguments()`.

7. **Reasoning Content as Instance Variable**: `self._reasoning_content` is set as side effect during response parsing. Better to return structured response: `(content, reasoning, usage)`.

8. **Manual Usage Calculation**: Some providers (Gemini) require separate API calls to count tokens after completion. This breaks streaming and adds latency. Consider caching token counts or using estimation for real-time display.

9. **No Message Validation**: Framework assumes all providers return properly formatted responses. No validation that `choices[0].message.content` exists before accessing it.

10. **Compression Without Semantic Understanding**: Truncating messages by token count can break coherence. Multi-turn tool use conversations get corrupted if tool results are truncated mid-JSON.

---

**Overall Assessment**: MetaGPT's harness-model protocol is **functional but OpenAI-centric**. It successfully abstracts multiple providers behind a unified interface, but tool calling and streaming remain provider-specific. The framework would benefit from:
- Universal streaming event system
- Tool schema translation layer (framework tools → provider-specific format)
- Provider capability matrix with graceful degradation
- Structured response objects instead of side-effect-laden parsing

The architecture is extensible (easy to add new providers) but not fully abstracted (features don't work uniformly across providers).
