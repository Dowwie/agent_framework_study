# Reference Architecture Specification

A new agent framework design informed by architectural forensics of 15 production frameworks.

Date: 2025-12-23
Based on: MetaGPT, Agent-Zero, Agno, AutoGen, AWS Strands, CAMEL, crewAI, Google ADK, LangGraph, LlamaIndex, MS Agent Framework, OpenAI Agents, Pydantic-AI, Swarm

## Design Principles

1. **Async-First**: Native async/await throughout, optional sync wrappers at entry points only
2. **Type-Safe**: Generics for DI, Pydantic for validation, frozen dataclasses for immutability
3. **Protocol-Based**: Structural typing via `@runtime_checkable` Protocol, minimal ABCs
4. **Error-as-Data**: Exceptions for critical failures, error messages for LLM self-correction
5. **Resource-Aware**: Token budgets, timeouts, sandboxing, circuit breakers from day one
6. **Observable**: OpenTelemetry integration, structured logging, event streaming
7. **Compositional**: Thin protocols, composition over inheritance, max depth 1

## Core Primitives

### Message

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Any
from uuid import UUID, uuid4

@dataclass(frozen=True)
class Message:
    """Immutable message in agent conversation.

    Based on: AutoGen, LangGraph, OpenAI Agents patterns
    """
    id: UUID = field(default_factory=uuid4)
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Tool-specific fields
    tool_calls: tuple[ToolCall, ...] | None = None
    tool_call_id: str | None = None

    # Optional fields
    reasoning: str | None = None  # For o1-style models
    images: tuple[str, ...] | None = None  # URLs or base64
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Validation: tool role must have tool_call_id
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("Tool messages must have tool_call_id")

@dataclass(frozen=True)
class ToolCall:
    """LLM request to execute a tool.

    Based on: OpenAI function calling format
    """
    id: str
    name: str
    arguments: dict[str, Any]
```

### State

```python
from typing import Annotated, TypedDict, Callable

# Reducer for message aggregation (LangGraph pattern)
def add_messages(
    existing: tuple[Message, ...],
    new: tuple[Message, ...]
) -> tuple[Message, ...]:
    """Merge messages by ID, append new ones."""
    seen = {msg.id: msg for msg in existing}
    for msg in new:
        seen[msg.id] = msg
    return tuple(seen.values())

class AgentState(TypedDict):
    """Typed agent state with custom reducers.

    Based on: LangGraph's Annotated reducer pattern
    """
    # Messages use custom merge logic
    messages: Annotated[tuple[Message, ...], add_messages]

    # Simple fields use last-value semantics
    user_id: str
    session_id: str
    iteration: int

    # Context variables (hidden from LLM)
    context: dict[str, Any]
```

### Result

```python
@dataclass(frozen=True)
class AgentResult:
    """Result of agent execution.

    Based on: Pydantic-AI Result types
    """
    output: str
    state: AgentState
    messages: tuple[Message, ...]
    usage: TokenUsage
    iterations: int
    is_truncated: bool = False  # Hit max iterations
    error: Exception | None = None

    # Streaming support
    events: tuple[Event, ...] = ()

@dataclass(frozen=True)
class StreamEvent:
    """Event emitted during streaming.

    Based on: Google ADK, LangGraph event patterns
    """
    type: Literal["token", "tool_start", "tool_end", "agent_switch", "error"]
    data: Any
    timestamp: datetime = field(default_factory=datetime.utcnow)

@dataclass(frozen=True)
class TokenUsage:
    """Token usage tracking.

    Based on: Pydantic-AI usage limits
    """
    input_tokens: int
    output_tokens: int
    total_tokens: int

    def exceeds(self, limit: "TokenBudget") -> bool:
        return (
            self.input_tokens > limit.max_input_tokens or
            self.output_tokens > limit.max_output_tokens or
            self.total_tokens > limit.max_total_tokens
        )
```

## Interface Contracts

### LLM Protocol

```python
from typing import Protocol, AsyncIterator, runtime_checkable

