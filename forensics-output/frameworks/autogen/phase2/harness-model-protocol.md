# Harness-Model Protocol Analysis: AutoGen

## Summary

- **Key Finding 1**: AutoGen uses a **universal internal message type** (`LLMMessage` union) with provider-specific adapters that transform to native API formats at the boundary, avoiding deep provider coupling
- **Key Finding 2**: **Modular transformation pipeline** introduced in PR #6063 uses composable transformer functions to convert messages, enabling model-specific overrides without forking entire clients
- **Key Finding 3**: **Streaming accumulates tool calls incrementally** with proper state management for partial JSON chunks, supporting both text deltas and complete CreateResult at stream end
- **Classification**: Unified message abstraction with pluggable transformation layer and native SDK clients (OpenAI, Anthropic)

## Detailed Analysis

### Message Protocol

**Wire Format Family**: Hybrid - OpenAI-compatible via transformation + Native Anthropic

**Providers Supported**:
- OpenAI (native via `openai` SDK)
- Azure OpenAI (via `openai` SDK)
- Anthropic/Claude (native via `anthropic` SDK, also via OpenAI-compatible endpoint)
- Gemini (via OpenAI-compatible endpoint)
- Ollama (via OpenAI-compatible endpoint)
- Custom models (via OpenAI-compatible base_url)

**Abstraction Strategy**: Universal internal type with modular transformation layer

**Core Message Types** (`autogen_core.models._types`):
```python
# Universal internal types (Pydantic BaseModel)
@dataclass
class SystemMessage(BaseModel):
    content: str
    type: Literal["SystemMessage"] = "SystemMessage"

@dataclass
class UserMessage(BaseModel):
    content: Union[str, List[Union[str, Image]]]  # Text or multimodal
    source: str  # Agent name
    type: Literal["UserMessage"] = "UserMessage"

@dataclass
class AssistantMessage(BaseModel):
    content: Union[str, List[FunctionCall]]  # Text or tool calls
    thought: str | None = None  # Reasoning trace (for R1, Claude thinking)
    source: str
    type: Literal["AssistantMessage"] = "AssistantMessage"

@dataclass
class FunctionExecutionResultMessage(BaseModel):
    content: List[FunctionExecutionResult]
    type: Literal["FunctionExecutionResultMessage"] = "FunctionExecutionResultMessage"

# Discriminated union
LLMMessage = Annotated[
    Union[SystemMessage, UserMessage, AssistantMessage, FunctionExecutionResultMessage],
    Field(discriminator="type")
]
```

**AgentChat Higher-Level Messages** (`autogen_agentchat.messages`):
```python
# Agent-to-agent communication (extends BaseChatMessage)
class TextMessage(BaseTextChatMessage): ...
class MultiModalMessage(BaseChatMessage): ...
class ToolCallSummaryMessage(BaseTextChatMessage): ...
class HandoffMessage(BaseTextChatMessage): ...  # Handoff to another agent
class StopMessage(BaseTextChatMessage): ...

# Structured messages with Pydantic models
class StructuredMessage(BaseChatMessage, Generic[StructuredContentType]): ...
```

**Message Transformation Pipeline** (OpenAI client):

Located in `autogen_ext.models.openai._message_transform.py`:
```python
# Modular transformer functions composed into pipelines
def _set_role(role: str):
    return lambda msg, ctx: {"role": role}

def _set_content_direct(message, context):
    return {"content": message.content}

def _set_multimodal_content(message, context):
    parts = []
    for part in message.content:
        if isinstance(part, str):
            parts.append({"type": "text", "text": part})
        elif isinstance(part, Image):
            parts.append(part.to_openai_format())
    return {"content": parts}

# Conditional routing based on message content
user_transformer = build_conditional_transformer_func(
    funcs_map={
        "text": [_set_role("user"), _set_prepend_text_content],
        "multimodal": [_set_role("user"), _set_multimodal_content],
    },
    condition_func=lambda msg, ctx: "text" if isinstance(msg.content, str) else "multimodal"
)

# Model-specific overrides (Gemini, Claude, Mistral)
register_transformer("openai", "gemini-1.5-pro", GEMINI_TRANSFORMER_MAP)
register_transformer("openai", "claude-3-sonnet", CLAUDE_TRANSFORMER_MAP)
```

