# Future Analysis Tasks

Research and analysis tasks identified during design sessions that are worth investigating but not blocking.

---

## Agno Event Taxonomy Analysis

**Source**: Design session 2025-12-27, critique evaluation
**Priority**: Low (informational)

**Context:**
The Agno Python framework defines a 17-event taxonomy for observability. While we shouldn't adopt their specific events (their abstractions differ from ours), analyzing what they track and why could inform our own telemetry design.

**Questions to answer:**
1. What are Agno's 17 event types?
2. What lifecycle stages do they capture?
3. Are there gaps in our current event set?
4. Are there events they track that we haven't considered?
5. How do their events map to OpenTelemetry semantic conventions (if at all)?

**Our current events:**
```elixir
[:agent_framework, :session, :start | :complete | :error]
[:agent_framework, :step, :start | :complete | :error]
[:agent_framework, :llm, :request | :response | :error]
[:agent_framework, :tool, :execute | :complete | :error]
```

**Potential additions to consider after analysis:**
- Sub-agent lifecycle events?
- Memory/context events (eviction, summarization)?
- Sandbox events?
- Interrupt/resume events?
- HITL events?

**Where to look:**
- Agno repository (if public)
- Agno documentation
- Framework comparison in `reports/synthesis/`

**Output:**
- Gap analysis between Agno events and ours
- Recommendations for additional events (if any)
- Alignment with OpenTelemetry GenAI conventions (if they exist)

---

## OpenTelemetry GenAI Semantic Conventions

**Source**: Design session 2025-12-27
**Priority**: Low

**Context:**
OpenTelemetry is developing semantic conventions for GenAI/LLM instrumentation. Aligning our telemetry with these conventions would improve interoperability with observability tools.

**Questions to answer:**
1. Do OTEL GenAI semantic conventions exist?
2. What attributes do they define for LLM calls?
3. How should we structure spans for agent workflows?
4. What metadata should be attached to LLM/tool spans?

**Where to look:**
- https://opentelemetry.io/docs/specs/semconv/
- OTEL GenAI working group (if exists)
- LangSmith, Langfuse for inspiration on LLM observability

---

## Tiktoken Elixir Bindings

**Source**: Design session 2025-12-24
**Priority**: Medium (needed for implementation)

**Context:**
Token counting is required for the 50/30/20 memory strategy. Need to evaluate options:

1. Existing Elixir tiktoken bindings?
2. NIF wrapper around tiktoken-rs?
3. Port to external Python/Rust process?
4. Approximation heuristics (chars/4)?

**Criteria:**
- Accuracy (must match OpenAI's counting)
- Performance (called frequently)
- Maintenance burden
- Deployment complexity

---

## LiteLLM Provider Unification Patterns

**Source**: Design session 2025-12-24
**Priority**: Low

**Context:**
LiteLLM unifies 100+ LLM provider APIs. Analyzing their abstraction could inform our LLM behaviour design.

**Questions to answer:**
1. How do they normalize request/response formats?
2. How do they handle provider-specific features?
3. What's their error normalization strategy?
4. How do they handle streaming differences?

---

## Context Compaction Alternatives

**Source**: Design session 2025-12-24
**Priority**: Medium

**Context:**
The 50/30/20 strategy uses LLM summarization for the "summary" tier. This adds cost and latency. Are there alternatives?

**Options to investigate:**
1. Extractive summarization (no LLM, keyword extraction)
2. Embedding-based clustering (group similar messages)
3. Structured extraction (extract facts, discard prose)
4. Hybrid (cheap model for summarization, expensive for agent)

---