@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers.

    Based on: MS Agent Framework, AutoGen Protocol patterns
    """
    async def generate(
        self,
        messages: tuple[Message, ...],
        tools: tuple[ToolSchema, ...] | None = None,
        **kwargs
    ) -> LLMResponse:
        """Generate completion for messages."""
        ...

    async def stream(
        self,
        messages: tuple[Message, ...],
        tools: tuple[ToolSchema, ...] | None = None,
        **kwargs
    ) -> AsyncIterator[StreamChunk]:
        """Stream completion tokens."""
        ...

@dataclass(frozen=True)
class LLMResponse:
    """Response from LLM.

    Based on: Google ADK error-in-response pattern
    """
    content: str
    tool_calls: tuple[ToolCall, ...] | None = None
    reasoning: str | None = None
    usage: TokenUsage
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter"]
    error: LLMError | None = None  # Non-fatal errors

@dataclass(frozen=True)
class StreamChunk:
    """Streaming chunk from LLM."""
    delta: str
    tool_call_delta: ToolCall | None = None
    finish_reason: Literal["stop", "length", "tool_calls"] | None = None
```

### Tool Protocol

```python
@runtime_checkable
class Tool(Protocol):
    """Protocol for agent tools.

    Based on: Pydantic-AI, CAMEL introspection patterns
    """
    @property
    def name(self) -> str:
        """Tool identifier."""
        ...

    @property
    def schema(self) -> ToolSchema:
        """JSON schema for tool parameters."""
        ...

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute tool with arguments."""
        ...

@dataclass(frozen=True)
class ToolSchema:
    """JSON schema for tool.

    Based on: OpenAI function calling schema
    """
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema

@dataclass(frozen=True)
class ToolResult:
    """Result of tool execution.

    Based on: LlamaIndex error-as-data, AWS Strands status pattern
    """
    content: str
    is_error: bool = False
    images: tuple[str, ...] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### Memory Protocol

```python
@runtime_checkable
class Memory(Protocol):
    """Protocol for agent memory.

    Based on: Agent-Zero three-tier, LangGraph checkpointing
    """
    async def get_context(
        self,
        state: AgentState,
        token_budget: int
    ) -> tuple[Message, ...]:
        """Retrieve relevant messages within token budget."""
        ...

    async def save(self, state: AgentState) -> None:
        """Persist agent state."""
        ...

    async def clear(self, session_id: str) -> None:
        """Clear session history."""
        ...

# Reference implementation
class HierarchicalMemory:
    """Three-tier memory with compression.

    Based on: Agent-Zero hierarchical compression (50/30/20)
    """
    def __init__(
        self,
        llm: LLMProvider,
        vector_store: VectorStore | None = None
    ):
        self.llm = llm
        self.vector_store = vector_store
        self.recent_limit = 0.5  # 50% of budget
        self.summary_limit = 0.3  # 30% of budget
        self.semantic_limit = 0.2  # 20% of budget

    async def get_context(
        self,
        state: AgentState,
        token_budget: int
    ) -> tuple[Message, ...]:
        messages = state["messages"]
        current_tokens = count_tokens(messages)

        if current_tokens <= token_budget:
            return messages

        # Tier 1: Recent messages (50%)
        recent_budget = int(token_budget * self.recent_limit)
        recent = self._get_recent(messages, recent_budget)

        # Tier 2: Summarized history (30%)
        summary_budget = int(token_budget * self.summary_limit)
        summary = await self._summarize_old(
            messages[:-len(recent)],
            summary_budget
        )

        # Tier 3: Semantic retrieval (20%)
        semantic_budget = int(token_budget * self.semantic_limit)
        semantic = await self._retrieve_semantic(
            state,
            semantic_budget
        )

        return tuple([*semantic, summary, *recent])

    def _get_recent(
        self,
        messages: tuple[Message, ...],
        budget: int
    ) -> tuple[Message, ...]:
        """FIFO eviction within budget."""
        result = []
        tokens = 0

        for msg in reversed(messages):
            msg_tokens = count_tokens([msg])
            if tokens + msg_tokens > budget:
                break
            result.insert(0, msg)
            tokens += msg_tokens

        return tuple(result)

    async def _summarize_old(
        self,
        messages: tuple[Message, ...],
        budget: int
    ) -> Message:
        """LLM-based summarization."""
        if not messages:
            return Message(
                role="system",
                content="No previous conversation."
            )

        summary_text = await self.llm.generate(
            messages=(
                Message(
                    role="system",
                    content="Summarize the following conversation concisely:"
                ),
                Message(
                    role="user",
                    content="\n\n".join(msg.content for msg in messages)
                )
            ),
            tools=None
        )

        return Message(
            role="system",
            content=f"Previous conversation summary:\n{summary_text.content}"
        )

    async def _retrieve_semantic(
        self,
        state: AgentState,
        budget: int
    ) -> tuple[Message, ...]:
        """Vector search for relevant context."""
        if not self.vector_store:
            return ()

        query = state["messages"][-1].content
        results = await self.vector_store.search(
            query=query,
            limit=10,
            token_budget=budget
        )

        return tuple(
            Message(
                role="system",
                content=f"Relevant context: {result.content}"
            )
            for result in results
        )
```

