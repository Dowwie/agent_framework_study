## Resilience Analysis: LangGraph

### Error Propagation Map

| Error Source | Error Type | Handling | Propagates? |
|--------------|-----------|----------|-------------|
| LLM API | RateLimitError | Retry with exponential backoff | No (if retries succeed) |
| LLM API | APIError | Retry configurable times | Yes (if retries exhausted) |
| LLM API | Timeout | Configurable per node | Yes |
| Node execution | Exception | Captured in PregelTask.error | Yes (stops graph) |
| State update | InvalidUpdateError | Immediate propagation | Yes |
| Checkpoint save | Exception | Propagates (blocks step completion) | Yes |
| Interrupt | GraphInterrupt | Controlled pause | No (resumable) |

### Error Propagation Flow

```
User Input
    ↓
┌─────────────────────────────────────────┐
│ Pregel Loop (pregel/_loop.py)          │
│   ↓                                     │
│ ┌─────────────────────────────────────┐ │
│ │ Task Execution (_executor.py)       │ │
│ │ • Exception → Captured in task      │ │
│ │ • Retry logic applied               │ │
│ │ • Error → PregelTask.error          │ │
│ └─────────────────────────────────────┘ │
│   ↓                                     │
│ ┌─────────────────────────────────────┐ │
│ │ Task Result Processing              │ │
│ │ • If error → log and propagate      │ │
│ │ • Available in state snapshot       │ │
│ └─────────────────────────────────────┘ │
│   ↓                                     │
│ ┌─────────────────────────────────────┐ │
│ │ Checkpoint Save                     │ │
│ │ • Error → Propagate (critical)      │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### Retry Logic

From `_internal/_retry.py` and `types.py`:

```python
class RetryPolicy(NamedTuple):
    initial_interval: float = 0.5    # First retry delay
    backoff_factor: float = 2.0      # Exponential multiplier
    max_interval: float = 128.0      # Cap on retry delay
    max_attempts: int = 3            # Total attempts
    jitter: bool = True              # Randomize delays
    retry_on: Callable[[Exception], bool] = default_retry_on
```

**Default retry filter** (from `_internal/_retry.py`):
```python
def default_retry_on(exc: Exception) -> bool:
    """Retry on common transient errors"""
    return isinstance(exc, (
        RateLimitError,
        APIError,
        Timeout,
        # Other transient errors
    ))
```

**Application**:
- Configured per-node: `builder.add_node("node", func, retry_policy=RetryPolicy(...))`
- Multiple policies: `retry_policy=[policy1, policy2]` - first matching applies
- Retry state not persisted (resets on graph resume)

### Sandboxing Assessment
- **Code Execution**: None (delegates to tool implementations)
- **File System**: Open (no built-in restrictions)
- **Network**: Open (no built-in restrictions)
- **Resource Limits**: Configurable timeouts per node

**Security model**: LangGraph itself provides no sandboxing. Security must be implemented at:
1. **Tool level**: Individual tools should sandbox code execution
2. **Infrastructure level**: Container/VM isolation for deployment
3. **LLM level**: Prompt injection defenses, output validation

**Rationale**: Framework focuses on orchestration, not execution isolation.

### Interrupt Mechanism

LangGraph's **interrupt** feature provides controlled pause/resume:

**Configuration**:
```python
graph = builder.compile(
    checkpointer=InMemorySaver(),
    interrupt_before=["human_review"],  # Pause before node
    interrupt_after=["action"],         # Pause after node
)
```

**Behavior**:
- Graph execution stops at interrupt point
- State checkpoint saved
- `GraphInterrupt` exception raised (caught by framework)
- Resume via `graph.invoke(None, config={"resuming": True})`

**Use cases**:
- Human-in-the-loop workflows
- Approval gates
- External system integration points

**Implementation** (from `pregel/_algo.py` and `_loop.py`):
```python
def should_interrupt(
    checkpoint: Checkpoint,
    interrupt_nodes: All | Sequence[str],
    snapshot_channels: Sequence[str],
    tasks: list[PregelExecutableTask],
) -> list[Interrupt] | None:
    """Check if execution should pause"""
    if interrupt_nodes == "*":
        # Interrupt on all nodes
        return [Interrupt(...) for task in tasks]
    elif any(task.name in interrupt_nodes for task in tasks):
        return [Interrupt(...)]
    return None
```

### Recovery Mechanisms

| Pattern | Implementation | Location |
|---------|---------------|----------|
| Retry | Exponential backoff, jitter | `_internal/_retry.py` |
| Checkpoint | Save/restore state | `checkpoint/base.py` |
| Interrupt | Pause/resume | `pregel/_loop.py` |
| Error capture | Task-level error storage | `types.py:PregelTask` |
| Circuit Breaker | Not built-in | - |

### Checkpoint-Based Recovery

**Checkpoint structure** (from `checkpoint/base.py`):
```python
class Checkpoint(TypedDict):
    v: int                                    # Version
    id: str                                   # Checkpoint ID
    ts: str                                   # Timestamp
    channel_values: dict[str, Any]            # State snapshot
    channel_versions: dict[str, int]          # Version tracking
    versions_seen: dict[str, dict[str, int]]  # Causal ordering
    pending_sends: list[PendingWrite]         # Queued updates
