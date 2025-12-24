# Resilience Analysis: CAMEL

## Error Handling Philosophy

### Exception Strategy

CAMEL follows a **fail-fast with recovery** approach:

1. **Propagate exceptions by default** - No silent failures
2. **Wrap with context** - Custom exceptions add framework-level info
3. **Retry at boundaries** - ModelManager, tool execution
4. **Graceful degradation** - Observability and optional features

### Custom Exception Hierarchy

```python
exceptions/
  └── models/
      └── ModelProcessingError  # Model execution failures
```

**Pattern:**
```python
try:
    response = await model.run(messages)
except Exception as e:
    raise ModelProcessingError(f"Model {model_type} failed: {e}") from e
```

**Benefits:**
- `raise ... from e` preserves full stack trace
- Custom types allow targeted catching
- Framework errors distinguishable from user code errors

**Weakness:** Limited exception hierarchy - most errors are generic Python exceptions

## Retry Logic

### Model Call Retries

**ModelManager** provides retry with backoff:

```python
class ModelManager:
    def __init__(
        self,
        models: List[BaseModelBackend],
        retry_attempts: int = 3,
        retry_delay: float = 1.0,
        ...
    ):
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay

    async def run(self, messages: List[Dict]) -> ChatCompletion:
        for attempt in range(self.retry_attempts):
            try:
                return await self.current_model.run(messages)
            except RateLimitError:
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
                    continue
                raise
```

**Retry Strategy:**
- Exponential backoff: `delay * (2 ** attempt)`
- Only retries on `RateLimitError`
- Other errors fail immediately

**Gap:** No retry for transient network errors, API timeouts, or 500-series responses

### Tool Execution Retries

**No automatic retry for tool calls** - Tools fail on first error

```python
async def _aexecute_tool(self, tool: FunctionTool, ...) -> ToolResult:
    try:
        if inspect.iscoroutinefunction(tool.func):
            result = await tool.func(**args)
        else:
            result = await loop.run_in_executor(_SYNC_TOOL_EXECUTOR, ...)
    except Exception as e:
        # No retry - propagate immediately
        return ToolResult(
            success=False,
            error_message=str(e),
            ...
        )
```

**Rationale:** Tools may have side effects (write file, send email), retry could be dangerous

**Alternative:** Could add `@retry` decorator opt-in for idempotent tools

## Fallback Mechanisms

### Model Fallback

**ModelManager supports cascading fallback:**

```python
class ModelManager:
    def __init__(
        self,
        models: List[BaseModelBackend],  # Ordered by preference
        fallback_on_error: bool = True,
        ...
    ):
        self.models = models
        self.fallback_on_error = fallback_on_error

    async def run(self, messages: List[Dict]) -> ChatCompletion:
        for model in self.models:
            try:
                return await model.run(messages)
            except Exception as e:
                if self.fallback_on_error and model != self.models[-1]:
                    logger.warning(f"Model {model} failed, trying next: {e}")
                    continue
                raise
```

**Pattern:**
1. Try primary model
2. On failure, try next in list
3. If all fail, raise last exception

**Use case:**
```python
manager = ModelManager(
    models=[
        OpenAIModel(ModelType.GPT_4O),      # Primary
        OpenAIModel(ModelType.GPT_4O_MINI), # Fallback 1
        AnthropicModel(ModelType.CLAUDE_3_5_SONNET), # Fallback 2
    ]
)
```

### Context Length Fallback

**Automatic context summarization on overflow:**

```python
TOKEN_LIMIT_ERROR_MARKERS = (
    "context_length_exceeded",
    "prompt is too long",
    "exceeded your current quota",
    "tokens must be reduced",
    "context length",
    "token count",
    "context limit",
)

async def _aget_model_response(self, ...):
    try:
        response = await self.model.run(messages)
    except Exception as e:
        if any(marker in str(e).lower() for marker in TOKEN_LIMIT_ERROR_MARKERS):
            # Summarize chat history
            await self.asummarize()
            # Retry with reduced context
            response = await self.model.run(messages)
        else:
            raise
```

