# Memory Orchestration Analysis: Agno

## Summary
- **Key Finding 1**: User-centric memory system - memories belong to users, not sessions
- **Key Finding 2**: Strategy pattern for memory optimization - currently only SUMMARIZE strategy
- **Key Finding 3**: Background memory creation via concurrent.futures.Future during agent run
- **Classification**: User memory with pluggable optimization strategies

## Memory Tiers
- **User Memories**: Long-term knowledge about users (preferences, facts)
- **Session History**: Conversation history per session (messages)
- **Session State**: Mutable dict state per session
- **Session Summaries**: Compressed session overviews

## Context Assembly Strategy
- **History**: Configurable number of previous messages/runs
- **Memories**: Retrieved from database, optionally added to context
- **State**: Session state can be injected as context
- **Summaries**: Session summaries can replace detailed history

## Detailed Analysis

### User Memory Model

**Purpose**: Store long-term knowledge about users that persists across sessions

**Schema** (inferred from usage in `memory/manager.py:117-126`):
```python
class UserMemory:
    memory_id: str      # Unique identifier
    user_id: str        # Owner of this memory
    memory: str         # The actual memory content
    # Additional fields for metadata, timestamps, etc.
```

**Storage**: Persisted to database (via BaseDb interface)

**Operations** (`memory/manager.py:59-66`):
- `add_memories`: Create new memories
- `update_memories`: Modify existing memories
- `delete_memories`: Remove memories
- `clear_memories`: Wipe all memories for user

### Memory Manager Pattern

**Evidence** (`memory/manager.py:42-95`):
```python
@dataclass
class MemoryManager:
    # Model used for memory management
    model: Optional[Model] = None

    # Prompt customization
    system_message: Optional[str] = None
    memory_capture_instructions: Optional[str] = None
    additional_instructions: Optional[str] = None

    # Whether memories were created in the last run
    memories_updated: bool = False

    # ----- db tools ---------
    delete_memories: bool = True
    clear_memories: bool = True
    update_memories: bool = True
    add_memories: bool = True

    # The database to store memories
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None
```

**Pattern**: MemoryManager orchestrates memory operations
- Uses a Model to analyze conversations and extract memories
- Supports custom prompts for memory capture
- Exposes CRUD operations as boolean flags
- Tracks whether memories were updated in last run

### Memory Retrieval

**Evidence** (`memory/manager.py:113-127`):
```python
def read_from_db(self, user_id: Optional[str] = None):
    if self.db:
        # If no user_id is provided, read all memories
        if user_id is None:
            all_memories: List[UserMemory] = self.db.get_user_memories()
        else:
            all_memories = self.db.get_user_memories(user_id=user_id)

        # Group memories by user_id
        memories: Dict[str, List[UserMemory]] = {}
        for memory in all_memories:
            if memory.user_id is not None and memory.memory_id is not None:
                memories.setdefault(memory.user_id, []).append(memory)

        return memories
    return None
```

**Pattern**: Retrieve all memories for user(s) from database
- Can fetch for specific user or all users
- Groups by user_id
- No filtering, ranking, or semantic search at this layer

### Memory Optimization Strategies

**Evidence** (`memory/strategies/base.py:9-56`):
```python
class MemoryOptimizationStrategy(ABC):
    """Abstract base class for memory optimization strategies."""

    @abstractmethod
    def optimize(
        self,
        memories: List[UserMemory],
        model: Model,
    ) -> List[UserMemory]:
        """Optimize memories synchronously."""
        raise NotImplementedError

    @abstractmethod
    async def aoptimize(
        self,
        memories: List[UserMemory],
        model: Model,
    ) -> List[UserMemory]:
        """Optimize memories asynchronously."""
        raise NotImplementedError

    def count_tokens(self, memories: List[UserMemory]) -> int:
        """Count total tokens across all memories."""
        return sum(count_text_tokens(m.memory or "") for m in memories)
```

**Strategy Pattern**: Pluggable memory optimization
- Strategies take a list of memories and return optimized list
- Can use Model for LLM-based optimization
- Token counting utility provided

**Current Strategies** (`memory/strategies/types.py:8-11`):
```python
class MemoryOptimizationStrategyType(str, Enum):
    SUMMARIZE = "summarize"
```

