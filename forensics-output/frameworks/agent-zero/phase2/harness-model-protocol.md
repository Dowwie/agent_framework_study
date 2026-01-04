# Harness-Model Protocol Analysis: Agent Zero

## Summary

- **Key Finding 1**: LiteLLM-based universal abstraction - Agent Zero uses LiteLLM as the sole provider adapter, supporting 100+ LLM providers through a unified interface with automatic format translation
- **Key Finding 2**: Custom tool encoding via text parsing - Tools are NOT transmitted via native function calling APIs; instead, the system prompt instructs models to output JSON objects that are then parsed with dirty JSON parsing
- **Key Finding 3**: Sophisticated streaming with reasoning separation - The framework implements dual-channel streaming (response + reasoning) with custom tag parsing for models without native reasoning support, plus real-time tool call detection from partial JSON
- **Classification**: **Prompt-based tool calling with universal LLM adapter**. Agent Zero sacrifices native function calling precision for maximum provider compatibility, using LiteLLM to normalize all providers to a common interface while parsing tool requests from LLM text output.

## Detailed Analysis

### Message Protocol

**Wire Format Family**: OpenAI-compatible (via LiteLLM normalization)

**Providers Supported**:
- All providers supported by LiteLLM (~100+)
- Explicitly configured providers found in `conf/model_providers.yaml`:
  - OpenAI, Anthropic, Google (Gemini), Groq, OpenRouter, Ollama, Azure, AWS Bedrock, etc.
- Provider configuration location: `/python/helpers/providers.py`
- Adapter location: `/models.py` (LiteLLMChatWrapper class)

**Abstraction Strategy**: **Unified LLM Gateway via LiteLLM**

Agent Zero implements a two-layer abstraction:

1. **LiteLLM Layer** (external dependency):
   - Normalizes all provider APIs to OpenAI-compatible format
   - Handles provider-specific quirks (auth, endpoints, parameters)
   - Returns standardized `ModelResponse` objects

2. **LangChain Wrapper Layer** (internal):
   - Wraps LiteLLM in LangChain's `SimpleChatModel` interface
   - Converts between LangChain message types and LiteLLM dict format
   - Adds Agent Zero-specific features (rate limiting, reasoning extraction, retry logic)

**Code Example** (`models.py:292-365`):

```python
class LiteLLMChatWrapper(SimpleChatModel):
    model_name: str
    provider: str
    kwargs: dict = {}

    def _convert_messages(self, messages: List[BaseMessage]) -> List[dict]:
        result = []
        # Map LangChain message types to LiteLLM roles
        role_mapping = {
            "human": "user",
            "ai": "assistant",
            "system": "system",
            "tool": "tool",
        }
        for m in messages:
            role = role_mapping.get(m.type, m.type)
            message_dict = {"role": role, "content": m.content}

            # Handle tool calls for AI messages (if present from LangChain)
            tool_calls = getattr(m, "tool_calls", None)
            if tool_calls:
                # Convert LangChain tool calls to LiteLLM format
                new_tool_calls = []
                for tool_call in tool_calls:
                    args = tool_call["args"]
                    if isinstance(args, dict):
                        args_str = json.dumps(args)
                    else:
                        args_str = str(args)

                    new_tool_calls.append({
                        "id": tool_call.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tool_call["name"],
                            "arguments": args_str,
                        },
                    })
                message_dict["tool_calls"] = new_tool_calls

            # Handle tool call ID for ToolMessage
            tool_call_id = getattr(m, "tool_call_id", None)
            if tool_call_id:
                message_dict["tool_call_id"] = tool_call_id

            result.append(message_dict)
        return result
```

**Message Flow**:
1. Agent constructs history as LangChain `BaseMessage` objects (SystemMessage, HumanMessage, AIMessage)
2. `LiteLLMChatWrapper._convert_messages()` translates to list of dicts with OpenAI-style roles
3. LiteLLM's `acompletion()` normalizes to provider-specific format
4. Provider responds in native format
5. LiteLLM normalizes response back to OpenAI-compatible format
6. Wrapper parses chunks and returns to Agent

**Key Insight**: Tool call support in the message conversion layer exists BUT IS NOT USED. Agent Zero does not leverage native function calling APIs. The `tool_calls` conversion code is dead code - tools are actually encoded in system prompts and parsed from text output (see Tool Call Encoding section).

### Tool Call Encoding

**Request Method**: **System Prompt Injection (Not Function Calling API)**

**Critical Finding**: Despite LiteLLM and LangChain both supporting native function calling, Agent Zero deliberately uses text-based tool encoding.

**Schema Transmission**:

Tools are described in Markdown format within the system prompt. The schema is human-readable prose, not JSON Schema.

Example from prompt assembly (`python/extensions/system_prompt/_10_system_prompt.py:38-42`):

```python
def get_tools_prompt(agent: Agent):
    prompt = agent.read_prompt("agent.system.tools.md")
    if agent.config.chat_model.vision:
        prompt += "\n\n" + agent.read_prompt("agent.system.tools_vision.md")
    return prompt
```

The system prompt (`prompts/agent.system.tools.md` and similar files) contains tool descriptions like:

