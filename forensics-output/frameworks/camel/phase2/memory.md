# Memory Orchestration Analysis: CAMEL

## Memory Architecture

### Layered Design

CAMEL implements a **4-layer memory architecture:**

```
Layer 4: Agent Memory (High-level interface)
   ├── ChatHistoryMemory
   ├── VectorDBMemory
   └── LongtermAgentMemory (combines both)
        ↓
Layer 3: Context Creators (Retrieval logic)
   └── ScoreBasedContextCreator
        ↓
Layer 2: Memory Blocks (Storage backends)
   ├── ChatHistoryBlock (in-memory list)
   └── VectorDBBlock (Qdrant, etc.)
        ↓
Layer 1: Records (Data units)
   ├── MemoryRecord (content + metadata)
   └── ContextRecord (retrieved context)
```

**Design Philosophy:**
- Each layer has single responsibility
- Layers compose cleanly
- Swap implementations without changing agent code

## Memory Types

### 1. Chat History Memory

**Simple conversation history:**

```python
class ChatHistoryMemory(AgentMemory):
    def __init__(self, context_creator: Optional[BaseContextCreator] = None):
        self.block = ChatHistoryBlock()
        self.context_creator = context_creator or ScoreBasedContextCreator()

    def write_record(self, record: MemoryRecord):
        self.block.add(record)

    def get_context(self) -> ContextRecord:
        records = self.block.retrieve_all()
        return self.context_creator.create_context(records)

    def clear(self):
        self.block.clear()
```

**Storage:**
- In-memory list of `MemoryRecord` objects
- No persistence across sessions
- Fast retrieval (no I/O)

**Use Case:** Short-term conversation context within a single session

### 2. Vector DB Memory

**Semantic search over embeddings:**

```python
class VectorDBMemory(AgentMemory):
    def __init__(
        self,
        vector_db_block: VectorDBBlock,
        context_creator: Optional[BaseContextCreator] = None,
    ):
        self.block = vector_db_block
        self.context_creator = context_creator or ScoreBasedContextCreator()

    def write_record(self, record: MemoryRecord):
        # Embed content and store in vector DB
        self.block.add(record)

    def get_context(self, query: Optional[str] = None) -> ContextRecord:
        if query:
            # Semantic search
            records = self.block.retrieve_by_similarity(query, top_k=10)
        else:
            # Retrieve recent
            records = self.block.retrieve_recent(limit=100)

        return self.context_creator.create_context(records)
```

**Storage:**
- Qdrant, Milvus, or other vector DBs
- Persistent across sessions
- Semantic search via embeddings

**Use Case:** Long-term memory, knowledge retrieval, RAG

### 3. Long-term Agent Memory

**Hybrid memory combining both:**

```python
class LongtermAgentMemory(AgentMemory):
    def __init__(
        self,
        chat_history_block: Optional[ChatHistoryBlock] = None,
        vector_db_block: Optional[VectorDBBlock] = None,
        context_creator: Optional[BaseContextCreator] = None,
    ):
        self.blocks = [
            chat_history_block or ChatHistoryBlock(),
            vector_db_block or VectorDBBlock(...),
        ]
        self.context_creator = context_creator or ScoreBasedContextCreator()

    def write_record(self, record: MemoryRecord):
        # Write to ALL blocks
        for block in self.blocks:
            block.add(record)

    def get_context(self, query: Optional[str] = None) -> ContextRecord:
        # Retrieve from ALL blocks, merge, and rank
        all_records = []
        for block in self.blocks:
            all_records.extend(block.retrieve(...))

        # Deduplicate and rank
        return self.context_creator.create_context(all_records)
```

**Strategy:**
- Recent messages from chat history (fast access)
- Relevant older messages from vector DB (semantic search)
- Merge and rank by relevance

**Use Case:** Agents that need both short-term and long-term memory

## Context Creation

### Score-Based Context Creator

**Intelligent context window management:**

```python
class ScoreBasedContextCreator(BaseContextCreator):
    def create_context(
        self,
        records: List[MemoryRecord],
        token_limit: Optional[int] = None,
    ) -> ContextRecord:
        # 1. Score each record by relevance
        scored_records = self._score_records(records)

        # 2. Sort by score (descending)
        scored_records.sort(key=lambda x: x.score, reverse=True)

        # 3. Pack into context window (greedy)
        selected_records = []
        total_tokens = 0
        for record, score in scored_records:
            record_tokens = self._count_tokens(record.content)
            if total_tokens + record_tokens <= token_limit:
                selected_records.append(record)
                total_tokens += record_tokens
            else:
                break

        return ContextRecord(
            records=selected_records,
            total_tokens=total_tokens,
        )

    def _score_records(self, records: List[MemoryRecord]) -> List[Tuple[MemoryRecord, float]]:
        scored = []
        for record in records:
            score = 0.0

            # Recency score: exponential decay
            time_diff = time.time() - record.timestamp
            recency_score = math.exp(-time_diff / 3600)  # 1-hour half-life
            score += recency_score * 0.5

            # Semantic similarity score (if query provided)
            if self.query_embedding:
                similarity = cosine_similarity(
                    self.query_embedding,
                    record.embedding
                )
                score += similarity * 0.5

            scored.append((record, score))
        return scored
```