## Agent Architecture

### Agent Core

```python
from typing import Generic, TypeVar

DepsT = TypeVar("DepsT")

@dataclass
class Agent(Generic[DepsT]):
    """Type-safe agent with dependency injection.

    Based on: Pydantic-AI generic types, OpenAI Agents configuration
    """
    # Core configuration
    llm: LLMProvider
    tools: tuple[Tool, ...] = ()
    memory: Memory | None = None

    # Instructions can be static or dynamic
    instructions: str | Callable[[RunContext[DepsT]], str] = "You are a helpful assistant."

    # Resource limits
    max_iterations: int = 10
    token_budget: TokenBudget = field(default_factory=TokenBudget.default)
    tool_timeout: float = 30.0

    # Hooks for extensibility
    hooks: AgentHooks[DepsT] | None = None

    # Handoffs for multi-agent
    handoffs: tuple["Agent", ...] = ()

    async def run(
        self,
        input: str,
        deps: DepsT | None = None,
        state: AgentState | None = None
    ) -> AgentResult:
        """Run agent to completion.

        Based on: Pydantic-AI graph execution, LangGraph BSP model
        """
        # Initialize context
        ctx = RunContext(
            agent=self,
            deps=deps,
            state=state or self._initial_state(),
            usage=TokenUsage(0, 0, 0),
            iteration=0
        )

        # Call lifecycle hook
        if self.hooks:
            await self.hooks.on_start(ctx)

        # Main execution loop
        try:
            result = await self._execute_loop(ctx, input)

            if self.hooks:
                await self.hooks.on_end(ctx, result)

            return result

        except Exception as e:
            if self.hooks:
                await self.hooks.on_error(ctx, e)
            raise

    async def stream(
        self,
        input: str,
        deps: DepsT | None = None,
        state: AgentState | None = None
    ) -> AsyncIterator[StreamEvent]:
        """Stream agent execution events.

        Based on: Google ADK event streaming, LangGraph stream modes
        """
        ctx = RunContext(
            agent=self,
            deps=deps,
            state=state or self._initial_state(),
            usage=TokenUsage(0, 0, 0),
            iteration=0
        )

        async for event in self._execute_loop_streaming(ctx, input):
            yield event

    async def _execute_loop(
        self,
        ctx: RunContext[DepsT],
        input: str
    ) -> AgentResult:
        """Core execution loop with resource limits.

        Based on: Pydantic-AI graph nodes, error-as-data pattern
        """
        # Add user message
        ctx.state["messages"] = ctx.state["messages"] + (
            Message(role="user", content=input),
        )

        for iteration in range(self.max_iterations):
            ctx.iteration = iteration

            # Pre-flight token check (Pydantic-AI pattern)
            if ctx.usage.exceeds(self.token_budget):
                return AgentResult(
                    output="Token budget exceeded",
                    state=ctx.state,
                    messages=ctx.state["messages"],
                    usage=ctx.usage,
                    iterations=iteration,
                    is_truncated=True
                )

            # Get memory context
            context_messages = await self._get_context(ctx)

            # Call LLM
            try:
                response = await self.llm.generate(
                    messages=context_messages,
                    tools=tuple(tool.schema for tool in self.tools)
                )
            except LLMError as e:
                # Circuit breaker check
                if self._should_circuit_break(e):
                    raise

                # Retry with backoff
                await asyncio.sleep(2 ** iteration)
                continue

            # Update usage
            ctx.usage = TokenUsage(
                input_tokens=ctx.usage.input_tokens + response.usage.input_tokens,
                output_tokens=ctx.usage.output_tokens + response.usage.output_tokens,
                total_tokens=ctx.usage.total_tokens + response.usage.total_tokens
            )

            # Add assistant message
            ctx.state["messages"] = ctx.state["messages"] + (
                Message(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                    reasoning=response.reasoning
                ),
            )

            # Check for completion
            if not response.tool_calls:
                # Save to memory
                if self.memory:
                    await self.memory.save(ctx.state)

                return AgentResult(
                    output=response.content,
                    state=ctx.state,
                    messages=ctx.state["messages"],
                    usage=ctx.usage,
                    iterations=iteration + 1
                )

            # Execute tools (parallel, with circuit breaker)
            tool_results = await self._execute_tools_parallel(
                ctx,
                response.tool_calls
            )

            # Add tool results to state
            ctx.state["messages"] = ctx.state["messages"] + tuple(tool_results)

            # Check for handoffs
            handoff = self._check_handoff(tool_results)
            if handoff:
                return await handoff.run(
                    input="Continue from previous agent",
                    deps=ctx.deps,
                    state=ctx.state
                )

        # Max iterations reached - graceful degradation
        return AgentResult(
            output=ctx.state["messages"][-1].content,
            state=ctx.state,
            messages=ctx.state["messages"],
            usage=ctx.usage,
            iterations=self.max_iterations,
            is_truncated=True
        )

    async def _execute_tools_parallel(
        self,
        ctx: RunContext[DepsT],
        tool_calls: tuple[ToolCall, ...]
    ) -> tuple[Message, ...]:
        """Execute tools in parallel with circuit breaker.

        Based on: CAMEL parallel execution, AWS Strands error handling
        """
        async def execute_one(call: ToolCall) -> Message:
            tool = self._get_tool(call.name)

            if not tool:
                # Graceful missing tool (Swarm pattern)
                return Message(
                    role="tool",
                    tool_call_id=call.id,
                    content=f"Error: Tool '{call.name}' not found"
                )

            try:
                # Execute with timeout and sandboxing
                result = await execute_tool_sandboxed(
                    tool=tool,
                    arguments=call.arguments,
                    timeout=self.tool_timeout
                )

                return Message(
                    role="tool",
                    tool_call_id=call.id,
                    content=result.content,
                    images=result.images,
                    metadata=result.metadata
                )

            except Exception as e:
                # Error-as-data for LLM self-correction
                return Message(
                    role="tool",
                    tool_call_id=call.id,
                    content=f"Error executing {call.name}: {e}\n\nPlease try again with corrected parameters."
                )

        # Parallel execution
        results = await asyncio.gather(
            *[execute_one(call) for call in tool_calls],
            return_exceptions=True
        )

        # Convert exceptions to error messages
        return tuple(
            result if isinstance(result, Message)
            else Message(
                role="tool",
                tool_call_id=tool_calls[i].id,
                content=f"Fatal error: {result}"
            )
            for i, result in enumerate(results)
        )

    async def _get_context(
        self,
        ctx: RunContext[DepsT]
    ) -> tuple[Message, ...]:
        """Assemble context for LLM.

        Based on: LlamaIndex initial_token_count, Agent-Zero compression
        """
        # Get dynamic instructions
        if callable(self.instructions):
            instructions = self.instructions(ctx)
        else:
            instructions = self.instructions

        system_message = Message(
            role="system",
            content=instructions
        )

        # Get memory context within budget
        if self.memory:
            # Reserve tokens for system message and new response
            reserved = count_tokens([system_message]) + 1000
            budget = self.token_budget.max_total_tokens - reserved

            memory_messages = await self.memory.get_context(
                state=ctx.state,
                token_budget=budget
            )
        else:
            memory_messages = ctx.state["messages"]

        return (system_message,) + memory_messages

    def _get_tool(self, name: str) -> Tool | None:
        """Get tool by name."""
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    def _check_handoff(
        self,
        tool_results: tuple[Message, ...]
    ) -> "Agent | None":
        """Check if tool results contain agent handoff.

        Based on: Swarm handoff pattern
        """
        # Implementation depends on handoff mechanism
        # Could be special tool result or metadata flag
        return None

    def _should_circuit_break(self, error: LLMError) -> bool:
        """Check if error should open circuit breaker."""
        # Track error rates, open circuit after threshold
        return False

    def _initial_state(self) -> AgentState:
        """Create initial agent state."""
        return AgentState(
            messages=(),
            user_id="",
            session_id="",
            iteration=0,
            context={}
        )
```