```
## Tools

You can use the following tools by responding with a JSON object:

{
  "tool_name": "response",
  "tool_args": {
    "message": "your response to the user"
  }
}

Available tools:
- response: Finish the task and respond to the user
- call_subordinate: Delegate a task to a subordinate agent
- code_execution_tool: Execute code in a sandboxed environment
- memory_save: Save information to long-term memory
...
```

**Response Parsing**:

Parser location: `/python/helpers/extract_tools.py:9-21`

```python
def json_parse_dirty(json:str) -> dict[str,Any] | None:
    if not json or not isinstance(json, str):
        return None

    ext_json = extract_json_object_string(json.strip())
    if ext_json:
        try:
            data = DirtyJson.parse_string(ext_json)
            if isinstance(data,dict): return data
        except Exception:
            return None
    return None

def extract_json_object_string(content):
    start = content.find('{')
    if start == -1:
        return ""
    end = content.rfind('}')
    if end == -1:
        return content[start:]  # No closing brace - return partial JSON
    else:
        return content[start:end+1]
```

**Parsing Flow** (`agent.py:782-821`):

```python
async def process_tools(self, msg: str):
    # Search for tool usage requests in agent message
    tool_request = extract_tools.json_parse_dirty(msg)

    if tool_request is not None:
        raw_tool_name = tool_request.get("tool_name", "")
        tool_args = tool_request.get("tool_args", {})

        tool_name = raw_tool_name
        tool_method = None

        # Support method syntax: "tool_name:method_name"
        if ":" in raw_tool_name:
            tool_name, tool_method = raw_tool_name.split(":", 1)

        # Try MCP tools first, then local tools
        tool = self.get_tool(name=tool_name, method=tool_method,
                            args=tool_args, message=msg,
                            loop_data=self.loop_data)

        if tool:
            response = await tool.execute(**tool_args)
            if response.break_loop:
                return response.message
    else:
        # No valid JSON found - add warning to history
        warning_msg = self.read_prompt("fw.msg_misformat.md")
        self.hist_add_warning(warning_msg)
```

**Tool Choice Support**:

| Feature | Support Level | Implementation |
|---------|---------------|----------------|
| Auto (model decides) | ✅ Full | Model chooses based on system prompt instructions |
| Required (force tool use) | ❌ None | Cannot force tool use; relies on model compliance |
| Specific tool (force one tool) | ❌ None | Cannot constrain to specific tool |
| None (prevent tools) | ✅ Full | Simply omit tool descriptions from system prompt |
| Parallel tool calls | ❌ None | JSON format expects single tool; no array support |

**Why Not Use Native Function Calling?**

The code comments and architecture suggest this was a deliberate choice for maximum provider compatibility. Native function calling support varies widely across providers:
- OpenAI: Full support, excellent quality
- Anthropic: Full support via tool use blocks
- Gemini: Partial support, schema restrictions
- Ollama/local models: Often no support or poor quality
- Smaller providers: Inconsistent or missing

By using prompt-based encoding, Agent Zero works with ANY text generation model, including those without function calling capabilities.

**Trade-offs**:

Advantages:
- Universal compatibility (works with any LLM)
- No provider-specific tool call formatting
- Simpler debugging (tool requests are visible text)
- Works with local/custom models

Disadvantages:
- Less reliable parsing (dirty JSON required)
- No structured validation until after LLM response
- Cannot enforce tool call format via API
- No parallel tool call support
- Wastes output tokens on JSON formatting overhead

### Streaming Implementation

**Protocol**: Native async iteration over LiteLLM's `acompletion()` stream

**Transport**: Not SSE/WebSocket at the protocol level - those are handled by LiteLLM's underlying HTTP clients. Agent Zero consumes LiteLLM's async generator.

**Partial Tool Call Handling**: **Supported via speculative JSON parsing**

Agent Zero implements sophisticated real-time tool detection during streaming:

Location: `agent.py:874-896`

```python
async def handle_response_stream(self, stream: str):
    await self.handle_intervention()
    try:
        if len(stream) < 25:
            return  # Too short to contain valid JSON
        # Try to parse incomplete JSON from stream
        response = DirtyJson.parse_string(stream)

        # If we got a valid tool request, extract it
        if isinstance(response, dict):
            tool_name = response.get("tool_name", "")
            if tool_name:
                # We detected a tool call mid-stream!
                await self.call_extensions(
                    "response_stream",
                    loop_data=self.loop_data,
                    text=stream,
                )
    except Exception:
        pass  # Invalid JSON (expected during streaming), continue
```

This allows the system to:
1. Detect tool calls before stream completion
2. Provide live feedback about which tool is being invoked
3. Potentially abort/intervene before tool execution

**Reasoning Channel Separation**:

Agent Zero implements dual-channel streaming to separate reasoning from response:

Location: `models.py:89-194` (ChatGenerationResult class)

```python
class ChatChunk(TypedDict):
    response_delta: str
    reasoning_delta: str

class ChatGenerationResult:
    def __init__(self):
        self.reasoning = ""
        self.response = ""
        self.native_reasoning = False  # Detect if model has native reasoning
        self.thinking_pairs = [("<think>", "</think>"), ("<reasoning>", "</reasoning>")]

    def add_chunk(self, chunk: ChatChunk) -> ChatChunk:
        if chunk["reasoning_delta"]:
            self.native_reasoning = True  # Model supports native reasoning (e.g., o1)

        if self.native_reasoning:
            # Use native reasoning channel from model
            processed_chunk = ChatChunk(
                response_delta=chunk["response_delta"],
                reasoning_delta=chunk["reasoning_delta"]
            )
        else:
            # Parse thinking tags manually from response
            processed_chunk = self._process_thinking_chunk(chunk)

        self.reasoning += processed_chunk["reasoning_delta"]
        self.response += processed_chunk["response_delta"]
        return processed_chunk
```

