# Harness-Model Protocol Analysis: Microsoft Agent Framework

## Summary

- **Key Finding 1**: Universal internal message format with provider-specific adapters - the framework uses a unified `ChatMessage` type internally with `Contents` as a polymorphic content container, then translates to/from provider-native formats at the adapter boundary
- **Key Finding 2**: Streaming handles partial tool calls via accumulator pattern - streaming chunks for function calls track `_last_call_id_name` state to reconstruct multi-chunk tool invocations, with FunctionCallContent supporting `__add__` for incremental accumulation
- **Key Finding 3**: Protocol-first multi-provider architecture - supports OpenAI, Anthropic, Azure, Bedrock, Ollama via thin adapter pattern that translates between universal types and provider wire formats

- **Classification**: **Gateway Pattern** - Framework maintains provider-agnostic internal types and uses adapter classes per provider to translate to/from native SDKs. Streaming, tool calling, and message conversion all happen at the adapter layer.

## Detailed Analysis

### Message Protocol

**Wire Format Family**: Multi-provider with adapters for each
**Providers Supported**:
- OpenAI/Azure OpenAI: `python/packages/core/agent_framework/openai/_chat_client.py`
- Anthropic: `python/packages/anthropic/agent_framework_anthropic/_chat_client.py`
- AWS Bedrock: `python/packages/bedrock/`
- Ollama: `python/packages/ollama/`
- Azure AI: `python/packages/azure-ai/`

**Abstraction Strategy**: Universal client interface + provider adapters

The framework defines a universal type system in `_types.py`:

```python
# Universal message envelope
class ChatMessage(SerializationMixin):
    """Represents a chat message.

    Attributes:
        role: The role of the author (SYSTEM, USER, ASSISTANT, TOOL)
        contents: List of content items (polymorphic)
        author_name: Optional author identifier
        message_id: Message identifier
    """
    role: Role
    contents: list[Contents]
    author_name: str | None
    message_id: str | None
    additional_properties: dict[str, Any]
    raw_representation: Any  # Provider-native object preserved
```

**Content Type Hierarchy** (Polymorphic Union):
```python
Contents = (
    TextContent
    | FunctionCallContent
    | FunctionResultContent
    | DataContent        # Binary data (images, audio)
    | UriContent         # Remote resources
    | UsageContent       # Token usage metadata
    | ErrorContent       # Error information
    | HostedFileContent  # Provider-hosted files
    | FunctionApprovalRequestContent   # HITL approval
    | FunctionApprovalResponseContent  # HITL response
    | TextReasoningContent  # Chain-of-thought (o1, Claude thinking)
)
```

**Provider Translation Example (OpenAI)**:

```python
# _prepare_message_for_openai in openai/_chat_client.py
def _prepare_message_for_openai(self, message: ChatMessage) -> list[dict[str, Any]]:
    all_messages: list[dict[str, Any]] = []
    for content in message.contents:
        # Skip approval content - internal framework state
        if isinstance(content, (FunctionApprovalRequestContent, FunctionApprovalResponseContent)):
            continue

        args: dict[str, Any] = {
            "role": message.role.value if isinstance(message.role, Role) else message.role,
        }

        match content:
            case FunctionCallContent():
                # Accumulate multiple tool calls in single message
                if all_messages and "tool_calls" in all_messages[-1]:
                    all_messages[-1]["tool_calls"].append(self._prepare_content_for_openai(content))
                else:
                    args["tool_calls"] = [self._prepare_content_for_openai(content)]
            case FunctionResultContent():
                args["tool_call_id"] = content.call_id
                if content.result is not None:
                    args["content"] = prepare_function_call_results(content.result)
            case _:
                if "content" not in args:
                    args["content"] = []
                args["content"].append(self._prepare_content_for_openai(content))

        if "content" in args or "tool_calls" in args:
            all_messages.append(args)
    return all_messages
```

**Provider Translation Example (Anthropic)**:

```python
# _prepare_message_for_anthropic in anthropic/_chat_client.py
def _prepare_message_for_anthropic(self, message: ChatMessage) -> dict[str, Any]:
    a_content: list[dict[str, Any]] = []
    for content in message.contents:
        match content.type:
            case "text":
                a_content.append({"type": "text", "text": content.text})
            case "function_call":
                a_content.append({
                    "type": "tool_use",
                    "id": content.call_id,
                    "name": content.name,
                    "input": content.parse_arguments(),
                })
            case "function_result":
                a_content.append({
                    "type": "tool_result",
                    "tool_use_id": content.call_id,
                    "content": prepare_function_call_results(content.result),
                    "is_error": content.exception is not None,
                })
            case "text_reasoning":
                a_content.append({"type": "thinking", "thinking": content.text})

    return {
        "role": ROLE_MAP.get(message.role, "user"),  # SYSTEM -> user, TOOL -> user
        "content": a_content,
    }
```

**Key Design Decisions**:
1. **Raw representation preserved**: Each content object stores `raw_representation` with the original provider object for debugging/tracing
2. **Role mapping per provider**: `ROLE_MAP` translates universal roles to provider-specific (e.g., Anthropic has no `TOOL` role, maps to `user`)
3. **Content filtering**: Provider-specific content (approval requests, reasoning) filtered at adapter boundary
4. **Multimodal support**: `DataContent` and `UriContent` handle images/audio with media type inspection

