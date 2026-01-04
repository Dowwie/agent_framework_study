# Harness-Model Protocol (HMP) Synthesis Report

## Executive Summary

This synthesis consolidates findings from comprehensive Harness-Model Protocol analyses across 14 major agent frameworks: LangGraph, Pydantic-AI, OpenAI Agents Python, Google ADK, AutoGen, CrewAI, Agent-Zero, Swarm, CAMEL, Microsoft Agent Framework, LlamaIndex, MetaGPT, Agno, and AWS Strands.

The Harness-Model Protocol layer represents the critical boundary between agent orchestration logic and LLM provider APIs. This layer handles message format translation, tool call encoding/decoding, streaming protocol management, and provider-specific capability adaptation. The design decisions made at this layer fundamentally determine a framework's extensibility, maintainability, and operational characteristics.

**Key Finding**: Frameworks cluster into four distinct provider abstraction strategies, each with significant trade-offs. The choice of abstraction strategy cascades through the entire framework architecture, influencing everything from error handling semantics to streaming behavior to tool calling capabilities.

---

## Part I: Provider Abstraction Strategies

### Taxonomy of Abstraction Approaches

Analysis of the 14 frameworks reveals four fundamental strategies for abstracting LLM provider differences:

| Strategy | Frameworks | Characteristics |
|----------|------------|-----------------|
| **Delegation** | LangGraph, CrewAI | Outsource abstraction to external libraries (LangChain, LiteLLM) |
| **Unified Internal Types** | AutoGen, LlamaIndex, Pydantic-AI, MS Agent Framework, CAMEL | Define canonical internal message/tool types with provider adapters |
| **Provider-Native SDKs** | Agno, AWS Strands | Use each provider's native SDK directly with thin orchestration |
| **OpenAI-Native** | Swarm, OpenAI Agents, MetaGPT | Optimize for OpenAI format, treat others as secondary |

### 1. Delegation Strategy

**Representatives**: LangGraph, CrewAI

**Mechanism**: These frameworks delegate the entire provider abstraction problem to specialized libraries rather than implementing their own adapter layer. LangGraph relies on LangChain's extensive model ecosystem, while CrewAI uses LiteLLM as its universal provider interface.

**Architecture Pattern**:
```
Agent Logic → Framework Orchestration → LangChain/LiteLLM → Provider APIs
```

**Advantages**:
- Immediate access to extensive provider coverage (LangChain supports 100+ providers)
- Reduced maintenance burden for provider-specific edge cases
- Benefit from community contributions and bug fixes in the dependency
- Focus framework development on orchestration rather than integration

**Disadvantages**:
- Transitive dependency complexity (LangChain alone brings 50+ dependencies)
- Version coupling creates upgrade friction and potential breaking changes
- Limited control over wire format details and provider-specific optimizations
- Error messages and stack traces become opaque, crossing library boundaries
- Performance overhead from abstraction layers
- Debugging requires understanding multiple codebases

**LangGraph Implementation Detail**:
LangGraph's `BaseChatModel` abstraction from LangChain provides the interface, but the actual provider negotiation happens deep within LangChain's model registry:

```python
# LangGraph sees this clean interface
from langchain_core.language_models import BaseChatModel

# But underneath, LangChain manages:
# - Provider detection and routing
# - Message format translation
# - Tool schema generation
# - Streaming protocol differences
# - Retry and rate limiting logic
```

**CrewAI LiteLLM Integration**:
CrewAI's delegation to LiteLLM provides OpenAI-compatible interface universally:

```python
# CrewAI's LLM class wraps LiteLLM
class LLM:
    def call(self, messages, tools=None, callbacks=None):
        # Delegates to litellm.completion()
        # LiteLLM handles all provider translation
        response = litellm.completion(
            model=self.model,
            messages=messages,
            tools=tools
        )
```

The delegation pattern trades implementation simplicity for operational complexity. Frameworks using this approach spend less time on provider integration but inherit the dependency's quirks and limitations.

### 2. Unified Internal Types Strategy

**Representatives**: AutoGen, LlamaIndex, Pydantic-AI, MS Agent Framework, CAMEL

**Mechanism**: These frameworks define a canonical internal message format that serves as the lingua franca for all agent logic. Provider-specific adapters translate between this internal format and each provider's native wire format at the boundary.

**Architecture Pattern**:
```
Agent Logic ←→ Internal Types ←→ Provider Adapters ←→ Provider APIs
```

**Advantages**:
- Provider-agnostic agent logic enables genuine portability
- Clear separation of concerns between orchestration and integration
- Consistent error handling semantics across providers
- Testable adapter layer with well-defined contracts
- Framework can optimize internal representations without breaking agents
- Enables provider-specific optimizations within adapters

**Disadvantages**:
- Lowest-common-denominator features limit access to provider-specific capabilities
- Translation overhead for every message (though typically negligible)
- Adapter maintenance burden scales with provider count
- Risk of semantic drift between internal model and provider capabilities
- Complex capability detection and graceful degradation logic required

**LlamaIndex ChatMessage Implementation**:
LlamaIndex's approach exemplifies mature unified type design with block-based content representation:

```python
class ChatMessage(BaseModel):
    """Universal message type with discriminated union content blocks."""
    role: MessageRole = MessageRole.USER
    additional_kwargs: dict[str, Any] = Field(default_factory=dict)
    blocks: list[ContentBlock] = Field(default_factory=list)

# Content blocks enable rich, typed content representation
ContentBlock = Annotated[
    Union[TextBlock, ImageBlock, AudioBlock, ToolCallBlock, ToolResultBlock, ...],
    Field(discriminator="block_type")
]
```

This block-based architecture allows LlamaIndex to represent any content type while maintaining type safety. Each block has a discriminator field enabling runtime type resolution.

**AutoGen Unified Format**:
AutoGen takes a message-centric approach with explicit tool call representation:

```python
# AutoGen's internal format
{
    "role": "assistant",
    "content": "Let me search for that.",
    "tool_calls": [
        {
            "id": "call_abc123",
            "type": "function",
            "function": {
                "name": "web_search",
                "arguments": "{\"query\": \"weather forecast\"}"
            }
        }
    ]
}
```

AutoGen adapters translate this format bidirectionally. The `OpenAIClient` preserves format nearly identically (since AutoGen's format mirrors OpenAI's), while `AnthropicClient` performs substantial restructuring to match Anthropic's content block model.

**Pydantic-AI Message Protocol**:
Pydantic-AI uses a sophisticated Protocol-based approach for type safety:

```python
class ModelMessage(Protocol):
    """Protocol defining the contract for all message types."""
    role: str
    content: str | list[ContentPart]

class ContentPart(Protocol):
    """Protocol for multimodal content parts."""
    type: str

# Concrete implementations
@dataclass
class TextPart:
    type: Literal["text"] = "text"
    text: str

@dataclass
class ToolCallPart:
    type: Literal["tool_call"] = "tool_call"
    tool_name: str
    args: dict[str, Any]
    tool_call_id: str
```

The Protocol-based design enables static type checking while allowing provider-specific extensions. Pydantic-AI's adapters implement the translation with explicit mapping logic:

```python
class AnthropicAdapter:
    def to_wire(self, msg: ModelMessage) -> dict:
        # Translate unified format to Anthropic's content blocks
        return {
            "role": self._map_role(msg.role),
            "content": [self._translate_part(p) for p in msg.content]
        }

    def _translate_part(self, part: ContentPart) -> dict:
        if isinstance(part, ToolCallPart):
            return {
                "type": "tool_use",
                "id": part.tool_call_id,
                "name": part.tool_name,
                "input": part.args
            }
```

**MS Agent Framework Gateway Pattern**:
Microsoft's framework implements the "Gateway" pattern with explicit universal types:

```python
class Message:
    """Universal message container."""
    role: str
    content: list[ContentItem]

class ContentItem:
    """Discriminated union for content types."""
    type: ContentType  # TEXT, IMAGE, TOOL_CALL, TOOL_RESULT
    data: Any

class ModelGateway(Protocol):
    """Provider-agnostic interface for all LLM operations."""
    async def complete(self, messages: list[Message]) -> Message
    async def stream(self, messages: list[Message]) -> AsyncIterator[Delta]
```

The Gateway pattern provides a clean abstraction boundary. Each provider implements the Gateway protocol:

```python
class OpenAIGateway(ModelGateway):
    async def complete(self, messages: list[Message]) -> Message:
        wire_messages = self._to_openai_format(messages)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=wire_messages
        )
        return self._from_openai_format(response)
```

### 3. Provider-Native SDK Strategy

**Representatives**: Agno, AWS Strands

**Mechanism**: Rather than abstracting away provider differences, these frameworks embrace them by using each provider's native SDK directly. A thin orchestration layer manages the differences without attempting deep unification.

**Architecture Pattern**:
```
Agent Logic → Orchestrator → Provider-Specific Code Paths → Native SDKs
```

**Advantages**:
- Full access to provider-specific features (thinking blocks, citations, etc.)
- No translation overhead or semantic loss
- Native error handling and retry semantics preserved
- Optimal performance for each provider
- Immediate access to new provider features without adapter updates

**Disadvantages**:
- Code branching for provider-specific logic throughout framework
- Testing matrix explodes (must test each provider path)
- Agent logic may inadvertently become provider-dependent
- Harder to swap providers without code changes
- Maintenance burden increases with each new provider

**Agno Implementation**:
Agno exemplifies this approach with explicit provider detection and branching:

```python
class Model:
    def __init__(self, provider: str, model_id: str):
        self.provider = provider
        if provider == "openai":
            self.client = OpenAI()
        elif provider == "anthropic":
            self.client = Anthropic()
        elif provider == "google":
            self.client = genai.GenerativeModel(model_id)
        # Each path uses native SDK directly
```

The streaming implementation reveals the complexity of this approach:

```python
async def stream_response(self) -> AsyncIterator[StreamEvent]:
    if self.provider == "openai":
        async for chunk in self.client.chat.completions.create(stream=True):
            yield self._openai_chunk_to_event(chunk)
    elif self.provider == "anthropic":
        async with self.client.messages.stream() as stream:
            async for event in stream:
                yield self._anthropic_event_to_event(event)
    elif self.provider == "google":
        for chunk in self.model.generate_content(stream=True):
            yield self._google_chunk_to_event(chunk)
```

**AWS Strands Bedrock-Native Design**:
AWS Strands takes the provider-native approach to its logical extreme by building specifically for AWS Bedrock:

```python
class Message(TypedDict):
    """Bedrock Converse API native format."""
    content: List[ContentBlock]
    role: Role  # "user" | "assistant"

ContentBlock = Union[TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock]

class TextBlock(TypedDict):
    text: str

class ToolUseBlock(TypedDict):
    toolUseId: str
    name: str
    input: Dict[str, Any]
```

This tight coupling to Bedrock's Converse API means optimal performance and feature access for AWS users, but requires adapters for non-Bedrock providers:

```python
class BedrockProvider:
    async def converse(self, messages: list[Message]) -> Message:
        # Direct Bedrock API call with native types
        response = await self.bedrock_client.converse(
            modelId=self.model_id,
            messages=messages,
            toolConfig=self.tool_config
        )
        return response["output"]["message"]
```

### 4. OpenAI-Native Strategy

**Representatives**: Swarm, OpenAI Agents Python, MetaGPT

**Mechanism**: These frameworks treat OpenAI's API format as canonical, implementing it as the native internal format. Other providers are supported through OpenAI-compatibility layers or are secondary concerns.

**Architecture Pattern**:
```
Agent Logic → OpenAI Format → OpenAI API (primary)
                           → Compatibility Layer → Other Providers (secondary)
```

**Advantages**:
- Simple implementation for OpenAI (no translation needed)
- Leverages OpenAI's de facto standard status
- Many providers offer OpenAI-compatible endpoints
- Minimal code for common use case
- Clear, well-documented format with extensive tooling

**Disadvantages**:
- Provider-specific features unavailable or awkwardly mapped
- Anthropic and Google require significant translation
- Locks framework design to OpenAI's API evolution
- May miss provider-specific optimizations
- Tool calling semantics differ across providers despite format similarity