The framework supports two modes:

1. **Native reasoning** (for models like o1, o3): Uses `reasoning_content` field from model response
2. **Tag-based reasoning** (for other models): Parses `<think>...</think>` or `<reasoning>...</reasoning>` tags from text output

Chunk parsing location: `models.py:803-827`

```python
def _parse_chunk(chunk: Any) -> ChatChunk:
    delta = chunk["choices"][0].get("delta", {})
    message = chunk["choices"][0].get("message", {}) or chunk["choices"][0].get("model_extra", {}).get("message", {})

    # Extract content (response channel)
    response_delta = (
        delta.get("content", "") if isinstance(delta, dict) else getattr(delta, "content", "")
    ) or (
        message.get("content", "") if isinstance(message, dict) else getattr(message, "content", "")
    )

    # Extract reasoning (if model supports it)
    reasoning_delta = (
        delta.get("reasoning_content", "") if isinstance(delta, dict) else getattr(delta, "reasoning_content", "")
    ) or (
        message.get("reasoning_content", "") if isinstance(message, dict) else getattr(message, "reasoning_content", "")
    )

    return ChatChunk(reasoning_delta=reasoning_delta, response_delta=response_delta)
```

**Event Types Emitted**:

Agent Zero uses an extension system to emit streaming events:

| Event | Trigger | Location | Data Passed |
|-------|---------|----------|-------------|
| `reasoning_stream_chunk` | Each reasoning delta | `agent.py:391-393` | `{"chunk": str, "full": str}` |
| `reasoning_stream_end` | Reasoning complete | `agent.py:424-426` | `loop_data` |
| `response_stream_chunk` | Each response delta | `agent.py:407-409` | `{"chunk": str, "full": str}` |
| `response_stream_end` | Response complete | `agent.py:427-429` | `loop_data` |
| `reasoning_stream` | Accumulated reasoning | `agent.py:867-872` | `text: str, loop_data` |
| `response_stream` | Accumulated response | `agent.py:874-896` | `text: str, loop_data` |

Extensions can subscribe to these events to:
- Mask sensitive content in streams
- Log streaming data
- Update UI in real-time
- Detect tool calls early

**Streaming Architecture**:

```python
# From agent.py:417-421 and models.py:456-553
async def call_chat_model(self, messages, response_callback, reasoning_callback):
    model = self.get_chat_model()

    # Unified call handles streaming internally
    response, reasoning = await model.unified_call(
        messages=messages,
        reasoning_callback=reasoning_callback,  # Called for each reasoning chunk
        response_callback=response_callback,    # Called for each response chunk
        rate_limiter_callback=self.rate_limiter_callback
    )
    return response, reasoning

# Inside LiteLLMChatWrapper.unified_call():
result = ChatGenerationResult()

_completion = await acompletion(
    model=self.model_name,
    messages=msgs_conv,
    stream=True,  # Always stream if callbacks provided
    **call_kwargs,
)

async for chunk in _completion:
    # Parse chunk into response_delta and reasoning_delta
    parsed = _parse_chunk(chunk)
    output = result.add_chunk(parsed)  # Accumulate and process

    # Fire callbacks with delta and accumulated text
    if output["reasoning_delta"]:
        if reasoning_callback:
            await reasoning_callback(output["reasoning_delta"], result.reasoning)
        if limiter:
            limiter.add(output=approximate_tokens(output["reasoning_delta"]))

    if output["response_delta"]:
        if response_callback:
            await response_callback(output["response_delta"], result.response)
        if limiter:
            limiter.add(output=approximate_tokens(output["response_delta"]))
```

### Agentic Primitives

#### System Prompt Assembly

**Location**: `agent.py:484-533` and `python/extensions/system_prompt/_10_system_prompt.py`

**Assembly Process**:

```python
async def prepare_prompt(self, loop_data: LoopData) -> list[BaseMessage]:
    # 1. Call pre-prompt extensions
    await self.call_extensions("message_loop_prompts_before", loop_data=loop_data)

    # 2. Build system prompt via extensions
    loop_data.system = await self.get_system_prompt(self.loop_data)

    # 3. Get compressed history
    loop_data.history_output = self.history.output()

    # 4. Call post-prompt extensions (e.g., memory recall)
    await self.call_extensions("message_loop_prompts_after", loop_data=loop_data)

    # 5. Concatenate system prompt sections
    system_text = "\n\n".join(loop_data.system)

    # 6. Build extras (temporary + persistent context)
    extras = history.Message(
        False,
        content=self.read_prompt(
            "agent.context.extras.md",
            extras=dirty_json.stringify(
                {**loop_data.extras_persistent, **loop_data.extras_temporary}
            ),
        ),
    ).output()

    # 7. Convert history + extras to LangChain format
    history_langchain = history.output_langchain(loop_data.history_output + extras)

    # 8. Assemble final prompt
    full_prompt = [
        SystemMessage(content=system_text),
        *history_langchain,
    ]

    return full_prompt
```