### Run Context

```python
@dataclass
class RunContext(Generic[DepsT]):
    """Context for agent execution.

    Based on: Pydantic-AI RunContext, OpenAI Agents ToolContext
    """
    agent: Agent[DepsT]
    deps: DepsT | None
    state: AgentState
    usage: TokenUsage
    iteration: int

@dataclass
class TokenBudget:
    """Token budget limits.

    Based on: Pydantic-AI usage limits
    """
    max_input_tokens: int
    max_output_tokens: int
    max_total_tokens: int

    @classmethod
    def default(cls) -> "TokenBudget":
        return cls(
            max_input_tokens=100_000,
            max_output_tokens=10_000,
            max_total_tokens=110_000
        )
```

### Tool Registration

```python
from typing import ParamSpec, TypeVar, Callable
import inspect

P = ParamSpec("P")
R = TypeVar("R")

def tool(
    func: Callable[P, R] | None = None,
    *,
    name: str | None = None,
    description: str | None = None
) -> Callable[[Callable[P, R]], Tool]:
    """Decorator for tool registration.

    Based on: CAMEL introspection, Pydantic-AI auto-schema
    """
    def decorator(fn: Callable[P, R]) -> FunctionTool:
        # Generate schema from function signature
        sig = inspect.signature(fn)
        params_schema = {}

        for param_name, param in sig.parameters.items():
            # Skip context parameters
            if param_name in ("ctx", "context"):
                continue

            # Generate JSON schema from type annotation
            if param.annotation != inspect.Parameter.empty:
                params_schema[param_name] = type_to_json_schema(
                    param.annotation
                )

        schema = ToolSchema(
            name=name or fn.__name__,
            description=description or (fn.__doc__ or "").strip(),
            parameters={
                "type": "object",
                "properties": params_schema,
                "required": [
                    p for p in sig.parameters
                    if p not in ("ctx", "context")
                    and sig.parameters[p].default == inspect.Parameter.empty
                ]
            }
        )

        return FunctionTool(
            fn=fn,
            schema=schema
        )

    if func is None:
        return decorator
    else:
        return decorator(func)

@dataclass
class FunctionTool:
    """Tool implementation wrapping function.

    Based on: Pydantic-AI FunctionTool, auto-context detection
    """
    fn: Callable
    schema: ToolSchema

    @property
    def name(self) -> str:
        return self.schema.name

    async def execute(
        self,
        arguments: dict[str, Any],
        context: RunContext | None = None
    ) -> ToolResult:
        """Execute function with arguments."""
        # Inject context if function expects it
        sig = inspect.signature(self.fn)
        if "ctx" in sig.parameters or "context" in sig.parameters:
            arguments = {**arguments, "ctx": context}

        # Execute (handle both sync and async)
        if inspect.iscoroutinefunction(self.fn):
            result = await self.fn(**arguments)
        else:
            result = await asyncio.to_thread(self.fn, **arguments)

        # Convert to ToolResult
        if isinstance(result, ToolResult):
            return result
        else:
            return ToolResult(content=str(result))
```