**Swarm's Minimal Approach**:
Swarm represents the purest form of OpenAI-native design (intentionally, as it's educational):

```python
def run(self, agent, messages, context_variables=None, stream=False):
    # Direct OpenAI client usage - no abstraction layer
    response = self.client.chat.completions.create(
        model=agent.model,
        messages=messages,
        tools=self._get_tools(agent),
        tool_choice=agent.tool_choice
    )
    return self._process_response(response, agent, context_variables)
```

Swarm's documentation explicitly states it's a reference implementation not intended for production. The lack of abstraction is a feature, not a bug - it demonstrates core agent patterns without infrastructure complexity.

**OpenAI Agents Python**:
OpenAI's official SDK takes the OpenAI-native approach but with sophisticated extensions:

```python
# Native Responses API usage
class OpenAIAgent:
    async def run(self, messages: list[dict]) -> Response:
        response = await self.client.responses.create(
            model=self.model,
            input=messages,
            tools=self.tools,
            # Responses API provides enhanced tool calling
        )
        return response
```

The framework provides official adapters for other providers but these are clearly secondary:

```python
# Anthropic adapter translates to/from OpenAI format
class AnthropicAdapter:
    def adapt_messages(self, openai_messages: list[dict]) -> list[dict]:
        # Convert OpenAI format to Anthropic content blocks
        return [self._convert_message(m) for m in openai_messages]
```

**MetaGPT Provider Registry**:
MetaGPT uses a registry pattern to manage providers while maintaining OpenAI as the canonical format:

```python
@register_provider([LLMType.OPENAI, LLMType.AZURE, LLMType.FIREWORKS])
class OpenAILLM(BaseLLM):
    """Primary provider - native OpenAI format."""

@register_provider([LLMType.ANTHROPIC])
class AnthropicLLM(BaseLLM):
    """Translates to/from OpenAI format internally."""

@register_provider([LLMType.GEMINI])
class GeminiLLM(BaseLLM):
    """Limited support - tool calling not implemented."""
```

The registry pattern allows provider selection at runtime while hiding translation complexity:

```python
def get_llm(config: LLMConfig) -> BaseLLM:
    provider_class = PROVIDER_REGISTRY[config.llm_type]
    return provider_class(config)
```

---

## Part II: Wire Format Analysis

### Message Format Families

Analysis reveals three primary wire format families across LLM providers, each with distinct structural assumptions:

#### 1. OpenAI Chat Completions Format

```json
{
  "role": "assistant",
  "content": "I'll search for that information.",
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "web_search",
        "arguments": "{\"query\": \"weather today\"}"
      }
    }
  ]
}
```

**Characteristics**:
- Top-level `content` field for text (nullable when tool_calls present)
- Tool calls as separate `tool_calls` array
- Arguments serialized as JSON string (not object)
- String-based tool call IDs for attribution
- Separate `tool` role for results

**Adopters**: OpenAI, Azure OpenAI, Groq, Together AI, Fireworks, most open-source providers

#### 2. Anthropic Messages Format

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "I'll search for that information."
    },
    {
      "type": "tool_use",
      "id": "toolu_01abc",
      "name": "web_search",
      "input": {"query": "weather today"}
    }
  ]
}
```

**Characteristics**:
- Content as array of typed blocks (never null, never just string)
- Tool calls inline within content array as `tool_use` blocks
- Arguments as native JSON object (not string)
- Tool results as `tool_result` blocks referencing `tool_use_id`
- Supports additional block types: `thinking`, `citations`

**Adopters**: Anthropic Claude models

#### 3. Google/Gemini Format

```json
{
  "role": "model",
  "parts": [
    {"text": "I'll search for that information."},
    {
      "functionCall": {
        "name": "web_search",
        "args": {"query": "weather today"}
      }
    }
  ]
}
```

**Characteristics**:
- Content as `parts` array (not `content`)
- Role uses `model` instead of `assistant`
- Function calls as `functionCall` (camelCase)
- No explicit tool call ID (managed implicitly)
- Tool results as `functionResponse` parts

**Adopters**: Google Gemini, Vertex AI

#### 4. AWS Bedrock Converse Format

```json
{
  "role": "assistant",
  "content": [
    {"text": "I'll search for that information."},
    {
      "toolUse": {
        "toolUseId": "tooluse_abc",
        "name": "web_search",
        "input": {"query": "weather today"}
      }
    }
  ]
}
```

**Characteristics**:
- Hybrid of OpenAI structure with Anthropic content blocks
- camelCase field names (`toolUse`, `toolUseId`)
- Arguments as native object (like Anthropic)
- Unified format for multiple underlying models (Claude, Titan, Llama)

**Adopters**: AWS Bedrock (all models through Converse API)

### Translation Complexity Matrix

The following matrix shows the relative complexity of translating between format families:

| From \ To | OpenAI | Anthropic | Google | Bedrock |
|-----------|--------|-----------|--------|---------|
| OpenAI | - | Medium | Medium | Low |
| Anthropic | Medium | - | Medium | Low |
| Google | Medium | Medium | - | Medium |
| Bedrock | Low | Low | Medium | - |

**Key Translation Challenges**:

1. **Content String vs Array**: OpenAI's nullable string content must become array for Anthropic/Bedrock
2. **Tool Call Location**: OpenAI's separate `tool_calls` array must merge into content for Anthropic
3. **Arguments Encoding**: OpenAI's stringified JSON must be parsed for Anthropic/Bedrock
4. **Role Mapping**: Google's `model` role needs translation to `assistant`
5. **Tool Call ID Generation**: Google lacks explicit IDs, requiring synthetic generation

**Example Translation (OpenAI → Anthropic)**:

```python
def openai_to_anthropic(msg: dict) -> dict:
    content_blocks = []

    # Handle text content
    if msg.get("content"):
        content_blocks.append({
            "type": "text",
            "text": msg["content"]
        })

    # Translate tool calls to tool_use blocks
    for tc in msg.get("tool_calls", []):
        content_blocks.append({
            "type": "tool_use",
            "id": tc["id"],
            "name": tc["function"]["name"],
            # Parse stringified arguments
            "input": json.loads(tc["function"]["arguments"])
        })

    return {
        "role": msg["role"],
        "content": content_blocks
    }
```

### Schema Transmission Patterns

Tool schemas must be transmitted to providers in their expected format. The primary formats observed:

#### JSON Schema Format (OpenAI, Anthropic, Bedrock)

```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "Get current weather for a location",
    "parameters": {
      "type": "object",
      "properties": {
        "location": {
          "type": "string",
          "description": "City name"
        },
        "unit": {
          "type": "string",
          "enum": ["celsius", "fahrenheit"]
        }
      },
      "required": ["location"]
    }
  }
}
```

#### Function Declarations Format (Google)

```json
{
  "function_declarations": [
    {
      "name": "get_weather",
      "description": "Get current weather for a location",
      "parameters": {
        "type": "object",
        "properties": {
          "location": {"type": "string"},
          "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
        },
        "required": ["location"]
      }
    }
  ]
}
```

**Schema Generation Approaches Observed**:

1. **Introspection-Based** (Pydantic-AI, AutoGen): Generate JSON Schema from Python type hints
2. **Decorator-Based** (CrewAI, LangGraph): Extract from `@tool` decorator metadata
3. **Manual Definition** (Swarm, Agent-Zero): Require explicit schema in tool registration
4. **Hybrid** (LlamaIndex, MS Agent Framework): Support both automatic and manual schemas

---

## Part III: Tool Call Encoding Deep Dive

### Tool Call Lifecycle

The complete tool call lifecycle involves multiple encoding/decoding stages:

```
1. Schema Registration
   Python Function → JSON Schema → Provider Format

2. Model Invocation
   Schema + Messages → Provider API → Response with Tool Calls

3. Tool Call Extraction
   Provider Response → Internal Tool Call Objects

4. Tool Execution
   Tool Call Objects → Function Invocation → Results

5. Result Encoding
   Execution Results → Provider-Specific Tool Result Format

6. Continuation
   Original Messages + Tool Results → Provider API → Final Response
```

### Tool Call ID Management

Tool call IDs serve as correlation identifiers linking tool calls to their results. Provider handling varies significantly:

| Provider | ID Format | ID Generation | Required for Results |
|----------|-----------|---------------|---------------------|
| OpenAI | `call_{uuid}` | Server-generated | Yes |
| Anthropic | `toolu_{base64}` | Server-generated | Yes |
| Bedrock | `tooluse_{uuid}` | Server-generated | Yes |
| Google | (none) | N/A | Position-based |

**Google's Position-Based Correlation**:
Google Gemini lacks explicit tool call IDs, requiring frameworks to correlate results by position:

```python
# Agno's approach for Google
def correlate_tool_results(calls: list, results: list) -> list:
    # Match by index - assumes same order
    return [
        {"functionResponse": {"name": call["functionCall"]["name"], "response": result}}
        for call, result in zip(calls, results)
    ]
```

This creates fragility when parallel tool calls complete out of order.

**Synthetic ID Generation**:
Several frameworks generate synthetic IDs for providers that don't provide them:

```python
# MS Agent Framework approach
def ensure_tool_call_id(tool_call: ToolCall) -> ToolCall:
    if not tool_call.id:
        tool_call.id = f"synth_{uuid.uuid4().hex[:12]}"
    return tool_call
```

### Parallel Tool Calling

Modern LLMs can request multiple tool calls in a single response. Framework handling varies:

**Concurrent Execution** (AutoGen, Pydantic-AI, MS Agent Framework):
```python
async def execute_tool_calls(calls: list[ToolCall]) -> list[ToolResult]:
    tasks = [execute_single(call) for call in calls]
    return await asyncio.gather(*tasks)