**System Prompt Components** (from `_10_system_prompt.py:18-31`):

```python
# Assembled in this order:
1. Main system prompt (agent.system.main.md)
2. Tools description (agent.system.tools.md)
3. MCP tools (if any MCP servers configured)
4. Secrets/API keys (agent.system.secrets.md)
5. Project context (agent.system.projects.*.md)
6. Custom behavior prompts (via _20_behaviour_prompt.py extension)
```

**Dynamic Elements**:
- Tools list: Generated from local tools + MCP tools
- Secrets: Injected from environment variables
- Project context: Active project files and structure
- Memory recalls: Injected via `message_loop_prompts_after` extension
- Current datetime: Added by `_60_include_current_datetime.py` extension
- Agent info: Agent number, hierarchy position

#### Scratchpad / Working Memory

**Not Implemented** - Agent Zero does not have a dedicated scratchpad.

Instead, it uses:
1. **Extras (Ephemeral Context)**: `loop_data.extras_temporary` and `loop_data.extras_persistent`
   - Cleared after each message loop iteration (temporary)
   - Persists across iterations (persistent)
   - Used by extensions to inject context

2. **Reasoning Channel**: Separated from response, but not persisted
   - Models can use `<think>` tags for internal reasoning
   - Reasoning is logged but not fed back into history
   - Effectively an "ephemeral scratchpad"

#### Interrupt / Human-in-the-Loop

**Implementation**: Exception-based control flow

Location: `agent.py:318-326` and `agent.py:564-598`

```python
class InterventionException(Exception):
    """Raised when user intervenes during agent execution"""
    pass

async def handle_intervention(self, progress: str = ""):
    # Check if user sent a message while agent was working
    if self.intervention:
        user_message = self.intervention
        self.intervention = None

        # Add intervention message to history
        self.hist_add_user_message(user_message, intervention=True)

        # Raise exception to break out of current execution
        raise InterventionException("User intervention")

    # Also check for pause state
    if self.paused:
        await self.wait_for_unpause()
```

**Intervention Points**:

The agent checks for intervention at critical points:
1. Before each LLM stream chunk (`agent.py:386, 401`)
2. Before tool execution (`agent.py:826, 830, 836, 842`)
3. During response/reasoning stream handling (`agent.py:867, 875`)

**Intervention Flow**:

```
User sends message → API sets agent.intervention → Agent checks at next intervention point
→ InterventionException raised → Caught in message loop (agent.py:455-456)
→ User message added to history → Loop continues with new context
```

**Pause Mechanism**:

Separate from intervention, allows freezing execution:

```python
async def pause(self):
    self.paused = True
    self.context.log.set_progress("Agent paused")

async def unpause(self):
    self.paused = False
    if self.paused_event:
        self.paused_event.set()
```

#### Conversation State Machine

**Not a Formal State Machine** - Agent Zero uses a simpler loop-based model.

**States** (implicit):
1. **Idle**: Waiting for user message
2. **Processing**: In message loop, calling LLM
3. **Tool Execution**: Executing tool, waiting for result
4. **Paused**: User paused, waiting for unpause
5. **Intervened**: User sent message mid-execution
6. **Completed**: Tool returned `break_loop=True`

**Transitions**:

```
Idle → (user message) → Processing
Processing → (tool request) → Tool Execution → Processing
Processing → (response tool) → Completed → Idle
Processing → (user intervention) → Intervened → Processing
Processing → (pause) → Paused → (unpause) → Processing
Processing → (error) → (if repairable) → Processing
                    → (if critical) → Idle
```

**Loop Structure** (`agent.py:356-483`):

```python
async def monologue(self):
    while True:  # Outer loop: restarts after completion or error
        try:
            self.loop_data = LoopData(user_message=self.last_user_message)
            await self.call_extensions("monologue_start", loop_data=self.loop_data)

            while True:  # Inner loop: message iterations
                self.loop_data.iteration += 1

                # Build prompt
                prompt = await self.prepare_prompt(loop_data=self.loop_data)

                # Call LLM
                agent_response, _reasoning = await self.call_chat_model(
                    messages=prompt,
                    response_callback=stream_callback,
                    reasoning_callback=reasoning_callback,
                )

                # Process tools
                tools_result = await self.process_tools(agent_response)
                if tools_result:  # Response tool called
                    return tools_result  # Break to outer loop

        except InterventionException:
            pass  # User intervened, restart inner loop
        except RepairableException as e:
            # Forward error to LLM for self-correction
            self.hist_add_warning(errors.format_error(e))
        except Exception as e:
            # Critical error - kill the loop
            self.handle_critical_exception(e)
```

### Provider Abstraction

**Abstraction Level**: **Gateway Pattern** via LiteLLM

Agent Zero achieves provider abstraction entirely through LiteLLM, with minimal custom logic.

**Provider Configuration** (`conf/model_providers.yaml`):