**Scoring Factors:**
1. **Recency:** Newer messages score higher (exponential decay)
2. **Semantic Similarity:** Relevant to current query
3. **Custom weights:** Balance recency vs. relevance

**Benefits:**
- Fits most relevant memories in context window
- Balances recent conversation with older relevant info
- Gracefully handles context overflow

**Alternative Creators:**
- `RecencyBasedContextCreator`: Only recency, no semantic search
- `RandomContextCreator`: For testing/baseline
- Custom: Implement `BaseContextCreator` interface

## Memory Records

### Memory Record Structure

```python
@dataclass
class MemoryRecord:
    content: str                  # The actual content
    uuid: str                     # Unique identifier
    timestamp: float              # When recorded
    embedding: Optional[ndarray]  # Semantic embedding
    metadata: Optional[Dict]      # Additional context
```

**Metadata Examples:**
- `role`: USER, ASSISTANT, SYSTEM
- `tool_calls`: List of tool calls in this turn
- `task_id`: For task-specific memory partitioning
- `importance`: User-defined importance score

### Context Record

```python
@dataclass
class ContextRecord:
    records: List[MemoryRecord]   # Selected records
    total_tokens: int             # Token count
    context_string: str           # Concatenated content
```

**Usage:**
```python
context = memory.get_context(query="What did we discuss about X?")
messages = [
    SystemMessage(content=system_prompt),
    *[UserMessage(content=r.content) for r in context.records],
    UserMessage(content=current_query),
]
```

## Memory Integration with Agents

### Automatic Memory Writing

**ChatAgent automatically writes to memory:**

```python
class ChatAgent:
    def __init__(
        self,
        ...,
        memory: Optional[AgentMemory] = None,
    ):
        self.memory = memory or ChatHistoryMemory()

    async def astep(self, input_message: BaseMessage):
        # 1. Write user message to memory
        user_record = MemoryRecord(
            content=input_message.content,
            uuid=str(uuid.uuid4()),
            timestamp=time.time(),
            metadata={"role": "USER"},
        )
        self.memory.write_record(user_record)

        # 2. Get response
        response = await self._aget_model_response(...)

        # 3. Write assistant response to memory
        assistant_record = MemoryRecord(
            content=response.content,
            uuid=str(uuid.uuid4()),
            timestamp=time.time(),
            metadata={"role": "ASSISTANT"},
        )
        self.memory.write_record(assistant_record)

        return response
```

**Pattern:** Memory writes are transparent to agent users

### Context Injection

**Memory retrieval before model call:**

```python
class ChatAgent:
    async def _aget_model_response(self, ...):
        # 1. Get relevant context from memory
        context = self.memory.get_context(query=current_message.content)

        # 2. Build messages list
        messages = [
            self.system_message.to_openai_message(),
            *[msg.to_openai_message() for msg in context.records],
            current_message.to_openai_message(),
        ]

        # 3. Call model with context
        response = await self.model.run(messages)
        return response
```

**Context Selection:**
- If memory has query support (VectorDB), use semantic search
- Otherwise, use most recent messages (ChatHistory)
- Respect token limit via context creator

## Memory Eviction

### Chat History Eviction

**Simple size-based eviction:**

```python
class ChatHistoryBlock:
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.records: List[MemoryRecord] = []

    def add(self, record: MemoryRecord):
        self.records.append(record)

        # FIFO eviction if over limit
        if len(self.records) > self.max_size:
            self.records.pop(0)
```

**Strategy:** First-In-First-Out (FIFO)

**Weakness:** May evict important early context

### Vector DB Eviction

**No automatic eviction:**

```python
class VectorDBBlock:
    def add(self, record: MemoryRecord):
        # No size limit - grows unbounded
        self.client.upsert(...)
```

**Manual cleanup:**
```python
# Delete old records
vector_db.delete_by_filter(
    filter={"timestamp": {"$lt": cutoff_time}}
)
```

**Gap:** No automatic importance-based eviction

**Better approach:**
- Track access frequency
- Evict low-importance, rarely-accessed records
- Keep high-importance records regardless of age

## Memory Toolkit Integration

### Memory as a Tool

**MemoryToolkit** exposes memory operations as tools:

```python
class MemoryToolkit(BaseToolkit, RegisteredAgentToolkit):
    def recall(self, query: str, top_k: int = 5) -> str:
        """Search memory for relevant information."""
        context = self._agent.memory.get_context(query=query)
        return "\n".join([r.content for r in context.records[:top_k]])

    def remember(self, content: str, importance: int = 5) -> str:
        """Store important information in long-term memory."""
        record = MemoryRecord(
            content=content,
            uuid=str(uuid.uuid4()),
            timestamp=time.time(),
            metadata={"importance": importance, "explicit": True},
        )
        self._agent.memory.write_record(record)
        return "Stored in memory"

    def forget(self, query: str) -> str:
        """Remove information from memory."""
        # Find and delete matching records
        ...

    def get_tools(self) -> List[FunctionTool]:
        return [
            FunctionTool(self.recall),
            FunctionTool(self.remember),
            FunctionTool(self.forget),
        ]
```