```

**Sequential Execution** (Swarm, Agent-Zero):
```python
def execute_tool_calls(calls: list[ToolCall]) -> list[ToolResult]:
    results = []
    for call in calls:
        results.append(execute_single(call))
    return results
```

**Implications**:
- Concurrent execution improves latency for independent tools
- Sequential execution simplifies debugging and maintains determinism
- Some tools may have dependencies requiring sequential execution
- Hybrid approaches (concurrent with dependency graph) add complexity

### Tool Result Formatting

After execution, results must be encoded for the next model turn:

**OpenAI Format**:
```json
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "{\"temperature\": 72, \"unit\": \"fahrenheit\"}"
}
```

**Anthropic Format**:
```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_01abc",
      "content": "Temperature: 72F"
    }
  ]
}
```

**Critical Difference**: Anthropic requires tool results in a `user` role message with `tool_result` content blocks, while OpenAI uses a dedicated `tool` role.

**Error Result Handling**:
Frameworks handle tool execution errors differently:

```python
# Pydantic-AI approach - structured error
def format_error_result(call_id: str, error: Exception) -> ToolResult:
    return ToolResult(
        tool_call_id=call_id,
        content=json.dumps({
            "error": True,
            "error_type": type(error).__name__,
            "message": str(error)
        }),
        is_error=True
    )

# Swarm approach - string error
def format_error_result(call_id: str, error: Exception) -> dict:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": f"Error: {error}"
    }
```

The structured approach enables model reasoning about error types, while the string approach is simpler but provides less semantic information.

---

## Part IV: Streaming Implementation Patterns

### Streaming Protocol Landscape

LLM providers use different streaming protocols with distinct characteristics:

| Provider | Protocol | Event Format | Chunk Granularity |
|----------|----------|--------------|-------------------|
| OpenAI | SSE | `data: {json}` | Token-level deltas |
| Anthropic | SSE | Typed events | Block-level events |
| Google | Iterator | Native objects | Chunk objects |
| Bedrock | Event stream | Binary frames | Mixed granularity |

### Server-Sent Events (SSE) Handling

OpenAI and Anthropic both use SSE but with different event structures:

**OpenAI SSE Format**:
```
data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"Hello"}}]}

data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":" world"}}]}

data: [DONE]
```

**Anthropic SSE Format**:
```
event: message_start
data: {"type":"message_start","message":{"id":"msg_abc"}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}

event: message_stop
data: {"type":"message_stop"}
```

**Key Differences**:
1. Anthropic uses typed events (`message_start`, `content_block_delta`) vs OpenAI's uniform chunk format
2. Anthropic's block-level events enable richer streaming (tool calls stream separately from text)
3. OpenAI uses `[DONE]` sentinel vs Anthropic's `message_stop` event
4. Anthropic provides explicit block indexing for parallel content blocks

### Delta Accumulation Patterns

Streaming responses arrive as deltas that must be accumulated into complete messages:

**Token-by-Token Accumulation** (Simple):
```python
class SimpleAccumulator:
    def __init__(self):
        self.content = ""

    def add_delta(self, delta: str):
        self.content += delta

    def get_message(self) -> str:
        return self.content
```

**Block-Aware Accumulation** (Agno's MessageData):
```python
@dataclass
class MessageData:
    """Accumulates streaming response into complete message."""
    response_content: Any = ""
    response_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    response_content_blocks: List[Dict[str, Any]] = field(default_factory=list)

    def add_content_delta(self, delta: str):
        self.response_content += delta

    def add_tool_call_delta(self, index: int, delta: dict):
        while len(self.response_tool_calls) <= index:
            self.response_tool_calls.append({
                "id": "", "type": "function",
                "function": {"name": "", "arguments": ""}
            })
        tc = self.response_tool_calls[index]
        if "name" in delta:
            tc["function"]["name"] += delta["name"]
        if "arguments" in delta:
            tc["function"]["arguments"] += delta["arguments"]
```

**Stateful Streaming** (AWS Strands):
AWS Strands implements a state machine for streaming that tracks the current context:

```python
class StreamingState:
    def __init__(self):
        self.current_block_type: Optional[str] = None
        self.current_block_index: int = 0
        self.text_buffer: str = ""
        self.tool_call_buffers: Dict[int, ToolCallBuffer] = {}
        self.complete: bool = False

    def process_event(self, event: StreamEvent):
        if event.type == "contentBlockStart":
            self.current_block_type = event.content_block.type
            self.current_block_index = event.index
        elif event.type == "contentBlockDelta":
            if self.current_block_type == "text":
                self.text_buffer += event.delta.text
            elif self.current_block_type == "toolUse":
                self._accumulate_tool_call(event.delta)
        elif event.type == "messageStop":
            self.complete = True
```

### Streaming Tool Calls

Tool calls in streaming responses present special challenges because the arguments arrive as partial JSON:

**Partial JSON Accumulation**:
```python
# Tool call arguments stream as fragments:
# {"argum
# ents": {"loca
# tion": "New York"}}

class ToolCallAccumulator:
    def __init__(self):
        self.name = ""
        self.arguments_buffer = ""

    def add_delta(self, delta: dict):
        if "name" in delta:
            self.name += delta["name"]
        if "arguments" in delta:
            self.arguments_buffer += delta["arguments"]

    def get_arguments(self) -> dict:
        # Only parse when complete
        return json.loads(self.arguments_buffer)
```

**Early Tool Call Detection** (Pydantic-AI):
Pydantic-AI attempts to detect tool calls early for responsive UX:

```python
class StreamingToolDetector:
    def __init__(self):
        self.detected_tools: List[str] = []

    def check_partial(self, buffer: str):
        # Detect tool name before arguments complete
        if '"name":' in buffer:
            # Extract partial name for early notification
            match = re.search(r'"name":\s*"([^"]*)', buffer)
            if match and match.group(1) not in self.detected_tools:
                self.detected_tools.append(match.group(1))
                self.on_tool_detected(match.group(1))
```

### Backpressure and Flow Control

Streaming introduces backpressure concerns when consumers can't keep up with producers:

**Buffered Approach** (Most Frameworks):
```python
async def stream_with_buffer(response: AsyncIterator[Chunk], max_buffer: int = 100):
    buffer: List[Chunk] = []
    async for chunk in response:
        buffer.append(chunk)
        if len(buffer) >= max_buffer:
            yield buffer
            buffer = []
    if buffer:
        yield buffer
```

**Unbounded Approach** (Swarm, Agent-Zero):
These frameworks don't implement backpressure, relying on Python's async iteration:

```python
async for event in response:
    yield event  # No buffering, direct passthrough
```

**Implications**:
- Unbounded streaming is simpler but risks memory issues with slow consumers
- Buffered streaming adds latency but provides safety guarantees
- Production systems should implement backpressure for reliability

---

## Part V: Agentic Primitives

### System Prompt Assembly

System prompts define agent identity and capabilities. Frameworks use different assembly strategies:

**Static Template** (Swarm):
```python
def get_system_prompt(agent: Agent) -> str:
    return agent.instructions  # Simple static string
```

**Dynamic Assembly** (AutoGen, CrewAI):
```python
def assemble_system_prompt(agent: Agent, context: Context) -> str:
    parts = [agent.base_instructions]

    # Add tool descriptions
    if agent.tools:
        parts.append("You have access to the following tools:")
        for tool in agent.tools:
            parts.append(f"- {tool.name}: {tool.description}")

    # Add context
    if context.get("memory"):
        parts.append(f"Previous context: {context['memory']}")

    # Add constraints
    if agent.constraints:
        parts.append(f"Constraints: {agent.constraints}")

    return "\n\n".join(parts)