```yaml
chat:
  openai:
    name: "OpenAI"
    litellm_provider: "openai"
  anthropic:
    name: "Anthropic"
    litellm_provider: "anthropic"
  gemini:
    name: "Google Gemini"
    litellm_provider: "gemini"
    kwargs:
      # Gemini-specific adjustments
      supports_response_schema: false
  ollama:
    name: "Ollama (Local)"
    litellm_provider: "ollama"
    kwargs:
      api_base: "http://localhost:11434"
  # ... ~20 more providers
```

**Provider Features Matrix**:

| Provider | Native in LiteLLM? | Function Calling | Streaming | Reasoning Channel | Vision | Agent Zero Support |
|----------|-------------------|------------------|-----------|-------------------|--------|-------------------|
| OpenAI | ✅ Yes | ✅ Yes (unused) | ✅ Yes | ✅ o1/o3 only | ✅ Yes | ✅ Full |
| Anthropic | ✅ Yes | ✅ Yes (unused) | ✅ Yes | ❌ No | ✅ Yes | ✅ Full |
| Google Gemini | ✅ Yes | ⚠️ Limited | ✅ Yes | ❌ No | ✅ Yes | ⚠️ Schema fixes needed* |
| Groq | ✅ Yes | ✅ Yes (unused) | ✅ Yes | ❌ No | ❌ No | ✅ Full |
| Ollama | ✅ Yes | ⚠️ Varies | ✅ Yes | ❌ No | ⚠️ Some models | ✅ Full |
| OpenRouter | ✅ Yes | ⚠️ Depends on model | ✅ Yes | ❌ No | ⚠️ Depends | ✅ Full |
| Azure OpenAI | ✅ Yes | ✅ Yes (unused) | ✅ Yes | ✅ o1/o3 | ✅ Yes | ✅ Full |
| AWS Bedrock | ✅ Yes | ⚠️ Limited | ✅ Yes | ❌ No | ⚠️ Some models | ✅ Full |

*Gemini schema fixes: `models.py:625-642` - Special handling for Gemini's JSON schema restrictions

**Provider-Specific Workarounds**:

1. **Gemini JSON Schema Fixes** (`models.py:625-642`):
```python
# Gemini has issues with $defs, $ref, additionalProperties
if "response_format" in kwrgs and model.startswith("gemini/"):
    kwrgs["response_format"]["json_schema"] = ChatGoogle("")._fix_gemini_schema(
        kwrgs["response_format"]["json_schema"]
    )

# Gemini wraps JSON in markdown code blocks
if self.provider == "gemini" and isinstance(msg.content, str):
    cleaned = browser_use_monkeypatch.gemini_clean_and_conform(msg.content)
    if cleaned:
        msg.content = cleaned
```

2. **Anthropic Tool Call Fixes** (`models.py:62`):
```python
litellm.modify_params = True  # Helps fix anthropic tool calls by browser-use
```

3. **API Key Round-Robin** (`models.py:200-214`):
```python
# Support multiple API keys for rate limit management
# API_KEY_OPENAI="key1,key2,key3" rotates through keys
if "," in key:
    api_keys = [k.strip() for k in key.split(",") if k.strip()]
    api_keys_round_robin[service] = api_keys_round_robin.get(service, -1) + 1
    key = api_keys[api_keys_round_robin[service] % len(api_keys)]
```

**Provider Selection**:

At runtime, provider selection is explicit via `ModelConfig`:

```python
@dataclass
class ModelConfig:
    type: ModelType  # CHAT or EMBEDDING
    provider: str    # "openai", "anthropic", etc.
    name: str        # "gpt-4", "claude-3-opus", etc.
    api_base: str = ""
    ctx_length: int = 0
    limit_requests: int = 0
    limit_input: int = 0
    limit_output: int = 0
    vision: bool = False
    kwargs: dict = field(default_factory=dict)
```

Agent config specifies separate models for different roles:

```python
@dataclass
class AgentConfig:
    chat_model: ModelConfig       # Main reasoning model
    utility_model: ModelConfig    # For summarization, memory, etc.
    embeddings_model: ModelConfig # For vector memory
    browser_model: ModelConfig    # For browser automation
```

This allows mixing providers:
- OpenAI GPT-4 for main reasoning
- Claude for utility tasks
- Local Ollama for embeddings
- Groq for browser automation

**Provider Graceful Degradation**:

| Feature | Degradation Strategy |
|---------|---------------------|
| Function calling not supported | ✅ Already using prompt-based tools - no degradation |
| Streaming not supported | ✅ Falls back to non-streaming via LiteLLM |
| Vision not supported | ⚠️ Agent proceeds anyway - tool execution may fail |
| Reasoning channel not available | ✅ Falls back to tag-based parsing (`<think>` tags) |
| Context window exceeded | ✅ Hierarchical compression in history manager |
| Rate limits hit | ✅ Built-in rate limiter with wait + callback |
| Transient errors (5xx, 429, 408) | ✅ Automatic retry with exponential backoff (max 2 retries) |

**Universal vs Provider-Native**:

Agent Zero uses **universal message types** internally (LangChain `BaseMessage`), never provider-native types. The conversion happens at the LiteLLM boundary:

```
Internal: LangChain BaseMessage (SystemMessage, HumanMessage, AIMessage)
    ↓
LiteLLMChatWrapper._convert_messages(): Convert to OpenAI-style dicts
    ↓
LiteLLM: Convert to provider-specific format (e.g., Anthropic Message API)
    ↓
Provider: Native format
    ↓
LiteLLM: Normalize response to OpenAI format
    ↓
LiteLLMChatWrapper: Parse into ChatChunk
    ↓
Agent: Process as universal types
```

