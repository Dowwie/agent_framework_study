# Memory Orchestration: crewAI

## Summary
- **Memory Tiers**: Four-tier system - Short-term, Long-term, Entity, External
- **Context Assembly**: Sequential concatenation of system + history + user
- **Eviction Strategy**: No automatic eviction - context window handling is opt-in
- **Token Management**: Tracking via callbacks, optional truncation

## Detailed Analysis

### Memory Architecture

**Four-Tier System**:

1. **Short-Term Memory** (memory/short_term/short_term_memory.py):
   - Storage: RAGStorage or Mem0Storage
   - Purpose: Recent conversation history
   - Scope: Current execution
   - Eviction: None automatic

2. **Long-Term Memory** (memory/long_term/long_term_memory.py):
   - Storage: SQLite or RAG
   - Purpose: Cross-execution learning
   - Scope: Persists across crew runs
   - Eviction: Database-managed

3. **Entity Memory** (memory/entity/entity_memory.py):
   - Storage: RAG-based
   - Purpose: Facts about entities (people, orgs, concepts)
   - Scope: Knowledge graph style
   - Eviction: Unknown

4. **External Memory** (memory/external/external_memory.py):
   - Storage: User-provided (Mem0 integration)
   - Purpose: Custom knowledge integration
   - Scope: Externally managed
   - Eviction: Provider-dependent

**Memory Creation** (crew_agent_executor.py:L206-208):
```python
self._create_short_term_memory(formatted_answer)
self._create_long_term_memory(formatted_answer)
self._create_external_memory(formatted_answer)
```

**Activation** (crew.py:L72):
```python
memory: bool = False  # Enables memory subsystem
```

### Context Assembly

**Message Structure** (utilities/types.py:L8):
```python
class LLMMessage(TypedDict):
    role: Literal["user", "assistant", "system"]
    content: str | list[dict[str, Any]]
```

**Assembly Pattern** (crew_agent_executor.py:L174-185):
```python
if "system" in self.prompt:
    system_prompt = self._format_prompt(self.prompt.get("system"), inputs)
    user_prompt = self._format_prompt(self.prompt.get("user"), inputs)
    self.messages.append(format_message_for_llm(system_prompt, role="system"))
    self.messages.append(format_message_for_llm(user_prompt))
else:
    user_prompt = self._format_prompt(self.prompt.get("prompt"), inputs)
    self.messages.append(format_message_for_llm(user_prompt))
```

**Order**: System → [History] → User → [Tool Results]
- System prompt: Agent configuration
- History: Retrieved from memory (if enabled)
- User: Current task
- Tool results: Appended during execution loop

**Retrieval** (memory/memory.py:L76):
```python
def search(self, query: str, limit: int = 5, score_threshold: float = 0.6):
    return self.storage.search(query, limit, score_threshold)
```

**Injection Point**: Before task execution, memory search results likely injected into prompt

### Token Management

**Counting** (agent/core.py:L76):
```python
from crewai.utilities.token_counter_callback import TokenCalcHandler
```

**Tracking** (types/usage_metrics.py:L11-46):
```python
class UsageMetrics(BaseModel):
    total_tokens: int = 0
    prompt_tokens: int = 0
    cached_prompt_tokens: int = 0
    completion_tokens: int = 0
    successful_requests: int = 0

    def add_usage_metrics(self, usage_metrics: Self) -> None:
        self.total_tokens += usage_metrics.total_tokens
        # In-place accumulation
```

**Budget Enforcement**:
- Optional via `respect_context_window: bool` (crew_agent_executor.py:L90)
- Utility: `handle_context_length` (crew_agent_executor.py:L36)
- Likely truncates oldest messages if limit exceeded

**No Proactive Eviction**:
- Messages accumulate unbounded by default
- Context window handling is reactive, not proactive
- No automatic summarization observed

### Memory Storage Backends

**RAGStorage** (memory/storage/rag_storage.py - referenced):
- Vector embeddings for semantic search
- Used by short-term, entity, external memory
- EmbedderConfig injection (memory/memory.py:L18)

**SQLite** (memory/storage/ltm_sqlite_storage.py - referenced):
- Structured storage for long-term memory
- SQL queries for retrieval

**Mem0** (memory/storage/mem0_storage.py - referenced):
- Third-party memory provider
- Opt-in via embedder_config (short_term_memory.py:L44)

**Interface** (memory/storage/interface.py - referenced):
- Common `save()` and `search()` methods
- Async variants: `asave()`, `asearch()`

### Memory Events

**Lifecycle Events** (short_term_memory.py:L9-16):
- `MemorySaveStartedEvent`, `MemorySaveCompletedEvent`, `MemorySaveFailedEvent`
- `MemoryQueryStartedEvent`, `MemoryQueryCompletedEvent`, `MemoryQueryFailedEvent`

**Emission Pattern**:
- Emitted by memory subsystem during save/query operations
- Enables observability and debugging

## Implications for New Framework

**Adopt**:
1. **Multi-tier memory** - separates transient from persistent, facts from conversations
2. **Pluggable storage** - RAG, SQL, external providers
3. **Semantic search** - vector embeddings for relevant retrieval
4. **Async memory operations** - don't block agent execution
5. **Memory events** - track save/retrieve operations

**Avoid**:
1. **No automatic eviction** - unbounded growth is dangerous
2. **Reactive context management** - wait until overflow instead of proactive summarization
3. **In-place metric mutation** - couples accumulation with metrics object
4. **Boolean memory flag** - coarse-grained, doesn't allow per-tier control

**Improve**:
1. Implement proactive summarization (sliding window with compression)
2. Add token budget per tier (e.g., short-term: 4K tokens, long-term: 1K tokens)
3. Use FIFO + recency-weighted eviction for short-term
4. Separate memory configuration from boolean flag (MemoryConfig object)
5. Add memory replay/rollback for debugging
6. Implement automatic fact extraction to entity memory
7. Use immutable metrics (return new instance from add_usage_metrics)

## Code References

- Memory base class: `lib/crewai/src/crewai/memory/memory.py:L15`
- Short-term memory: `lib/crewai/src/crewai/memory/short_term/short_term_memory.py`
- Long-term memory: `lib/crewai/src/crewai/memory/long_term/long_term_memory.py`
- Entity memory: `lib/crewai/src/crewai/memory/entity/entity_memory.py`
- External memory: `lib/crewai/src/crewai/memory/external/external_memory.py`
- Memory creation: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L206-208`
- Context assembly: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L174-185`
- Token tracking: `lib/crewai/src/crewai/types/usage_metrics.py:L11`
- Context handling: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L36`

## Anti-Patterns Observed

1. **No automatic eviction**: Messages accumulate until manual intervention
2. **Boolean memory flag**: All-or-nothing, can't enable subset of tiers
3. **Reactive truncation**: Wait for overflow instead of proactive management
4. **In-place metric accumulation**: Mutates shared object
5. **No summarization**: Old messages preserved verbatim
6. **Unbounded short-term memory**: Should have automatic FIFO eviction