### Tool Call Encoding

**Request Method**: Function calling API (native support per provider)

**Schema Transmission**: JSON Schema format for most providers

**OpenAI Tool Preparation**:
```python
def _prepare_tools_for_openai(self, tools: Sequence[ToolProtocol | MutableMapping[str, Any]]) -> list[dict[str, Any]]:
    chat_tools: list[dict[str, Any]] = []
    for tool in tools:
        if isinstance(tool, ToolProtocol):
            match tool:
                case AIFunction():
                    # AIFunction.to_json_schema_spec() generates OpenAI function calling format
                    chat_tools.append(tool.to_json_schema_spec())
                case _:
                    logger.debug("Unsupported tool passed (type: %s), ignoring", type(tool))
        else:
            chat_tools.append(tool if isinstance(tool, dict) else dict(tool))
    return chat_tools
```

**Anthropic Tool Preparation**:
```python
def _prepare_tools_for_anthropic(self, chat_options: ChatOptions) -> dict[str, Any] | None:
    result: dict[str, Any] = {}
    tool_list: list[MutableMapping[str, Any]] = []
    mcp_server_list: list[MutableMapping[str, Any]] = []

    for tool in chat_options.tools:
        match tool:
            case AIFunction():
                tool_list.append({
                    "type": "custom",
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters(),  # JSON Schema
                })
            case HostedWebSearchTool():
                tool_list.append({
                    "type": "web_search_20250305",
                    "name": "web_search",
                })
            case HostedCodeInterpreterTool():
                tool_list.append({
                    "type": "code_execution_20250825",
                    "name": "code_execution",
                })
            case HostedMCPTool():
                # MCP server configuration
                server_def: dict[str, Any] = {
                    "type": "url",
                    "name": tool.name,
                    "url": str(tool.url),
                }
                if tool.allowed_tools:
                    server_def["tool_configuration"] = {"allowed_tools": list(tool.allowed_tools)}
                mcp_server_list.append(server_def)

    if tool_list:
        result["tools"] = tool_list
    if mcp_server_list:
        result["mcp_servers"] = mcp_server_list
    return result or None
```

**Response Parsing (OpenAI)**:
```python
def _parse_tool_calls_from_openai(self, choice: Choice | ChunkChoice) -> list[Contents]:
    resp: list[Contents] = []
    content = choice.message if isinstance(choice, Choice) else choice.delta
    if content and content.tool_calls:
        for tool in content.tool_calls:
            if not isinstance(tool, ChatCompletionMessageCustomToolCall) and tool.function:
                fcc = FunctionCallContent(
                    call_id=tool.id if tool.id else "",
                    name=tool.function.name if tool.function.name else "",
                    arguments=tool.function.arguments if tool.function.arguments else "",
                    raw_representation=tool.function,
                )
                resp.append(fcc)
    return resp
```

**Response Parsing (Anthropic)**:
```python
def _parse_contents_from_anthropic(self, content: Sequence[BetaContentBlock | ...]) -> list[Contents]:
    contents: list[Contents] = []
    for content_block in content:
        match content_block.type:
            case "tool_use" | "mcp_tool_use" | "server_tool_use":
                # Track last call for streaming reconstruction
                self._last_call_id_name = (content_block.id, content_block.name)
                contents.append(
                    FunctionCallContent(
                        call_id=content_block.id,
                        name=content_block.name,
                        arguments=content_block.input,  # Already parsed dict
                        raw_representation=content_block,
                    )
                )
            case "input_json_delta":  # Streaming partial tool call
                call_id, name = self._last_call_id_name if self._last_call_id_name else ("", "")
                contents.append(
                    FunctionCallContent(
                        call_id=call_id,
                        name=name,
                        arguments=content_block.partial_json,  # Incremental JSON
                        raw_representation=content_block,
                    )
                )
    return contents
```

**Tool Choice Support**:

| Provider | auto | required | none | specific function | parallel |
|----------|------|----------|------|-------------------|----------|
| OpenAI | ✓ (default) | ✓ | ✓ | ✓ (via tool_choice dict) | ✓ (parallel_tool_calls param) |
| Anthropic | ✓ (type: auto) | ✓ (type: any or type: tool) | ✓ (type: none) | ✓ (type: tool, name: X) | ✓ (disable_parallel_tool_use) |
| Azure | ✓ (same as OpenAI) | ✓ | ✓ | ✓ | ✓ |
| Bedrock | Provider-dependent | Provider-dependent | Provider-dependent | Provider-dependent | Provider-dependent |

**Tool Choice Translation (Anthropic Example)**:
```python
if chat_options.tool_choice is not None:
    tool_choice_mode = (
        chat_options.tool_choice if isinstance(chat_options.tool_choice, str)
        else chat_options.tool_choice.mode
    )
    match tool_choice_mode:
        case "auto":
            tool_choice: dict[str, Any] = {"type": "auto"}
            if chat_options.allow_multiple_tool_calls is not None:
                tool_choice["disable_parallel_tool_use"] = not chat_options.allow_multiple_tool_calls
            result["tool_choice"] = tool_choice
        case "required":
            if (not isinstance(chat_options.tool_choice, str)
                and chat_options.tool_choice.required_function_name):
                tool_choice = {
                    "type": "tool",
                    "name": chat_options.tool_choice.required_function_name,
                }
            else:
                tool_choice = {"type": "any"}
            result["tool_choice"] = tool_choice
        case "none":
            result["tool_choice"] = {"type": "none"}
```