This ensures no provider-specific code leaks into the agent logic.

## Code References

### Message Protocol & Streaming
- `models.py:1-920` - All LLM integration code
- `models.py:292-455` - LiteLLMChatWrapper (main abstraction)
- `models.py:456-563` - unified_call() streaming implementation
- `models.py:89-194` - ChatGenerationResult (reasoning separation)
- `models.py:803-827` - _parse_chunk() (extract deltas from provider response)
- `python/helpers/call_llm.py:18-68` - Utility LLM call wrapper

### Tool Call Encoding & Parsing
- `python/helpers/extract_tools.py:9-36` - JSON parsing (dirty JSON)
- `agent.py:782-865` - process_tools() (tool execution flow)
- `agent.py:874-896` - handle_response_stream() (real-time tool detection)
- `prompts/agent.system.tools.py:8-30` - Tool schema generator
- `python/extensions/system_prompt/_10_system_prompt.py:38-42` - Tool prompt assembly

### System Prompt & Context
- `agent.py:484-533` - prepare_prompt() (full prompt assembly)
- `python/extensions/system_prompt/_10_system_prompt.py:9-83` - System prompt extensions
- `python/helpers/history.py:294-453` - History class (hierarchical compression)
- `python/helpers/history.py:364-446` - compress() (memory management)

### Provider Abstraction
- `python/helpers/providers.py:11-101` - ProviderManager (YAML config loader)
- `models.py:831-843` - _adjust_call_args() (provider-specific fixes)
- `models.py:846-891` - _merge_provider_defaults() (inject provider config)
- `conf/model_providers.yaml` - Provider configuration

### Agentic Primitives
- `agent.py:564-598` - handle_intervention() (HITL)
- `agent.py:318-326` - InterventionException (control flow)
- `agent.py:356-483` - monologue() (main loop + state machine)
- `agent.py:535-563` - handle_critical_exception() (error handling)

### Rate Limiting & Retry
- `python/helpers/rate_limiter.py` - RateLimiter class (not shown in excerpts)
- `models.py:228-250` - _is_transient_litellm_error() (retry logic)
- `models.py:253-272` - apply_rate_limiter() (token-aware throttling)
- `models.py:498-562` - Retry loop in unified_call()

## Implications for New Framework

### Positive Patterns

1. **LiteLLM as Universal Adapter**
   - **Rationale**: Agent Zero supports 100+ providers with ~900 lines of wrapper code
   - **Implementation**: Single `LiteLLMChatWrapper` class handles all providers
   - **Benefit**: Zero maintenance burden for provider-specific quirks
   - **Recommendation**: Strongly consider LiteLLM (or similar gateway) over custom adapters

2. **Dual-Channel Streaming (Response + Reasoning)**
   - **Rationale**: Separates model reasoning from user-facing output
   - **Implementation**: `ChatGenerationResult` accumulates both channels separately
   - **Benefit**: Can hide reasoning, log separately, or use for debugging
   - **Recommendation**: Adopt this pattern - reasoning visibility is valuable for agentic systems

3. **Dirty JSON Parsing for Robustness**
   - **Rationale**: LLMs often output malformed JSON (trailing commas, unescaped quotes, etc.)
   - **Implementation**: `DirtyJson.parse_string()` handles common JSON errors
   - **Benefit**: Reduces failed tool calls due to formatting errors
   - **Recommendation**: Use tolerant parsing, but also provide LLM feedback on format errors

4. **Extension System for Streaming Events**
   - **Rationale**: Different consumers need different streaming behavior (masking, logging, UI)
   - **Implementation**: Extensions hook into `*_stream_chunk` events to modify streams
   - **Benefit**: Core streaming logic remains simple, extensions add features
   - **Recommendation**: Adopt event-based streaming with subscriber pattern

5. **Real-Time Tool Detection from Partial JSON**
   - **Rationale**: Enables UI feedback before LLM completes response
   - **Implementation**: Speculatively parse JSON during streaming
   - **Benefit**: Better UX - user sees "Calling tool X" immediately
   - **Recommendation**: Implement this for long-running tool calls

6. **Unified `unified_call()` API**
   - **Rationale**: Single method handles streaming, non-streaming, callbacks, rate limiting, retry
   - **Implementation**: `async def unified_call(messages, response_callback=None, reasoning_callback=None, ...)`
   - **Benefit**: Simple interface, no need to switch between stream/non-stream methods
   - **Recommendation**: Consolidate streaming variants into one API

7. **Provider Configuration as Data**
   - **Rationale**: Non-developers can add providers via YAML without code changes
   - **Implementation**: `conf/model_providers.yaml` loaded by ProviderManager
   - **Benefit**: Extensibility without recompilation
   - **Recommendation**: Externalize provider config, especially for OSS projects

### Considerations

1. **Prompt-Based Tool Encoding Trade-off**
   - **Context**: Agent Zero sacrifices native function calling for compatibility
   - **Decision Point**: Will your framework prioritize:
     - **Compatibility** (support all LLMs)? → Use prompt-based encoding
     - **Reliability** (minimize parsing errors)? → Use native function calling with fallback
   - **Hybrid Approach**: Detect provider capabilities, use native function calling when available, fall back to prompts
   - **Recommendation**: Implement both, prefer native function calling where available