## Multi-Agent Patterns

### Handoff Pattern (Swarm-Style)

```python
@tool
def transfer_to_sales() -> Agent:
    """Transfer conversation to sales agent."""
    return sales_agent

# Agent with handoffs
agent = Agent(
    llm=llm,
    tools=(transfer_to_sales,),
    handoffs=(sales_agent,)
)
```

### Graph Pattern (LangGraph-Style)

```python
from enum import Enum

class WorkflowState(TypedDict):
    messages: Annotated[tuple[Message, ...], add_messages]
    next_agent: str
    result: str | None

class Workflow:
    """Graph-based multi-agent workflow.

    Based on: LangGraph StateGraph, MS Agent Framework
    """
    def __init__(self):
        self.nodes: dict[str, Agent] = {}
        self.edges: dict[str, Callable[[WorkflowState], str]] = {}

    def add_agent(self, name: str, agent: Agent):
        """Add agent as node."""
        self.nodes[name] = agent

    def add_edge(
        self,
        from_node: str,
        to_node: str,
        condition: Callable[[WorkflowState], bool] | None = None
    ):
        """Add edge between nodes."""
        if condition:
            # Conditional edge
            def route(state: WorkflowState) -> str:
                return to_node if condition(state) else "END"
            self.edges[from_node] = route
        else:
            # Direct edge
            self.edges[from_node] = lambda s: to_node

    async def run(self, input: str) -> AgentResult:
        """Execute workflow."""
        state = WorkflowState(
            messages=(),
            next_agent="START",
            result=None
        )

        current = "START"
        while current != "END":
            agent = self.nodes[current]
            result = await agent.run(input, state=state)

            state["messages"] = result.messages
            state["result"] = result.output

            # Determine next node
            router = self.edges.get(current)
            if router:
                current = router(state)
            else:
                current = "END"

        return result
```