### Streaming Implementation

**Protocol**: Provider-native (OpenAI uses AsyncIterator[ChatCompletionChunk], Anthropic uses AsyncMessageStream)

**Partial Tool Call Handling**: Supported via accumulator pattern

**OpenAI Streaming**:
```python
async def _inner_get_streaming_response(
    self,
    *,
    messages: MutableSequence[ChatMessage],
    chat_options: ChatOptions,
    **kwargs: Any,
) -> AsyncIterable[ChatResponseUpdate]:
    client = await self._ensure_client()
    options_dict = self._prepare_options(messages, chat_options)
    options_dict["stream_options"] = {"include_usage": True}  # Request final usage stats

    async for chunk in await client.chat.completions.create(stream=True, **options_dict):
        if len(chunk.choices) == 0 and chunk.usage is None:
            continue  # Skip empty chunks
        yield self._parse_response_update_from_openai(chunk)
```

**Anthropic Streaming with State Tracking**:
```python
class AnthropicClient(BaseChatClient):
    def __init__(self, ...):
        # Streaming requires tracking last function call for partial chunks
        self._last_call_id_name: tuple[str, str] | None = None

    async def _inner_get_streaming_response(
        self,
        *,
        messages: MutableSequence[ChatMessage],
        chat_options: ChatOptions,
        **kwargs: Any,
    ) -> AsyncIterable[ChatResponseUpdate]:
        run_options = self._prepare_options(messages, chat_options, **kwargs)
        async for chunk in await self.anthropic_client.beta.messages.create(**run_options, stream=True):
            parsed_chunk = self._process_stream_event(chunk)
            if parsed_chunk:
                yield parsed_chunk

    def _process_stream_event(self, event: BetaRawMessageStreamEvent) -> ChatResponseUpdate | None:
        match event.type:
            case "message_start":
                # Initial message with usage
                return ChatResponseUpdate(
                    response_id=event.message.id,
                    contents=[...],
                    model_id=event.message.model,
                )
            case "content_block_start":
                # New content block (text, tool_use, etc.)
                contents = self._parse_contents_from_anthropic([event.content_block])
                return ChatResponseUpdate(contents=contents, raw_response=event)
            case "content_block_delta":
                # Incremental update to current content block
                contents = self._parse_contents_from_anthropic([event.delta])
                return ChatResponseUpdate(contents=contents, raw_response=event)
            case "message_delta":
                # Final usage stats
                usage = self._parse_usage_from_anthropic(event.usage)
                return ChatResponseUpdate(
                    contents=[UsageContent(details=usage)] if usage else [],
                    raw_response=event,
                )
```

**FunctionCallContent Accumulation**:
```python
class FunctionCallContent(BaseContent):
    def __add__(self, other: "FunctionCallContent") -> "FunctionCallContent":
        """Concatenate two FunctionCallContent instances (for streaming accumulation)."""
        if not isinstance(other, FunctionCallContent):
            raise ValueError("Can only add two FunctionCallContent objects together.")

        # Concatenate arguments (handles partial JSON)
        if isinstance(self.arguments, str) and isinstance(other.arguments, str):
            new_arguments = self.arguments + other.arguments
        elif isinstance(self.arguments, Mapping) and isinstance(other.arguments, Mapping):
            new_arguments = {**self.arguments, **other.arguments}
        else:
            new_arguments = other.arguments if other.arguments else self.arguments

        return FunctionCallContent(
            call_id=other.call_id if other.call_id else self.call_id,
            name=other.name if other.name else self.name,
            arguments=new_arguments,
        )
```

**Event Types Emitted**:

| Event Type | OpenAI | Anthropic | Contains |
|------------|--------|-----------|----------|
| Text Delta | ChatResponseUpdate with TextContent | content_block_delta (text_delta) | Incremental text |
| Tool Call Start | ChatResponseUpdate with FunctionCallContent | content_block_start (tool_use) | Tool ID, name |
| Tool Call Delta | ChatResponseUpdate with FunctionCallContent (partial args) | content_block_delta (input_json_delta) | Partial JSON arguments |
| Tool Call Complete | (implicit - final chunk) | content_block_stop | Marks completion |
| Usage Stats | ChatResponseUpdate with UsageContent | message_delta (usage) | Token counts |
| Finish Reason | ChatResponseUpdate.finish_reason | message_delta (stop_reason) | stop/length/tool_calls |

**Key Insight**: Anthropic requires stateful tracking (`_last_call_id_name`) because `input_json_delta` events don't re-send the tool ID/name. OpenAI includes full tool call metadata in each chunk.

### Agentic Primitives

#### System Prompt Assembly

**OpenAI Approach**: System messages as first message with role="system"
```python
def _prepare_messages_for_openai(self, chat_messages: Sequence[ChatMessage], ...) -> list[dict[str, Any]]:
    # System messages passed as-is with role="system"
    list_of_list = [self._prepare_message_for_openai(message) for message in chat_messages]
    return list(chain.from_iterable(list_of_list))
```

