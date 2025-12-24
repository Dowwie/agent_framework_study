# Anti-Pattern Catalog

Patterns observed across 15 agent frameworks that should NOT be repeated in new implementations.

## Critical (Must Avoid)

### 1. Unbounded Memory Growth
**Observed in**: 12 of 15 frameworks (Agent-Zero, Agno, crewAI, Google ADK, LlamaIndex, MetaGPT, OpenAI Agents, Pydantic-AI, Swarm, autogen, AWS Strands, MS Agent)

**Problem**:
- Message history grows linearly without eviction
- No automatic summarization or compression
- Eventually exceeds LLM context window
- Silent failure or cryptic API errors

**Impact**:
- Long conversations crash with "context_length_exceeded"
- Token costs explode
- Performance degrades as history grows
- Users must manually implement truncation

**Evidence**:
```python
# Swarm (swarm/core.py:120-140)
history.append({"role": "assistant", "content": response})
# No eviction logic - unbounded growth

# crewAI (agent/agent.py:400+)
self.messages.append(new_message)
# No token counting, no truncation
```

**Recommendation**:
```python
# Agent-Zero's hierarchical compression (best practice)
def compress(self, token_limit: int):
    # 50% current topic, 30% historical topics, 20% bulks
    if current_topic_tokens > limit * 0.5:
        summarize_messages()
    if historical_tokens > limit * 0.3:
        move_to_bulk()
    if bulk_tokens > limit * 0.2:
        drop_oldest()

# Minimum: Token-based sliding window
def add_message(msg):
    self.history.append(msg)
    while count_tokens(self.history) > TOKEN_BUDGET:
        self.history.pop(0)  # FIFO eviction
```

**Better Alternative**: Three-tier memory with automatic management:
- Tier 1: Recent messages (token-budget enforced)
- Tier 2: Summarized history (LLM-compressed)
- Tier 3: Vector DB for long-term (semantic retrieval)

---

### 2. Silent Exception Swallowing
**Observed in**: MetaGPT, Agent-Zero, Agno, crewAI, AWS Strands

**Problem**:
- Exceptions caught and logged but not surfaced
- `@handle_exception` decorators return None on failure
- Failed operations appear to succeed
- No telemetry on failure rates

**Impact**:
- Debugging requires source-level inspection
- Silent failures corrupt agent state
- No visibility into production error rates
- Tool failures go unnoticed

**Evidence**:
```python
# MetaGPT (schema.py:73, 96-116)
@handle_exception
def serialize(self):
    try:
        return json.dumps(self.data)
    except Exception:
        return None  # Silent failure

# Agent-Zero (agent.py:454-478)
try:
    result = tool.execute()
except Exception as e:
    logger.warning(f"Tool failed: {e}")
    # Continues execution, doesn't inform LLM
```

**Recommendation**:
```python
# LlamaIndex pattern - error as data
class AgentOutput:
    retry_messages: list[ChatMessage] | None = None
    is_error: bool = False

def execute_tool(tool, args):
    try:
        return tool(**args)
    except Exception as e:
        return AgentOutput(
            retry_messages=[
                ChatMessage(role="user", content=f"Error: {e}\n\nPlease try again.")
            ],
            is_error=True
        )

# Pydantic-AI pattern - structured exceptions
class ToolExecutionError(Exception):
    def __init__(self, tool_name: str, args: dict, error: Exception):
        self.tool_name = tool_name
        self.args = args
        self.original_error = error
        super().__init__(f"Tool {tool_name} failed: {error}")
```

**Better Alternative**: Use Result types, explicit error propagation, structured logging

---

### 3. Configuration God Objects
**Observed in**: Agno (250+ fields), crewAI (200+ fields), CAMEL (20+ constructor params)

**Problem**:
- Agent/AgentConfig classes with hundreds of configuration fields
- Analysis paralysis for users
- No sensible defaults
- Overwhelming API surface
- Impossible to reason about configuration space

**Impact**:
- New users don't know where to start
- Documentation burden
- Testing combinatorial explosion
- Breaking changes on every release

**Evidence**:
```python
# Agno (agent/agent.py:184+)
@dataclass
class Agent:
    # 250+ configuration fields
    enable_agentic_memory: bool = False
    add_session_state_to_context: bool = False
    add_history_to_messages: bool = True
    num_history_responses: int = 3
    # ... 246 more fields
```