### Society Pattern (CAMEL-Style)

```python
class WorkforceMode(Enum):
    """Orchestration modes.

    Based on: CAMEL Workforce patterns
    """
    PARALLEL = "parallel"  # All agents execute independently
    PIPELINE = "pipeline"  # Sequential with data flow
    LOOP = "loop"  # Iterative refinement

class Workforce:
    """High-level multi-agent orchestration.

    Based on: CAMEL society patterns
    """
    def __init__(
        self,
        agents: tuple[Agent, ...],
        mode: WorkforceMode = WorkforceMode.PARALLEL
    ):
        self.agents = agents
        self.mode = mode

    async def run(self, input: str) -> list[AgentResult]:
        """Execute agents according to mode."""
        if self.mode == WorkforceMode.PARALLEL:
            return await asyncio.gather(
                *[agent.run(input) for agent in self.agents]
            )

        elif self.mode == WorkforceMode.PIPELINE:
            result = input
            results = []
            for agent in self.agents:
                agent_result = await agent.run(result)
                results.append(agent_result)
                result = agent_result.output
            return results

        elif self.mode == WorkforceMode.LOOP:
            results = []
            current_input = input
            for iteration in range(10):  # Max iterations
                iteration_results = []
                for agent in self.agents:
                    result = await agent.run(current_input)
                    iteration_results.append(result)

                # Check convergence
                if all(r.output == iteration_results[0].output for r in iteration_results):
                    break

                # Refine input for next iteration
                current_input = "\n".join(r.output for r in iteration_results)
                results.extend(iteration_results)

            return results
```

## Observability

### Hooks

```python
@runtime_checkable
class AgentHooks(Protocol, Generic[DepsT]):
    """Lifecycle hooks for agents.

    Based on: OpenAI Agents hooks, Google ADK middleware
    """
    async def on_start(self, ctx: RunContext[DepsT]) -> None:
        """Called when agent starts."""
        ...

    async def on_llm_start(
        self,
        ctx: RunContext[DepsT],
        messages: tuple[Message, ...]
    ) -> None:
        """Called before LLM call."""
        ...

    async def on_llm_end(
        self,
        ctx: RunContext[DepsT],
        response: LLMResponse
    ) -> None:
        """Called after LLM call."""
        ...

    async def on_tool_start(
        self,
        ctx: RunContext[DepsT],
        tool_call: ToolCall
    ) -> None:
        """Called before tool execution."""
        ...

    async def on_tool_end(
        self,
        ctx: RunContext[DepsT],
        result: ToolResult
    ) -> None:
        """Called after tool execution."""
        ...

    async def on_end(
        self,
        ctx: RunContext[DepsT],
        result: AgentResult
    ) -> None:
        """Called when agent completes."""
        ...

    async def on_error(
        self,
        ctx: RunContext[DepsT],
        error: Exception
    ) -> None:
        """Called when agent errors."""
        ...
```