```

**Template Rendering** (MetaGPT):
MetaGPT uses Jinja-style templates for complex prompt assembly:

```python
SYSTEM_TEMPLATE = """
You are {{ role_name }}.
Your responsibilities: {{ responsibilities }}

{% if tools %}
Available actions:
{% for tool in tools %}
- {{ tool.name }}: {{ tool.description }}
{% endfor %}
{% endif %}

{% if context %}
Current context:
{{ context }}
{% endif %}
"""

def render_system_prompt(agent: Agent, context: dict) -> str:
    return Template(SYSTEM_TEMPLATE).render(
        role_name=agent.role,
        responsibilities=agent.responsibilities,
        tools=agent.tools,
        context=context
    )
```

### Scratchpad and Working Memory

Agents need working memory for multi-step reasoning. Implementation approaches:

**In-Context Scratchpad** (Agent-Zero):
Agent-Zero maintains a scratchpad directly in conversation context:

```python
class Scratchpad:
    def __init__(self):
        self.notes: List[str] = []

    def add(self, note: str):
        self.notes.append(note)

    def as_message(self) -> dict:
        return {
            "role": "system",
            "content": f"Working memory:\n" + "\n".join(self.notes)
        }

    def inject_into_messages(self, messages: List[dict]) -> List[dict]:
        # Insert scratchpad after system prompt
        return messages[:1] + [self.as_message()] + messages[1:]
```

**Structured Memory** (AutoGen, MS Agent Framework):
These frameworks maintain typed memory structures:

```python
@dataclass
class WorkingMemory:
    facts: Dict[str, Any] = field(default_factory=dict)
    hypotheses: List[str] = field(default_factory=list)
    plan: List[str] = field(default_factory=list)
    completed_steps: List[str] = field(default_factory=list)

    def to_prompt_section(self) -> str:
        sections = []
        if self.facts:
            sections.append(f"Known facts: {json.dumps(self.facts)}")
        if self.plan:
            sections.append(f"Current plan:\n" + "\n".join(
                f"{'[x]' if s in self.completed_steps else '[ ]'} {s}"
                for s in self.plan
            ))
        return "\n".join(sections)
```

**External Memory Store** (LlamaIndex):
LlamaIndex supports external memory through vector stores and retrievers:

```python
class MemoryEnabledAgent:
    def __init__(self, memory_index: VectorStoreIndex):
        self.memory = memory_index

    async def retrieve_relevant_memory(self, query: str) -> List[str]:
        retriever = self.memory.as_retriever(similarity_top_k=5)
        nodes = await retriever.aretrieve(query)
        return [node.text for node in nodes]

    async def augment_messages(self, messages: List[dict]) -> List[dict]:
        # Get relevant memory for current context
        last_user_msg = next(m for m in reversed(messages) if m["role"] == "user")
        memories = await self.retrieve_relevant_memory(last_user_msg["content"])

        if memories:
            memory_msg = {
                "role": "system",
                "content": f"Relevant past context:\n" + "\n".join(memories)
            }
            return messages[:1] + [memory_msg] + messages[1:]
        return messages
```

### Human-in-the-Loop (HITL) Patterns

HITL enables human oversight of agent actions. Implementation patterns observed:

**Confirmation Gate** (Swarm, Pydantic-AI):
```python
class ConfirmationGate:
    def __init__(self, require_confirmation: Callable[[ToolCall], bool]):
        self.require_confirmation = require_confirmation

    async def check(self, tool_call: ToolCall) -> bool:
        if self.require_confirmation(tool_call):
            # Block execution until human confirms
            return await self.get_human_confirmation(tool_call)
        return True

    async def get_human_confirmation(self, tool_call: ToolCall) -> bool:
        print(f"Agent wants to execute: {tool_call.name}({tool_call.arguments})")
        response = input("Allow? (y/n): ")
        return response.lower() == "y"
```

**Approval Workflow** (AutoGen):
AutoGen implements a more sophisticated approval workflow:

```python
class HumanApprovalAgent:
    """Agent that requires human approval for certain actions."""

    async def process_tool_calls(self, calls: List[ToolCall]) -> List[ToolResult]:
        results = []
        for call in calls:
            if self.needs_approval(call):
                approval = await self.request_approval(call)
                if approval.approved:
                    results.append(await self.execute(call))
                else:
                    results.append(ToolResult(
                        tool_call_id=call.id,
                        content=f"Action denied by human: {approval.reason}",
                        is_error=True
                    ))
            else:
                results.append(await self.execute(call))
        return results

    def needs_approval(self, call: ToolCall) -> bool:
        # Configurable approval rules
        return call.name in self.sensitive_tools
```

**Interrupt Mechanism** (Google ADK):
Google ADK provides an interrupt mechanism for pausing agent execution:

```python
class InterruptibleAgent:
    def __init__(self):
        self.interrupt_requested = False
        self.interrupt_reason: Optional[str] = None

    async def run(self, messages: List[dict]) -> AsyncIterator[Event]:
        while not self.should_stop():
            if self.interrupt_requested:
                yield InterruptEvent(reason=self.interrupt_reason)
                # Wait for resume signal
                await self.wait_for_resume()

            response = await self.model.generate(messages)
            yield ResponseEvent(response)

            if response.has_tool_calls:
                for call in response.tool_calls:
                    if self.interrupt_requested:
                        yield InterruptEvent(
                            reason=self.interrupt_reason,
                            pending_call=call
                        )
                        await self.wait_for_resume()
                    result = await self.execute(call)
                    messages.append(result.as_message())
```

### Conversation State Management

Agents must manage conversation state across turns. Patterns observed:

**Immutable State** (Pydantic-AI):
```python
@dataclass(frozen=True)
class ConversationState:
    messages: Tuple[Message, ...]
    tool_calls_pending: Tuple[ToolCall, ...]
    iteration: int

    def with_message(self, message: Message) -> "ConversationState":
        return ConversationState(
            messages=self.messages + (message,),
            tool_calls_pending=self.tool_calls_pending,
            iteration=self.iteration
        )

    def with_iteration(self) -> "ConversationState":
        return ConversationState(
            messages=self.messages,
            tool_calls_pending=(),
            iteration=self.iteration + 1
        )
```

**Mutable State Machine** (LangGraph):
LangGraph uses explicit state machines for complex flows:

```python
class AgentState(TypedDict):
    messages: List[Message]
    current_node: str
    tool_calls: List[ToolCall]
    iteration_count: int

def create_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("reason", reason_node)
    graph.add_node("execute_tools", execute_tools_node)
    graph.add_node("respond", respond_node)

    graph.add_edge("reason", should_execute_tools)
    graph.add_edge("execute_tools", "reason")
    graph.add_edge("reason", "respond")

    return graph.compile()
```

**Event-Sourced State** (MS Agent Framework):
```python
class EventSourcedConversation:
    def __init__(self):
        self.events: List[ConversationEvent] = []

    def apply(self, event: ConversationEvent):
        self.events.append(event)

    def get_state(self) -> ConversationState:
        state = ConversationState.initial()
        for event in self.events:
            state = event.apply_to(state)
        return state

    def get_messages(self) -> List[Message]:
        return self.get_state().messages
