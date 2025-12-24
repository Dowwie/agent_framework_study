# Elixir Agent Framework Design

A production-grade agent framework for Elixir, informed by architectural forensics of 15 Python agent frameworks.

## Design Principles

1. **Deep Agents Pattern** - Explicit planning, hierarchical delegation, persistent memory, extreme context engineering
2. **Broadway-First** - Leverage production-grade pipeline processing
3. **ETS as Hot Cache** - PostgreSQL as durability layer with write-behind
4. **Behaviour-Driven** - Protocols and behaviours for extensibility
5. **Observability Built-In** - Telemetry + OpenTelemetry from day one

## Design Decisions Summary

| Dimension | Decision |
|-----------|----------|
| Core Architecture | Deep Agents via Broadway pipeline |
| Process Structure | Broadway + GenStage producer with :queue |
| State Model | PostgreSQL + Redis with Ecto embedded schemas |
| Message Protocol | Lightweight reference structs (session_id, plan_id, step_index) |
| ETS Layout | 4 tables: :sessions, :messages, :context, :cache |
| Clustering | Node affinity + ex_hash_ring + write-behind persistence |
| Tool System | Ecto schemas, introspection-based JSON schema, Task isolation |
| LLM Integration | Req + Behaviour adapters, PubSub streaming, Hammer rate limiting, :fuse circuit breaker |
| Memory/Context | Token budget + eviction, pgvector + pg_bm25, tiktoken NIF |
| Multi-Agent | SessionController GenServer + Broadway execution |
| Observability | Telemetry + OpenTelemetry, step-level granularity |
| Error Handling | Feed errors to LLM, checkpoint recovery, configurable max iterations |
| Interrupts/Breakpoints | Hybrid (step-level + runtime registry), timeout with default action |
| Human-in-the-Loop | Step type + tool, PubSub → Phoenix Channel → WebSocket |
| Time Travel Debugging | Hybrid snapshots + events, L1 view-only inspection |

## Key Libraries