**Anthropic Approach**: Separate `system` parameter, first system message extracted
```python
def _prepare_options(self, messages: MutableSequence[ChatMessage], chat_options: ChatOptions, **kwargs) -> dict[str, Any]:
    run_options = {...}

    # First system message passed as instructions
    if messages and isinstance(messages[0], ChatMessage) and messages[0].role == Role.SYSTEM:
        run_options["system"] = messages[0].text  # Extracted to separate param

    run_options["messages"] = self._prepare_messages_for_anthropic(messages)  # Skips first if SYSTEM
    return run_options
```

**Dynamic Instructions Support**:
```python
class ChatOptions(SerializationMixin):
    """
    Attributes:
        instructions: Optional system instructions to prepend to messages
    """
    instructions: str | None = None

# In BaseChatClient:
async def get_response(self, messages: ..., **kwargs) -> ChatResponse:
    prepared_messages = prepare_messages(messages)
    chat_options = ChatOptions(**kwargs)

    # Instructions injected as first system message if provided
    if chat_options.instructions:
        prepared_messages.insert(0, ChatMessage(role=Role.SYSTEM, text=chat_options.instructions))
```

#### Scratchpad / Working Memory

The framework uses `ChatMessage` history as the scratchpad. No explicit "working memory" primitive - everything is in message history.

**Multi-turn Tool Conversations**:
```python
# Example flow:
messages = [
    ChatMessage(role=Role.USER, text="What's the weather in SF?"),
    ChatMessage(role=Role.ASSISTANT, contents=[
        FunctionCallContent(call_id="call_123", name="get_weather", arguments='{"location": "SF"}')
    ]),
    ChatMessage(role=Role.TOOL, contents=[
        FunctionResultContent(call_id="call_123", name="get_weather", result="Sunny, 72°F")
    ]),
    ChatMessage(role=Role.ASSISTANT, text="The weather in SF is sunny, 72°F."),
]
```

**Tool Result Attribution**:
- `FunctionResultContent.call_id` matches `FunctionCallContent.call_id`
- OpenAI requires `tool_call_id` in message
- Anthropic requires `tool_use_id` in tool_result content

#### Interrupt / Human-in-the-Loop

**Approval Content Types**:
```python
class FunctionApprovalRequestContent(BaseContent):
    """Request for human approval before executing a function.

    Attributes:
        type: Always "function_approval_request"
        function_call: The FunctionCallContent to be approved
        approval_id: Unique identifier for tracking approval
    """

class FunctionApprovalResponseContent(BaseContent):
    """Human response to a function approval request.

    Attributes:
        type: Always "function_approval_response"
        function_call: The FunctionCallContent that was approved/rejected
        approval_id: Matches the request
        approved: Boolean approval decision
    """
```

**Approval Workflow**:
```python
# 1. Agent requests function execution
response = await client.get_response(messages)
if any(isinstance(c, FunctionApprovalRequestContent) for m in response.messages for c in m.contents):
    # 2. Framework pauses and emits approval request
    approval_request = next(c for m in response.messages for c in m.contents
                          if isinstance(c, FunctionApprovalRequestContent))

    # 3. Application prompts user
    user_decision = await prompt_user(approval_request.function_call)

    # 4. Application sends approval response
    messages.append(ChatMessage(
        role=Role.USER,
        contents=[FunctionApprovalResponseContent(
            function_call=approval_request.function_call,
            approval_id=approval_request.approval_id,
            approved=user_decision,
        )]
    ))

    # 5. Resume execution
    response = await client.get_response(messages)
```

**Note**: Approval content is **filtered** at the provider adapter boundary:
```python
# From _prepare_message_for_openai:
for content in message.contents:
    # Skip approval content - it's internal framework state, not for the LLM
    if isinstance(content, (FunctionApprovalRequestContent, FunctionApprovalResponseContent)):
        continue
```

This means approval is purely framework-level orchestration, invisible to the LLM.

#### Conversation State Machine

The framework uses `AgentThread` to manage conversation state:

```python
class AgentThread:
    """Represents a conversation thread with message history.

    Attributes:
        messages: List of ChatMessage in conversation
        metadata: Thread-level metadata (user_id, session_id, etc.)
    """
    messages: list[ChatMessage]
    metadata: dict[str, Any]

class ChatMessageStoreProtocol(Protocol):
    """Protocol for persisting conversation threads."""

    async def save_thread(self, thread_id: str, thread: AgentThread) -> None: ...
    async def load_thread(self, thread_id: str) -> AgentThread | None: ...
    async def delete_thread(self, thread_id: str) -> None: ...
```

**State Reconstruction for Stateless APIs**:

All providers are stateless - the framework reconstructs full conversation context on each request:

```python
async def get_response(self, messages: str | ChatMessage | list[str] | list[ChatMessage], **kwargs) -> ChatResponse:
    # 1. Normalize input to list[ChatMessage]
    prepared_messages = prepare_messages(messages)

    # 2. Load thread history if thread_id provided
    if thread_id := kwargs.get("thread_id"):
        thread = await self.thread_store.load_thread(thread_id)
        prepared_messages = thread.messages + prepared_messages

    # 3. Build ChatOptions
    chat_options = ChatOptions(**kwargs)

    # 4. Call provider with FULL history
    response = await self._inner_get_response(
        messages=prepared_messages,
        chat_options=chat_options,
    )

    # 5. Append response to thread
    if thread_id:
        thread.messages.extend(response.messages)
        await self.thread_store.save_thread(thread_id, thread)

    return response
```

