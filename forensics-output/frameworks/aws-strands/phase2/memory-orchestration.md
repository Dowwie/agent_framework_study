# Memory Orchestration: AWS Strands

## Summary
- **Key Finding 1**: Three-tier memory system (messages, session, conversation manager)
- **Key Finding 2**: Pluggable eviction strategies via ConversationManager ABC
- **Classification**: Managed state with configurable retention policies

## Detailed Analysis

### Memory Tiers

#### Tier 1: In-Memory Messages (agent.messages)
- **Type**: `List[Message]`
- **Scope**: Single agent invocation lifecycle
- **Retention**: Until agent garbage collected
- **Mutability**: Mutable list (append-only pattern)
- **Access**: Direct via `agent.messages`

#### Tier 2: Session State (SessionManager)
- **Type**: `Session`, `SessionAgent`, `SessionMessage`
- **Scope**: Across multiple agent invocations
- **Retention**: Until explicitly deleted
- **Persistence**: User-provided backend (DynamoDB, S3, etc.)
- **Serialization**: `to_dict()` / `from_dict()` with base64 encoding

#### Tier 3: Conversation Management (ConversationManager)
- **Type**: ABC with multiple strategies
- **Scope**: Controls Tier 1 size
- **Retention**: Based on strategy (sliding window, summarization)
- **Mutability**: Modifies `agent.messages` in-place

### Context Assembly

#### Message Structure (types/content.py:L178)
```python
class Message(TypedDict):
    content: List[ContentBlock]  # Heterogeneous content
    role: Role  # "user" | "assistant"
```

#### ContentBlock Types (types/content.py:L74)
- text: str
- image: ImageContent
- video: VideoContent
- document: DocumentContent
- toolUse: ToolUse
- toolResult: ToolResult
- reasoningContent: ReasoningContentBlock
- guardContent: GuardContent
- citationsContent: CitationsContentBlock
- cachePoint: CachePoint

**Assembly Pattern**:
```python
# User input
messages.append({
    "role": "user",
    "content": [{"text": user_input}]
})

# Model response with tool use
messages.append({
    "role": "assistant",
    "content": [
        {"text": "Let me check that..."},
        {"toolUse": {"name": "search", "toolUseId": "...", "input": {...}}}
    ]
})

# Tool result
messages.append({
    "role": "user",  # Tool results are "user" role!
    "content": [
        {"toolResult": {"toolUseId": "...", "content": [...], "status": "success"}}
    ]
})
```

**Critical Insight**: Tool results use "user" role (convention from Bedrock API)

### Eviction Policies

#### 1. SlidingWindowConversationManager
- **Strategy**: FIFO removal of oldest messages
- **Trigger**: Message count exceeds threshold
- **Implementation**: `messages.pop(0)` until size <= max
- **Tradeoff**: Loses long-term context

#### 2. SummarizingConversationManager
- **Strategy**: LLM-based compression of old messages
- **Trigger**: Message count exceeds threshold
- **Implementation**:
  1. Select messages to summarize (oldest N)
  2. Call LLM with summarization prompt
  3. Replace selected messages with single summary message
- **Tradeoff**: Summarization quality depends on LLM

#### 3. NullConversationManager
- **Strategy**: No eviction
- **Trigger**: Never
- **Implementation**: No-op
- **Tradeoff**: Eventual context window overflow

### Context Window Management

#### Overflow Detection
**Exception**: `ContextWindowOverflowException` raised by model

#### Recovery Flow
```python
try:
    response = await model.stream(messages, ...)
except ContextWindowOverflowException as e:
    conversation_manager.reduce_context(agent, e)
    # Retry with reduced context
    response = await model.stream(messages, ...)
```

#### reduce_context() Implementations

**SlidingWindow**:
```python
def reduce_context(self, agent, e=None, **kwargs):
    # Remove oldest N messages
    for _ in range(REDUCTION_SIZE):
        if len(agent.messages) > 0:
            agent.messages.pop(0)
            self.removed_message_count += 1
```

**Summarizing**:
```python
def reduce_context(self, agent, e=None, **kwargs):
    # Summarize oldest messages
    old_messages = agent.messages[:N]
    summary = await llm_summarize(old_messages)
    agent.messages = [summary] + agent.messages[N:]
    self.removed_message_count += N
```

### Short-Term vs Long-Term Memory