**Recommendation**:
```python
# Builder pattern with presets
class Agent:
    @classmethod
    def for_chat(cls, llm: LLM) -> AgentBuilder:
        return AgentBuilder(llm).with_memory().with_basic_tools()

    @classmethod
    def for_research(cls, llm: LLM) -> AgentBuilder:
        return AgentBuilder(llm).with_memory().with_search().with_planning()

# Usage
agent = Agent.for_chat(llm).with_custom_tools([search]).build()

# Only 10-15 common settings exposed
# Advanced users access full config via .configure()
```

**Better Alternative**: Start with 10-15 essential settings, provide preset configurations, use builder pattern

---

### 4. Deep Inheritance Hierarchies
**Observed in**: LangChain (not in study but referenced), crewAI (depth 3+), some tool implementations

**Problem**:
- BaseChain → Chain → LLMChain → ConversationalChain → 3+ more levels
- Impossible to understand what methods are called
- Violates Liskov Substitution Principle
- Tight coupling throughout hierarchy
- Hard to debug and test

**Impact**:
- New developers cannot navigate codebase
- Refactoring breaks everything
- Testing requires complex mocking
- Performance overhead from method resolution

**Evidence**:
```python
# Anti-pattern (hypothetical from descriptions)
class BaseTool(ABC):
    def execute(self): ...

class ToolWithContext(BaseTool):
    def execute(self, context): ...

class ValidatedTool(ToolWithContext):
    def execute(self, context):
        self.validate()
        return super().execute(context)

class RetryableTool(ValidatedTool):
    # 4 levels deep - hard to reason about
```

**Recommendation**:
```python
# Composition over inheritance
@dataclass
class Tool:
    execute_fn: Callable
    validator: Validator | None = None
    retry_policy: RetryPolicy | None = None

    async def execute(self, **kwargs):
        if self.validator:
            self.validator.validate(kwargs)

        result = await self.execute_fn(**kwargs)

        if self.retry_policy and result.is_error:
            return await self.retry_policy.retry(self.execute_fn, kwargs)

        return result

# Protocol for structural typing
class ToolProtocol(Protocol):
    async def execute(self, **kwargs) -> Result: ...
```

**Better Alternative**: Maximum depth 1, use composition and protocols, delegate to services

---

### 5. String-Based Identifiers
**Observed in**: MetaGPT (action class names), Agent-Zero (extension points), Agno (agent names), LlamaIndex (tool names)

**Problem**:
- Actions identified by `__name__` strings
- Message routing via string matching
- Extension points registered by string
- Refactoring breaks routing
- No compile-time safety

**Impact**:
- Typos cause silent failures
- Refactoring class names breaks message routing
- No IDE autocomplete for identifiers
- Hard to trace message flow
- Fragile integration points

**Evidence**:
```python
# MetaGPT (role.py:288, schema.py:269-279)
action_name = any_to_str(action)  # Converts class to string
if message.cause_by == "UserRequirement":  # String comparison
    self.handle_message(message)

# Agent-Zero (agent.py:921)
call_extensions("monologue_start", ...)  # String literal, typo-prone

# LlamaIndex (tools.py)
if tool.metadata.name == "handoff":  # String comparison
```

**Recommendation**:
```python
# Use enums or typed literals
class ExtensionPoint(Enum):
    MONOLOGUE_START = "monologue_start"
    AGENT_INIT = "agent_init"
    BEFORE_TOOL = "before_tool"

def call_extensions(point: ExtensionPoint, **kwargs):
    # Type-safe, IDE autocomplete

# Or use types directly
class ActionType:
    pass

class UserRequirement(ActionType):
    pass

# Type-based routing
def route_message(msg: Message, action_type: Type[ActionType]):
    if isinstance(action_type, UserRequirement):
        ...
```

**Better Alternative**: Use enums, typed literals, or direct type references - never strings for routing

---

### 6. Mutable State Without Thread Safety
**Observed in**: Agent-Zero, Agno, crewAI, AWS Strands, CAMEL