```

---

## Part VI: Advanced Content Block Patterns

### Content Block Type Taxonomy

Modern LLM APIs support rich content beyond plain text. Analysis reveals these block types across providers:

| Block Type | OpenAI | Anthropic | Google | Bedrock |
|------------|--------|-----------|--------|---------|
| Text | Yes | Yes | Yes | Yes |
| Image | Yes | Yes | Yes | Yes |
| Audio | Yes | No | Yes | No |
| Video | No | No | Yes | No |
| Tool Call | Yes | Yes | Yes | Yes |
| Tool Result | Yes | Yes | Yes | Yes |
| Thinking | No | Yes | No | No |
| Citations | No | Yes | No | No |
| Code Execution | No | No | Yes | No |

### Thinking Blocks (Anthropic-Specific)

Claude's "extended thinking" feature surfaces reasoning steps as explicit blocks:

```json
{
  "type": "thinking",
  "thinking": "Let me analyze this step by step...\n1. First consideration...\n2. Second point..."
}
```

**Framework Handling**:

**Pydantic-AI** - Explicit thinking support:
```python
class ThinkingBlock:
    type: Literal["thinking"] = "thinking"
    content: str

def parse_anthropic_content(blocks: List[dict]) -> List[ContentPart]:
    parts = []
    for block in blocks:
        if block["type"] == "thinking":
            parts.append(ThinkingBlock(content=block["thinking"]))
        elif block["type"] == "text":
            parts.append(TextPart(text=block["text"]))
    return parts
```

**Most Frameworks** - Thinking blocks ignored or stripped:
```python
def parse_content(blocks: List[dict]) -> str:
    # Only extract text content, ignore thinking blocks
    return "".join(
        b["text"] for b in blocks if b["type"] == "text"
    )
```

### Citation Blocks (Anthropic-Specific)

Claude can provide citations for claims when provided with documents:

```json
{
  "type": "citation",
  "cited_text": "The revenue grew 15% year-over-year",
  "document_title": "Q4 Earnings Report",
  "document_index": 0,
  "start_char_offset": 1234,
  "end_char_offset": 1275
}
```

**Framework Support**:
Most frameworks do not explicitly support citations, passing them through as unknown content or discarding them. LlamaIndex has emerging support through its document citation features.

### Multimodal Content Handling

**Image Input Patterns**:

```python
# OpenAI format
{
    "type": "image_url",
    "image_url": {
        "url": "data:image/png;base64,{base64_data}",
        "detail": "high"  # or "low", "auto"
    }
}

# Anthropic format
{
    "type": "image",
    "source": {
        "type": "base64",
        "media_type": "image/png",
        "data": "{base64_data}"
    }
}

# Google format
{
    "inline_data": {
        "mime_type": "image/png",
        "data": "{base64_data}"
    }
}
```

**Framework Abstraction** (LlamaIndex):
```python
class ImageBlock(BaseModel):
    block_type: Literal["image"] = "image"
    image: bytes  # Raw bytes
    mime_type: str = "image/png"

    def to_openai(self) -> dict:
        b64 = base64.b64encode(self.image).decode()
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{self.mime_type};base64,{b64}"}
        }

    def to_anthropic(self) -> dict:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": self.mime_type,
                "data": base64.b64encode(self.image).decode()
            }
        }