**Anthropic Client** transforms directly to native format:
```python
def user_message_to_anthropic(message: UserMessage) -> MessageParam:
    if isinstance(message.content, str):
        return {"role": "user", "content": message.content}
    else:
        blocks = []
        for part in message.content:
            if isinstance(part, str):
                blocks.append(TextBlockParam(type="text", text=part))
            elif isinstance(part, Image):
                blocks.append(ImageBlockParam(
                    type="image",
                    source=Base64ImageSourceParam(
                        type="base64",
                        media_type=get_mime_type_from_image(part),
                        data=part.to_base64()
                    )
                ))
        return {"role": "user", "content": blocks}

# Tool results map to user role with tool_result content type
def tool_message_to_anthropic(message: FunctionExecutionResultMessage):
    return [{
        "role": "user",  # Anthropic uses user role for tool results
        "content": [
            ToolResultBlockParam(
                type="tool_result",
                tool_use_id=result.call_id,
                content=result.content
            )
            for result in message.content
        ]
    }]
```

### Tool Call Encoding

**Request Method**: Native function calling API for both OpenAI and Anthropic

**Schema Transmission** (OpenAI):
```python
def convert_tools(tools: Sequence[Tool | ToolSchema]) -> List[ChatCompletionToolParam]:
    result = []
    for tool in tools:
        tool_schema = tool.schema if isinstance(tool, Tool) else tool
        result.append({
            "type": "function",
            "function": {
                "name": tool_schema["name"],
                "description": tool_schema.get("description", ""),
                "parameters": tool_schema.get("parameters", {}),
                "strict": tool_schema.get("strict", False)  # Structured output mode
            }
        })
    return result

# Sent as:
# messages=[...], tools=[...], tool_choice="auto"|"required"|"none"|{"type": "function", "function": {"name": "..."}}
```

**Schema Transmission** (Anthropic):
```python
def convert_tools(tools: Sequence[Tool | ToolSchema]) -> List[ToolParam]:
    result = []
    for tool in tools:
        tool_schema = tool.schema if isinstance(tool, Tool) else tool
        tool_params = {
            "type": "object",
            "properties": tool_schema["parameters"]["properties"],
            "required": tool_schema["parameters"].get("required", [])
        }
        result.append(ToolParam(
            name=tool_schema["name"],
            input_schema=tool_params,
            description=tool_schema.get("description", "")
        ))
    return result

# tool_choice mapping: "auto" -> {"type": "auto"}, "required" -> {"type": "any"}, Tool -> {"type": "tool", "name": "..."}
```

**Response Parsing** (OpenAI):
```python
# Non-streaming
if choice.message.tool_calls:
    content = [
        FunctionCall(
            id=tool_call.id,
            arguments=tool_call.function.arguments,  # JSON string
            name=normalize_name(tool_call.function.name)
        )
        for tool_call in choice.message.tool_calls
    ]
    finish_reason = "function_calls"

# Streaming - accumulates tool calls by index
full_tool_calls: Dict[int, FunctionCall] = {}
for chunk in stream:
    if choice.delta.tool_calls:
        for tool_call_chunk in choice.delta.tool_calls:
            idx = tool_call_chunk.index
            if idx not in full_tool_calls:
                full_tool_calls[idx] = FunctionCall(id="", arguments="", name="")

            if tool_call_chunk.id:
                full_tool_calls[idx].id += tool_call_chunk.id
            if tool_call_chunk.function.name:
                full_tool_calls[idx].name += tool_call_chunk.function.name
            if tool_call_chunk.function.arguments:
                full_tool_calls[idx].arguments += tool_call_chunk.function.arguments

content = list(full_tool_calls.values())
```

**Response Parsing** (Anthropic):
```python
# Non-streaming
tool_uses = [block for block in result.content if getattr(block, "type", None) == "tool_use"]
if tool_uses:
    content = [
        FunctionCall(
            id=tool_use.id,
            name=normalize_name(tool_use.name),
            arguments=json.dumps(tool_use.input) if isinstance(tool_use.input, dict) else str(tool_use.input)
        )
        for tool_use in tool_uses
    ]

# Streaming - accumulates partial JSON
tool_calls: Dict[str, Dict[str, Any]] = {}
current_tool_id: Optional[str] = None

if chunk.type == "content_block_start" and chunk.content_block.type == "tool_use":
    current_tool_id = chunk.content_block.id
    tool_calls[current_tool_id] = {
        "id": chunk.content_block.id,
        "name": chunk.content_block.name,
        "input": json.dumps(chunk.content_block.input),
        "partial_json": ""
    }
elif chunk.type == "content_block_delta" and chunk.delta.type == "input_json_delta":
    tool_calls[current_tool_id]["partial_json"] += chunk.delta.partial_json
```