**Limited**: Only one strategy currently implemented
- SUMMARIZE: Compress memories into summaries
- Could add: DEDUPLICATE, PRIORITIZE, SEMANTIC_MERGE, etc.

### Factory Pattern for Strategies

**Evidence** (`memory/strategies/types.py:14-37`):
```python
class MemoryOptimizationStrategyFactory:
    @classmethod
    def create_strategy(
        cls,
        strategy_type: MemoryOptimizationStrategyType,
        **kwargs
    ) -> MemoryOptimizationStrategy:
        strategy_map = {
            MemoryOptimizationStrategyType.SUMMARIZE: cls._create_summarize_strategy,
        }
        return strategy_map[strategy_type](**kwargs)

    @classmethod
    def _create_summarize_strategy(cls, **kwargs):
        from agno.memory.strategies.summarize import SummarizeStrategy
        return SummarizeStrategy(**kwargs)
```

**Pattern**: Factory creates strategies by type
- Allows lazy import of strategy implementations
- Extensible via adding entries to `strategy_map`

### Background Memory Creation

**Evidence** (`agent/agent.py:1069-1073`):
```python
# 4. Start memory creation in background thread
memory_future = self._start_memory_future(
    run_messages=run_messages,
    user_id=user_id,
    existing_future=memory_future,
)
```

**Pattern**: Memory extraction runs in parallel with main execution
- Uses concurrent.futures.Future
- Doesn't block agent response
- Waited on at end of run to ensure completion

**Benefit**: Reduces perceived latency - user gets response while memories are being saved

### Memory Search Response

**Evidence** (`memory/manager.py:32-38`):
```python
class MemorySearchResponse(BaseModel):
    """Model for Memory Search Response."""

    memory_ids: List[str] = Field(
        ...,
        description="The IDs of the memories that are most semantically similar to the query.",
    )
```

**Pattern**: Semantic search returns memory IDs, not full memories
- Client must fetch full memories by ID
- Allows ranking/filtering before retrieval
- Implies vector-based semantic search (though implementation not shown here)

### Session Summaries (Compression)

**Pattern** (inferred from Agent fields): Session summaries compress long conversations
- `enable_session_summaries`: Generate summaries at end of runs
- `add_session_summary_to_context`: Use summary instead of full history
- Managed by `SessionSummaryManager`

**Eviction**: Summaries replace detailed history to manage context window

### No Explicit Eviction Policy

**Observation**: No automatic memory pruning based on:
- Age (LRU/LFU)
- Relevance score decay
- Token budget constraints

Memories persist until explicitly deleted.

## Implications for New Framework

1. **User-centric memory is correct** - Memories should belong to users, not sessions
2. **Strategy pattern is extensible** - Easy to add new optimization strategies
3. **Background memory creation is smart** - Don't block on memory writes
4. **Semantic search needed** - MemorySearchResponse suggests vector search; ensure implementation
5. **Eviction policy missing** - Add LRU or relevance-based pruning for long-term users
6. **Token budgeting needed** - No automatic constraint on total memory tokens

## Anti-Patterns Observed

1. **No memory ranking** - All memories retrieved equally, no relevance scoring
2. **No memory deduplication** - Could store redundant information
3. **No memory versioning** - Updates overwrite, can't track changes
4. **No memory relationships** - Can't model connections between memories
5. **Limited optimization strategies** - Only SUMMARIZE implemented
6. **No token budget** - Could exceed context window with too many memories
7. **Sync/async duplication** - Both optimize() and aoptimize() required in strategy

## Code References
- `libs/agno/agno/memory/__init__.py:1-7` - Memory module exports
- `libs/agno/agno/memory/manager.py:42-95` - MemoryManager dataclass
- `libs/agno/agno/memory/manager.py:113-127` - Memory retrieval from database
- `libs/agno/agno/memory/manager.py:32-38` - MemorySearchResponse schema
- `libs/agno/agno/memory/strategies/base.py:9-56` - MemoryOptimizationStrategy ABC
- `libs/agno/agno/memory/strategies/types.py:8-11` - MemoryOptimizationStrategyType enum
- `libs/agno/agno/memory/strategies/types.py:14-37` - MemoryOptimizationStrategyFactory
- `libs/agno/agno/agent/agent.py:1069-1073` - Background memory creation pattern
