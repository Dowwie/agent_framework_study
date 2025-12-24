# Framework Comparison Matrix

Analysis Date: 2025-12-23
Frameworks Analyzed: 15

## Engineering Chassis

### Data Substrate & Typing

| Dimension | Leading Approaches | Notable Frameworks | Recommendation |
|-----------|-------------------|-------------------|----------------|
| **Typing Strategy** | Pydantic V2 dominant (11/15) | MetaGPT, LlamaIndex, Pydantic-AI, Google ADK, crewAI | **Pydantic V2** for validation-critical boundaries, frozen dataclasses for internal types |
| **Immutability** | Mixed - mostly mutable by default | LangGraph (frozen dataclasses), MS Agent (mixed) | **Frozen by default** - explicit `frozen=True` on dataclasses, immutable state with copy-on-write |
| **Serialization** | Pydantic auto-serialization vs manual | LlamaIndex (class name injection), Agent-Zero (manual JSON) | **Class name injection** pattern (LlamaIndex) + Pydantic `model_dump(mode="json")` |
| **Generic Types** | Strong in type-safe frameworks | Pydantic-AI (`Agent[DepsT, OutputT]`), MS Agent (Protocol generics) | **Generics for DI** - type-safe dependency injection via generic type parameters |

**Key Insight**: Hybrid approach wins - Pydantic for validation at boundaries, frozen dataclasses for internal speed.

### Execution Model

| Dimension | Pattern | Frameworks | Recommendation |
|-----------|---------|------------|----------------|
| **Async Model** | Native async vs sync-first | **Native**: LangGraph, Pydantic-AI, MS Agent, AWS Strands, Google ADK<br>**Sync-first**: Agno, Agent-Zero, crewAI | **Native async** with optional sync wrappers at entry points only |
| **Concurrency** | Tool parallelism support | CAMEL (concurrent tools + streaming), Agent-Zero (ThreadPoolExecutor), **Most**: Sequential only | **Parallel tool execution** via `asyncio.gather()` with configurable concurrency limits |
| **Streaming** | AsyncGenerator patterns | LangGraph (three stream modes), AWS Strands (bidirectional), Pydantic-AI (auto-complete), Google ADK (events) | **Event-driven streaming** with AsyncGenerator[Event, None] + semantic events |
| **Event Loop Management** | Nested loop handling | OpenAI Agents (sophisticated reuse), Agent-Zero (`nest_asyncio`) | **Single event loop** - no nesting, proper async context manager patterns |

**Critical Pattern**: CAMEL's concurrent tool + streaming (execute tools in background while streaming content) reduces latency.

### Component Model & Extensibility

| Dimension | Pattern | Best Examples | Recommendation |
|-----------|---------|---------------|----------------|
| **Abstraction Depth** | Protocols vs ABCs vs Inheritance | **Protocol**: MS Agent, AutoGen<br>**ABC**: Most others<br>**Inheritance**: MetaGPT (depth 1), crewAI (depth 2) | **Protocols first** - structural typing, optional helper classes |
| **Dependency Injection** | Constructor injection dominant | Pydantic-AI (`RunContext[DepsT]`), MS Agent (generics), LlamaIndex (Settings singleton - anti-pattern) | **Generic type parameters** for type-safe DI, avoid globals |
| **Configuration** | Code-first vs config-heavy | **Code**: LangGraph, Swarm, Pydantic-AI<br>**Config**: Agno (250+ fields), AutoGen (component system) | **Code-first with YAML option** - builder pattern for presets |
| **Extension Points** | Tool/Agent/Memory hooks | MetaGPT (extensions), Agent-Zero (20+ hooks), CAMEL (metaclass auto-enhancement), Google ADK (middleware) | **Middleware pipeline** + lifecycle hooks (before/after agent, tool, LLM) |

**Anti-Pattern Alert**: Agno's 250-field Agent dataclass creates analysis paralysis. Use builder pattern with sensible defaults.

### Resilience & Error Handling

