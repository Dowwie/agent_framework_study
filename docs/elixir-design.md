# Elixir Agent Framework Design

A production-grade agent framework for Elixir, informed by architectural forensics of 15 Python agent frameworks.

## Background

### Problem Statement

Building agentic AI systems requires orchestrating LLM calls, tool execution, state management, and human interaction. Python dominates this space with frameworks like LangGraph, CrewAI, and AutoGen. However, these frameworks exhibit common architectural flaws: unbounded memory growth (80%), mutable state without thread safety, and synchronous operations wrapped in async facades.

Elixir's OTP platform offers primitives that solve these problems natively: supervised processes for fault isolation, ETS for concurrent state, and the actor model for coordination. Rather than port Python patterns, this framework applies Elixir idioms to achieve equivalent capabilities.

### Design Context

This design emerged from analyzing 15 Python agent frameworks:
- **LangGraph** - Graph-based state machines with checkpointing
- **CrewAI** - Role-based multi-agent orchestration
- **AutoGen** - Conversational agent patterns
- **Swarm** - Lightweight handoff-based coordination
- **PydanticAI** - Type-safe tool interfaces
- And 10 others (see `reports/synthesis/comparison-matrix.md`)

Key patterns extracted:
- **Deep Agents**: Explicit planning, hierarchical delegation, persistent memory
- **State Reducers**: Controlled state updates (mapped to Ecto changesets)
- **Tool Introspection**: Schema generation from type definitions
- **Checkpointing**: Durable state for recovery and time-travel

### Architectural Decisions

Two major simplifications were made after initial design:

1. **Broadway → GenServer + Task**: Broadway is optimized for broker ingestion (Kafka, RabbitMQ). Agent workflows generate work internally, have stateful steps, and include cycles. Plain OTP primitives are simpler and sufficient.

2. **Explicit Graph → Pattern Matching**: LangGraph uses declarative graph definitions because Python lacks pattern matching. In Elixir, GenServer callback clauses **are** the state machine transitions. The graph is implicit but equally expressive.

### Target Use Cases

- Research agents with planning and tool use
- Multi-step workflows with human approval gates
- Long-running sessions with checkpoint recovery
- Distributed agent clusters with session affinity

## Design Principles

1. **Deep Agents Pattern** - Explicit planning, hierarchical delegation, persistent memory, extreme context engineering
2. **Plain OTP** - GenServer + Task over abstraction layers; pattern matching over explicit graph DSL
3. **ETS as Hot Cache** - PostgreSQL as durability layer with write-behind
4. **Behaviour-Driven** - Protocols and behaviours for extensibility
5. **Observability Built-In** - Telemetry + OpenTelemetry from day one

## Design Decisions Summary

| # | Dimension | Decision |
|---|-----------|----------|
| 1 | Core Architecture | Deep Agents via GenServer + Task |
| 2 | Process Structure | SessionController GenServer + Task.async for steps |
| 3 | State Model | PostgreSQL + Redis with Ecto embedded schemas |
| 4 | Message Protocol | Lightweight reference structs (session_id, plan_id, step_index) |
| 5 | ETS Layout | 5 tables: :sessions, :messages, :context, :cache, :sub_agent_contexts |
| 6 | Clustering | Node affinity + ex_hash_ring + write-behind persistence |
| 7 | Tool System | Ecto schemas, introspection, ToolError for structured errors, sandbox_mode callback |
| 8 | LLM Integration | Req + Behaviour adapters, PubSub streaming, Hammer rate limiting, :fuse circuit breaker |
| 9 | Memory/Context | Token budget + eviction, pgvector + pg_bm25, tiktoken NIF |
| 10 | Multi-Agent | SessionController orchestrates sub-agents; hub-and-spoke coordination |
| 11 | Observability | Telemetry + OpenTelemetry, step-level granularity |
| 12 | Error Handling | Feed errors to LLM (via ToolError), checkpoint recovery, configurable max iterations |
| 13 | Interrupts/Breakpoints | Hybrid (step-level + runtime registry), timeout with default action |
| 14 | Human-in-the-Loop | Step type + tool, PubSub → Phoenix Channel → WebSocket |
| 15 | Time Travel Debugging | Hybrid snapshots + events, L1 view-only inspection |
| 16 | Sub-Agent Architecture | Task-based with ETS context; ephemeral processes, persistent context |
| 17 | Artifact/Workspace Memory | S3-compatible storage with behaviour abstraction; reference + tool pattern |
| 18 | System Prompts | EEx templates in priv/prompts/; directory override; ship with defaults |
| 19 | Context Handoff | Hybrid extraction: code extracts facts, LLM extracts interpretation |
| 20 | Hierarchical Memory | 50/30/20 split: recent verbatim, historical summary, semantic retrieval |
| 21 | Sandbox Interface | Behaviour + WebSocket protocol for external code execution sandbox |