```

**Recovery workflow**:
1. Graph pauses (interrupt or error)
2. Checkpoint saved with current state
3. User inspects state via `graph.get_state(config)`
4. User optionally updates state via `graph.update_state(config, values)`
5. Graph resumes from checkpoint

**Resume modes**:
```python
# Resume from last checkpoint
graph.invoke(None, config=checkpoint_config)

# Resume with state update
graph.update_state(checkpoint_config, {"field": "new_value"})
graph.invoke(None, config=checkpoint_config)
```

### Error Context Preservation

**Task error storage** (from `types.py`):
```python
class PregelTask(NamedTuple):
    id: str
    name: str
    path: tuple[str | int | tuple, ...]
    error: Exception | None = None  # Captured exception
    interrupts: tuple[Interrupt, ...] = ()
    state: RunnableConfig | StateSnapshot | None = None
    result: Any | None = None
```

**Error accessibility**:
```python
snapshot = graph.get_state(config)
for task in snapshot.tasks:
    if task.error:
        print(f"Task {task.name} failed: {task.error}")
```

### Durability Modes

From `types.py` and `pregel/main.py`:

```python
Durability = Literal["sync", "async", "exit"]
```

**Trade-offs**:

| Mode | Checkpoint Timing | Performance | Resilience |
|------|------------------|-------------|------------|
| `sync` | Before each step | Slowest | Highest (no data loss) |
| `async` | Asynchronous during step | Fast | Medium (potential loss if crash) |
| `exit` | Only on graph exit | Fastest | Low (loss if crash mid-execution) |

**Configuration**:
```python
graph.compile(checkpointer=saver)  # Defaults to "sync"

# Override in config
graph.invoke(input, config={"durability": "async"})
```

### Managed Resource Lifecycle

From `managed/base.py`:

**Pattern**: Context managers for resource cleanup

```python
# Managed values automatically cleaned up on graph exit
# Example: database connections, file handles
```

**Cleanup guarantee**: Even if graph fails, managed resources are cleaned up.

### Error Messages

LangGraph provides **structured error messages** (from `errors.py`):

```python
def create_error_message(
    message: str,
    error_code: ErrorCode,
) -> str:
    """Create detailed error with code and guidance"""
    ...

class ErrorCode(Enum):
    GRAPH_RECURSION_LIMIT = "GRAPH_RECURSION_LIMIT"
    INVALID_CONCURRENT_GRAPH_UPDATE = "INVALID_CONCURRENT_GRAPH_UPDATE"
    INVALID_GRAPH_NODE_RETURN_VALUE = "INVALID_GRAPH_NODE_RETURN_VALUE"
    CHECKPOINT_NOT_LATEST = "CHECKPOINT_NOT_LATEST"
    # ... more error codes
```

**Benefits**:
- Actionable error messages
- Error codes for programmatic handling
- Context about what went wrong and how to fix

### Task Timeout

**Configurable per-node**:
```python
# Not directly exposed in public API, but available via config
# Timeout handled by executor
```

**Behavior**:
- Task execution cancelled after timeout
- Exception captured in `PregelTask.error`
- Graph can continue or stop based on error handling

### Risk Assessment

**Critical Gaps**:
1. **No built-in circuit breaker**: Repeated failures can overwhelm external services
2. **No rate limiting**: Must be implemented in LLM client
3. **No sandboxing**: Code execution in tools is unsafe by default
4. **Limited timeout control**: No fine-grained timeout configuration in public API

**Production Considerations**:
1. **Wrap LLM calls** with circuit breakers (use external library)
2. **Implement tool sandboxing** (Docker, gVisor, or restricted execution)
3. **Monitor checkpoint size**: Large states can cause memory issues
4. **Set reasonable recursion limits**: Default 25 may be too low or high
5. **Use async durability** for performance-critical paths

**Production Ready**: Yes, with caveats
- ✅ Strong checkpoint-based recovery
- ✅ Configurable retry logic
- ✅ Task-level error capture
- ⚠️ No built-in sandboxing (add externally)
- ⚠️ No circuit breakers (add externally)
- ⚠️ Checkpoint overhead can be significant

### Recommendations

**Strengths**:
- Checkpoint-based recovery is robust and well-designed
- Retry logic is configurable and reasonable
- Interrupt mechanism enables human-in-the-loop
- Error context preserved in task objects
- Durability modes allow performance tuning

**Weaknesses**:
- No sandboxing for dangerous operations
- No circuit breakers for external service protection
- Limited timeout configuration
- Checkpoint saves can fail, halting execution

**Best practices to adopt**:
1. Checkpoint-based pause/resume for long-running workflows
2. Interrupt mechanism for human-in-the-loop
3. Task-level error capture and propagation
4. Configurable durability for perf vs safety trade-off
5. Structured error codes for better error handling
6. Per-node retry policies with exponential backoff