| Dimension | Pattern | Frameworks | Recommendation |
|-----------|---------|------------|----------------|
| **Retry Logic** | Exponential backoff | Agent-Zero (transient error detection), CAMEL (ModelManager fallback), Pydantic-AI (three-layer) | **Three-layer retry**: Graph-level (validation), Tool-level (with LLM feedback), HTTP-level (transient) |
| **Error Propagation** | Exception vs Result types | **Exception**: Most frameworks<br>**Error-as-data**: LlamaIndex, Google ADK, AWS Strands | **Error-as-data + retry messages** - LLM sees errors for self-correction |
| **Circuit Breakers** | Missing in all frameworks | None implemented | **Add circuit breaker** - track failure rates, auto-disable failing tools/LLMs |
| **Sandboxing** | Code execution isolation | Agent-Zero (Docker SSH), AWS Strands (subprocess mention) | **Subprocess isolation** with resource limits (CPU, memory, time, network) |
| **Timeout Enforcement** | Per-operation limits | CAMEL (metaclass auto-timeout), AWS Strands (hardcoded), **Most**: None | **Configurable timeouts** at all async boundaries (tool, LLM, agent, workflow) |

**Best Pattern**: Pydantic-AI's three-layer retry (graph validation → tool retry with feedback → HTTP transient errors)

## Cognitive Architecture

### Reasoning Patterns

| Pattern | Frameworks | Characteristics | Use Case |
|---------|------------|-----------------|----------|
| **ReAct** | MetaGPT, Agent-Zero, LlamaIndex, crewAI | Thought → Action → Observation loop | General-purpose tool use |
| **Function Calling** | Google ADK, Pydantic-AI, Swarm, OpenAI Agents | Native LLM function calls, no text parsing | Clean integration with GPT-4/Gemini |
| **Configurable** | MetaGPT (REACT/BY_ORDER/PLAN_AND_ACT) | Multiple modes selectable at runtime | Adapt to task complexity |
| **Graph-Based** | LangGraph, MS Agent, Pydantic-AI | User-defined state machines | Complex workflows, conditional routing |
| **None** | AutoGen | Framework-agnostic execution substrate | Maximum flexibility |

**Recommendation**: **Support multiple patterns** - Default to function calling (simpler), provide ReAct helper, enable graph-based for complex workflows.

**Critical Gap**: Most frameworks lack explicit planning phase. Add optional Plan-and-Solve variant.

### Memory Systems

| Tier | Implementation | Frameworks | Scalability |
|------|---------------|------------|-------------|
| **Short-Term** | In-memory conversation history | All frameworks | Unbounded growth risk in 12/15 |
| **Eviction** | Token-aware truncation | Agent-Zero (hierarchical compression 50/30/20), LlamaIndex (initial_token_count), AWS Strands (sliding window) | Agent-Zero's three-tier compression is best |
| **Summarization** | LLM-based compression | Agent-Zero (bulk/topic/message hierarchy), CAMEL (ChatSummaryMemoryBuffer), **Most**: None | Critical for long conversations |
| **Long-Term** | Vector DB integration | crewAI (RAG/Mem0), CAMEL (VectorMemory), MetaGPT (entity memory), LlamaIndex (core feature) | Essential for knowledge retention |
| **Persistence** | Session/checkpoint storage | LangGraph (SQL/Redis checkpoints), OpenAI Agents (SQLite/Conversations API), Google ADK (service abstraction) | Production requirement |

**Best Architecture**: Agent-Zero's hierarchical compression (Bulk 20% / Topic 30% / Message 50%) + vector DB for long-term

**Anti-Pattern**: Unbounded growth without eviction (12/15 frameworks). Always implement token budgets.

### Tool Interface

| Dimension | Approach | Examples | Recommendation |
|-----------|----------|----------|----------------|
| **Schema Generation** | Introspection-based | CAMEL (zero boilerplate), MetaGPT (AST parsing), Pydantic-AI (TypeAdapter), LangGraph (Pydantic via LangChain) | **Automatic from type hints + docstrings** |
| **Registration** | Decorator pattern dominant | `@tool`, `@function_tool`, `@register_tool` across all | **Decorator primary**, class-based for complex cases |
| **Error Feedback** | Feed errors to LLM | LlamaIndex (retry messages), Pydantic-AI (validation errors formatted), Swarm (missing tool), crewAI (observations) | **Structured error messages** sent to LLM for self-correction |
| **Context Injection** | RunContext/ToolContext | Pydantic-AI (auto-detect), OpenAI Agents (three signatures), Google ADK (ToolContext) | **Auto-detect context parameter** via signature inspection |
| **HITL** | Human-in-the-loop | Google ADK (ToolConfirmation), OpenAI Agents (guardrails) | **First-class confirmation** for destructive operations |
| **Parallel Execution** | Concurrent tool calls | CAMEL (asyncio.gather), **Most**: Sequential | **Configurable parallelism** with concurrency limits |