**Tool Choice Support**:

| Parameter | OpenAI | Anthropic | Notes |
|-----------|--------|-----------|-------|
| `"auto"` | `"auto"` | `{"type": "auto"}` | Model chooses |
| `"required"` | `"required"` | `{"type": "any"}` | Must use a tool |
| `"none"` | `"none"` | Not sent | No tools |
| `Tool` object | `{"type": "function", "function": {"name": "..."}}` | `{"type": "tool", "name": "..."}` | Force specific tool |

**Tool Result Attribution**:
```python
# OpenAI: tool role with tool_call_id
ChatCompletionToolMessageParam(
    content=result.content,
    role="tool",
    tool_call_id=result.call_id  # Matches FunctionCall.id
)

# Anthropic: user role with tool_result content block
{
    "role": "user",
    "content": [
        {
            "type": "tool_result",
            "tool_use_id": result.call_id,  # Matches ToolUseBlock.id
            "content": result.content
        }
    ]
}
```

### Streaming Implementation

**Protocol**: SSE (Server-Sent Events) via native SDK async generators

**OpenAI Streaming**:
```python
async def create_stream(self, messages, tools, ...):
    stream = await self._client.chat.completions.create(
        messages=oai_messages,
        stream=True,
        tools=tools,
        **create_args
    )

    # Accumulator state
    content_deltas: List[str] = []
    thought_deltas: List[str] = []  # For reasoning models (R1, DeepSeek)
    full_tool_calls: Dict[int, FunctionCall] = {}
    stop_reason = None

    async for chunk in stream:
        choice = chunk.choices[0]

        # Text content
        if choice.delta.content:
            content_deltas.append(choice.delta.content)
            yield choice.delta.content  # Stream text immediately

        # Reasoning content (R1 models)
        if choice.delta.model_extra and "reasoning_content" in choice.delta.model_extra:
            reasoning = choice.delta.model_extra["reasoning_content"]
            thought_deltas.append(reasoning)
            yield reasoning

        # Tool calls (accumulated by index)
        if choice.delta.tool_calls:
            for tool_call_chunk in choice.delta.tool_calls:
                idx = tool_call_chunk.index
                if idx not in full_tool_calls:
                    full_tool_calls[idx] = FunctionCall(id="", arguments="", name="")

                full_tool_calls[idx].id += tool_call_chunk.id or ""
                full_tool_calls[idx].name += tool_call_chunk.function.name or ""
                full_tool_calls[idx].arguments += tool_call_chunk.function.arguments or ""

        stop_reason = choice.finish_reason or stop_reason

    # Final result
    if full_tool_calls:
        content = list(full_tool_calls.values())
        thought = "".join(content_deltas) if content_deltas else None
    else:
        content = "".join(content_deltas)
        thought = "".join(thought_deltas) if thought_deltas else None

    yield CreateResult(finish_reason=stop_reason, content=content, thought=thought, ...)
```