2. **No Parallel Tool Calling**
   - **Context**: JSON format expects `{"tool_name": "...", "tool_args": {...}}` (single tool)
   - **Limitation**: Cannot call multiple tools in one response
   - **Impact**: Multi-step tasks require multiple LLM calls
   - **Recommendation**: If using prompt-based encoding, support array format: `[{"tool_name": "A", ...}, {"tool_name": "B", ...}]`

3. **Exception-Based Control Flow**
   - **Context**: `InterventionException` used for normal flow (user messages during execution)
   - **Anti-Pattern**: Exceptions are for exceptional conditions, not control flow
   - **Impact**: Confusing stack traces, harder debugging
   - **Recommendation**: Use return values or state flags for intervention; reserve exceptions for errors

4. **Tool Call Attribution Missing**
   - **Context**: No `tool_call_id` tracking in prompt-based tools
   - **Limitation**: Cannot match tool results to specific calls in conversation
   - **Impact**: Ambiguous history if multiple tool calls of same type
   - **Recommendation**: If using prompt-based tools, inject unique IDs into tool requests during parsing

5. **No Scratchpad / Working Memory**
   - **Context**: Agent Zero lacks persistent reasoning buffer
   - **Limitation**: Model must fit all reasoning in single response
   - **Impact**: Complex reasoning may be truncated by output limits
   - **Recommendation**: Add scratchpad primitive - separate tool for writing notes that persist across iterations

6. **Rate Limiter Token Approximation**
   - **Context**: Uses heuristic token counting, not provider's tokenizer
   - **Limitation**: Can under/over estimate, hit rate limits unexpectedly
   - **Impact**: Wasted API calls when underestimating, unnecessary throttling when overestimating
   - **Recommendation**: Use provider-specific tokenizers (tiktoken for OpenAI, anthropic tokenizer, etc.)

## Anti-Patterns Observed

### Critical Issues to Avoid

1. **Dead Code in Tool Call Conversion**
   - **Location**: `models.py:333-362` - Tool call conversion in `_convert_messages()`
   - **Issue**: Code exists to convert LangChain tool calls to LiteLLM format, but is NEVER USED
   - **Evidence**: Agent never populates `tool_calls` attribute on messages; only uses text parsing
   - **Impact**: Misleading codebase - appears to support native function calling but doesn't
   - **Recommendation**: Either remove dead code OR implement actual function calling support

2. **Global Mutable State**
   - **Location**: `models.py:197-198`
   ```python
   rate_limiters: dict[str, RateLimiter] = {}
   api_keys_round_robin: dict[str, int] = {}
   ```
   - **Issue**: Module-level globals prevent isolated testing, concurrent instances
   - **Impact**: Cannot run multiple agents with different rate limits; testing requires state reset
   - **Recommendation**: Move to instance attributes or use dependency injection

3. **Nested Event Loop with `nest_asyncio`**
   - **Location**: `agent.py:4` and `models.py:284-289`
   - **Issue**: Allows nested `asyncio.run()` calls, which masks event loop issues
   - **Impact**: Hides deadlocks, makes debugging async issues harder
   - **Recommendation**: Restructure to avoid nesting; use proper async/await patterns

4. **No Schema Validation on Tool Arguments**
   - **Location**: Tool execution in `agent.py:835` - `await tool.execute(**tool_args)`
   - **Issue**: Arguments from JSON are passed directly to Python functions without validation
   - **Impact**: Type errors, missing required args, or malicious input can crash tools
   - **Recommendation**: Use Pydantic models for tool arguments with validation before execution

5. **Lossy Reasoning Channel**
   - **Location**: `models.py:89-194` - Reasoning extracted but not persisted
   - **Issue**: Reasoning is logged/streamed but never added to conversation history
   - **Impact**: Model loses its own reasoning in multi-turn conversations
   - **Recommendation**: Optionally persist reasoning to history (with compression) for long-term context

6. **Approximate Token Counting**
   - **Location**: `python/helpers/tokens.py` (not shown) - Uses heuristic `len(text) / 4`
   - **Issue**: Different tokenizers have different token counts for same text
   - **Impact**: History compression may be too aggressive or too lenient
   - **Recommendation**: Use provider-specific tokenizers for accurate counts

7. **Dirty JSON Without Schema Enforcement**
   - **Location**: `python/helpers/extract_tools.py:16` - `DirtyJson.parse_string()`
   - **Issue**: Tolerates malformed JSON but doesn't validate against expected schema
   - **Impact**: Silent failures when LLM outputs wrong shape (e.g., missing `tool_name` key)
   - **Recommendation**: Validate parsed JSON against schema; provide feedback to LLM on schema violations

8. **No Timeout on Tool Execution**
   - **Location**: `agent.py:835` - Tool execution has no timeout
   - **Issue**: Long-running or hung tools can freeze agent indefinitely
   - **Impact**: Poor UX, no way to recover from tool hangs
   - **Recommendation**: Wrap tool execution in `asyncio.wait_for()` with configurable timeout

