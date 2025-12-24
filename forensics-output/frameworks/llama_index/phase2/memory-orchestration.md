# Memory Orchestration: LlamaIndex

## Summary
- **Key Finding 1**: Token-based eviction strategy with FIFO (First In, First Out) message dropping
- **Key Finding 2**: Chat store abstraction separates memory interface from storage backend
- **Key Finding 3**: Simple concatenation for context assembly, no sophisticated RAG or summarization in base implementation
- **Classification**: Token-limited buffer with pluggable storage

## Detailed Analysis

### Context Assembly

**Method**: Simple concatenation

Memory returns a list of `ChatMessage` objects that are directly passed to the LLM. No fancy processing.

**Order**: User-defined, typically chronological
- System message (if present)
- Chat history (from memory.get())
- Current user query

**Evidence** (chat_memory_buffer.py:L114-151):
```python
def get(self, input: Optional[str] = None, initial_token_count: int = 0) -> List[ChatMessage]:
    chat_history = self.get_all()  # Get full history
    # ... token-based truncation ...
    return chat_history[-message_count:]  # Return last N messages that fit
```

The agent/workflow then uses this directly:
```python
memory_messages = memory.get()
llm_input = [system_message] + memory_messages + [user_query]
```

### Memory Tiers

LlamaIndex supports multiple memory tier implementations:

| Tier | Storage | Capacity | Location |
|------|---------|----------|----------|
| ChatMemoryBuffer | In-memory list (SimpleChatStore) | Token-limited | chat_memory_buffer.py:L19 |
| VectorMemory | Vector database | Unlimited (semantic retrieval) | vector_memory.py |
| ChatSummaryMemoryBuffer | Summarized history | Token-limited + summary | chat_summary_memory_buffer.py |
| ComposableMemory | Multiple memory blocks | Configurable | simple_composable_memory.py |
| BaseChatStoreMemory | Abstract with chat store | Backend-dependent | memory/types.py:L82 |

**Default**: ChatMemoryBuffer with SimpleChatStore

### Eviction Strategy

**Strategy**: Token-based FIFO with role-aware trimming

**Trigger**: Token count exceeds `token_limit`

**Location**: chat_memory_buffer.py:L114-151

**Algorithm**:
```python
1. Count tokens in current message history
2. If exceeds limit:
   a. Remove oldest message
   b. If removed message leaves ASSISTANT or TOOL at start:
      - Remove those too (maintain valid message sequence)
   c. Recount tokens
   d. Repeat until within limit OR only 1 message left
3. If single message exceeds limit:
   - Return empty list (pathological case)
```

**Role-Aware Trimming** (L130-140):
Ensures chat history doesn't start with ASSISTANT or TOOL messages (invalid for most LLMs):
```python
while chat_history[-message_count].role in (MessageRole.TOOL, MessageRole.ASSISTANT):
    message_count -= 1  # Remove preceding messages too
```

**Evidence**:
- Token counting: `len(self.tokenizer_fn(msg_str))` (L166)
- FIFO: `chat_history[-message_count:]` takes last N messages (L151)
- No summarization in base class (delegated to ChatSummaryMemoryBuffer)

### Token Management

**Counting Method**: Tokenizer function (default: tiktoken)

**Setup** (chat_memory_buffer.py:L13, L27-30, L161-166):
```python
tokenizer_fn: Callable[[str], List] = Field(
    default_factory=get_tokenizer,  # Uses tiktoken by default
    exclude=True,
)

def _token_count_for_messages(self, messages: List[ChatMessage]) -> int:
    msg_str = " ".join(str(m.content) for m in messages)
    return len(self.tokenizer_fn(msg_str))
```

**Budget Enforcement**: Yes, via `token_limit` parameter

**Token Limit Calculation** (L67-71):
```python
if llm is not None:
    context_window = llm.metadata.context_window
    token_limit = token_limit or int(context_window * DEFAULT_TOKEN_LIMIT_RATIO)
elif token_limit is None:
    token_limit = DEFAULT_TOKEN_LIMIT  # 3000 tokens
```