**No built-in state machines** - orchestration happens at application level or via workflow graphs (separate concern).

### Provider Abstraction

**Architecture**: Protocol + Base Class + Provider Implementations

```python
@runtime_checkable
class ChatClientProtocol(Protocol):
    """Structural interface - any class with these methods is compatible."""

    @property
    def additional_properties(self) -> dict[str, Any]: ...

    async def get_response(
        self,
        messages: str | ChatMessage | list[str] | list[ChatMessage],
        **kwargs: Any,
    ) -> ChatResponse: ...

    def get_streaming_response(
        self,
        messages: str | ChatMessage | list[str] | list[ChatMessage],
        **kwargs: Any,
    ) -> AsyncIterable[ChatResponseUpdate]: ...
```

**Base Implementation**:
```python
class BaseChatClient(ABC):
    """Abstract base providing common functionality."""

    @abstractmethod
    async def _inner_get_response(
        self,
        *,
        messages: MutableSequence[ChatMessage],
        chat_options: ChatOptions,
        **kwargs: Any,
    ) -> ChatResponse:
        """Provider-specific response generation (must override)."""

    @abstractmethod
    async def _inner_get_streaming_response(
        self,
        *,
        messages: MutableSequence[ChatMessage],
        chat_options: ChatOptions,
        **kwargs: Any,
    ) -> AsyncIterable[ChatResponseUpdate]:
        """Provider-specific streaming (must override)."""

    # Common logic (message normalization, middleware, etc.)
    async def get_response(self, messages, **kwargs) -> ChatResponse:
        prepared_messages = prepare_messages(messages)
        chat_options = ChatOptions(**kwargs)
        return await self._inner_get_response(
            messages=prepared_messages,
            chat_options=chat_options,
        )
```

**Provider Feature Matrix**:

| Provider | Location | Streaming | Tool Calling | Multimodal | Reasoning (CoT) | MCP Support | Web Search |
|----------|----------|-----------|--------------|------------|-----------------|-------------|------------|
| OpenAI | `core/openai/` | ✓ (SSE) | ✓ (parallel) | ✓ (image, audio) | ✓ (o1 models) | ✗ | ✓ (via tool) |
| Azure OpenAI | `core/azure/` | ✓ (SSE) | ✓ (parallel) | ✓ (image, audio) | ✓ (o1 models) | ✗ | ✓ (via tool) |
| Anthropic | `anthropic/` | ✓ (SSE) | ✓ (parallel) | ✓ (image) | ✓ (extended thinking) | ✓ (native) | ✓ (native tool) |
| AWS Bedrock | `bedrock/` | ✓ | Model-dependent | Model-dependent | Model-dependent | ✗ | ✗ |
| Ollama | `ollama/` | ✓ | ✓ | ✓ | Model-dependent | ✗ | ✗ |
| Azure AI | `azure-ai/` | ✓ | ✓ | ✓ | Model-dependent | ✗ | ✗ |

**Feature Graceful Degradation**:

```python
# Example: Anthropic doesn't support TOOL role, maps to USER
ROLE_MAP: dict[Role, str] = {
    Role.USER: "user",
    Role.ASSISTANT: "assistant",
    Role.SYSTEM: "user",  # No system role in Anthropic messages
    Role.TOOL: "user",    # No tool role, send as user message
}

# Example: Max tokens handling
if not run_options.get("max_tokens"):
    if provider == "anthropic":
        # Anthropic REQUIRES max_tokens, use default
        run_options["max_tokens"] = ANTHROPIC_DEFAULT_MAX_TOKENS
    elif provider == "openai":
        # OpenAI uses model default if omitted
        pass
```

**Provider-Specific Features**:

```python
# OpenAI: Reasoning models (o1 series)
if reasoning_details := getattr(choice.message, "reasoning_details", None):
    contents.append(TextReasoningContent(None, protected_data=json.dumps(reasoning_details)))

# Anthropic: Extended thinking
case "thinking" | "thinking_delta":
    contents.append(TextReasoningContent(text=content_block.thinking, raw_representation=content_block))

# Anthropic: Web search as native tool
case HostedWebSearchTool():
    tool_list.append({
        "type": "web_search_20250305",
        "name": "web_search",
    })

# Anthropic: Code execution as native tool
case HostedCodeInterpreterTool():
    tool_list.append({
        "type": "code_execution_20250825",
        "name": "code_execution",
    })

# Anthropic: MCP servers
case HostedMCPTool():
    mcp_server_list.append({
        "type": "url",
        "name": tool.name,
        "url": str(tool.url),
    })
```

## Code References

### Core Type System
- `/repos/ms-agent-framework/python/packages/core/agent_framework/_types.py:2028-2330` - ChatMessage, ChatResponse, ChatResponseUpdate
- `/repos/ms-agent-framework/python/packages/core/agent_framework/_types.py:600-1890` - Content type hierarchy (TextContent, FunctionCallContent, etc.)
- `/repos/ms-agent-framework/python/packages/core/agent_framework/_types.py:1890-2028` - Role enum with SYSTEM, USER, ASSISTANT, TOOL

