# Memory Orchestration: Google ADK

## Summary
- **Key Finding 1**: Three-tier memory: Session history + External memory service + Context caching
- **Key Finding 2**: No automatic summarization - full conversation history maintained
- **Classification**: Persistent session-based with optional vector memory

## Detailed Analysis

### Memory Tiers

```
Tier 1: Session State (Short-term)
  ├─ Conversation history (all messages)
  ├─ Agent state (per-agent state dict)
  ├─ Artifacts (file uploads, outputs)
  └─ Storage: SQLite, PostgreSQL, or in-memory

Tier 2: External Memory (Long-term)
  ├─ Vector-based retrieval
  ├─ Vertex AI Memory Bank
  └─ Vertex AI RAG (Retrieval-Augmented Generation)

Tier 3: Context Caching (Optimization)
  ├─ Gemini context cache
  ├─ Caches static instructions/tools
  └─ Reduces token usage for repeated content
```

### Session Management

**BaseSessionService** abstraction with implementations:
- `InMemorySessionService` - Non-persistent (testing)
- `SqliteSessionService` - Local persistence
- `DatabaseSessionService` - PostgreSQL/Cloud SQL
- `VertexAISessionService` - Vertex AI Agent Engine

**Session Schema**:
```python
Session:
  - session_id: str
  - events: list[Event]  # Full conversation history
  - agent_states: dict[str, Any]  # Per-agent state
  - artifacts: dict[str, bytes]  # File storage
  - created_at: datetime
  - updated_at: datetime
```

**Persistence Strategy**:
- Append-only event log
- No compaction or summarization
- All events retained indefinitely

### Memory Services

**BaseMemoryService** abstraction:
- `InMemoryMemoryService` - Simple in-memory store (no retrieval)
- `VertexAIMemoryBankService` - Vector-based memory with retrieval
- `VertexAIRAGMemoryService` - RAG integration

**MemoryEntry Schema**:
```python
MemoryEntry:
  - content: str
  - metadata: dict[str, str]
```

**Usage Pattern**:
```python
# Store memory
memory_service.add_memory(MemoryEntry(content="...", metadata={...}))

# Retrieve relevant memories
memories = memory_service.search(query="...", top_k=5)
```

### Context Assembly

**ContentsProcessor** builds the conversation history:

1. **Static Instructions**: System prompt (cached)
2. **Tools**: Function declarations (cached)
3. **Memory Retrieval**: Inject relevant memories from MemoryService
4. **Conversation History**: All previous events
5. **User Input**: Current message

**No Summarization**:
- Full conversation history sent on every LLM call
- Context window management left to developer
- No automatic sliding window

### Eviction Policies

**Session Events**: None (events accumulate indefinitely)

**Memory Service**: Implementation-dependent
- InMemoryMemoryService: No eviction (grows forever)
- VertexAIMemoryBankService: Managed by Vertex AI (FIFO likely)

**Context Cache**: Automatic TTL-based eviction by Gemini

### Context Caching Strategy

**ContextCacheProcessor**:
- Caches static content (instructions, tools)
- Reduces tokens for repeated content
- Automatic cache invalidation on changes

**Cache Lifecycle**:
```python
ContextCacheConfig:
  - ttl: timedelta  # Time to live
  - cache_id: str   # Cache identifier
```

### State Management

**Agent State**:
- Per-agent state dictionary stored in session
- Loaded via `BaseAgent._load_agent_state()`
- Updated via `InvocationContext.agent_states`

**Concurrency**:
- No distributed locking
- Last-write-wins semantics
- Race condition risk in multi-instance deployments

### Artifact Management

**BaseArtifactService** abstraction:
- `InMemoryArtifactService` - Non-persistent
- `FileArtifactService` - Local file system
- `GcsArtifactService` - Google Cloud Storage

**Artifact Operations**:
```python
# Save artifact
artifact_service.save(name="file.txt", data=bytes, metadata={})

# Load artifact
data = artifact_service.load(name="file.txt")

# List artifacts
names = artifact_service.list()
```

## Implications for New Framework

### Positive Patterns
- **Three-tier approach**: Session + Memory + Cache covers short/long term needs
- **Service abstraction**: Easy to swap storage backends
- **Context caching**: Smart optimization for repeated content
- **Artifact handling**: Built-in file storage

### Considerations
- **No summarization**: Token usage explodes for long conversations
- **No eviction**: Sessions grow unbounded (disk space risk)
- **No compression**: Events stored as-is (no deduplication)
- **No distributed lock**: Concurrent writes can corrupt state

## Code References
- `sessions/base_session_service.py` - Session abstraction
- `sessions/database_session_service.py` - PostgreSQL implementation
- `sessions/sqlite_session_service.py` - SQLite implementation
- `sessions/session.py` - Session data model
- `sessions/state.py` - Agent state management
- `memory/base_memory_service.py` - Memory abstraction
- `memory/vertex_ai_memory_bank_service.py` - Vector memory
- `memory/memory_entry.py` - Memory data model
- `artifacts/base_artifact_service.py` - Artifact abstraction
- `flows/llm_flows/context_cache_processor.py` - Context caching

## Anti-Patterns Observed
- **Unbounded growth**: No automatic conversation summarization or trimming
- **No memory budget**: Framework allows sessions to grow to arbitrary size
- **No indexing**: InMemoryMemoryService is O(n) lookup (no vector search)
- **Weak concurrency**: No optimistic locking for state updates
