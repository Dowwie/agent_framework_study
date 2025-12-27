# Enhancing Elixir Agent Framework: Architectural Critique & Recommendations

This document outlines refinements for the Elixir Agent Framework design based on forensic analysis of 15+ production Python agent frameworks and the "Golden Stack" reference architecture.

## 1. Concurrency & Determinism
**Current Design:** Uses GenServer + Task.async for step execution.
**Critique:** While Elixir provides native isolation (solving many Python pitfalls), it lacks the rigorous **Bulk Synchronous Parallel (BSP)** execution model of top-tier frameworks like LangGraph.
**Recommendations:**
- **Deterministic Updates:** Ensure the `SessionController` processes parallel `Task` results in a deterministic order (e.g., sorting by step index/ID) before applying state transitions.
- **Superstep Modeling:** Explicitly divide transitions into `Plan -> Execute -> Update` phases to maintain consistency for "Time Travel" debugging.

## 2. Hierarchical Memory Management
**Current Design:** Mentions "Token budget + eviction."
**Critique:** 80% of existing frameworks fail due to unbounded memory growth. Generic FIFO eviction is insufficient for complex reasoning.
**Recommendations:**
- **Adopt 50/30/20 Strategy:** Implement hierarchical compression in the `ContextBuilder`:
    - **50% Recent:** Verbatim messages for immediate context.
    - **30% Summary:** Rolling summary of historical interactions.
    - **20% Semantic:** Vector-retrieved "long-term" facts.
- **Asynchronous Pruning:** Use background processes to handle summarization and embedding updates so they don't block the main execution loop.

## 3. Tool Sandboxing (Critical Security)
**Current Design:** Relies on "Task isolation" for tools.
**Critique:** **Critical Risk.** A BEAM Task provides concurrency isolation but zero security isolation. LLM-generated code running in a Task can access the host filesystem, network, and environment variables.
**Recommendations:**
- **External Execution:** Move tool execution (especially code) to an external sandbox:
    - **Wasmex (WASM):** For high-performance, safe in-process execution.
    - **Sidecar Containers:** Execute code in ephemeral Docker/Podman containers.
- **Capability-Based Access:** Implement a manifest for each tool defining restricted paths or network domains.

## 4. Resilience & Hardening
**Current Design:** Includes `:fuse` and `Hammer`.
**Critique:** This is a major strength over Python frameworks.
**Recommendations:**
- **Self-Correction (Error-as-Data):** Standardize tool errors as structured data (e.g., `{:error, %ToolError{message: "...", retry: true}}`). Feed the error message back to the LLM to allow for autonomous self-correction without crashing the session.
- **Checkpoint Recovery:** Ensure `SessionController` state is snapshotted to PostgreSQL *after* every successful state transition to allow for seamless recovery across node restarts.

## 5. Type Safety & Identity
**Current Design:** Ecto schemas and string IDs.
**Critique:** "Stringly-typed" IDs (routing by name/string) are a frequent cause of production failures in Python.
**Recommendations:**
- **Tagged Tuples/Structs:** Use opaque types or specific structs for `SessionID` and `StepID` to prevent argument-swapping bugs.
- **Behaviour-Based DI:** Emulate Pydantic-AI's dependency injection using Elixir Behaviours and Protocols to ensure tools have type-safe access to resources (e.g., DB connections, API keys) without using globals.

## 6. Observability
**Current Design:** Telemetry + OpenTelemetry.
**Recommendations:**
- **Standardized Taxonomy:** Adopt the **Agno 17 Event Taxonomy** (e.g., `run_started`, `llm_stream_chunk`, `agent_handoff`, `reasoning_step`) to ensure compatibility with external observability tools and dashboards.
- **Trace Propagation:** Ensure the `trace_id` from the initial request is correctly propagated through the `SessionController` into the spawned `Task` processes.

## Summary of Immediate Actions
1. **Pivot from Task to WASM/Docker** for code-execution tools.
2. **Implement the 50/30/20 compression** logic in the `ContextBuilder`.
3. **Refine state updates** to be deterministic for "Time Travel" consistency.
4. **Standardize the Telemetry event vocabulary** to match industry-leading taxonomies.