#### Short-Term (Working Memory)
- **Location**: `agent.messages` (Tier 1)
- **Scope**: Current conversation
- **Size**: Managed by ConversationManager
- **Typical Size**: 10-50 messages

#### Long-Term (Episodic Memory)
- **Location**: SessionManager (Tier 2)
- **Scope**: Across sessions
- **Size**: Unlimited (storage-dependent)
- **Access**: Restore via `session_manager.restore_session()`

**No semantic memory tier observed**:
- No vector embeddings
- No retrieval-augmented memory
- No importance-based filtering

### Memory Serialization

#### SessionMessage (types/session.py:L59)
```python
@dataclass
class SessionMessage:
    message: Message
    message_id: int
    redact_message: Optional[Message] = None  # Redaction support
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return encode_bytes_values(asdict(self))

    @classmethod
    def from_dict(cls, env: dict) -> "SessionMessage":
        return cls(**decode_bytes_values(extracted_params))
```

**Special Handling**:
- Base64 encode bytes values for JSON compatibility
- ISO timestamp strings
- Optional redaction (GDPR/privacy)
- Forward-compatible deserialization (ignores unknown keys)

#### SessionAgent (types/session.py:L108)
```python
@dataclass
class SessionAgent:
    agent_id: str
    state: dict[str, Any]  # User-managed state
    conversation_manager_state: dict[str, Any]
    _internal_state: dict[str, Any]  # Interrupt state, etc.
    created_at: str
    updated_at: str
```

**Restoration Pattern**:
```python
session_agent = SessionAgent.from_dict(loaded_data)
agent.state.update(session_agent.state)
agent.conversation_manager.restore_from_session(session_agent.conversation_manager_state)
session_agent.initialize_internal_state(agent)
```

### Cache Points (Prompt Caching)

#### CachePoint (types/content.py:L64)
```python
class CachePoint(TypedDict):
    type: str  # "default"
```

**Usage**: Inserted into content blocks to mark cacheable boundaries

**Purpose**: Optimize repeated context (system prompts, long documents)

**Provider Support**: Model-specific (e.g., Claude prompt caching)

### State Boundaries

#### User-Managed State
- **Location**: `agent.state` (AgentState object)
- **Type**: `dict[str, Any]`
- **Persistence**: Via SessionAgent
- **Access**: `agent.state.get()`, `agent.state.set(key, value)`

#### Framework-Managed State
- **Location**: `agent._internal_state`
- **Type**: `dict[str, Any]`
- **Contents**: `_interrupt_state`, future extensions
- **Persistence**: Automatic via SessionAgent
- **Access**: Private (underscore prefix)

### Memory Scaling Patterns

#### Horizontal Scaling (Multi-Agent)
- Each agent has isolated memory
- No shared memory tier
- Cross-agent communication via explicit messaging

#### Vertical Scaling (Context Growth)
- ConversationManager handles size limits
- Session storage offloads to external backends
- No automatic partitioning of large contexts

## Code References
- `src/strands/types/content.py:178-192` - Message and ContentBlock types
- `src/strands/types/session.py:59-105` - SessionMessage with serialization
- `src/strands/types/session.py:108-189` - SessionAgent state container
- `src/strands/agent/conversation_manager/conversation_manager.py:12-89` - ConversationManager ABC
- `src/strands/agent/conversation_manager/sliding_window_conversation_manager.py` - FIFO eviction
- `src/strands/agent/conversation_manager/summarizing_conversation_manager.py` - LLM compression

## Implications for New Framework
- **Adopt**: Three-tier memory (working, session, persistence)
- **Adopt**: Pluggable eviction strategies via ABC
- **Adopt**: Base64 encoding for bytes in JSON serialization
- **Adopt**: Forward-compatible deserialization (ignore unknown keys)
- **Adopt**: Redaction support for privacy compliance
- **Reconsider**: Add semantic memory tier (vector embeddings)
- **Reconsider**: Add importance-based filtering
- **Reconsider**: Functional message updates (avoid in-place mutation)

## Anti-Patterns Observed
- **In-Place Message Mutation**: ConversationManager directly modifies `agent.messages`
- **No Semantic Memory**: No vector-based retrieval (only sequential)
- **Tool Results as User Role**: Convention from Bedrock API (confusing)
- **Untyped State Dicts**: User state is `dict[str, Any]` (no validation)