## Key Libraries

- **Ecto** - Data modeling, validation, changesets
- **Req** - HTTP client with streaming
- **ex_hash_ring** - Consistent hashing (Discord's library)
- **Hammer** - Rate limiting
- **:fuse** - Circuit breaker
- **Poolboy** - Connection pooling for LLM clients
- **Phoenix.PubSub** - Streaming to UI
- **Telemetry + OpenTelemetry** - Observability
- **pgvector + pg_bm25** - Vector and text search in PostgreSQL
- **ex_aws_s3** - S3-compatible artifact storage

## Architecture

### Supervision Tree

```
                            ┌─────────────────────────────┐
                            │    AgentFramework.App       │
                            │    (Application)            │
                            └─────────────┬───────────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    │                     │                     │
                    ▼                     ▼                     ▼
        ┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐
        │  ETS Supervisor   │  │  Session.Supervisor│  │  Infrastructure   │
        │  (one_for_one)    │  │  (DynamicSupervisor)│  │  Supervisor       │
        └─────────┬─────────┘  └─────────┬─────────┘  └─────────┬─────────┘
                  │                      │                      │
      ┌───────────┼───────────┐          │          ┌───────────┼───────────┐
      ▼           ▼           ▼          │          ▼           ▼           ▼
   :sessions  :messages  :context        │    PersistenceWorker  HashRing  LLM.Pool
   :cache     (ETS)      (ETS)           │    (GenServer)       Manager   (Poolboy)
   (ETS)                                 │
                                         │
                           ┌─────────────┼─────────────┐
                           ▼             ▼             ▼
                     SessionCtrl   SessionCtrl   SessionCtrl
                     (GenServer)   (GenServer)   (GenServer)
                           │
                           │ spawns Task.async
                           ▼
                     ┌─────────────┐
                     │    Task     │──► LLM call / Tool execution
                     └─────────────┘
                           │
                           │ result message
                           ▼
                     Controller updates state, {:continue, :next_step}
```

### Cluster Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      libcluster                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐      │
│  │   Node A    │    │   Node B    │    │   Node C    │      │
│  │ ETS (local) │    │ ETS (local) │    │ ETS (local) │      │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘      │
│         └──────────────────┼──────────────────┘              │
│                            ▼                                 │
│                   ┌─────────────────┐                        │
│                   │   PostgreSQL    │◄── Write-behind        │
│                   └─────────────────┘                        │
│              ┌─────────────────────┐                         │
│              │   ex_hash_ring      │◄── Session routing      │
│              └─────────────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

### Session Control Flow

```
┌───────────────────────────────────────────────────────────────────────┐
│                         SessionController                              │
│                           (GenServer)                                  │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ init/1 ──► {:continue, :plan}                                   │  │
│  │                     │                                            │  │
│  │                     ▼                                            │  │
│  │ handle_continue(:plan) ──► Task.async(create_plan)              │  │
│  │                     │                                            │  │
│  │                     ▼                                            │  │
│  │ handle_info({ref, plan}) ──► store plan, {:continue, :next_step}│  │
│  │                     │                                            │  │
│  │         ┌───────────┴───────────┐                                │  │
│  │         ▼                       ▼                                │  │
│  │   {:ok, step}            {:human_input, step}                    │  │
│  │         │                       │                                │  │
│  │         ▼                       ▼                                │  │
│  │   Task.async(execute)    broadcast HITL request                  │  │
│  │         │                 await provide_input                    │  │
│  │         ▼                       │                                │  │
│  │   handle_info(result)           │                                │  │
│  │         │                       │                                │  │
│  │         └───────────┬───────────┘                                │  │
│  │                     ▼                                            │  │
│  │           {:continue, :next_step}                                │  │
│  │                     │                                            │  │
│  │         ┌───────────┴───────────┐                                │  │
│  │         ▼                       ▼                                │  │
│  │       :done              more steps...                           │  │
│  │         │                                                        │  │
│  │         ▼                                                        │  │
│  │   {:stop, :normal}                                               │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

## Module Structure

```
lib/
├── agent_framework/
│   ├── application.ex              # OTP Application
│   │
│   ├── state/                      # State Model
│   │   ├── ets_supervisor.ex       # Supervises ETS table owners
│   │   ├── tables.ex               # ETS table creation/access
│   │   ├── persistence_worker.ex   # Write-behind to Postgres
│   │   └── hash_ring.ex            # ex_hash_ring integration
│   │
│   ├── schemas/                    # Ecto Embedded Schemas
│   │   ├── session.ex
│   │   ├── plan.ex
│   │   ├── step.ex
│   │   ├── message.ex
│   │   ├── context.ex
│   │   ├── checkpoint.ex
│   │   ├── sub_agent_context.ex    # Sub-agent conversation history
│   │   ├── sub_agent_result.ex     # Structured sub-agent output
│   │   ├── artifact.ex             # Workspace artifact metadata
│   │   └── tool_error.ex           # Structured tool errors (Dim 7 refinement)
│   │
│   ├── session/                    # Session Management
│   │   ├── supervisor.ex           # DynamicSupervisor
│   │   ├── controller.ex           # Core GenServer (state machine)
│   │   ├── step_executor.ex        # Task logic for step execution
│   │   ├── router.ex               # Routes to owning node
│   │   └── registry.ex             # Process registry
│   │
│   ├── sub_agent/                  # Sub-Agent System (Dim 16)
│   │   ├── runner.ex               # Task-based sub-agent execution
│   │   ├── context.ex              # ETS context load/save
│   │   └── synthesizer.ex          # Result extraction (code + LLM)
│   │
│   ├── storage/                    # Artifact Storage (Dim 17)
│   │   ├── behaviour.ex            # Storage behaviour
│   │   ├── s3.ex                   # S3-compatible (ex_aws_s3)
│   │   └── local.ex                # Local filesystem (dev/test)
│   │
│   ├── prompts/                    # System Prompts (Dim 18)
│   │   └── loader.ex               # EEx template loading + caching
│   │
│   ├── tools/                      # Tool System (Dim 7)
│   │   ├── behaviour.ex            # Includes sandbox_mode/0 callback
│   │   ├── registry.ex
│   │   ├── schema.ex
│   │   ├── executor.ex
│   │   └── builtin/
│   │       ├── web_search.ex
│   │       ├── write_artifact.ex   # Write to workspace (Dim 17)
│   │       ├── read_artifact.ex    # Read from workspace (Dim 17)
│   │       ├── list_artifacts.ex   # List session artifacts (Dim 17)
│   │       └── code_execute.ex     # Sandboxed code execution (Dim 21)
│   │
│   ├── llm/                        # LLM Integration
│   │   ├── behaviour.ex
│   │   ├── client.ex
│   │   ├── pool.ex                 # Poolboy connection pooling
│   │   ├── streaming.ex
│   │   ├── providers/
│   │   ├── rate_limiter.ex
│   │   └── circuit_breaker.ex
│   │
│   ├── memory/                     # Memory/Context (Dim 9, 20)
│   │   ├── token_counter.ex
│   │   ├── context_builder.ex      # Implements 50/30/20 strategy
│   │   ├── summary_generator.ex    # Background LLM summarization
│   │   ├── eviction.ex
│   │   └── search.ex
│   │
│   ├── sandbox/                    # Code Execution Sandbox (Dim 21)
│   │   ├── behaviour.ex            # Sandbox behaviour definition
│   │   └── websocket_client.ex     # WebSocket client to external sandbox
│   │
│   ├── telemetry/                  # Observability
│   │   ├── events.ex
│   │   ├── handlers.ex
│   │   └── otel.ex
│   │
│   ├── recovery/                   # Error Recovery
│   │   ├── checkpoint.ex
│   │   └── supervisor_callbacks.ex
│   │
│   ├── interrupts/                 # Interrupts/Breakpoints
│   │   ├── breakpoints.ex          # Runtime breakpoint registry
│   │   └── interrupt_handler.ex    # Timeout + resume logic
│   │
│   ├── hitl/                       # Human-in-the-Loop
│   │   ├── ask_human_tool.ex       # Tool for emergent HITL
│   │   └── input_handler.ex        # Input delivery/timeout
│   │
│   └── time_travel/                # Time Travel Debugging
│       ├── event.ex                # Event schema
│       ├── snapshotter.ex          # Periodic full snapshots
│       └── query.ex                # state_at, timeline APIs
│
├── agent_framework.ex              # Public API
├── mix.exs
│
priv/
└── prompts/                        # System Prompt Templates (Dim 18)
    ├── _shared/
    │   ├── artifact_conventions.md.eex
    │   ├── tool_guidelines.md.eex
    │   └── hitl_protocols.md.eex
    ├── orchestrator.md.eex
    ├── researcher.md.eex
    ├── coder.md.eex
    ├── writer.md.eex
    └── reviewer.md.eex
```

## Key Types

```elixir
# Session State (GenServer state for SessionController)
@type session :: %AgentFramework.Schemas.Session{
  id: String.t(),
  user_id: String.t(),
  state: :planning | :executing | :interrupted | :awaiting_human | :completed | :failed,
  plan: plan() | nil,
  config: map(),
  max_iterations: pos_integer(),
  current_iteration: non_neg_integer(),
  pending_task: reference() | nil,    # Task.async ref when step is executing
  subscribers: [pid()]                 # Processes to notify on events
}

# Plan with Steps
@type plan :: %AgentFramework.Schemas.Plan{
  id: String.t(),
  goal: String.t(),
  steps: [step()],
  current_step_index: non_neg_integer()
}

# Individual Step
@type step :: %AgentFramework.Schemas.Step{
  id: String.t(),
  type: :research | :code | :write | :review | :human_input | :custom,
  description: String.t(),
  status: :pending | :in_progress | :completed | :failed | :skipped,
  executor: module() | nil,           # Optional custom executor module
  dependencies: [String.t()],         # Step IDs that must complete first
  result: map() | nil,
  error: String.t() | nil,
  # Interrupt configuration
  interrupt: :none | :before | :after,
  interrupt_timeout_ms: pos_integer(),
  interrupt_default_action: :continue | :fail
}

# Step Reference (lightweight pointer for cross-process communication)
@type step_ref :: %{
  session_id: String.t(),
  plan_id: String.t(),
  step_index: non_neg_integer(),
  metadata: map()
}
```

## Tool Definition Example

```elixir
defmodule MyTools.WebSearch do
  @moduledoc """
  Wraps Serper API for web search. Rate limited to 100 req/min.
  """

  use AgentFramework.Tool

  @tool_description """
  Search the web for current information. Use when:
  - User asks about recent events
  - User needs up-to-date facts
  """

  @field_descriptions %{
    query: "The search query to execute",
    max_results: "Maximum number of results to return (1-100)"
  }

  @primary_key false
  embedded_schema do
    field :query, :string
    field :max_results, :integer, default: 10
  end

  def changeset(tool, attrs) do
    tool
    |> cast(attrs, [:query, :max_results])
    |> validate_required([:query])
    |> validate_number(:max_results, greater_than: 0, less_than_or_equal_to: 100)
  end

  @impl AgentFramework.Tool
  def execute(%__MODULE__{query: query, max_results: max}) do
    # Implementation
    {:ok, results}
  end
end
```

## Telemetry Events

```elixir
# Session lifecycle
[:agent_framework, :session, :start]
[:agent_framework, :session, :complete]
[:agent_framework, :session, :error]

# Step lifecycle
[:agent_framework, :step, :start]
[:agent_framework, :step, :complete]
[:agent_framework, :step, :error]

# LLM calls
[:agent_framework, :llm, :request]
[:agent_framework, :llm, :response]
[:agent_framework, :llm, :error]

# Tool execution
[:agent_framework, :tool, :execute]
[:agent_framework, :tool, :complete]
[:agent_framework, :tool, :error]
```

## Interrupts/Breakpoints

**Step-level configuration:**
```elixir
# In Step schema
field :interrupt, Ecto.Enum, values: [:none, :before, :after], default: :none
field :interrupt_timeout_ms, :integer, default: 300_000  # 5 min
field :interrupt_default_action, Ecto.Enum, values: [:continue, :fail], default: :fail
```

**Runtime API:**
```elixir
# Set breakpoints dynamically (for debugging)
AgentFramework.Breakpoints.set(session_id, :before, :code_execute)
AgentFramework.Breakpoints.set(session_id, :after, step_id)
AgentFramework.Breakpoints.clear(session_id)

# Resume after interrupt
AgentFramework.Session.resume(session_id)
AgentFramework.Session.resume(session_id, modified_step: %{...})
```

## Human-in-the-Loop (HITL)

**Architecture:**
```
Frontend (WebSocket) ←→ Phoenix Channel ←→ PubSub ←→ SessionController
```

**Planned HITL (step type):**
```elixir
%Step{
  type: :human_input,
  description: "Review research and provide feedback",
  input_schema: %{feedback: :string, approved: :boolean},
  timeout_ms: 600_000
}
```

**Emergent HITL (tool):**
```elixir
defmodule AgentFramework.Tools.AskHuman do
  use AgentFramework.Tool

  @tool_description "Ask the human user for input or clarification"

  embedded_schema do
    field :question, :string
    field :options, {:array, :string}, default: []
  end
end
```

**Response delivery:**
```elixir
AgentFramework.Session.provide_input(session_id, step_id, %{
  feedback: "Looks good",
  approved: true
})
```

## Time Travel Debugging

**Event schema:**
```elixir
defmodule AgentFramework.Schemas.Event do
  embedded_schema do
    field :session_id, :binary_id
    field :step_index, :integer
    field :sequence, :integer
    field :timestamp, :utc_datetime_usec
    field :type, Ecto.Enum, values: [
      :step_started, :step_completed, :step_failed,
      :llm_request, :llm_response,
      :tool_called, :tool_result,
      :interrupt_triggered, :interrupt_resumed,
      :hitl_requested, :hitl_received
    ]
    field :data, :map
  end
end
```

**Query API:**
```elixir
# Reconstruct state at any point
TimeTravel.state_at(session_id, step_index)

# Get events for a specific step
TimeTravel.events_for_step(session_id, step_index)

# Full ordered timeline
TimeTravel.full_timeline(session_id)
```

**Snapshot strategy:** Full snapshot every 5 steps + events between. Reconstruct by loading nearest snapshot and applying subsequent events.

## Sub-Agent Architecture

Sub-agents provide hierarchical delegation with context isolation. Each sub-agent runs as a Task with its context persisted in ETS.

**Architecture:**
```
SessionController (orchestrator)
    │
    ├── spawns Task (sub_agent_id: "researcher_1")
    │       └── loads context from ETS[:sub_agent_contexts]
    │       └── runs multi-turn LLM loop internally
    │       └── saves context to ETS[:sub_agent_contexts]
    │       └── returns SubAgentResult
    │
    └── can spawn another Task for same sub_agent_id later
            └── context restored from ETS (resumable)
```

**Context schema:**
```elixir
defmodule AgentFramework.Schemas.SubAgentContext do
  embedded_schema do
    field :session_id, :binary_id
    field :sub_agent_id, :string  # e.g., "researcher_1"
    field :agent_type, Ecto.Enum, values: [:researcher, :coder, :writer, :reviewer, :custom]
    field :messages, {:array, :map}  # conversation history
    field :tool_results, {:array, :map}
    field :artifacts_created, {:array, :string}  # paths
    field :created_at, :utc_datetime_usec
    field :updated_at, :utc_datetime_usec
  end
end
```

**Coordination model:** Hub-and-spoke via orchestrator. Sub-agents cannot communicate directly; they return to the orchestrator, which decides next actions.

## Artifact/Workspace Storage

Artifacts (research notes, code, drafts) are stored in S3-compatible storage and referenced by path, not included in context.

**Storage behaviour:**
```elixir
defmodule AgentFramework.Storage do
  @callback write(session_id, path, content) :: {:ok, artifact_url} | {:error, term()}
  @callback read(artifact_url) :: {:ok, content} | {:error, term()}
  @callback list(session_id, prefix) :: {:ok, [artifact_url]} | {:error, term()}
  @callback delete(artifact_url) :: :ok | {:error, term()}
end
```

**Path conventions:**
```
s3://{bucket}/{session_id}/{artifact_type}/{filename}

Types: research/, code/, drafts/, data/, logs/
```

**Artifact metadata:**
```elixir
defmodule AgentFramework.Schemas.Artifact do
  embedded_schema do
    field :session_id, :binary_id
    field :sub_agent_id, :string
    field :type, Ecto.Enum, values: [:research, :code, :draft, :data, :log]
    field :path, :string  # s3://bucket/path
    field :filename, :string
    field :content_type, :string
    field :size_bytes, :integer
    field :created_by_step, :integer
    field :created_at, :utc_datetime_usec
  end
end
```

**Built-in tools:** `WriteArtifact`, `ReadArtifact`, `ListArtifacts`

## System Prompts

Prompts are EEx templates in `priv/prompts/`. Framework ships with battle-tested defaults; users can override via directory config.

**Loading:**
```elixir
defmodule AgentFramework.Prompts do
  def get(agent_type, assigns \\ %{}) do
    path = resolve_path(agent_type)
    EEx.eval_file(path, assigns: Map.to_list(assigns))
  end
end
```

**Override:**
```elixir
# config/config.exs
config :agent_framework, :prompts_dir, "priv/my_prompts"
# Missing files fall back to framework defaults
```

**Template variables available:**
- `@agent_type` - Type of agent (researcher, coder, etc.)
- `@goal` - Session goal
- `@tool_names` - List of available tools
- `@workspace_path` - S3 path for artifacts
- `@step` - Current step details

## Context Handoff Protocol

When sub-agents return to the orchestrator, results are extracted via hybrid approach:

**Code extracts (deterministic):**
- `artifacts_created` - Paths created during execution
- `tools_used` - Tool names called
- `token_usage` - Input/output tokens
- `duration_ms` - Execution time

**LLM extracts (interpretation):**
- `summary` - 1-2 sentence summary
- `status` - completed | partial | blocked | failed
- `recommendations` - Suggested next steps
- `blockers` - What's preventing progress
- `confidence` - 0-1 confidence score
- Type-specific fields (sources for researcher, tests_status for coder, etc.)

**Result schema:**
```elixir
defmodule AgentFramework.Schemas.SubAgentResult do
  embedded_schema do
    field :sub_agent_id, :string
    field :agent_type, Ecto.Enum, values: [:researcher, :coder, :writer, :reviewer, :custom]
    field :status, Ecto.Enum, values: [:completed, :partial, :blocked, :failed]

    # Code-extracted
    field :artifacts_created, {:array, :string}
    field :tools_used, {:array, :string}
    field :token_usage, :map
    field :duration_ms, :integer

    # LLM-extracted
    field :summary, :string
    field :recommendations, {:array, :string}
    field :blockers, {:array, :string}
    field :confidence, :float
    embeds_one :type_specific, :map
  end
end
```

## Hierarchical Memory Strategy

The 50/30/20 strategy addresses unbounded memory growth (anti-pattern #1) by allocating token budget across three tiers:

```
Token Budget Allocation:
├── 50% Recent Messages (verbatim, most recent first)
├── 30% Historical Summary (LLM-compressed rolling summary)
└── 20% Semantic Retrieval (pgvector similarity search)
```

### Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `@summary_token_threshold` | 4000 | Unsummarized tokens before regeneration |
| `@summary_target_tokens` | 2000 | Target size for generated summary |
| `@semantic_top_k` | 20 | Max results from pgvector query |

### Summary Generation

- **Trigger**: Token threshold (when unsummarized tokens > 4000)
- **Mode**: Full replacement (not incremental)
- **Execution**: Background Task, non-blocking
- **Cache**: ETS with no TTL (token-triggered invalidation only)
- **Persistence**: Write-behind to Postgres

### Semantic Retrieval

- **Embedding unit**: Per-message (each message is one vector)
- **Query source**: Current user message content
- **Budget fitting**: Top-K with token accumulation (accumulate until budget filled)
- **Index**: pgvector with IVFFlat on `embedding vector_cosine_ops`

### Context Output

Returns structured `%Context{}` preserving tier provenance:

```elixir
defmodule AgentFramework.Schemas.Context do
  @type t :: %__MODULE__{
    session_id: String.t(),
    summary: String.t() | nil,
    recent_messages: [Message.t()],
    semantic_messages: [Message.t()],  # Attributed with "[From earlier in conversation]"
    total_tokens: non_neg_integer(),
    metadata: map()
  }
end
```

### Integration Point

Called once per LLM call in `StepExecutor`, before each invocation. Tool loop iterations rebuild context with new tool results included.

## Sandbox Interface

Code execution tools require security isolation beyond what BEAM Tasks provide. The framework defines an interface to external sandboxes without implementing the sandbox runtime itself.

**Design scope:**
- Define behaviour + Fathom Sandbox Protocol (FSP)
- Build client to connect to external sandbox
- Do NOT implement sandbox server (separate concern)

### Connection Management

- **Pool**: Poolboy with configurable size (default 5, max overflow 10)
- **Reconnection**: Immediate retry first, then exponential backoff (100ms → 30s max)
- **Health check**: Workers validate connection before checkout

### Fathom Sandbox Protocol v1.0

See [`docs/fathom-sandbox-protocol.md`](fathom-sandbox-protocol.md) for full specification.

| Property | Value |
|----------|-------|
| Encoding | JSON over WebSocket |
| Versioning | `v` field in every message |
| Output mode | Streaming only |
| Session model | Stateless |

**Message types:**
- Client → Sandbox: `execute`, `cancel`, `ping`
- Sandbox → Client: `ack`, `status`, `stdout`, `stderr`, `result`, `error`, `pong`

**Key error codes:** `TIMEOUT`, `OOM`, `OUTPUT_LIMIT`, `SANDBOX_OVERLOADED`, `INTERNAL_ERROR`

### Configuration

```elixir
config :agent_framework, AgentFramework.Sandbox,
  url: "wss://sandbox.example.com/ws",
  auth: [api_key: "...", refresh_url: "..."],
  pool: [size: 5, max_overflow: 10],
  timeouts: [connect_timeout_ms: 5_000, execution_default_ms: 30_000]
```

### Tool Integration

Tools declare `sandbox_mode/0` callback. Default is `:none` (in-process). Code execution tools specify `:external` to route through sandbox pool. Routing checked at execution time.

## ToolError Schema

Structured errors from tool execution, providing enough context for LLM self-correction.

### Schema

```elixir
defmodule AgentFramework.Schemas.ToolError do
  @type t :: %__MODULE__{
    tool_name: String.t(),
    error_type: :validation | :execution | :timeout | :sandbox | :permission,
    message: String.t(),
    retryable: boolean(),
    context: map()
  }

  # Constructor helpers
  def validation_error(tool_name, message, context \\ %{})
  def execution_error(tool_name, message, opts \\ [])
  def timeout_error(tool_name, timeout_ms)
  def from_api_error(tool_name, %{status: status, body: body})
  def from_exception(tool_name, exception)

  # LLM formatting
  def format_for_llm(%__MODULE__{} = error)
end
```

### Executor Integration

All tool errors wrapped in ToolError. The executor normalizes raw `{:error, reason}` returns automatically for backward compatibility.

```elixir
# Tools SHOULD return ToolError
{:error, ToolError.execution_error("web_search", "Rate limited", retryable: true)}

# But legacy returns are auto-wrapped
{:error, "Something went wrong"}  # → ToolError.execution_error(...)
```

### LLM Feedback Format

```
Tool `web_search` failed.
Error type: timeout
Message: Execution timed out after 30000ms
This error is not retryable.
```

Formatting defined in `ToolError.format_for_llm/1`, invoked by `StepExecutor` when building tool result messages. Context shown selectively (validation, execution only) to avoid leaking internals.

## Public API

The `AgentFramework` module exposes the primary interface:

```elixir
defmodule AgentFramework do
  @moduledoc """
  Public API for the Agent Framework.
  """

  # Session Lifecycle
  @spec start_session(String.t(), keyword()) :: {:ok, session_id} | {:error, term()}
  def start_session(goal, opts \\ [])

  @spec stop_session(String.t()) :: :ok | {:error, :not_found}
  def stop_session(session_id)

  @spec get_session(String.t()) :: {:ok, Session.t()} | {:error, :not_found}
  def get_session(session_id)

  @spec subscribe(String.t()) :: :ok
  def subscribe(session_id)

  # Interrupt Control
  @spec resume(String.t(), keyword()) :: :ok | {:error, term()}
  def resume(session_id, opts \\ [])

  @spec pause(String.t()) :: :ok | {:error, term()}
  def pause(session_id)

  # Human-in-the-Loop
  @spec provide_input(String.t(), String.t(), map()) :: :ok | {:error, term()}
  def provide_input(session_id, step_id, input)

  # Breakpoints (debugging)
  @spec set_breakpoint(String.t(), :before | :after, atom() | String.t()) :: :ok
  def set_breakpoint(session_id, position, step_type_or_id)

  @spec clear_breakpoints(String.t()) :: :ok
  def clear_breakpoints(session_id)

  # Time Travel
  @spec state_at(String.t(), non_neg_integer()) :: {:ok, Session.t()} | {:error, term()}
  def state_at(session_id, step_index)

  @spec timeline(String.t()) :: {:ok, [Event.t()]} | {:error, term()}
  def timeline(session_id)
end
```

**Usage Example:**

```elixir
# Start a research session
{:ok, session_id} = AgentFramework.start_session(
  "Research quantum computing advances in 2024",
  tools: [MyTools.WebSearch, MyTools.FileWrite],
  max_iterations: 15
)

# Subscribe to events
AgentFramework.subscribe(session_id)

# Receive events in calling process
receive do
  {:agent_framework, :step_complete, %{step: step, result: result}} ->
    IO.puts("Step #{step.id} completed")

  {:agent_framework, :hitl_request, %{step: step, question: q}} ->
    AgentFramework.provide_input(session_id, step.id, %{answer: "approved"})

  {:agent_framework, :session_complete, %{result: result}} ->
    IO.puts("Done: #{inspect(result)}")
end
```

## Implementation Order

1. **Foundation** - ETS tables (5 tables), Ecto schemas, persistence worker
2. **Session Management** - Controller GenServer, step executor, supervisor, registry
3. **Tools** - Behaviour, registry, executor, schema generation
4. **Storage Layer** - Storage behaviour, S3 adapter, local adapter, artifact tools
5. **System Prompts** - EEx loader, default templates, override mechanism
6. **Sub-Agent System** - Runner, context management, result synthesizer
7. **LLM Integration** - Provider behaviour, pool, OpenAI adapter, streaming
8. **Memory & Context** - Token counter, context builder, eviction
9. **Interrupts & HITL** - Breakpoints, interrupt handler, AskHuman tool, Phoenix Channel
10. **Time Travel** - Event logging, snapshotter, query API
11. **Clustering** - Hash ring, cross-node routing, failover
12. **Observability & Hardening** - Telemetry, checkpoints, integration tests

## Architectural Note: Why GenServer + Task (Not Broadway)

After initial design with Broadway, expert analysis revealed a mismatch:

| Broadway Assumption | Our Reality |
|---------------------|-------------|
| Messages from external broker | Work generated internally |
| High-throughput streams | Low-throughput, stateful |
| Homogeneous batches | Heterogeneous steps |
| DAG pipeline | Graph with cycles |

**The simpler solution**: GenServer for state machine logic, Task.async for step execution. This is idiomatic OTP and avoids unnecessary abstraction.

**What we kept from Broadway thinking**: Telemetry events, graceful shutdown, pooling (via Poolboy for LLM connections).

## Architectural Note: Why Pattern Matching (Not Explicit Graph)

We considered adding a Graph DSL like LangGraph's `StateGraph`. Expert analysis concluded:

| Concern | Explicit Graph | Pattern Matching |
|---------|----------------|------------------|
| Cycle handling | Requires bounds declaration | `max_iterations` already handles |
| Conditional routing | `add_conditional_edges()` | `next_action/1` function clauses |
| Visualization | Native | Can generate from plan state |
| Runtime behavior | No difference | Equivalent expressiveness |

**The Elixir idiom**: Pattern matching in GenServer callbacks **is** a state machine graph. LangGraph needed explicit graphs because Python lacks pattern matching.

**Future option**: If visualization becomes critical, add `SessionInspector` to generate Mermaid/DOT diagrams from plan state. If many agents share common patterns, consider a workflow DSL layer.

## Anti-Patterns to Avoid

From analysis of 15 Python frameworks:

1. Unbounded memory growth (80% of frameworks)
2. Silent exception swallowing
3. No max iterations (infinite loop risk)
4. Mutable state without thread safety
5. No tool sandboxing
6. Configuration god objects (250+ fields)
7. Deep inheritance hierarchies
8. String-based identifiers for routing
9. Global mutable state
10. Sync wrapped in async

## Research Items

See `docs/TODO-ANALYSIS.md` for detailed research tasks:
- Tiktoken Elixir bindings (NIF implementation)
- Compaction alternatives to LLM summarization
- LiteLLM analysis for provider unification patterns
- Agno event taxonomy analysis (observability patterns)
- OpenTelemetry GenAI semantic conventions

## References

### Adopted Patterns
- [Deep Agents Pattern](https://www.philschmid.de/deep-research-agent) - Core architecture inspiration
- [ex_hash_ring](https://github.com/discord/ex_hash_ring) - Consistent hashing for session affinity
- [LangGraph](https://langchain-ai.github.io/langgraph/) - Reference for checkpointing, interrupts, HITL

### Considered but Not Adopted
- [Broadway](https://hexdocs.pm/broadway) - Evaluated for pipeline processing; rejected as overfit for broker ingestion (see Architectural Notes)

### Project Artifacts
- Framework analysis: `reports/synthesis/comparison-matrix.md`
- Anti-patterns catalog: `reports/synthesis/antipatterns.md`
- Protocol specification: `docs/fathom-sandbox-protocol.md`
- Session logs:
  - `docs/elixir-sessions/2025-12-24-0639.md` (Dimensions 1-13)
  - `docs/elixir-sessions/2025-12-25-0409.md` (Dimensions 14-17, gap resolution)
  - `docs/elixir-sessions/2025-12-27-0639.md` (Dimensions 20-21, critique evaluation)
  - `docs/elixir-sessions/2025-12-27-1100.md` (Dimension 20-21 gap resolution, FSP v1.0)
- Gap analysis: `fathom_gap.md`
- Research backlog: `docs/TODO-ANALYSIS.md`