**Summarization Strategy:**
1. Detect context overflow via string matching
2. Call `asummarize()` to condense history
3. Replace chat history with summary
4. Retry with reduced messages

**Weakness:** String-based error detection is fragile across providers

## Timeout Handling

### Universal Timeout Protection

**Metaclass-based automatic timeout wrapping:**

```python
class BaseToolkit(metaclass=AgentOpsMeta):
    timeout: Optional[float] = Constants.TIMEOUT_THRESHOLD

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for attr_name, attr_value in cls.__dict__.items():
            if callable(attr_value) and not attr_name.startswith("__"):
                if not getattr(attr_value, '_manual_timeout', False):
                    setattr(cls, attr_name, with_timeout(attr_value))
```

**with_timeout decorator:**
```python
def with_timeout(func):
    @functools.wraps(func)
    async def async_wrapper(self, *args, **kwargs):
        timeout = getattr(self, 'timeout', None)
        if timeout:
            return await asyncio.wait_for(func(self, *args, **kwargs), timeout=timeout)
        return await func(self, *args, **kwargs)

    @functools.wraps(func)
    def sync_wrapper(self, *args, **kwargs):
        # For sync functions, use threading.Timer or signal
        ...

    return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
```

**Coverage:**
- ALL toolkit methods get automatic timeout
- Default: `Constants.TIMEOUT_THRESHOLD` (configurable)
- Opt-out via `_manual_timeout = True`

**Benefits:**
- Zero boilerplate for tool authors
- Prevents runaway tool execution
- Uniform timeout behavior

**Gaps:**
- No timeout on model calls (could hang indefinitely)
- No timeout on agent.step() itself

## Circuit Breaker Pattern

### Not Implemented

CAMEL **lacks circuit breaker** for failing services:

**What's missing:**
```python
# Hypothetical circuit breaker
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout: float = 60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.last_failure_time = None

    async def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "HALF_OPEN"
            else:
                raise CircuitOpenError()

        try:
            result = await func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
            raise
```

**Impact:** Repeated failures to external services (APIs, DBs) will keep being retried without backpressure

## Resource Cleanup

### Temporary File Management

**atexit-based cleanup:**

```python
_temp_files: Set[str] = set()
_temp_files_lock = threading.Lock()

def _cleanup_temp_files():
    with _temp_files_lock:
        for path in _temp_files:
            try:
                os.unlink(path)
            except Exception:
                pass  # Silent failure

atexit.register(_cleanup_temp_files)
```

**Registration:**
```python
# In code that creates temp files:
temp_path = "/tmp/file.txt"
with _temp_files_lock:
    _temp_files.add(temp_path)
```

**Strengths:**
- Global registry ensures cleanup
- Thread-safe access
- Silent failure handling (file may be already deleted)

**Weaknesses:**
- Only runs on clean shutdown (not SIGKILL)
- Global state makes testing harder
- No scoped cleanup (files live until process exit)

**Better alternative:**
```python
@contextmanager
def temp_file(suffix: str):
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        yield path
    finally:
        os.close(fd)
        os.unlink(path)
```

### Agent State Cleanup

**Reset mechanism:**
```python
class ChatAgent:
    def reset(self):
        self.memory.clear()
        self.terminated = False
        self.init_messages()
        return self.stored_messages
```

**Pattern:**
- Agents are stateful and reusable
- `reset()` restores initial state
- Memory is cleared, not recreated (efficiency)

**Gap:** No automatic resource cleanup on agent deletion (e.g., close DB connections, release locks)

## Failure Recovery

### Workforce Failure Handling

**Production-ready failure recovery:**

```python
workforce/
  └── utils.py
      ├── RecoveryStrategy (Enum):
      │   - RETRY
      │   - SKIP
      │   - FALLBACK
      │   - TERMINATE
      └── FailureHandlingConfig:
          - max_retries: int
          - retry_delay: float
          - fallback_workers: List[Worker]
          - on_failure: Callable
```

