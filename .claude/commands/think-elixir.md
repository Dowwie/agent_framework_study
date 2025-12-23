# Elixir Agent Framework Design Session

Facilitate a structured design discussion for an idiomatic Elixir agent framework, using insights from the architectural forensics analysis.

## Session Logging

**IMPORTANT**: This session must be logged for future reference.

At session start:
1. Create session directory if needed: `mkdir -p docs/elixir-sessions`
2. Create session file with timestamp: `docs/elixir-sessions/YYYY-MM-DD-HHmm.md`
3. Initialize with session header

Throughout the session:
- After each decision point, append the exchange to the session file
- Include both the options presented AND the user's reasoning
- Capture deferred decisions and open questions

Session file format:

```markdown
# Elixir Design Session - [Date]

## Session Context
- Analysis artifacts used: [list files read]
- Session goal: [what we're deciding]

---

## Dimension 1: [Name]

### Options Presented
[Summary of options and trade-offs]

### Discussion
[Key points from conversation]

### Decision
**Choice**: [what was decided]
**Rationale**: [user's reasoning]
**Trade-offs accepted**: [what we're giving up]

---

## Dimension 2: [Name]
[Continue pattern...]

---

## Session Summary
- Decisions made: [count]
- Decisions deferred: [count]
- Next steps: [what to do next]
```

Also update `docs/elixir-design.md` with the consolidated decisions (without conversation detail).

## Session Resume

To continue a previous session:
1. List existing sessions: `ls docs/elixir-sessions/`
2. Read the most recent (or specified) session file
3. Summarize where we left off: decisions made, decisions pending
4. Continue from the next undecided dimension

When resuming, start with:
> "Resuming session from [date]. We've decided on [X, Y, Z]. Still open: [A, B, C]. Let's continue with [next dimension]..."

## Prerequisites

Before starting, verify analysis artifacts exist:

```bash
ls reports/synthesis/
```

If empty, inform the user they need to run `/analyze-frameworks` first.

## Session Structure

This is a **collaborative design session**, not a one-shot output. Guide the user through decisions incrementally, capturing their choices as you go.

### Phase 1: Load Context

Read the synthesis artifacts to ground the discussion:

1. `reports/synthesis/comparison-matrix.md` - Design decisions across frameworks
2. `reports/synthesis/antipatterns.md` - What to avoid
3. `reports/synthesis/reference-architecture.md` - Conceptual primitives

Summarize the key patterns discovered, framed as **concepts** not Python implementations:
- Reasoning patterns (ReAct, Plan-and-Solve, Reflection, etc.)
- State management approaches
- Tool interface designs
- Memory/context strategies
- Multi-agent coordination models
- Error handling philosophies

### Phase 2: Elixir Design Dimensions

Work through each dimension, presenting options and trade-offs. Use the AskUserQuestion tool to capture decisions.

#### Dimension 1: Process Architecture

Present the core question: How do agents map to OTP processes?

**Options to discuss:**
- **GenServer per conversation** - Stateful, long-lived, handles message history
- **GenServer per agent type** - Shared instance, state passed in calls
- **Task-based ephemeral** - Spawn per request, no persistent state
- **GenStage pipeline** - Backpressure-aware, streaming-native

**Elixir-specific considerations:**
- Supervision tree structure
- Process registry (Registry vs global)
- State recovery on crash
- Hot code upgrades

#### Dimension 2: State Model

Present findings on state patterns, then discuss Elixir idioms:

**From analysis:**
- Immutable vs mutable patterns observed
- Copy-on-write semantics
- State shape (flat vs nested)

**Elixir options:**
- Structs with `@enforce_keys`
- ETS for shared read-heavy state
- Agent for simple state cells
- Mnesia for distributed state

#### Dimension 3: Message Protocol

Present the message types discovered, then design Elixir equivalents:

**From analysis:**
- Message roles (system, user, assistant, tool)
- Tool call/result structures
- Streaming chunk formats

**Elixir options:**
- Tagged tuples: `{:user, content}`, `{:tool_call, name, args}`
- Structs with protocols
- Behaviour callbacks
- GenStage events

#### Dimension 4: Tool System

Present tool interface patterns, then Elixir design:

**From analysis:**
- Schema generation approaches
- Error feedback mechanisms
- Registration patterns

