# Elixir Agent Framework Enhancements

This document outlines architectural enhancements for the Elixir Agent Framework, derived from a critique of `docs/elixir-design.md` informed by forensic analysis of 15+ Python agent frameworks and the unique capabilities of the BEAM/OTP runtime.

## 1. Concurrency: From Serial to Scatter-Gather
**Observation:** The current design uses a singular `pending_task: reference() | nil`, which restricts agents to serial execution.
**Recommendation:** Enable parallel tool execution (Scatter-Gather) to leverage BEAM's true strength.
- **Change:** Update Session State to `pending_tasks: %{reference() => task_metadata()}`.
- **Mechanism:** Use a `MapSet` or `Map` to track multiple concurrent `Task.async` calls.
- **Benefit:** Allows an agent to perform multiple searches, fact-checks, or computations simultaneously, significantly reducing latency compared to serial Python-style loops.

## 2. Tooling: Context-Aware & Macro-Driven DX
**Observation:** Manually writing Ecto schemas and changesets for every tool is high-friction (DX anti-pattern). Lack of context in `execute/1` leads to Process Dictionary hacks.
**Recommendation:** Use Macros for boilerplate and pass explicit context.
- **Change:** Implement `use AgentTool` macro to auto-generate Ecto schemas and changesets from function attributes and types.
- **Signature:** Change tool execution to `execute(tool_struct, context_map)`.
- **Benefit:** Reduces boilerplate, catches schema errors at compile-time, and ensures "pure" functional tools that don't rely on hidden global state (Process Dictionary).

## 3. Resilience: State-Aware "Let It Crash"
**Observation:** Standard supervision restarts a process with the same state, which can lead to "Deterministic Doom Loops" if the LLM output triggers a logic bug.
**Recommendation:** Implement State-Aware recovery.
- **Change:** The Supervisor or a `handle_info` monitor should detect a crash and **inject a System Message** into the session history before restarting: *"The previous execution path caused a system crash. Please attempt a different strategy."*
- **Benefit:** Forces the LLM to deviate from the path that caused the crash, turning a fatal logic error into a self-correction opportunity.

## 4. Autonomy: Reactive Event-Driven Agents
**Observation:** The design targets a Request/Response model (user-driven), missing the opportunity for truly autonomous agents.
**Recommendation:** Enable agents to live as long-running, reactive actors.
- **Change:** Expose a `handle_event/2` callback in the `SessionController`. Allow agents to subscribe to `Phoenix.PubSub` topics or `pg` groups.
- **Benefit:** Agents can react to environment changes (e.g., market data, file system events, CI/CD signals) without a user prompt, moving from "Chatbots" to "Autonomous Systems."

## 5. Persistence: Event Sourcing as Source of Truth
**Observation:** Maintaining separate Ecto state schemas and "Time Travel" event logs creates risk of divergence and architectural complexity.
**Recommendation:** Converge State and History into a single Event Stream.
- **Change:** Adopt Event Sourcing. The database stores an immutable stream of events (`MessageAdded`, `ToolCalled`, `PlanUpdated`).
- **Mechanism:** The `Session` state is reconstructed by a `fold/reduce` over the event stream.
- **Benefit:** "Time Travel" becomes a native property of the system rather than a feature. State recovery and debugging become deterministic and trivial.

## Summary: BEAM Superpowers vs. Python Porting
While the current design solves the *mechanics* of Python's failures (async, memory), these enhancements move the framework from "Python-in-Elixir" to a native **Actor-Based Agent Intelligence**.

| Feature | Python Mental Model | BEAM Mental Model |
| :--- | :--- | :--- |
| **Execution** | Serial Loop | Concurrent Scatter-Gather |
| **Coordination** | Orchestrator (Hub-and-Spoke) | PubSub (Mesh/Society) |
| **Recovery** | Exception Handling | State-Aware Supervision |
| **Logic** | Request/Response | Reactive/Autonomous |
| **Persistence** | Snapshot DB | Event Sourcing |