**Workforce orchestration with recovery:**
```python
class Workforce:
    def __init__(
        self,
        mode: WorkforceMode,  # PARALLEL, PIPELINE, LOOP
        failure_handling: FailureHandlingConfig = ...,
    ):
        self.failure_handling = failure_handling

    async def run_task(self, worker: Worker, task: Task):
        for attempt in range(self.failure_handling.max_retries):
            try:
                return await worker.execute(task)
            except Exception as e:
                if self.failure_handling.recovery_strategy == RecoveryStrategy.RETRY:
                    await asyncio.sleep(self.failure_handling.retry_delay)
                    continue
                elif self.failure_handling.recovery_strategy == RecoveryStrategy.FALLBACK:
                    return await self._try_fallback_workers(task)
                elif self.failure_handling.recovery_strategy == RecoveryStrategy.SKIP:
                    logger.warning(f"Skipping failed task: {e}")
                    return None
                else:  # TERMINATE
                    raise
```

**Strengths:**
- Comprehensive recovery strategies
- Configurable retry logic
- Fallback worker chains
- Custom failure callbacks

**This is production-grade** - One of CAMEL's strongest resilience features

### Stop Event Integration

**Graceful shutdown via threading.Event:**

```python
class RolePlaying:
    def __init__(
        self,
        ...,
        stop_event: Optional[threading.Event] = None,
    ):
        self.stop_event = stop_event

    def step(self, ...):
        if self.stop_event and self.stop_event.is_set():
            # Graceful termination
            return None
```

**Benefits:**
- External control of agent loops
- Clean shutdown without killing threads
- Useful for long-running workflows

## Observability for Resilience

### Integrated Logging

**Standard Python logging:**
```python
from camel.logger import get_logger

logger = get_logger(__name__)

# Usage:
logger.warning(f"Model {model} failed, trying next: {e}")
logger.error(f"All models failed: {e}")
```

**Configurable log levels:**
```python
from camel import set_log_level, disable_logging, enable_logging

set_log_level("DEBUG")  # For detailed diagnostics
disable_logging()       # For production
```

**Gap:** No structured logging (JSON logs for parsing/alerting)

### Tracing Integration

**Optional distributed tracing:**
```python
@observe()  # Langfuse, TraceRoot, or AgentOps
async def astep(self, ...):
    # Automatically traced
    ...
```

**Benefits:**
- Performance profiling
- Error tracking across service boundaries
- Request flow visualization

**Weakness:** Requires manual decorator application - not automatic

## Resilience Score

**Overall: 7/10**

**Breakdown:**
- Error Handling: 7/10 (Good propagation, limited hierarchy)
- Retry Logic: 6/10 (Models yes, tools no, no circuit breaker)
- Fallback: 8/10 (Model fallback + context summarization)
- Timeout: 9/10 (Excellent automatic toolkit timeouts)
- Cleanup: 6/10 (atexit works but not bulletproof)
- Failure Recovery: 9/10 (Workforce recovery is excellent)
- Observability: 7/10 (Good logging, optional tracing)

## Patterns to Adopt

1. **Metaclass-based timeout wrapping:** Universal protection without boilerplate
2. **Model fallback chains:** `ModelManager` with ordered fallback list
3. **Workforce failure handling:** `RecoveryStrategy` enum with configurable behavior
4. **Context summarization on overflow:** Automatic recovery from token limits
5. **Stop event pattern:** Graceful shutdown via threading.Event

## Patterns to Avoid

1. **String-based error detection:** Use structured error codes
2. **atexit-only cleanup:** Add context managers for scoped cleanup
3. **No tool retries:** Consider opt-in retry for idempotent tools
4. **Missing circuit breakers:** Add for external service resilience
5. **No model call timeouts:** Could hang indefinitely

## Recommendations

1. **Add CircuitBreaker:** For external APIs, databases, and model providers
2. **Structured error codes:** Replace string matching with error code enums
3. **Context managers for resources:** Replace atexit with `@contextmanager`
4. **Automatic tracing:** Make observability default, not opt-in
5. **Tool-level retry:** Add `@idempotent` decorator for safe retries
6. **Model call timeouts:** Set upper bound on all model API calls
7. **Structured logging:** JSON logs for production monitoring