### Client Protocol & Base Class
- `/repos/ms-agent-framework/python/packages/core/agent_framework/_clients.py:42-200` - ChatClientProtocol (structural interface)
- `/repos/ms-agent-framework/python/packages/core/agent_framework/_clients.py:200-400` - BaseChatClient (abstract base)

### OpenAI Adapter
- `/repos/ms-agent-framework/python/packages/core/agent_framework/openai/_chat_client.py:62-128` - Streaming and non-streaming methods
- `/repos/ms-agent-framework/python/packages/core/agent_framework/openai/_chat_client.py:224-289` - Response parsing from OpenAI format
- `/repos/ms-agent-framework/python/packages/core/agent_framework/openai/_chat_client.py:359-488` - Message preparation for OpenAI format
- `/repos/ms-agent-framework/python/packages/core/agent_framework/openai/_chat_client.py:131-144` - Tool preparation for OpenAI

### Anthropic Adapter
- `/repos/ms-agent-framework/python/packages/anthropic/agent_framework_anthropic/_chat_client.py:209-236` - Streaming and non-streaming methods
- `/repos/ms-agent-framework/python/packages/anthropic/agent_framework_anthropic/_chat_client.py:487-509` - Response processing
- `/repos/ms-agent-framework/python/packages/anthropic/agent_framework_anthropic/_chat_client.py:511-662` - Streaming event processing with state tracking
- `/repos/ms-agent-framework/python/packages/anthropic/agent_framework_anthropic/_chat_client.py:328-392` - Message preparation for Anthropic format
- `/repos/ms-agent-framework/python/packages/anthropic/agent_framework_anthropic/_chat_client.py:394-483` - Tool preparation with MCP support

### Content Type Implementations
- `/repos/ms-agent-framework/python/packages/core/agent_framework/_types.py:91-154` - Content parsing utilities
- `/repos/ms-agent-framework/python/packages/core/agent_framework/_types.py:600-750` - TextContent with concatenation support
- `/repos/ms-agent-framework/python/packages/core/agent_framework/_types.py:1200-1400` - FunctionCallContent with accumulation
- `/repos/ms-agent-framework/python/packages/core/agent_framework/_types.py:1400-1550` - FunctionResultContent

### Approval Primitives (HITL)
- `/repos/ms-agent-framework/python/packages/core/agent_framework/_types.py:1650-1750` - FunctionApprovalRequestContent
- `/repos/ms-agent-framework/python/packages/core/agent_framework/_types.py:1750-1850` - FunctionApprovalResponseContent

## Implications for New Framework

### Positive Patterns

1. **Universal Internal Types with Provider Adapters**
   - **Why it works**: Clean separation between framework logic and provider quirks
   - **Implementation**: Define `Message`, `Content`, `Response` as framework types, then `ProviderAdapter.to_provider()` and `from_provider()` methods
   - **Benefit**: Add new providers without touching core logic, swap providers transparently

2. **Content as Polymorphic Union**
   - **Why it works**: Extensible without breaking changes (add new content types without modifying existing code)
   - **Implementation**: `Content = TextContent | ToolCallContent | ImageContent | ...` with match/case dispatch
   - **Benefit**: Type-safe multimodal support, handles provider-specific content (reasoning, citations) gracefully

3. **Raw Representation Preservation**
   - **Why it works**: Debugging/introspection without losing provider-native data
   - **Implementation**: Every content/message object has `raw_representation: Any` field storing original provider object
   - **Benefit**: Framework users can access provider-specific fields not exposed in universal API

4. **Streaming State Tracking Pattern**
   - **Why it works**: Handles partial tool calls correctly without buffering entire response
   - **Implementation**: `_last_call_id_name` instance variable + `Content.__add__()` for accumulation
   - **Benefit**: Works with providers that send incremental JSON (Anthropic) vs complete tool calls (OpenAI)

5. **Approval as Content Type (not callback)**
   - **Why it works**: Approval requests are just messages, not separate control flow
   - **Implementation**: `ApprovalRequestContent` in response -> app renders UI -> `ApprovalResponseContent` in next request
   - **Benefit**: HITL works with any transport (HTTP, WebSocket, CLI) without special plumbing

6. **Protocol-First Design**
   - **Why it works**: Users can implement custom clients without inheriting framework classes
   - **Implementation**: `@runtime_checkable Protocol` for interfaces, optional base class for common logic
   - **Benefit**: Drop-in custom providers (local models, caching layers) without framework lock-in

### Considerations

1. **Provider Feature Parity Not Guaranteed**
   - **Issue**: Anthropic has MCP/web search/code execution as native tools; OpenAI doesn't
   - **Decision**: Expose as `HostedXTool` types, each provider maps to native or custom function
   - **Trade-off**: Framework code knows about provider-specific features, but encapsulated in tool types

2. **Role Mapping Complexity**
   - **Issue**: Each provider has different role semantics (Anthropic: no TOOL role, maps SYSTEM to parameter)
   - **Decision**: Universal `Role` enum + per-provider `ROLE_MAP`
   - **Trade-off**: Leaky abstraction - users need to understand role limitations per provider