### OpenTelemetry Integration

```python
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

class TelemetryHooks:
    """OpenTelemetry integration hooks.

    Based on: AutoGen, Google ADK observability
    """
    def __init__(self, tracer_name: str = "agent-framework"):
        self.tracer = trace.get_tracer(tracer_name)

    async def on_start(self, ctx: RunContext) -> None:
        ctx.span = self.tracer.start_span("agent.run")
        ctx.span.set_attribute("agent.iteration", ctx.iteration)

    async def on_llm_start(
        self,
        ctx: RunContext,
        messages: tuple[Message, ...]
    ) -> None:
        ctx.llm_span = self.tracer.start_span(
            "llm.generate",
            context=ctx.span
        )
        ctx.llm_span.set_attribute("llm.input_messages", len(messages))

    async def on_llm_end(
        self,
        ctx: RunContext,
        response: LLMResponse
    ) -> None:
        ctx.llm_span.set_attribute("llm.output_tokens", response.usage.output_tokens)
        ctx.llm_span.set_attribute("llm.finish_reason", response.finish_reason)
        ctx.llm_span.end()

    async def on_tool_start(
        self,
        ctx: RunContext,
        tool_call: ToolCall
    ) -> None:
        ctx.tool_span = self.tracer.start_span(
            f"tool.{tool_call.name}",
            context=ctx.span
        )

    async def on_tool_end(
        self,
        ctx: RunContext,
        result: ToolResult
    ) -> None:
        ctx.tool_span.set_attribute("tool.is_error", result.is_error)
        ctx.tool_span.end()

    async def on_end(
        self,
        ctx: RunContext,
        result: AgentResult
    ) -> None:
        ctx.span.set_attribute("agent.iterations", result.iterations)
        ctx.span.set_attribute("agent.total_tokens", result.usage.total_tokens)
        ctx.span.set_status(Status(StatusCode.OK))
        ctx.span.end()

    async def on_error(
        self,
        ctx: RunContext,
        error: Exception
    ) -> None:
        ctx.span.record_exception(error)
        ctx.span.set_status(Status(StatusCode.ERROR, str(error)))
        ctx.span.end()
```

## Usage Examples

### Simple Chatbot

```python
@tool
async def search_web(query: str) -> str:
    """Search the web for information."""
    return await search_api.query(query)

agent = Agent(
    llm=OpenAIProvider(model="gpt-4"),
    tools=(search_web,),
    instructions="You are a helpful assistant."
)

result = await agent.run("What's the weather in SF?")
print(result.output)
```

### With Dependencies

```python
@dataclass
class DatabaseDeps:
    db: Database

@tool
async def get_user_data(ctx: RunContext[DatabaseDeps], user_id: str) -> dict:
    """Retrieve user data from database."""
    return await ctx.deps.db.query("SELECT * FROM users WHERE id = ?", user_id)

agent = Agent[DatabaseDeps](
    llm=llm,
    tools=(get_user_data,),
)

result = await agent.run(
    "Get info for user 123",
    deps=DatabaseDeps(db=database)
)
```

### Multi-Agent Workflow

```python
# Define specialist agents
researcher = Agent(
    llm=llm,
    tools=(search_web, read_paper),
    instructions="You are a research specialist."
)

writer = Agent(
    llm=llm,
    tools=(save_draft, format_text),
    instructions="You are a writing specialist."
)

# Sequential pipeline
workflow = Workforce(
    agents=(researcher, writer),
    mode=WorkforceMode.PIPELINE
)

results = await workflow.run("Write a blog post about AI agents")
final_output = results[-1].output
```

## Implementation Roadmap

### Phase 1: Core Primitives (Week 1-2)
- [ ] Message, State, Result types
- [ ] LLMProvider Protocol with OpenAI/Anthropic implementations
- [ ] Basic Agent class with sync execution loop
- [ ] Tool Protocol and decorator
- [ ] Simple in-memory Memory implementation