**Anthropic Streaming**:
```python
async def create_stream(self, messages, tools, ...):
    stream = await self._client.messages.create(
        messages=anthropic_messages,
        stream=True,
        tools=tools,
        **request_args
    )

    # Accumulator state
    text_content: List[str] = []
    thinking_content: List[str] = []  # Extended thinking mode
    tool_calls: Dict[str, Dict[str, Any]] = {}
    current_tool_id: Optional[str] = None

    async for chunk in stream:
        # Tool use start
        if chunk.type == "content_block_start" and chunk.content_block.type == "tool_use":
            current_tool_id = chunk.content_block.id
            tool_calls[current_tool_id] = {
                "id": chunk.content_block.id,
                "name": chunk.content_block.name,
                "input": json.dumps(chunk.content_block.input),
                "partial_json": ""
            }

        # Thinking block
        elif chunk.type == "content_block_start" and chunk.content_block.type == "thinking":
            pass  # Start tracking thinking

        # Content deltas
        elif chunk.type == "content_block_delta":
            if chunk.delta.type == "text_delta":
                text_content.append(chunk.delta.text)
                yield chunk.delta.text  # Stream immediately

            elif chunk.delta.type == "thinking_delta":
                thinking_content.append(chunk.delta.thinking)
                yield chunk.delta.thinking  # Stream thinking

            elif chunk.delta.type == "input_json_delta":
                # Accumulate partial JSON for tool input
                tool_calls[current_tool_id]["partial_json"] += chunk.delta.partial_json

        # Block end
        elif chunk.type == "content_block_stop":
            if current_tool_id and tool_calls[current_tool_id]["partial_json"]:
                # Use accumulated partial JSON as final input
                tool_calls[current_tool_id]["input"] = tool_calls[current_tool_id]["partial_json"]
            current_tool_id = None

    # Final result
    if tool_calls:
        content = [FunctionCall(**tool_data) for tool_data in tool_calls.values()]
        thought = "".join(thinking_content) or "".join(text_content) or None
    else:
        content = "".join(text_content)
        thought = "".join(thinking_content) if thinking_content else None

    yield CreateResult(finish_reason=stop_reason, content=content, thought=thought, ...)
```

**Partial Tool Call Handling**: Yes, both providers accumulate properly
- OpenAI: Accumulates by `index`, appending `id`, `name`, `arguments` deltas
- Anthropic: Accumulates `partial_json` field for each tool, replaces final `input`

**Event Types Emitted**:

| Event | When | Data |
|-------|------|------|
| `LLMStreamStartEvent` | First chunk received | `messages` (input) |
| `str` chunks | During streaming | Text content or thinking deltas |
| `CreateResult` | Stream end | Final aggregated result with `finish_reason`, `content`, `usage`, `thought` |
| `LLMStreamEndEvent` | Stream end (logged) | `response`, `prompt_tokens`, `completion_tokens` |

**Empty Chunk Handling**:
```python
# OpenAI handles empty chunks gracefully
if len(chunk.choices) == 0:
    empty_chunk_count += 1
    if empty_chunk_count >= 10:
        warnings.warn("Received more than 10 consecutive empty chunks")
    continue
```

### Agentic Primitives

**System Prompt Assembly**:

OpenAI:
```python
# System messages passed directly in messages list
oai_messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "..."}
]

# Multiple system messages merged if model doesn't support them
if not model_info.get("multiple_system_messages", False):
    # Merge continuous system messages into one
    system_content = "\n".join([msg.content for msg in messages if isinstance(msg, SystemMessage)])
    messages = [SystemMessage(content=system_content)] + [m for m in messages if not isinstance(m, SystemMessage)]
```

Anthropic:
```python
# System message separate from messages array
request_args = {
    "model": "claude-3-sonnet",
    "system": "You are a helpful assistant.",  # Single system string
    "messages": [{"role": "user", "content": "..."}]
}

# Multiple system messages merged into single string
system_messages = [m for m in messages if isinstance(m, SystemMessage)]
system_content = "\n".join([m.content for m in system_messages])
```

**Scratchpad / Working Memory**:

Thought field for reasoning traces:
```python
@dataclass
class AssistantMessage(BaseModel):
    content: Union[str, List[FunctionCall]]
    thought: str | None = None  # Reasoning/scratchpad content

@dataclass
class CreateResult(BaseModel):
    content: Union[str, List[FunctionCall]]
    thought: Optional[str] = None  # Reasoning trace

# R1 models: Extract thinking from <think>...</think> tags
if ModelFamily.R1 and thought is None:
    thought, content = parse_r1_content(content)

# Anthropic extended thinking mode
request_args["thinking"] = {"type": "enabled", "budget_tokens": 1000}

# Thinking blocks in stream
if chunk.type == "content_block_delta" and chunk.delta.type == "thinking_delta":
    thought_deltas.append(chunk.delta.thinking)
```

**Interrupt / Human-in-the-Loop**:

Not directly in harness-model protocol, but supported at higher level:
```python
# AgentChat level
class UserInputRequestedEvent(BaseAgentEvent):
    request_id: str
    content: Literal[""] = ""

# Teams can interrupt and request human input
class HandoffMessage(BaseTextChatMessage):
    target: str  # Agent to hand off to
    context: List[LLMMessage] = []
```

**Conversation State Machine**:

Multi-turn conversation reconstructed via message list:
```python
# Each create() call receives full conversation history
messages = [
    SystemMessage(content="You are an assistant."),
    UserMessage(content="What's the weather?", source="user"),
    AssistantMessage(content=[FunctionCall(name="get_weather", ...)], source="assistant"),
    FunctionExecutionResultMessage(content=[FunctionExecutionResult(content="Sunny", call_id="1")]),
    # Next turn...
]

# Stateless API - full context each time
result = await client.create(messages=messages, tools=tools)
```

**Finish Reason Normalization**:
```python
def normalize_stop_reason(stop_reason: str | None) -> FinishReasons:
    # OpenAI
    if stop_reason == "stop": return "stop"
    elif stop_reason == "length": return "length"
    elif stop_reason == "tool_calls": return "function_calls"
    elif stop_reason == "content_filter": return "content_filter"

    # Anthropic
    elif stop_reason == "end_turn": return "stop"
    elif stop_reason == "max_tokens": return "length"
    elif stop_reason == "tool_use": return "function_calls"

    return "unknown"
```

### Provider Abstraction

**ChatCompletionClient Protocol** (`autogen_core.models`):
```python
class ChatCompletionClient(ComponentBase[BaseModel], ABC):
    @abstractmethod
    async def create(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[Tool | ToolSchema] = [],
        tool_choice: Tool | Literal["auto", "required", "none"] = "auto",
        json_output: Optional[bool | type[BaseModel]] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Optional[CancellationToken] = None,
    ) -> CreateResult: ...

    @abstractmethod
    def create_stream(...) -> AsyncGenerator[Union[str, CreateResult], None]: ...

    @abstractmethod
    def count_tokens(self, messages, tools) -> int: ...

    @abstractmethod
    def remaining_tokens(self, messages, tools) -> int: ...

    @property
    @abstractmethod
    def model_info(self) -> ModelInfo: ...
```

**Provider Implementations**:

| Provider | Location | Base URL | Notes |
|----------|----------|----------|-------|
| OpenAI | `autogen_ext.models.openai.OpenAIChatCompletionClient` | `https://api.openai.com/v1` | Native SDK |
| Azure OpenAI | `autogen_ext.models.openai.AzureOpenAIChatCompletionClient` | Azure endpoint | Native SDK with AAD auth |
| Anthropic | `autogen_ext.models.anthropic.AnthropicChatCompletionClient` | `https://api.anthropic.com` | Native SDK |
| Anthropic Bedrock | `autogen_ext.models.anthropic.AnthropicBedrockChatCompletionClient` | AWS Bedrock | Native SDK with AWS credentials |
| Gemini | `OpenAIChatCompletionClient(base_url="https://generativelanguage.googleapis.com/v1beta/openai/")` | Google endpoint | OpenAI-compatible |
| Claude via OpenAI | `OpenAIChatCompletionClient(base_url="https://api.anthropic.com/v1/openai/")` | Anthropic OpenAI endpoint | OpenAI-compatible |
| Ollama | `OpenAIChatCompletionClient(base_url="http://localhost:11434/v1")` | Local | OpenAI-compatible |

**Model Info / Capabilities**:
```python
@dataclass
class ModelInfo(TypedDict, total=False):
    vision: Required[bool]  # Supports image input
    function_calling: Required[bool]  # Supports tools
    json_output: Required[bool]  # Supports {"type": "json_object"}
    family: Required[ModelFamily.ANY | str]  # gpt-4o, claude-3-sonnet, etc.
    structured_output: Required[bool]  # Supports Pydantic model schemas
    multiple_system_messages: Optional[bool]  # Multiple non-consecutive system messages

# Auto-detected from model name or explicitly provided
model_info = _model_info.get_info("gpt-4o")  # Auto-lookup
# Or: model_info=ModelInfo(vision=True, function_calling=True, ...)
```

**Feature Matrix**:

| Feature | OpenAI | Anthropic | Gemini (OAI) | Notes |
|---------|--------|-----------|--------------|-------|
| Text generation | ✅ | ✅ | ✅ | |
| Vision (images) | ✅ | ✅ | ✅ | |
| Function calling | ✅ | ✅ | ✅ | |
| Parallel tool calls | ✅ | ✅ | ✅ | Multiple tools in one turn |
| JSON mode | ✅ | ⚠️ | ✅ | Anthropic via prompt engineering |
| Structured output | ✅ | ❌ | ⚠️ | Pydantic schema -> strict JSON |
| Streaming | ✅ | ✅ | ✅ | |
| Streaming tool calls | ✅ | ✅ | ✅ | Partial JSON accumulation |
| Token counting | ✅ | ⚠️ | ⚠️ | OpenAI via tiktoken, others estimated |
| Thought/reasoning | ✅ | ✅ | ❌ | R1, Claude extended thinking |
| Multiple system msgs | ✅ | ❌ | ⚠️ | OpenAI yes, Anthropic merged |

**Graceful Degradation**:
```python
# Vision check
if self.model_info["vision"] is False:
    if any(isinstance(x, Image) for x in message.content):
        raise ValueError("Model does not support vision and image was provided")

# Function calling check
if self.model_info["function_calling"] is False and len(tools) > 0:
    raise ValueError("Model does not support function calling")

# JSON output check
if self.model_info["json_output"] is False and json_output is True:
    raise ValueError("Model does not support JSON output")

# Structured output check
if self.model_info["structured_output"] is False and isinstance(json_output, type):
    raise ValueError("Model does not support structured output")
```

**Token Counting**:
```python
# OpenAI: tiktoken-based
def count_tokens_openai(messages, model, tools):
    encoding = tiktoken.encoding_for_model(model)  # or cl100k_base
    num_tokens = 0

    # Message tokens
    for message in messages:
        num_tokens += 3  # Message overhead
        num_tokens += len(encoding.encode(message.content))
        if isinstance(message.content, list):
            for part in message.content:
                if isinstance(part, Image):
                    num_tokens += calculate_vision_tokens(part)  # Vision token estimation

    # Tool tokens
    for tool in tools:
        num_tokens += len(encoding.encode(tool.name))
        num_tokens += len(encoding.encode(tool.description))
        # + parameter schema tokens

    return num_tokens

# Anthropic: Approximation using cl100k_base
def count_tokens(messages, tools):
    encoding = tiktoken.get_encoding("cl100k_base")  # Approximation
    # Similar logic, less accurate for Claude-specific tokenization
```

## Code References

**Core Protocol**:
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-core/src/autogen_core/models/_model_client.py:209-301` - ChatCompletionClient interface
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-core/src/autogen_core/models/_types.py:10-128` - LLMMessage types and CreateResult

**OpenAI Client**:
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/openai/_openai_client.py:432-1177` - BaseOpenAIChatCompletionClient
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/openai/_openai_client.py:663-814` - create() method
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/openai/_openai_client.py:816-1081` - create_stream() method
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/openai/_openai_client.py:244-271` - convert_tools()
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/openai/_openai_client.py:274-296` - convert_tool_choice()

**Anthropic Client**:
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/anthropic/_anthropic_client.py:444-1174` - BaseAnthropicChatCompletionClient
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/anthropic/_anthropic_client.py:552-763` - create() method
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/anthropic/_anthropic_client.py:765-1058` - create_stream() method
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/anthropic/_anthropic_client.py:199-230` - user_message_to_anthropic()
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/anthropic/_anthropic_client.py:237-284` - assistant_message_to_anthropic()
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/anthropic/_anthropic_client.py:319-359` - convert_tools()

**Message Transformation**:
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/openai/_message_transform.py:1-561` - Modular transformation pipeline
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/openai/_message_transform.py:186-278` - Mini transformer functions
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-ext/src/autogen_ext/models/openai/_message_transform.py:450-520` - Transformer maps (base, Gemini, Claude, Mistral)

**AgentChat Messages**:
- `/Users/dgordon/my_projects/agent_framework_study/repos/autogen/python/packages/autogen-agentchat/src/autogen_agentchat/messages.py:26-693` - BaseChatMessage hierarchy

## Implications for New Framework

### Positive Patterns

1. **Universal internal message type**: Avoids provider lock-in, enables swapping models without changing agent code
2. **Modular transformation pipeline**: Composable functions allow model-specific tweaks without forking entire clients
3. **Thought field for reasoning**: First-class support for CoT/scratchpad enables reasoning model integration
4. **Streaming accumulation pattern**: Properly handles partial tool calls with index-based (OpenAI) or ID-based (Anthropic) accumulators
5. **ModelInfo capabilities**: Explicit feature matrix prevents runtime errors, enables graceful degradation
6. **Discriminated unions**: Type-safe message handling with Pydantic discriminators
7. **Cancellation tokens**: Async task cancellation for timeouts/interrupts