**Elixir options:**
- Behaviour with `@callback`
- Module attributes for schema
- Protocol for execution
- Dynamic dispatch via Registry

#### Dimension 5: Agent Loop

Present reasoning loop patterns, then Elixir translation:

**From analysis:**
- ReAct (think-act-observe)
- Plan-and-Solve
- Reflection patterns
- Termination conditions

**Elixir options:**
- Recursive function with pattern matching on result
- `Stream.resource/3` for lazy evaluation
- GenServer `handle_continue` for async steps
- State machine via `:gen_statem`

#### Dimension 6: LLM Integration

Present LLM interface patterns:

**From analysis:**
- Sync vs async invocation
- Streaming approaches
- Token counting
- Rate limiting

**Elixir options:**
- Req/Finch for HTTP
- GenStage producer for streaming
- Token bucket via `:leaky_bucket`
- Circuit breaker via `:fuse`

#### Dimension 7: Memory/Context

Present memory patterns:

**From analysis:**
- Context window management
- Eviction strategies
- Memory tiers

**Elixir options:**
- ETS with TTL
- Cachex for caching
- Vector store integration
- Process dictionary (discouraged but possible)

#### Dimension 8: Multi-Agent Coordination

Present coordination patterns:

**From analysis:**
- Handoff mechanisms
- Shared vs isolated state
- Routing strategies

**Elixir options:**
- PubSub for broadcast
- Registry for discovery
- Horde for distributed
- Swarm for clustering

#### Dimension 9: Observability

Present observability patterns:

**From analysis:**
- Callback hooks
- Event emission
- Tracing

**Elixir options:**
- Telemetry events
- Logger metadata
- OpenTelemetry integration
- Broadway for event processing

#### Dimension 10: Error Handling

Present error philosophies:

**From analysis:**
- Error propagation patterns
- Retry mechanisms
- Graceful degradation

**Elixir options:**
- Let it crash + supervision
- Tagged tuples `{:ok, _} | {:error, _}`
- `with` chains
- Circuit breakers

### Phase 3: Capture Decisions

As decisions are made, build a design document. After each dimension, summarize the user's choice.

Create/update `docs/elixir-design.md` with:

```markdown
# Elixir Agent Framework Design

## Design Decisions

### Process Architecture
**Decision**: [User's choice]
**Rationale**: [Why this fits their needs]

### State Model
**Decision**: [User's choice]
**Rationale**: [Why]

[Continue for each dimension...]

## Deferred Decisions
- [Things to decide later]

## Open Questions
- [Unresolved items]
```

### Phase 4: Architecture Sketch

Once core decisions are made, produce:

1. **Supervision tree diagram** - ASCII art showing process hierarchy
2. **Module structure** - Directory layout for the project
3. **Type specifications** - Key `@type` definitions
4. **Behaviour definitions** - Core callbacks

### Phase 5: Next Steps

Summarize:
- Decisions made
- Decisions deferred
- Recommended implementation order
- First module to build

## Session Guidelines

1. **One dimension at a time** - Don't overwhelm with all decisions at once
2. **Present trade-offs** - Every choice has costs; make them explicit
3. **Capture rationale** - Why matters more than what
4. **Allow "decide later"** - Not everything needs resolution now
5. **Reference analysis** - Quote specific findings when relevant
6. **Stay idiomatic** - Elixir solutions, not Python ports

## Example Interaction Flow

```
Claude: Let's start with Process Architecture. The analysis found that most
        frameworks use a single executor class that maintains conversation
        state. In Elixir, we have several options...

        [Presents options with trade-offs]

        Given your use case, which approach resonates?

User: I'm thinking GenServer per conversation, but I'm worried about
      memory if we have thousands of concurrent users.

Claude: That's a valid concern. Let's consider a hybrid: GenServer per
        conversation with automatic hibernation after idle timeout, plus
        state serialization to ETS or Redis for recovery. This gives you
        the clean API of GenServer with bounded memory.

        Want to go with that hybrid approach, or explore other options?

User: Yes, let's do the hybrid.

Claude: [Updates design document with decision and rationale]
        [Moves to next dimension]
```

## Anti-patterns to Avoid

From the analysis, actively steer away from:
- [Will be populated from antipatterns.md]
- Deep inheritance hierarchies (use behaviours/protocols instead)
- Mutable shared state (use message passing)
- Blocking operations in GenServer callbacks (use Task)