9. **Extension System with String-Based Event Names**
   - **Location**: `agent.py:921` - `await self.call_extensions("monologue_start", ...)`
   - **Issue**: No compile-time checking of extension point names
   - **Impact**: Typos cause silent failures (extension not called)
   - **Recommendation**: Use enum or constants for extension points

10. **Browser-Use Monkeypatching**
    - **Location**: `models.py:60`, `python/helpers/browser_use_monkeypatch.py`
    - **Issue**: Runtime monkeypatching of third-party library to fix Gemini issues
    - **Impact**: Brittle, breaks when library updates, hard to debug
    - **Recommendation**: Contribute fixes upstream or use adapter pattern instead of monkeypatching

## Recommendations for New Framework

### High Priority

1. **Use LiteLLM or Similar Gateway**
   - Avoid building custom provider adapters
   - LiteLLM handles 100+ providers, well-maintained, OSS
   - Alternative: Vercel AI SDK (TypeScript), LlamaIndex (Python)

2. **Implement Hybrid Tool Encoding**
   - Detect provider capabilities at runtime
   - Prefer native function calling (more reliable)
   - Fall back to prompt-based encoding (more compatible)
   - Example decision tree:
     ```
     if provider.supports_function_calling and model.supports_function_calling:
         use native function calling API
     else:
         use prompt-based encoding with JSON schema
     ```

3. **Separate Reasoning from Response**
   - Dual-channel streaming is highly valuable
   - Persist reasoning optionally (configurably)
   - Allow UI to show/hide reasoning
   - Use for debugging and prompt engineering

4. **Implement Proper Tool Call Attribution**
   - Generate unique `tool_call_id` for each tool request
   - Track IDs through execution and result matching
   - Enables multi-turn tool conversations
   - Required for native function calling anyway

5. **Add Scratchpad Primitive**
   - Dedicated tool for model to write persistent notes
   - Notes survive across iterations
   - Compressed separately from main history
   - Enables complex multi-step reasoning

### Medium Priority

6. **Provider-Specific Tokenizers**
   - Use `tiktoken` for OpenAI
   - Use Anthropic's tokenizer for Claude
   - Fallback to heuristic for unknown providers
   - Critical for accurate rate limiting and history compression

7. **Schema Validation on Tool Arguments**
   - Use Pydantic V2 for tool input validation
   - Auto-generate JSON Schema from Pydantic models
   - Validate parsed JSON before execution
   - Return validation errors to LLM for self-correction

8. **Timeout and Cancellation for Tool Execution**
   - Wrap tool calls in `asyncio.wait_for(timeout=X)`
   - Allow user to cancel in-flight tool calls
   - Implement progressive timeout (warn at 80%, kill at 100%)

9. **Event-Based Streaming with Strong Typing**
   - Use enum for event types (compile-time safety)
   - Use Pydantic models for event payloads
   - Implement pub/sub for extensibility
   - Example:
     ```python
     class StreamEventType(Enum):
         REASONING_CHUNK = "reasoning_chunk"
         RESPONSE_CHUNK = "response_chunk"

     class StreamEvent(BaseModel):
         type: StreamEventType
         delta: str
         accumulated: str
         metadata: dict
     ```

10. **Graceful Degradation Matrix**
    - Document which features require which provider capabilities
    - Provide clear error messages when feature unsupported
    - Auto-disable features based on provider
    - Example: "Vision tools disabled - model X doesn't support images"

### Low Priority

11. **Real-Time Tool Detection**
    - Parse partial JSON during streaming
    - Show "Calling tool X..." immediately
    - Nice-to-have for UX, not critical

12. **Configuration as Data**
    - Externalize provider config to YAML/JSON
    - Allow runtime provider addition
    - Good for extensibility, not critical for MVP

13. **API Key Round-Robin**
    - Support multiple keys per provider
    - Rotate through keys for rate limit management
    - Advanced feature, not needed initially

## Conclusion

Agent Zero demonstrates a **pragmatic, compatibility-first approach** to LLM integration. By delegating provider abstraction to LiteLLM and using prompt-based tool encoding, it achieves universal LLM support with minimal code.

**Key Strengths**:
- Universal provider support (100+ LLMs)
- Sophisticated streaming with reasoning separation
- Real-time tool detection from partial responses
- Clean extension system for customization
- Robust error handling with retry and self-correction

**Key Weaknesses**:
- Sacrifices reliability of native function calling for compatibility
- No parallel tool calling support
- Missing tool call attribution (no IDs)
- No scratchpad/working memory primitive
- Approximate token counting
- Global mutable state
- Dead code misleads about function calling support

**For a New Framework**:

**Adopt** Agent Zero's LiteLLM-based provider abstraction, dual-channel streaming, dirty JSON parsing, extension system architecture, and retry logic.

**Avoid** its prompt-only tool encoding (support both native and prompt-based), exception-based control flow, global state, and lack of schema validation.

**Enhance** with hybrid tool encoding (native + fallback), proper tool call attribution, scratchpad primitive, provider-specific tokenizers, and strong typing throughout.

The ideal approach is a **hybrid model**: use Agent Zero's universal gateway pattern (via LiteLLM) but layer native function calling support on top, falling back to prompt-based encoding only when necessary. This combines maximum compatibility with maximum reliability.