### Phase 2: Async & Streaming (Week 3-4)
- [ ] Convert to native async/await
- [ ] AsyncIterator streaming support
- [ ] Parallel tool execution
- [ ] Event streaming (tokens, tool calls, state)
- [ ] Sync wrappers at entry points

### Phase 3: Resource Management (Week 5-6)
- [ ] Token counting integration (tiktoken)
- [ ] Hierarchical memory with compression
- [ ] Three-layer retry logic
- [ ] Circuit breaker implementation
- [ ] Tool sandboxing (subprocess)
- [ ] Timeout enforcement

### Phase 4: Multi-Agent (Week 7-8)
- [ ] Handoff pattern (Swarm-style)
- [ ] Graph execution (LangGraph BSP)
- [ ] Society patterns (Workforce modes)
- [ ] State checkpointing
- [ ] Resume from checkpoint

### Phase 5: Observability (Week 9-10)
- [ ] OpenTelemetry integration
- [ ] Structured logging
- [ ] Usage tracking and billing
- [ ] LangGraph-style stream modes (values, updates, debug)
- [ ] Tracing visualization

### Phase 6: Production Hardening (Week 11-12)
- [ ] Comprehensive error taxonomy
- [ ] Guardrails (input/output validation)
- [ ] Rate limiting
- [ ] Persistent memory backends (SQL, Redis)
- [ ] Session management
- [ ] Load testing and optimization

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                          Agent[DepsT]                        │
├──────────────────────────────────────────────────────────────┤
│  Instructions  │  Max Iterations  │  Token Budget  │  Hooks  │
├──────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │   LLM    │  │  Tools   │  │  Memory  │  │ Handoffs │    │
│  │ Protocol │  │ Protocol │  │ Protocol │  │  (Agents)│    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
│                                                                │
├──────────────────────────────────────────────────────────────┤
│                    Execution Loop                             │
│                                                                │
│  1. Get Context (Memory + Instructions)                       │
│  2. LLM Generate (with tools)                                 │
│  3. Execute Tools (parallel, sandboxed)                       │
│  4. Update State (immutable)                                  │
│  5. Check Termination (max iterations, handoff, done)        │
│  6. Repeat or Return                                          │
│                                                                │
├──────────────────────────────────────────────────────────────┤
│              State (Immutable, Checkpointable)                │
│                                                                │
│  Messages (with reducers) │ Usage │ Context Variables        │
└──────────────────────────────────────────────────────────────┘

             ▲                                  │
             │                                  │
             │ Hooks                            │ Events
             │                                  ▼

┌──────────────────────────┐      ┌──────────────────────────┐
│   OpenTelemetry          │      │    Stream Consumers      │
│   (Tracing, Metrics)     │      │    (UI, Logging, etc)    │
└──────────────────────────┘      └──────────────────────────┘
```

## Key Design Decisions Rationale

1. **Generic Types for DI**: Type-safe dependencies without global state (Pydantic-AI pattern)
2. **Frozen Dataclasses**: Immutability prevents mutation bugs in async code (LangGraph pattern)
3. **Protocol-First**: Structural typing enables flexibility without coupling (MS Agent, AutoGen)
4. **Error-as-Data**: LLM self-correction without complex retry logic (LlamaIndex, Google ADK)
5. **Three-Layer Retry**: Separation of concerns for different failure modes (Pydantic-AI)
6. **Hierarchical Memory**: Optimize for different retention needs (Agent-Zero 50/30/20)
7. **Parallel Tools**: Leverage async for speed (CAMEL concurrent execution)
8. **Sandboxed Execution**: Security and resource limits (Agent-Zero Docker, best practice)
9. **Max Iterations**: Prevent infinite loops with graceful degradation (best practice)
10. **Observability Built-In**: Production requirement, not afterthought (AutoGen, Google ADK)

## Success Metrics

Framework is successful if it achieves:

- **Type Safety**: 100% type coverage, mypy strict mode passes
- **Performance**: < 100ms overhead per agent step
- **Reliability**: 99.9% uptime in production deployments
- **Developer Experience**: < 10 minutes from install to first agent
- **Extensibility**: New LLM provider in < 100 LOC
- **Production-Ready**: Passes all security/reliability audits