3. **Streaming Event Heterogeneity**
   - **Issue**: OpenAI streams choice deltas, Anthropic streams message blocks with type-specific events
   - **Decision**: Emit universal `ChatResponseUpdate` with polymorphic `contents`, provider adapter maps events
   - **Trade-off**: Applications can't rely on event timing/granularity consistency across providers

4. **Multi-turn Tool Conversations**
   - **Issue**: No explicit "turn" boundary - just append messages to history
   - **Decision**: Application manages conversation loop (send message -> check for tool calls -> execute -> append results -> send again)
   - **Trade-off**: Verbose application code, but maximum control over tool execution (error handling, approval, logging)

5. **No Automatic Message Pruning**
   - **Issue**: Context window exhaustion on long conversations
   - **Decision**: Framework doesn't truncate - users must implement pruning strategy
   - **Trade-off**: Correct decision (pruning is domain-specific), but no helper utilities provided

## Anti-Patterns Observed

### 1. Stateful Streaming (`_last_call_id_name`)

**Location**: `anthropic/_chat_client.py:205`

**Issue**: Instance variable `_last_call_id_name` tracks tool call state across stream events

```python
class AnthropicClient(BaseChatClient):
    def __init__(self, ...):
        self._last_call_id_name: tuple[str, str] | None = None

    def _parse_contents_from_anthropic(self, content):
        match content_block.type:
            case "tool_use":
                self._last_call_id_name = (content_block.id, content_block.name)  # Mutation!
            case "input_json_delta":
                call_id, name = self._last_call_id_name or ("", "")  # Relies on state
```

**Problem**:
- Not thread-safe (concurrent streaming requests will clobber state)
- Violates functional streaming principle (chunks should be self-contained)
- Debugging nightmare (implicit coupling between events)

**Better Approach**: Stream accumulator pattern
```python
class StreamAccumulator:
    def __init__(self):
        self.pending_tool_calls: dict[str, ToolCallState] = {}

    def process_event(self, event) -> list[Content]:
        match event.type:
            case "tool_use":
                self.pending_tool_calls[event.id] = ToolCallState(
                    id=event.id, name=event.name, arguments=""
                )
            case "input_json_delta":
                # Look up by index or explicit ID in event
                state = self.pending_tool_calls[event.index]
                state.arguments += event.partial_json
                return [FunctionCallContent(state.id, state.name, state.arguments)]

# Usage:
async for event in stream:
    accumulator.process_event(event)
```

### 2. String-Based Content Type Dispatch

**Location**: `_types.py:91-130`

```python
def _parse_content(content_data: MutableMapping[str, Any]) -> "Contents":
    content_type = str(content_data.get("type"))
    match content_type:  # String matching!
        case "text":
            return TextContent.from_dict(content_data)
        case "function_call":
            return FunctionCallContent.from_dict(content_data)
        # ... 10 more cases
        case _:
            raise ContentError(f"Unknown content type '{content_type}'")
```

**Problem**:
- Typos not caught by type system (`"functio_call"` would silently fail)
- No IDE autocomplete for content types
- Adding new content type requires modifying central dispatcher

**Better Approach**: Registry pattern with type-based dispatch
```python
class ContentRegistry:
    _types: dict[type[Content], str] = {}
    _parsers: dict[str, type[Content]] = {}

    @classmethod
    def register(cls, content_cls: type[Content], type_name: str):
        cls._types[content_cls] = type_name
        cls._parsers[type_name] = content_cls

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Content:
        type_name = data.get("type")
        if parser := cls._parsers.get(type_name):
            return parser.from_dict(data)
        raise ContentError(f"Unknown content type: {type_name}")

# Registration:
ContentRegistry.register(TextContent, "text")
ContentRegistry.register(FunctionCallContent, "function_call")

# Usage:
content = ContentRegistry.parse({"type": "text", "text": "hello"})
```

### 3. Large Monolithic `_types.py`

**Location**: `core/agent_framework/_types.py` (3500+ lines)

**Issue**: Single file contains:
- 15+ content types
- ChatMessage, ChatResponse, ChatResponseUpdate
- Role, FinishReason, ToolMode enums
- UsageDetails, Annotations
- Serialization mixins
- Parsing utilities

**Problem**:
- Slow IDE performance (autocomplete lag)
- Merge conflicts on multi-developer teams
- Difficult to navigate (find specific type requires scrolling)
- Circular import risks (everything imports from one file)

**Better Approach**: Module structure
```
types/
  __init__.py          # Re-export public API
  message.py           # ChatMessage, ChatResponse, ChatResponseUpdate
  content.py           # BaseContent, Contents union
  content_types/
    __init__.py
    text.py            # TextContent
    function.py        # FunctionCallContent, FunctionResultContent
    multimodal.py      # DataContent, UriContent
    metadata.py        # UsageContent, ErrorContent
  enums.py             # Role, FinishReason, ToolMode
  annotations.py       # Annotations, CitationAnnotation
  usage.py             # UsageDetails
  serialization.py     # SerializationMixin
```

### 4. Role Mapping in Multiple Places

**Issue**: Role translation logic duplicated per provider

```python
# OpenAI: Inline in message preparation
args = {"role": message.role.value if isinstance(message.role, Role) else message.role}

# Anthropic: Separate ROLE_MAP constant
ROLE_MAP: dict[Role, str] = {
    Role.USER: "user",
    Role.ASSISTANT: "assistant",
    Role.SYSTEM: "user",
    Role.TOOL: "user",
}
return {"role": ROLE_MAP.get(message.role, "user"), ...}
```