**Problem**:
- Dataclasses are mutable by default
- State mutated during async execution
- No locks or atomic operations
- Shared context modified in-place
- Race conditions in concurrent scenarios

**Impact**:
- Non-deterministic behavior
- State corruption
- Hard-to-reproduce bugs
- Concurrency bugs in production
- Testing nightmares

**Evidence**:
```python
# Agent-Zero (agent.py:151)
self.data[key] = value  # Mutable dict in async context

# Agno (workflow/types.py)
@dataclass  # Not frozen
class StepOutput:
    content: str  # Can be mutated
    # Modified during execution without locks

# AWS Strands (agent.py)
def manage(self, messages: List[Message]):
    messages.clear()  # In-place mutation
    messages.extend(new_messages)
```

**Recommendation**:
```python
# Frozen dataclasses by default
@dataclass(frozen=True)
class AgentState:
    messages: tuple[Message, ...]  # Immutable sequence
    context: dict[str, Any]  # Will need to copy

    def with_message(self, msg: Message) -> "AgentState":
        return dataclasses.replace(
            self,
            messages=self.messages + (msg,)
        )

# Or use Pydantic with immutability
class AgentState(BaseModel):
    model_config = ConfigDict(frozen=True)
    messages: list[Message]

    def with_message(self, msg: Message) -> "AgentState":
        return self.model_copy(
            update={"messages": self.messages + [msg]}
        )
```

**Better Alternative**: Frozen dataclasses, functional updates (copy-on-write), explicit state transitions

---

### 7. Sync-to-Async Wrappers (Wrong Direction)
**Observed in**: crewAI, Agno, LlamaIndex, Swarm (fully sync)

**Problem**:
- Synchronous core with `asyncio.to_thread()` wrappers
- Loses async benefits (cancellation, context managers)
- Thread pool overhead
- Dual API surface doubles testing
- Defeats purpose of async

**Impact**:
- Cannot properly cancel operations
- Context managers don't work across threads
- Performance overhead from thread switching
- Testing both paths is complex
- Confusing semantics

**Evidence**:
```python
# crewAI (crew.py)
async def kickoff_async(self):
    return await asyncio.to_thread(self.kickoff)
    # Sync wrapped in thread - loses async benefits

# Agno (agent/agent.py)
def run(self, message: str):  # Sync version
    # 128 sync methods

async def arun(self, message: str):  # Async version
    # 56 async methods
    # Drift risk between implementations
```

**Recommendation**:
```python
# Async-first design
class Agent:
    async def run(self, message: str) -> Response:
        # Native async implementation
        response = await self.llm.generate(message)
        if response.tool_calls:
            results = await asyncio.gather(
                *[self.execute_tool(call) for call in response.tool_calls]
            )
        return response

    def run_sync(self, message: str) -> Response:
        # Thin sync wrapper at entry point only
        return asyncio.run(self.run(message))
```

**Better Alternative**: Async-native with sync wrappers at entry points only, never wrap sync in threads

---

## Design Smells (Should Avoid)

### 8. No Max Iterations / Infinite Loop Risk
**Observed in**: Google ADK, AWS Strands, Agent-Zero, multiple frameworks

**Problem**:
- Control loop runs until text response
- No maximum iteration count
- LLM can loop forever on same tool calls
- No loop detection

**Impact**:
- Agent hangs indefinitely
- Token costs spiral
- No automatic failure mode
- Must kill process manually

**Evidence**:
```python
# Google ADK (agent.py)
while True:
    response = await llm.generate()
    if response.type == "text":
        return response
    # No max_iterations check

# AWS Strands - recursive calls
def handle_tool_execution():
    result = execute_tools()
    return event_loop_cycle()  # Unbounded recursion
```

**Recommendation**:
```python
class Agent:
    def __init__(self, max_iterations: int = 10):
        self.max_iterations = max_iterations

    async def run(self, message: str):
        for iteration in range(self.max_iterations):
            response = await self.llm.generate()

            if response.is_final:
                return response

            if response.tool_calls:
                await self.execute_tools(response.tool_calls)

        # Graceful degradation
        return Response(
            content="Max iterations reached. Here's my best attempt...",
            is_truncated=True
        )
```

**Better Alternative**: Always enforce max_iterations, provide graceful degradation, add loop detection