**DEFAULT_TOKEN_LIMIT_RATIO**: 0.75 (75% of context window reserved for history)

This leaves 25% for system prompt, user query, and LLM response.

### Storage Abstraction

**Chat Store Interface** (memory/types.py:L82-152):
```python
class BaseChatStoreMemory(BaseMemory):
    chat_store: SerializeAsAny[BaseChatStore] = Field(default_factory=SimpleChatStore)
    chat_store_key: str = Field(default=DEFAULT_CHAT_STORE_KEY)

    def get_all(self) -> List[ChatMessage]:
        return self.chat_store.get_messages(self.chat_store_key)

    def put(self, message: ChatMessage) -> None:
        self.chat_store.add_message(self.chat_store_key, message)
```

**Pluggable Backends**:
- `SimpleChatStore`: In-memory dict
- `RedisChatStore`: Redis backend (via integration)
- `PostgresChatStore`: PostgreSQL backend
- Custom stores via `BaseChatStore` interface

**Multi-Tenancy**: Supported via `chat_store_key` parameter (L86)

### Initial Token Count Parameter

**Purpose**: Reserve tokens for system prompt and other context

```python
def get(self, input: Optional[str] = None, initial_token_count: int = 0) -> List[ChatMessage]:
    if initial_token_count > self.token_limit:
        raise ValueError("Initial token count exceeds token limit")

    # ... eviction logic uses (token_count + initial_token_count) ...
```

This allows callers to say "I need 500 tokens for system prompt, so only give me messages that fit in remaining budget."

## Code References

- `llama-index-core/llama_index/core/memory/chat_memory_buffer.py:19` — ChatMemoryBuffer class
- `llama-index-core/llama_index/core/memory/chat_memory_buffer.py:114` — Eviction algorithm
- `llama-index-core/llama_index/core/memory/types.py:82` — BaseChatStoreMemory
- `llama-index-core/llama_index/core/memory/chat_summary_memory_buffer.py` — Summarization variant
- `llama-index-core/llama_index/core/storage/chat_store/base.py` — BaseChatStore interface

## Implications for New Framework

1. **Token-based eviction is essential**: Using a token limit rather than message count prevents context window overflow.

2. **Pluggable storage via abstract interface**: Separating memory logic from storage enables scaling (in-memory for dev, Redis for prod).

3. **Role-aware trimming**: Ensuring valid message sequences (no orphaned ASSISTANT/TOOL messages) prevents LLM errors.

4. **Initial token count parameter**: Reserving budget for non-history context is a simple but effective pattern.

5. **Default to 75% context window**: Leaving 25% for system prompt and response is a reasonable heuristic.

6. **Async wrappers via to_thread**: For I/O-heavy chat stores (Redis, Postgres), wrapping sync methods with `asyncio.to_thread()` is acceptable.

## Anti-Patterns Observed

1. **No summarization in base class**: When eviction happens, information is lost. Summarization should be built in, not an optional subclass.

2. **String concatenation for token counting**: Joining messages with spaces is approximate. Should use actual LLM tokenization on structured messages.

3. **Pathological case returns empty list**: If a single message exceeds token limit, returning `[]` silently loses data. Should raise an error or truncate the message.

4. **No semantic retrieval in base tier**: All history is chronological. For long conversations, semantic retrieval (RAG over history) would be valuable.

5. **Deprecated class still in use**: ChatMemoryBuffer is marked deprecated but is the default. Confusing for users.

6. **No eviction metrics**: No logging or events when messages are evicted, making it hard to debug context issues.

## Recommendations

- Implement summarization by default (not just in subclass)
- Use structured message tokenization (not string concatenation)
- Add eviction events for observability
- Raise error for oversized messages (don't silently drop all context)
- Implement hybrid memory: recent + semantic retrieval
- Add memory compression strategies (entity extraction, fact storage)
- Remove deprecated classes or promote them to first-class