**Key Innovation**: CAMEL's metaclass auto-enhancement wraps all toolkit methods with timeout protection automatically.

### Multi-Agent Coordination

| Pattern | Frameworks | Mechanism | Use Case |
|---------|------------|-----------|----------|
| **Hierarchical** | Agent-Zero, crewAI, Google ADK, Agno, CAMEL | Supervisor delegates to workers | Task decomposition |
| **Sequential Handoff** | Swarm, OpenAI Agents | Tool-based agent switching | Triage, escalation |
| **Graph-Based** | LangGraph, MS Agent, AWS Strands | Edges define routing logic | Complex workflows |
| **Publish/Subscribe** | MetaGPT (environment bus), AutoGen (topics) | Message passing | Event-driven coordination |
| **Society Patterns** | CAMEL (RolePlaying, Workforce, BabyAGI) | High-level orchestration | Reusable patterns |
| **Peer-to-Peer** | Limited support | Mostly hierarchical | Collaborative deliberation |

**Best Patterns**:
- **Handoff**: Swarm/OpenAI Agents tool-based delegation (elegant, explicit)
- **Orchestration**: CAMEL Workforce (PARALLEL/PIPELINE/LOOP modes with failure handling)
- **Graph**: LangGraph BSP execution (deterministic, resumable)

**Missing**: True swarm behavior (parallel autonomous agents), consensus mechanisms (voting, quorum)

## Decision Matrix

### For Simple Chatbots
**Recommendation**: Swarm patterns (tool-based handoff) + function calling
- No graph overhead
- Clean agent switching
- Easy to understand

### For Production Workflows
**Recommendation**: LangGraph-style BSP + checkpointing + error-as-data
- Resumable execution
- Deterministic despite parallelism
- Rich error context

### For Multi-Agent Systems
**Recommendation**: CAMEL society patterns + MetaGPT action-message causality
- Reusable orchestration modes
- Traceable message routing
- Flexible coordination

### For Research/Experimentation
**Recommendation**: AutoGen-style infrastructure (no opinions)
- Maximum flexibility
- Protocol-based extensibility
- Multiple implementation options

## Synthesis Recommendations

### Must Have (Core Features)

1. **Pydantic V2 + Frozen Dataclasses**
   - Boundaries: Pydantic BaseModel for validation
   - Internal: `@dataclass(frozen=True)` for immutability
   - Serialization: LlamaIndex class name injection pattern

2. **Native Async with Event-Driven Streaming**
   - Async/await throughout
   - AsyncGenerator[Event, None] for streaming
   - Semantic events (not just tokens)
   - CAMEL's concurrent tool + streaming innovation

3. **Protocol-First Extensibility**
   - `@runtime_checkable` Protocol for interfaces
   - Optional base classes for convenience
   - Middleware pipeline for cross-cutting concerns
   - Lifecycle hooks (before/after agent/tool/LLM)

4. **Three-Layer Retry + Error-as-Data**
   - Graph: Output validation retries
   - Tool: Self-correction with LLM feedback
   - HTTP: Exponential backoff for transient failures
   - Circuit breakers for cascading failure prevention

5. **Hierarchical Memory with Token Budgets**
   - Short-term: Agent-Zero's 50/30/20 compression
   - Long-term: Vector DB for semantic retrieval
   - Eviction: Token-aware with summarization
   - Checkpointing: LangGraph-style persistence

6. **Introspection-Based Tools**
   - Decorator registration (`@tool`)
   - Automatic schema from types + docstrings
   - Parallel execution with limits
   - Structured error feedback to LLM