---

### 9. No Tool Execution Sandboxing
**Observed in**: 14 of 15 frameworks (only Agent-Zero has Docker isolation)

**Problem**:
- Tools execute in same process as agent
- Full filesystem and network access
- No resource limits (CPU, memory, time)
- Can block event loop
- Security risk for untrusted code

**Impact**:
- Tools can consume unlimited resources
- Blocking tools freeze entire agent
- Security vulnerabilities
- No isolation from host system
- Cannot enforce timeouts

**Evidence**:
```python
# Most frameworks
async def execute_tool(tool: Tool, args: dict):
    return await tool.execute(**args)
    # No isolation, no limits, same process
```

**Recommendation**:
```python
import asyncio
import resource

async def execute_tool_sandboxed(
    tool: Tool,
    args: dict,
    timeout: float = 30.0,
    max_memory_mb: int = 512
):
    # Run in subprocess with limits
    def limited_execution():
        # Set resource limits
        resource.setrlimit(
            resource.RLIMIT_AS,
            (max_memory_mb * 1024 * 1024, max_memory_mb * 1024 * 1024)
        )
        return tool.execute(**args)

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(limited_execution),
            timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        return ToolError(f"Tool timed out after {timeout}s")
    except MemoryError:
        return ToolError(f"Tool exceeded memory limit")
```

**Better Alternative**: Subprocess isolation, resource limits (CPU/memory/time), network restrictions, filesystem sandboxing

---

### 10. Global Mutable State
**Observed in**: LlamaIndex (Settings singleton), OpenAI Agents (DEFAULT_AGENT_RUNNER), Agent-Zero (global rate limiters)

**Problem**:
- Module-level globals for configuration
- Singleton pattern with mutation
- Action-at-a-distance bugs
- Difficult to test
- Cannot run isolated instances

**Impact**:
- Tests interfere with each other
- Cannot run multiple configs in same process
- Global state makes testing hard
- Surprising behavior in multi-tenant scenarios
- Thread safety concerns

**Evidence**:
```python
# LlamaIndex (settings.py)
@dataclass
class _Settings:
    _llm: Optional[LLM] = None
    # Global singleton, mutated via properties

_settings = _Settings()

def get_llm():
    return _settings._llm

# OpenAI Agents (run.py:84)
DEFAULT_AGENT_RUNNER = Runner()

def set_default_agent_runner(runner):
    global DEFAULT_AGENT_RUNNER
    DEFAULT_AGENT_RUNNER = runner
```

**Recommendation**:
```python
# Dependency injection
class Agent:
    def __init__(
        self,
        llm: LLM,
        tools: list[Tool],
        memory: Memory,
    ):
        self.llm = llm
        self.tools = tools
        self.memory = memory

# Or context-based config
from contextvars import ContextVar

current_config: ContextVar[Config] = ContextVar("config")

async def run_agent():
    config = current_config.get()
    # Each async context has isolated config
```

**Better Alternative**: Constructor injection, context variables, explicit passing - never globals

---

## Production Gaps (Missing Features)

### 11. No Circuit Breakers
**Observed in**: All 15 frameworks

**Problem**:
- No protection against cascading failures
- Repeated calls to failing tools/LLMs
- No automatic degradation
- Failure storms in distributed systems

**Impact**:
- Wasted API calls to failing services
- Increased latency
- Cost explosion
- System-wide failures

**Recommendation**:
```python
class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_duration: float = 60.0
    ):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout_duration = timeout_duration
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.next_attempt = None

    async def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() < self.next_attempt:
                raise CircuitOpenError("Circuit breaker is OPEN")
            self.state = "HALF_OPEN"

        try:
            result = await func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.reset()
            return result
        except Exception as e:
            self.record_failure()
            raise

    def record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.next_attempt = time.time() + self.timeout_duration
```

**Better Alternative**: Implement circuit breaker pattern per LLM provider and per tool, configurable thresholds

---

### 12. No Automatic Summarization
**Observed in**: 13 of 15 frameworks (only Agent-Zero and CAMEL have it)

**Problem**:
- Old messages evicted without summarization
- Information loss when hitting token limits
- No compression of long conversations
- Context quality degrades