- **Broadway** - Pipeline processing with batching, rate limiting, telemetry
- **Ecto** - Data modeling, validation, changesets
- **Req** - HTTP client with streaming
- **ex_hash_ring** - Consistent hashing (Discord's library)
- **Hammer** - Rate limiting
- **:fuse** - Circuit breaker
- **Phoenix.PubSub** - Streaming to UI
- **Telemetry + OpenTelemetry** - Observability
- **pgvector + pg_bm25** - Vector and text search in PostgreSQL

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
        │  ETS Supervisor   │  │  Infrastructure   │  │  Session          │
        │  (one_for_one)    │  │  Supervisor       │  │  Supervisor       │
        └─────────┬─────────┘  └─────────┬─────────┘  └─────────┬─────────┘
                  │                      │                      │
      ┌───────────┼───────────┐          │          ┌───────────┼───────────┐
      ▼           ▼           ▼          │          ▼           ▼           ▼
   :sessions  :messages  :context        │    SessionCtrl   SessionCtrl  ...
   :cache     (ETS)      (ETS)           │    (GenServer)   (GenServer)
   (ETS)                                 │
                                         │
              ┌──────────────────────────┼──────────────────────────┐
              ▼                          ▼                          ▼
    ┌───────────────────┐    ┌───────────────────┐    ┌───────────────────┐
    │  Broadway         │    │  PersistenceWorker│    │  HashRing         │
    │  Pipeline         │    │  (GenServer)      │    │  Manager          │
    └─────────┬─────────┘    │  Write-behind     │    │  (GenServer)      │
              │              └───────────────────┘    └───────────────────┘
    ┌─────────┴─────────┐
    ▼                   ▼
  Producer           Processors
  (GenStage)         ┌─────────┬─────────┐
                     ▼         ▼         ▼
               Researcher   Coder    Writer
               (pool: 2)  (pool: 2) (pool: 1)
                     │         │         │
                     └────┬────┴────┬────┘
                          ▼         ▼
                       Batcher   Batcher
                       (default) (priority)
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
┌────────────────────────────────────────────────────────────────────┐
│                         Session Layer                               │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐        │
│  │ SessionCtrl 1  │  │ SessionCtrl 2  │  │ SessionCtrl N  │        │
│  │ (GenServer)    │  │ (GenServer)    │  │ (GenServer)    │        │
│  └───────┬────────┘  └───────┬────────┘  └───────┬────────┘        │
│          │                   │                   │                  │
│          └───────────────────┼───────────────────┘                  │
│                              │ enqueue steps                        │
└──────────────────────────────┼──────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       Broadway Pipeline                               │
│                                                                       │
│  [Producer] → [Researcher] → ┐                                        │
│            → [Coder]     → ─┼─→ [Batcher] → step_complete message    │
│            → [Writer]    → ─┘                                        │
└──────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                    back to SessionController
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
│   │   └── checkpoint.ex
│   │
│   ├── session/                    # Session Management
│   │   ├── supervisor.ex           # DynamicSupervisor
│   │   ├── controller.ex           # GenServer per session
│   │   ├── router.ex               # Routes to owning node
│   │   └── registry.ex             # Process registry
│   │
│   ├── pipeline/                   # Broadway Pipeline
│   │   ├── broadway.ex             # Broadway configuration
│   │   ├── producer.ex             # GenStage producer
│   │   ├── processors/
│   │   │   ├── researcher.ex
│   │   │   ├── coder.ex
│   │   │   └── writer.ex
│   │   └── batcher.ex
│   │
│   ├── tools/                      # Tool System
│   │   ├── behaviour.ex
│   │   ├── registry.ex
│   │   ├── schema.ex
│   │   ├── executor.ex
│   │   └── builtin/
│   │
│   ├── llm/                        # LLM Integration
│   │   ├── behaviour.ex
│   │   ├── client.ex
│   │   ├── streaming.ex
│   │   ├── providers/
│   │   ├── rate_limiter.ex
│   │   └── circuit_breaker.ex
│   │
│   ├── memory/                     # Memory/Context
│   │   ├── token_counter.ex
│   │   ├── context_builder.ex
│   │   ├── eviction.ex
│   │   └── search.ex
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
└── mix.exs
```

## Key Types

```elixir
# Session State
@type session :: %AgentFramework.Schemas.Session{
  id: String.t(),
  user_id: String.t(),
  state: :planning | :executing | :completed | :failed,
  plan: plan() | nil,
  config: map(),
  max_iterations: pos_integer(),
  current_iteration: non_neg_integer()
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
  type: :research | :code | :write | :review | :custom,
  description: String.t(),
  status: :pending | :in_progress | :completed | :failed | :skipped,
  processor: atom(),
  dependencies: [String.t()],
  result: map() | nil,
  error: String.t() | nil
}

# Broadway Message (lightweight reference)
@type broadway_message :: %{
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

## Implementation Order

1. **Foundation** - ETS tables, Ecto schemas, persistence worker
2. **Session Management** - Controller, supervisor, registry
3. **Pipeline** - Producer, Broadway config, first processor
4. **Tools** - Behaviour, registry, executor, schema generation
5. **LLM Integration** - Provider behaviour, OpenAI adapter, streaming
6. **Memory & Context** - Token counter, context builder, eviction
7. **Interrupts & HITL** - Breakpoints, interrupt handler, AskHuman tool, Phoenix Channel
8. **Time Travel** - Event logging, snapshotter, query API
9. **Clustering** - Hash ring, cross-node routing, failover
10. **Observability & Hardening** - Telemetry, checkpoints, integration tests

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

- Tiktoken Elixir bindings (NIF implementation)
- Compaction alternatives to LLM summarization
- LiteLLM analysis for provider unification patterns

## References

- [Deep Agents Pattern](https://www.philschmid.de/deep-research-agent)
- [ex_hash_ring](https://github.com/discord/ex_hash_ring)
- [Broadway](https://hexdocs.pm/broadway)
- Session log: `docs/elixir-sessions/2025-12-24-0639.md`