7. **Flexible Multi-Agent**
   - Handoff: Swarm-style tool delegation
   - Graph: LangGraph BSP for complex workflows
   - Society: CAMEL patterns (RolePlaying, Workforce)
   - Pub/Sub: MetaGPT-style message bus (optional)

### Should Have (Enhanced Features)

8. **Observability Built-In**
   - OpenTelemetry integration (AutoGen, Google ADK)
   - Structured logging with trace IDs
   - Token usage tracking (Pydantic-AI)
   - LangGraph's three stream modes (values, updates, debug)

9. **Resource Management**
   - Configurable timeouts at all boundaries
   - Token budgets with pre-flight estimation
   - Concurrency limits (tools, agents, LLM calls)
   - Sandboxing for tool execution

10. **Multiple Reasoning Patterns**
    - Function calling (default - simple, clean)
    - ReAct (explicit thought traces)
    - Plan-and-Solve (for complex tasks)
    - Graph-based (user-defined state machines)

### Nice to Have (Advanced Features)

11. **HITL Workflows**
    - Google ADK's ToolConfirmation pattern
    - OpenAI Agents' guardrails (input/output)
    - LangGraph interrupt mechanism
    - Approval workflows for destructive operations

12. **Dynamic System Prompts**
    - Pydantic-AI's callable instructions
    - Re-evaluation per step
    - Context-aware prompting

13. **MCP Integration**
    - Model Context Protocol for tool servers
    - Dynamic tool loading
    - Cross-framework tool reuse

## Framework Rankings

### Overall Architecture (Engineering + Cognitive)

1. **LangGraph** (9.2/10) - Best-in-class execution engine, checkpointing, BSP model
2. **Pydantic-AI** (8.8/10) - Type safety, DX, production-ready patterns
3. **AutoGen** (8.7/10) - Industrial-strength infrastructure, Protocol-first
4. **CAMEL** (8.5/10) - Tool DX, concurrent streaming, society patterns
5. **MS Agent Framework** (8.3/10) - Protocol-first, graph workflows, dual-language
6. **MetaGPT** (8.0/10) - Composability, multiple reasoning modes, action causality
7. **Google ADK** (7.8/10) - Enterprise-grade, event-driven, HITL built-in
8. **Agent-Zero** (7.5/10) - Memory compression, extension system, production features
9. **OpenAI Agents** (7.3/10) - Lifecycle hooks, guardrails, configuration-first
10. **LlamaIndex** (7.0/10) - Error-as-data, workflow execution, Pydantic everywhere
11. **AWS Strands** (6.8/10) - Streaming, graph multi-agent, hybrid typing
12. **crewAI** (6.5/10) - Event observability, multi-tier memory, decorator tools
13. **Agno** (6.2/10) - Structured reasoning, dual APIs, config explosion
14. **autogen** (6.0/10) - Message-driven, cross-language, minimal cognitive features
15. **Swarm** (5.5/10) - Educational simplicity, handoff pattern, not production-ready

### Type Safety & DX

1. Pydantic-AI (generics, TypeAdapter, excellent errors)
2. MS Agent Framework (Protocol-first, structural typing)
3. AutoGen (Pydantic + Protocols, decorator routing)
4. LangGraph (Annotated reducers, typed state)
5. Google ADK (ClassVar config pattern)

### Production Readiness

1. LangGraph (checkpointing, observability, error preservation)
2. Google ADK (enterprise-grade, event-driven, service abstraction)
3. AutoGen (intervention handlers, distributed tracing)
4. Agent-Zero (retry logic, sandboxing, rate limiting)
5. Pydantic-AI (three-layer retry, usage limits, streaming auto-complete)

### Multi-Agent Sophistication

1. CAMEL (society patterns, workforce orchestration)
2. MetaGPT (environment bus, action-message causality)
3. LangGraph (graph-based, Send pattern for parallelism)
4. AutoGen (pub/sub, cross-language, MagenticOne)
5. MS Agent Framework (graph workflows, checkpointing)

### Developer Experience

1. CAMEL (zero-boilerplate tools, introspection schemas)
2. Swarm (380 lines, elegant handoff, easy to learn)
3. Pydantic-AI (decorator tools, auto-context injection)
4. LangGraph (graph DSL, three stream modes)
5. Google ADK (decorator tools, HITL first-class)