**Impact**:
- Agent loses important context
- Users must re-explain information
- Degraded performance over time
- Silent information loss

**Recommendation**:
```python
# Agent-Zero's hierarchical compression
class HierarchicalMemory:
    async def compress(self):
        # Compress attention (middle messages)
        if len(self.messages) > 10:
            middle = self.messages[2:-2]
            summary = await self.llm.summarize(middle)
            self.messages = [
                self.messages[0],  # System
                self.messages[1],  # First user
                ChatMessage(role="system", content=f"Previous conversation: {summary}"),
                *self.messages[-2:]  # Recent messages
            ]
```

**Better Alternative**: LLM-based summarization before eviction, hierarchical compression, preserve key facts

---

### 13. Sequential-Only Tool Execution
**Observed in**: 13 of 15 frameworks (CAMEL and partial support in others are exceptions)

**Problem**:
- Tools executed one at a time
- Common pattern (search + weather) not optimized
- Parallel tool calls not supported
- Wasted latency

**Impact**:
- Slow agent response times
- Inefficient use of async runtime
- User-visible delays

**Recommendation**:
```python
async def execute_tools(tool_calls: list[ToolCall]):
    # Execute independent tools in parallel
    results = await asyncio.gather(
        *[execute_tool(call) for call in tool_calls],
        return_exceptions=True
    )

    # Handle results
    return [
        result if not isinstance(result, Exception)
        else ToolError(str(result))
        for result in results
    ]
```

**Better Alternative**: Parallel tool execution with configurable concurrency limits, respect dependencies

---

## Testing Anti-Patterns

### 14. No Deterministic Test Mode
**Observed in**: Most frameworks

**Problem**:
- Hard to test LLM-based code
- No mock LLM responses
- No record/replay
- Tests require real API calls
- Flaky tests

**Impact**:
- Tests are slow
- Tests cost money
- Cannot test offline
- Hard to reproduce failures
- CI/CD challenges

**Recommendation**:
```python
# Pydantic-AI's test model
class TestModel:
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.call_count = 0

    async def generate(self, messages):
        response = self.responses[self.call_count]
        self.call_count += 1
        return Response(content=response)

# Usage in tests
def test_agent():
    agent = Agent(
        llm=TestModel([
            "I'll search for that",
            "Here are the results: ..."
        ])
    )
    result = agent.run("test query")
    assert result.success
```

**Better Alternative**: Mock LLM responses, record/replay cassettes, deterministic test mode

---

## Summary

### Top 5 Most Critical Anti-Patterns

1. **Unbounded Memory Growth** - Affects 80% of frameworks, causes production failures
2. **Silent Exception Swallowing** - Hides failures, makes debugging impossible
3. **No Max Iterations** - Agent hangs, infinite loops, runaway costs
4. **Mutable State Without Locks** - Race conditions, non-deterministic behavior
5. **No Tool Sandboxing** - Security risk, resource exhaustion, blocking

### Common Themes

- **Missing Resource Management**: Token budgets, timeouts, sandboxing
- **Poor Error Handling**: Silent failures, no retry logic, no circuit breakers
- **Over-Engineering**: Deep inheritance, god objects, 250+ config fields
- **Under-Engineering**: No summarization, no parallelism, no testing support
- **Type Safety Gaps**: String-based routing, Any types, mutable defaults

### Framework-Specific Worst Offenders

- **Configuration Explosion**: Agno (250 fields), crewAI (200 fields)
- **Memory Management**: Swarm, Pydantic-AI, Google ADK (no eviction at all)
- **Sync-First Design**: crewAI, Agno (dual APIs everywhere)
- **Global State**: LlamaIndex (Settings singleton)
- **String Routing**: MetaGPT (class name matching)

### Lessons for New Framework

**DO**:
- Frozen dataclasses by default
- Token budgets with automatic eviction
- Three-layer retry (graph, tool, HTTP)
- Protocol-first extensibility
- Native async throughout
- Error-as-data for LLM feedback
- Max iterations with graceful degradation

**DON'T**:
- Silent exception swallowing
- Unbounded state growth
- String-based identifiers
- Global mutable state
- Deep inheritance (> 1 level)
- Sync wrapped in async.to_thread
- God objects (keep classes under 300 LOC)