### Considerations

1. **Token counting accuracy**: Only accurate for OpenAI (tiktoken), others are approximations
2. **Structured output limitations**: Only fully supported for OpenAI, Anthropic falls back to prompt engineering
3. **System message merging**: Different models have different constraints, requires normalization logic
4. **Provider-specific quirks**: Empty content, whitespace handling, tool result roles differ
5. **Streaming events**: Framework emits logs but no rich event stream for UI consumption
6. **Message size**: Full conversation history sent each turn, no automatic truncation or summarization

## Anti-Patterns Observed

### 1. Silent Feature Degradation

**Issue**: Model capability checks raise exceptions instead of degrading gracefully:
```python
if self.model_info["json_output"] is False and json_output is True:
    raise ValueError("Model does not support JSON output")
```

**Better Approach**:
- For JSON mode: Fall back to prompt engineering ("Return JSON format")
- For structured output: Use schema validation post-generation
- Emit warnings instead of hard failures for optional features

### 2. Inconsistent Empty Content Handling

**Issue**: Different providers handle empty strings differently:
```python
# Gemini: Empty string -> " "
content = message.content or " "

# Claude: Empty content checked separately
if not content.strip():
    return {"pass_message": True}
```

**Better Approach**: Normalize at message construction time, not transformation time

### 3. Model-Specific Logic in Generic Client

**Issue**: Model family checks scattered throughout OpenAI client:
```python
if create_args.get("model", "unknown").startswith("claude-"):
    messages = self._rstrip_last_assistant_message(messages)

if self._model_info["family"] == ModelFamily.R1:
    thought, content = parse_r1_content(content)
```

**Better Approach**: Extract model-specific logic to transformation pipeline or provider-specific subclasses

### 4. Duplicate Transformation Logic

**Issue**: OpenAI and Anthropic clients have parallel message transformation:
```python
# OpenAI: _message_transform.py with registry
# Anthropic: Direct functions (user_message_to_anthropic, assistant_message_to_anthropic)
```

**Better Approach**: Unified transformation layer for all providers

### 5. Hardcoded Base URLs

**Issue**: Special-cased base URLs for Gemini/Claude in OpenAI client:
```python
if copied_args["model"].startswith("gemini-"):
    copied_args["base_url"] = "https://generativelanguage.googleapis.com/v1beta/openai/"
if copied_args["model"].startswith("claude-"):
    copied_args["base_url"] = "https://api.anthropic.com/v1/openai/"
```

**Better Approach**: Provider registry with auto-detection

### 6. No Multi-Provider Load Balancing

**Issue**: Single client per request, no automatic failover or load distribution

**Better Approach**: Provider pool with round-robin, rate limiting, automatic retries

### 7. Tool State Persistence Required

**Issue**: Anthropic requires `tools` in subsequent messages even after tool use:
```python
# Must store last used tools
self._last_used_tools = converted_tools
# Later messages with tool results need the original tools array
request_args["tools"] = self._last_used_tools
```

**Better Approach**: Framework should track tool context automatically across turns

### 8. No Streaming Event Standardization

**Issue**: Different chunks yielded based on provider:
```python
# OpenAI: content deltas, reasoning deltas, final CreateResult
# Anthropic: text deltas, thinking deltas, final CreateResult
```

**Better Approach**:
- Emit structured events: `TextChunk`, `ThinkingChunk`, `ToolCallStarted`, `ToolCallCompleted`
- Allow subscribers to filter event types
- Standardize across providers

### 9. Vision Token Estimation Complexity

**Issue**: Complex heuristic for image token calculation:
```python
def calculate_vision_tokens(image: Image, detail: str = "auto") -> int:
    # 50+ lines of scaling, tiling, token calculation
    # Only accurate for OpenAI
```

**Better Approach**: Provider-specific estimation, warn users about approximations

### 10. Missing Response Validation

**Issue**: No validation that tool call IDs in results match tool calls in assistant message

**Better Approach**:
- Validate `tool_call_id` matches a prior `FunctionCall.id`
- Warn on orphaned tool results
- Reject malformed tool call/result pairs