```

---

## Part VII: Error Handling and Resilience

### Error Classification

Errors in the HMP layer fall into several categories:

| Category | Examples | Recovery Strategy |
|----------|----------|-------------------|
| **Network** | Timeout, connection reset | Retry with backoff |
| **Rate Limit** | 429 errors, quota exceeded | Exponential backoff, queue |
| **Authentication** | Invalid API key, expired token | Fail fast, notify |
| **Validation** | Malformed request, schema error | Fix and retry |
| **Model** | Content policy, context length | Adjust and retry |
| **Tool** | Execution failure, timeout | Return error to model |

### Retry Strategies Observed

**Simple Exponential Backoff** (Swarm):
```python
def call_with_retry(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return func()
        except RateLimitError:
            wait = 2 ** attempt
            time.sleep(wait)
    raise MaxRetriesExceeded()
```

**Sophisticated Retry** (Pydantic-AI, AutoGen):
```python
class RetryPolicy:
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter: bool = True,
        retryable_errors: Set[Type[Exception]] = {RateLimitError, TimeoutError}
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.retryable_errors = retryable_errors

    def should_retry(self, error: Exception, attempt: int) -> bool:
        if attempt >= self.max_attempts:
            return False
        return type(error) in self.retryable_errors

    def get_delay(self, attempt: int) -> float:
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        if self.jitter:
            delay *= random.uniform(0.5, 1.5)
        return delay
```

**Provider-Specific Retry** (MS Agent Framework):
```python
class ProviderAwareRetry:
    RETRY_HEADERS = {
        "openai": "retry-after",
        "anthropic": "retry-after",
        "google": "retry-delay-ms"
    }

    def get_retry_delay(self, response: Response, provider: str) -> float:
        header = self.RETRY_HEADERS.get(provider)
        if header and header in response.headers:
            return float(response.headers[header])
        return self.default_policy.get_delay(self.attempt)
```

### Error Propagation Patterns

**Structured Error Types** (Pydantic-AI):
```python
class LLMError(Exception):
    """Base error for LLM operations."""
    pass

class RateLimitError(LLMError):
    retry_after: Optional[float] = None

class ValidationError(LLMError):
    field: str
    message: str

class ContentPolicyError(LLMError):
    categories: List[str]

class ContextLengthError(LLMError):
    limit: int
    actual: int
```

**Error Wrapping** (AutoGen):
```python
def wrap_provider_error(error: Exception, provider: str) -> LLMError:
    """Normalize provider errors to internal types."""
    error_map = {
        "openai": {
            openai.RateLimitError: RateLimitError,
            openai.BadRequestError: ValidationError,
            openai.AuthenticationError: AuthenticationError,
        },
        "anthropic": {
            anthropic.RateLimitError: RateLimitError,
            anthropic.BadRequestError: ValidationError,
        }
    }

    provider_map = error_map.get(provider, {})
    for provider_error, internal_error in provider_map.items():
        if isinstance(error, provider_error):
            return internal_error(str(error))

    return LLMError(f"Unknown error from {provider}: {error}")
```

### Context Length Management

Context length limits are a common source of errors:

**Preemptive Truncation** (AutoGen, LangGraph):
```python
class ContextManager:
    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens
        self.tokenizer = get_tokenizer()

    def fit_messages(self, messages: List[dict]) -> List[dict]:
        total_tokens = sum(self.count_tokens(m) for m in messages)

        if total_tokens <= self.max_tokens:
            return messages

        # Keep system message and recent messages
        system = messages[0] if messages[0]["role"] == "system" else None
        remaining = self.max_tokens - (self.count_tokens(system) if system else 0)

        fitted = []
        for msg in reversed(messages[1:] if system else messages):
            msg_tokens = self.count_tokens(msg)
            if msg_tokens <= remaining:
                fitted.insert(0, msg)
                remaining -= msg_tokens
            else:
                break

        return ([system] if system else []) + fitted
```

**Summarization Fallback** (LlamaIndex):
```python
class SummarizingContextManager:
    async def fit_messages(self, messages: List[dict]) -> List[dict]:
        if self.fits(messages):
            return messages

        # Summarize older messages
        old_messages = messages[1:-5]  # Keep system and last 5
        summary = await self.summarize(old_messages)

        return [
            messages[0],  # System
            {"role": "system", "content": f"Previous conversation summary: {summary}"},
            *messages[-5:]  # Recent messages
        ]
```

---

## Part VIII: Anti-Patterns Catalog

### 1. Leaky Abstractions

**Pattern**: Provider-specific details leak through abstraction layers.

**Example** (observed in multiple frameworks):
```python
class Message:
    content: str
    # Leaky: Anthropic-specific field exposed in universal type
    thinking: Optional[str] = None
    # Leaky: OpenAI-specific field
    function_call: Optional[dict] = None
```

**Better Approach**:
```python
class Message:
    content: str
    # Provider-specific data stored opaquely
    provider_metadata: dict = Field(default_factory=dict)
```

### 2. String Concatenation for Prompt Assembly

**Pattern**: Building prompts through string concatenation instead of structured composition.

**Example**:
```python
def build_prompt(agent, context):
    prompt = agent.instructions + "\n\n"
    prompt += "Tools:\n"
    for tool in agent.tools:
        prompt += f"- {tool.name}\n"
    prompt += "\nContext:\n" + str(context)
    return prompt
```

**Problems**:
- No escaping or injection protection
- Difficult to modify individual sections
- No validation of prompt structure
- Hard to test components in isolation

**Better Approach**:
```python
class PromptBuilder:
    def __init__(self):
        self.sections: List[PromptSection] = []

    def add_section(self, name: str, content: str, priority: int = 0):
        self.sections.append(PromptSection(name, content, priority))

    def build(self) -> str:
        sorted_sections = sorted(self.sections, key=lambda s: s.priority)
        return "\n\n".join(s.content for s in sorted_sections)
```

### 3. Implicit Provider Detection

**Pattern**: Guessing provider from model name string.

**Example**:
```python
def get_provider(model: str) -> str:
    if "gpt" in model.lower():
        return "openai"
    elif "claude" in model.lower():
        return "anthropic"
    elif "gemini" in model.lower():
        return "google"
    return "unknown"
```

**Problems**:
- Fragile to new model names
- Ambiguous for fine-tuned models
- No validation of assumption

**Better Approach**:
```python
class ModelConfig:
    model_id: str
    provider: str  # Explicit, required

    @classmethod
    def openai(cls, model: str) -> "ModelConfig":
        return cls(model_id=model, provider="openai")
```

### 4. Synchronous Tool Execution in Async Context

**Pattern**: Blocking on tool execution in async streaming handlers.

**Example**:
```python
async def handle_stream(response):
    async for chunk in response:
        if chunk.has_tool_call:
            # BLOCKING: Defeats purpose of async
            result = execute_tool_sync(chunk.tool_call)
            yield result
```

**Better Approach**:
```python
async def handle_stream(response):
    async for chunk in response:
        if chunk.has_tool_call:
            # Non-blocking
            result = await execute_tool_async(chunk.tool_call)
            yield result
```

### 5. Unbounded Message History

**Pattern**: Accumulating all messages without pruning or summarization.

**Example**:
```python
class Agent:
    def __init__(self):
        self.messages = []  # Grows forever

    async def chat(self, user_message: str):
        self.messages.append({"role": "user", "content": user_message})
        response = await self.llm.generate(self.messages)
        self.messages.append(response)  # Never pruned
        return response
```

**Problems**:
- Eventually exceeds context window
- Memory grows unboundedly
- Older context may be irrelevant

**Better Approach**:
```python
class Agent:
    def __init__(self, max_messages: int = 50):
        self.messages: deque = deque(maxlen=max_messages)
        self.summary: Optional[str] = None

    async def chat(self, user_message: str):
        if len(self.messages) >= self.messages.maxlen - 5:
            await self.summarize_old_messages()
        # Continue with pruned context
```

### 6. Ignoring Tool Call IDs

**Pattern**: Not properly tracking tool call IDs for result attribution.

**Example**:
```python
def execute_tools(tool_calls):
    results = []
    for call in tool_calls:
        result = execute(call)
        results.append({
            "role": "tool",
            "content": str(result)
            # Missing: tool_call_id
        })
    return results
```

**Problems**:
- Model cannot correlate results with calls
- Parallel tool calls become ambiguous
- Some providers reject responses without IDs

### 7. Hardcoded Provider URLs

**Pattern**: Embedding provider endpoints in code.

**Example**:
```python
class OpenAIClient:
    BASE_URL = "https://api.openai.com/v1"  # Hardcoded
```

**Problems**:
- Cannot use proxies or custom endpoints
- Azure OpenAI requires different URLs
- Testing requires mocking at HTTP level

**Better Approach**:
```python
class OpenAIClient:
    def __init__(self, base_url: str = "https://api.openai.com/v1"):
        self.base_url = base_url
```

### 8. Missing Capability Detection

**Pattern**: Assuming all models support all features.

**Example**:
```python
def generate(messages, tools):
    # Assumes all models support tools
    return client.chat(messages=messages, tools=tools)
```

**Problems**:
- Fails for models without tool support
- May get degraded responses without warning
- No graceful fallback

**Better Approach**:
```python
class ModelCapabilities:
    supports_tools: bool
    supports_vision: bool
    supports_streaming: bool
    max_context_length: int

def generate(messages, tools, capabilities: ModelCapabilities):
    if tools and not capabilities.supports_tools:
        raise UnsupportedFeatureError("Model does not support tools")
    # Proceed with validated capabilities
```

---

## Part IX: Design Recommendations

### For New Framework Development

Based on the analysis of 14 frameworks, the following recommendations emerge for designing a new agent framework's HMP layer:

#### 1. Choose Unified Internal Types

The Unified Internal Types strategy offers the best balance of flexibility and maintainability. Implement:

```python
@dataclass(frozen=True)
class ContentBlock:
    """Base for all content types with discriminator."""
    block_type: str

@dataclass(frozen=True)
class TextBlock(ContentBlock):
    block_type: Literal["text"] = "text"
    text: str

@dataclass(frozen=True)
class ToolCallBlock(ContentBlock):
    block_type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: Dict[str, Any]

@dataclass(frozen=True)
class Message:
    role: str
    blocks: Tuple[ContentBlock, ...]
    metadata: Dict[str, Any] = field(default_factory=dict)
```

#### 2. Implement Provider Adapters as Protocols

```python
class ProviderAdapter(Protocol):
    """Contract for all provider adapters."""

    def to_wire_format(self, messages: List[Message]) -> Any:
        """Convert internal messages to provider format."""
        ...

    def from_wire_format(self, response: Any) -> Message:
        """Convert provider response to internal format."""
        ...

    def format_tools(self, tools: List[Tool]) -> Any:
        """Convert tool definitions to provider format."""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Report provider capabilities."""
        ...
```

#### 3. Design for Streaming First

Make streaming the default path, with non-streaming as a convenience wrapper:

```python
class LLMClient:
    async def stream(
        self,
        messages: List[Message],
        tools: Optional[List[Tool]] = None
    ) -> AsyncIterator[StreamEvent]:
        """Primary interface - always streams."""
        ...

    async def complete(
        self,
        messages: List[Message],
        tools: Optional[List[Tool]] = None
    ) -> Message:
        """Convenience wrapper that accumulates stream."""
        accumulator = MessageAccumulator()
        async for event in self.stream(messages, tools):
            accumulator.add(event)
        return accumulator.get_message()
```

#### 4. Explicit Capability Negotiation

```python
@dataclass
class ProviderCapabilities:
    supports_tools: bool = True
    supports_parallel_tools: bool = True
    supports_vision: bool = False
    supports_audio: bool = False
    supports_streaming: bool = True
    supports_thinking: bool = False
    max_context_tokens: int = 128000
    max_output_tokens: int = 4096

def negotiate_capabilities(
    required: ProviderCapabilities,
    available: ProviderCapabilities
) -> ProviderCapabilities:
    """Determine effective capabilities, raise if requirements unmet."""
    if required.supports_tools and not available.supports_tools:
        raise CapabilityMismatch("Tools required but not available")
    # Return intersection of capabilities
    return ProviderCapabilities(
        supports_tools=required.supports_tools and available.supports_tools,
        # ...
    )
```

#### 5. Structured Error Hierarchy

```python
class HMPError(Exception):
    """Base for all HMP layer errors."""
    recoverable: bool = False

class TransientError(HMPError):
    """Errors that may succeed on retry."""
    recoverable = True
    retry_after: Optional[float] = None

class PermanentError(HMPError):
    """Errors that will not succeed on retry."""
    recoverable = False

class RateLimitError(TransientError):
    pass

class AuthenticationError(PermanentError):
    pass

class ValidationError(PermanentError):
    field: str
    message: str
```

#### 6. Composable Middleware Architecture

```python
class Middleware(Protocol):
    async def process(
        self,
        request: LLMRequest,
        next: Callable[[LLMRequest], Awaitable[LLMResponse]]
    ) -> LLMResponse:
        ...

class RetryMiddleware(Middleware):
    async def process(self, request, next):
        for attempt in range(self.max_retries):
            try:
                return await next(request)
            except TransientError as e:
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(e.retry_after or self.get_delay(attempt))

class LoggingMiddleware(Middleware):
    async def process(self, request, next):
        self.log_request(request)
        response = await next(request)
        self.log_response(response)
        return response

# Compose middleware stack
client = LLMClient(
    middlewares=[LoggingMiddleware(), RetryMiddleware(), RateLimitMiddleware()]
)
```

### Migration Recommendations for Existing Frameworks

For frameworks looking to improve their HMP layer:

1. **Audit provider-specific leakage**: Identify where provider details leak through abstractions
2. **Introduce capability detection**: Add explicit capability checking before feature use
3. **Standardize error types**: Create consistent error hierarchy across providers
4. **Add streaming accumulators**: Implement proper delta accumulation for streaming
5. **Implement tool call ID tracking**: Ensure proper correlation of calls and results
6. **Add context length management**: Implement preemptive truncation or summarization

---

## Part X: Comparative Analysis Matrix

### Provider Abstraction Strategy Comparison

| Framework | Strategy | Provider Count | Extensibility | Maintenance Burden |
|-----------|----------|----------------|---------------|-------------------|
| LangGraph | Delegation | 100+ (LangChain) | Low | Inherited |
| CrewAI | Delegation | 100+ (LiteLLM) | Low | Inherited |
| AutoGen | Unified Types | 4 native | High | Medium |
| LlamaIndex | Unified Types | 6 native | High | Medium |
| Pydantic-AI | Unified Types | 4 native | High | Medium |
| MS Agent | Gateway | 3 native | High | Medium |
| CAMEL | Unified Types | 5 native | High | High |
| Agno | Native SDKs | 8 native | Low | High |
| AWS Strands | Native (Bedrock) | 1 (multi-model) | Low | Low |
| Swarm | OpenAI-Native | 1 | None | None |
| OpenAI Agents | OpenAI-Native | 3 | Low | Low |
| MetaGPT | OpenAI-Native | 4 | Low | Medium |
| Agent-Zero | Universal Adapter | Many | Medium | Medium |
| Google ADK | Native (Gemini) | 1 | Low | Low |

### Feature Support Matrix

| Framework | Streaming | Parallel Tools | Vision | Thinking Blocks | HITL |
|-----------|-----------|----------------|--------|-----------------|------|
| LangGraph | Yes | Yes | Yes | Via LangChain | Callbacks |
| CrewAI | Yes | Yes | Yes | No | Yes |
| AutoGen | Yes | Yes | Yes | No | Yes |
| LlamaIndex | Yes | Yes | Yes | Partial | No |
| Pydantic-AI | Yes | Yes | Yes | Yes | Yes |
| MS Agent | Yes | Yes | Yes | Partial | Yes |
| CAMEL | Yes | No | Yes | No | No |
| Agno | Yes | Yes | Yes | Partial | Yes |
| AWS Strands | Yes | Yes | Yes | No | Yes |
| Swarm | Yes | No | No | No | Basic |
| OpenAI Agents | Yes | Yes | Yes | No | Yes |
| MetaGPT | Partial | No | No | No | No |
| Agent-Zero | Partial | No | Yes | No | Yes |
| Google ADK | Yes | Yes | Yes | No | Yes |

### Streaming Implementation Quality

| Framework | Stream Architecture | Backpressure | Error Recovery | Tool Call Streaming |
|-----------|---------------------|--------------|----------------|---------------------|
| LangGraph | Callbacks + Events | Via LangChain | Via LangChain | Yes |
| CrewAI | Generator | No | Basic | Limited |
| AutoGen | Event-based | No | Yes | Yes |
| LlamaIndex | Generator | No | Yes | Yes |
| Pydantic-AI | AsyncIterator | No | Yes | Yes |
| MS Agent | AsyncIterator | Basic | Yes | Yes |
| CAMEL | Generator | No | No | No |
| Agno | AsyncIterator + Accumulator | No | Yes | Yes |
| AWS Strands | Event Stream | Yes | Yes | Yes |
| Swarm | Generator | No | No | Limited |
| OpenAI Agents | AsyncIterator | No | Yes | Yes |
| MetaGPT | Partial | No | No | No |
| Agent-Zero | Basic | No | No | No |
| Google ADK | Iterator | No | Yes | Yes |

---

## Conclusion

The Harness-Model Protocol layer is a critical architectural decision point that shapes the entire agent framework. Analysis of 14 frameworks reveals:

1. **Four distinct abstraction strategies** with clear trade-offs between simplicity, flexibility, and maintenance burden
2. **Wire format translation** remains a significant source of bugs and complexity
3. **Streaming implementations** vary widely in sophistication, with many frameworks lacking proper backpressure handling
4. **Tool calling** is universally supported but with inconsistent ID management and error handling
5. **Agentic primitives** (system prompts, memory, HITL) have diverse implementations without established patterns

For new framework development, the Unified Internal Types strategy with Protocol-based adapters offers the best balance. Streaming should be the primary interface, with non-streaming as a convenience wrapper. Explicit capability negotiation prevents runtime surprises.

The most successful frameworks share these characteristics:
- **Clear separation** between internal representation and wire format
- **Explicit capability modeling** rather than runtime discovery
- **Structured error hierarchies** that enable intelligent retry
- **Composable middleware** for cross-cutting concerns
- **First-class streaming support** with proper accumulation

These patterns should guide both new framework development and evolution of existing systems.

---

*Report generated from analysis of 14 agent frameworks, comprising 11,602 lines of HMP analysis documentation.*