**Usage:**
```python
agent = ChatAgent(
    memory=LongtermAgentMemory(...),
    toolkits_to_register_agent=[MemoryToolkit()],
)

# Agent can now use memory tools:
# - recall("what did the user say about X?")
# - remember("User's favorite color is blue", importance=9)
# - forget("old project details")
```

**Innovation:** Agent can **control its own memory** via tools

## Memory Persistence

### Storage Backends

**VectorDBBlock supports persistent storage:**

```python
class VectorDBBlock(MemoryBlock):
    def __init__(
        self,
        collection_name: str = "camel_memory",
        embedding_model: Optional[BaseEmbedding] = None,
        storage_path: Optional[str] = None,  # Persistent storage
    ):
        if storage_path:
            # Persistent Qdrant instance
            self.client = QdrantClient(path=storage_path)
        else:
            # In-memory Qdrant
            self.client = QdrantClient(":memory:")
```

**Persistence Options:**
- File-based: Qdrant local storage
- Database: PostgreSQL with pgvector
- Cloud: Qdrant Cloud, Pinecone, Weaviate

### Session Management

**No built-in session abstraction:**

**What's missing:**
```python
# Hypothetical session manager (NOT in CAMEL)
class SessionManager:
    def save_session(self, session_id: str, agent: ChatAgent):
        # Save agent state + memory to persistent storage
        ...

    def load_session(self, session_id: str) -> ChatAgent:
        # Restore agent from storage
        ...
```

**Current approach:** Users must manually save/load memory blocks

**Workaround:**
```python
# Manual session save
storage = JsonStorage("session_123.json")
for record in agent.memory.block.records:
    storage.save(record.to_dict())

# Manual session load
records = [MemoryRecord.from_dict(d) for d in storage.load()]
agent.memory.block.records = records
```

## Memory Scoring

**CAMEL lacks sophisticated memory scoring:**

**What exists:**
- Recency (timestamp-based)
- Semantic similarity (embedding-based)
- Simple weighted sum

**What's missing:**
- Importance propagation (important facts referenced later)
- Access frequency tracking (oft-used memories)
- Emotional salience (user frustration, success moments)
- Task relevance (partition by task/project)
- User-defined tags/categories

**Better scoring:**
```python
def score_record(record: MemoryRecord, context: Dict) -> float:
    score = 0.0

    # Recency (exponential decay)
    age_hours = (time.time() - record.timestamp) / 3600
    score += 0.3 * math.exp(-age_hours / 24)  # 24-hour half-life

    # Semantic similarity to current query
    if context.get("query_embedding"):
        similarity = cosine_similarity(
            context["query_embedding"],
            record.embedding
        )
        score += 0.3 * similarity

    # Explicit importance (user-tagged)
    importance = record.metadata.get("importance", 5) / 10
    score += 0.2 * importance

    # Access frequency (how often referenced)
    access_count = record.metadata.get("access_count", 0)
    score += 0.1 * math.log1p(access_count)

    # Task relevance (same project/task)
    if record.metadata.get("task_id") == context.get("current_task_id"):
        score += 0.1

    return score
```

## Memory Orchestration Score

**Overall: 7/10**

**Breakdown:**
- Architecture: 9/10 (clean layering, composable)
- Types: 8/10 (ChatHistory + VectorDB + hybrid)
- Context Creation: 8/10 (score-based is good, but simple)
- Eviction: 5/10 (FIFO only, no importance-based)
- Persistence: 7/10 (VectorDB supports it, but no sessions)
- Integration: 9/10 (automatic writes, MemoryToolkit)
- Scoring: 6/10 (basic recency + similarity)

## Patterns to Adopt

1. **Layered memory architecture:** Records → Blocks → Creators → Memory
2. **Hybrid memory:** Combine short-term (chat history) + long-term (vector DB)
3. **Pluggable context creators:** Swap retrieval strategies easily
4. **Memory as tools:** Let agent control its own memory
5. **Automatic memory writes:** Transparent to users
6. **Score-based retrieval:** Balance recency vs. relevance

## Patterns to Avoid

1. **No session management:** Manual save/load is error-prone
2. **FIFO eviction only:** Should consider importance
3. **Simple scoring:** Missing access frequency, importance propagation
4. **No memory partitioning:** Can't separate contexts (work vs. personal)
5. **Unbounded vector DB growth:** Needs automatic cleanup

## Recommendations

1. **Add session manager:** Save/restore agent state + memory
2. **Importance-based eviction:** Keep important memories, discard trivial
3. **Access tracking:** Track how often memories are referenced
4. **Memory partitioning:** Separate contexts by task/project/user
5. **Automatic cleanup:** Background job to evict low-value records
6. **Memory summarization:** Compress old conversations into summaries
7. **Memory graph:** Link related memories for better retrieval