**Problem**:
- Inconsistent patterns across providers
- Easy to miss edge cases (what if role is custom string?)
- No central documentation of role mapping rules

**Better Approach**: Provider capability declaration
```python
class ProviderCapabilities:
    supported_roles: set[Role] = {Role.USER, Role.ASSISTANT, Role.SYSTEM, Role.TOOL}
    role_map: dict[Role, str] = {
        Role.USER: "user",
        Role.ASSISTANT: "assistant",
        Role.SYSTEM: "system",
        Role.TOOL: "tool",
    }

class AnthropicCapabilities(ProviderCapabilities):
    supported_roles = {Role.USER, Role.ASSISTANT}  # No SYSTEM/TOOL
    role_map = {
        Role.USER: "user",
        Role.ASSISTANT: "assistant",
        Role.SYSTEM: "user",  # Fallback
        Role.TOOL: "user",    # Fallback
    }
    system_message_mode = "parameter"  # vs "message"

# Usage in adapter:
def map_role(self, role: Role) -> str:
    if role not in self.capabilities.supported_roles:
        logger.warning(f"Provider doesn't support {role}, using fallback")
    return self.capabilities.role_map[role]
```

### 5. No Streaming Progress Tracking

**Issue**: No metadata about stream position/completion

```python
async for chunk in client.get_streaming_response(messages):
    # Is this the first chunk? Last chunk? Middle?
    # How much more is coming?
    # Can I cancel the stream?
    process_chunk(chunk)
```

**Problem**:
- Applications can't show progress bars
- Can't implement timeout on "no chunks received in N seconds"
- Can't differentiate between "stream ended" vs "network stalled"

**Better Approach**: Stream metadata + sentinel events
```python
@dataclass
class StreamMetadata:
    stream_id: str
    chunk_index: int
    is_final: bool
    estimated_remaining: int | None  # If provider supports

class ChatResponseUpdate:
    contents: list[Content]
    metadata: StreamMetadata

# Usage:
async for chunk in client.get_streaming_response(messages):
    if chunk.metadata.chunk_index == 0:
        show_spinner()
    if chunk.metadata.is_final:
        hide_spinner()
    if chunk.metadata.estimated_remaining:
        update_progress_bar(chunk.metadata.chunk_index / chunk.metadata.estimated_remaining)
```

### 6. Tool Result Serialization Ambiguity

**Issue**: `prepare_function_call_results()` coerces results to strings inconsistently

```python
def prepare_function_call_results(result: Any) -> str:
    """Convert function results to string for provider consumption."""
    if isinstance(result, str):
        return result
    if isinstance(result, BaseModel):
        return result.model_dump_json()
    if isinstance(result, list) and all(isinstance(x, BaseContent) for x in result):
        # List of content objects - serialize as JSON array
        return json.dumps([x.to_dict() for x in result])
    # Default: use JSON
    return json.dumps(result)
```

**Problem**:
- Loss of type information (structured data becomes strings)
- Providers with native structured tool results (Anthropic) can't use them
- Inconsistent handling of lists (sometimes Content[], sometimes JSON)

**Better Approach**: Provider-specific result formatting
```python
class ProviderAdapter:
    def format_tool_result(self, result: Any) -> ProviderToolResult:
        """Override per provider to use native result format."""
        raise NotImplementedError

class AnthropicAdapter(ProviderAdapter):
    def format_tool_result(self, result: Any) -> dict[str, Any]:
        if isinstance(result, list) and all(isinstance(x, Content) for x in result):
            # Anthropic supports content blocks in tool results
            return {"content": [self._content_to_anthropic(c) for c in result]}
        return {"content": str(result)}

class OpenAIAdapter(ProviderAdapter):
    def format_tool_result(self, result: Any) -> str:
        # OpenAI only accepts strings
        if isinstance(result, str):
            return result
        return json.dumps(result)
```

---

## Final Recommendations

### For New Framework (Elixir)

1. **Adopt Universal Internal Types**: Define `Message`, `Content`, `Response` as framework types, provider adapters translate at boundary
2. **Use Pattern Matching for Content Dispatch**: Elixir's pattern matching eliminates string-based type checking
3. **Stream with Accumulators**: GenServer-based accumulator per stream (no mutable instance variables)
4. **Provider as Behaviour**: Define `@callback` for required functions, each provider implements as module
5. **Capability Declaration**: Each provider module exports `capabilities()` map with supported features
6. **Content as Tagged Union**: `{:text, text} | {:tool_call, call} | {:tool_result, result}` - no classes needed
7. **Avoid Approval as Special Case**: Model HITL as message exchange (request/response pattern), not framework primitive
8. **Explicit Stream Metadata**: Include `chunk_index`, `is_final`, `stream_id` in every chunk

### What NOT to Copy

1. **Mutable streaming state** (`_last_call_id_name`) - use process-based accumulator
2. **Large monolithic type files** - separate into logical modules
3. **String-based dispatch** - use pattern matching
4. **Inconsistent role mapping** - centralize in provider capabilities
5. **Silent result coercion** - explicit formatter per provider
6. **No streaming progress** - include metadata in every chunk
