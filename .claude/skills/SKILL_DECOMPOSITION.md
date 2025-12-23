# Architectural Forensics Protocol: Skill Decomposition

## Overview

This document decomposes the Architectural Forensics Protocol into **12 discrete, modular skills** that a software engineering agent can utilize. Each skill is designed to be:

- **Self-contained**: Executable independently with clear inputs/outputs
- **Composable**: Can be chained together for complex analysis workflows
- **Reusable**: Applicable across different framework analysis tasks

---

## Skill Taxonomy

```
architectural-forensics/
├── Phase 1: Engineering Chassis
│   ├── 1. codebase-mapping          # Repository structure & dependency analysis
│   ├── 2. data-substrate-analysis   # Types, state, serialization patterns
│   ├── 3. execution-engine-analysis # Control flow, concurrency, event architecture
│   ├── 4. component-model-analysis  # Extensibility, DI, configuration patterns
│   └── 5. resilience-analysis       # Error handling, sandboxing, boundaries
│
├── Phase 2: Cognitive Architecture
│   ├── 6. control-loop-extraction   # Reasoning patterns, step functions, termination
│   ├── 7. memory-orchestration      # Context management, eviction, state continuity
│   ├── 8. tool-interface-analysis   # Schema generation, feedback loops
│   └── 9. multi-agent-analysis      # Coordination, handoffs, shared state
│
└── Phase 3: Synthesis
    ├── 10. comparative-matrix        # Best-of-breed decision framework
    ├── 11. antipattern-catalog       # Technical debt documentation
    └── 12. architecture-synthesis    # Reference architecture generation
```

---

## Skill Definitions

### Skill 1: `codebase-mapping`

**Purpose**: Generate a structural map of a codebase to enable targeted analysis.

**Inputs**:
- Repository URL or local path
- Optional: specific directories to focus on

**Outputs**:
- File tree with annotations
- Dependency graph (imports/exports)
- Entry point identification
- Module boundary map

**Key Operations**:
1. Clone/access repository
2. Generate file tree (excluding node_modules, __pycache__, etc.)
3. Parse import statements to build dependency graph
4. Identify entry points (main.py, index.ts, setup.py, pyproject.toml)
5. Detect package boundaries and public APIs

**Trigger Phrases**: "map the codebase", "show me the structure", "dependency analysis"

---

### Skill 2: `data-substrate-analysis`

**Purpose**: Analyze the fundamental data primitives and state management patterns.

**Inputs**:
- Codebase path
- Focus files (typically types.py, models.py, schema.py, state.py)

**Outputs**:
- Typing strategy assessment (strict vs. loose)
- Immutability analysis report
- Serialization strategy summary
- State management patterns

**Key Operations**:
1. Locate type definition files
2. Classify typing approach:
   - Pydantic models → "Strict/Validated"
   - TypedDict → "Structural"
   - Plain dicts → "Loose/Untyped"
   - dataclasses → "Structural/Immutable"
3. Analyze mutation patterns (in-place vs. copy-on-write)
4. Identify serialization methods (json(), dict(), pickle, msgpack)
5. Document state shape and lifecycle

**Trigger Phrases**: "analyze types", "state management", "data primitives"

---

### Skill 3: `execution-engine-analysis`

**Purpose**: Understand the control flow and concurrency model.

**Inputs**:
- Codebase path
- Entry point / main execution file

**Outputs**:
- Concurrency model classification
- Execution topology (DAG/FSM/Linear)
- Event emission patterns
- Observability hook inventory

**Key Operations**:
1. Identify async/sync patterns:
   - Look for `async def`, `await`, `asyncio`
   - Detect thread pools, process pools
   - Identify sync wrappers around async
2. Classify execution model:
   - Graph-based (nodes, edges, DAG)
   - State machine (states, transitions)
   - Linear chain (sequential steps)
3. Catalog event mechanisms:
   - Callbacks/Listeners
   - Async generators (yield)
   - Event emitters
4. Map observability hooks (pre/post execution, tool calls)

**Trigger Phrases**: "control flow", "async analysis", "execution model"

---

### Skill 4: `component-model-analysis`

**Purpose**: Evaluate extensibility patterns and configuration approaches.

**Inputs**:
- Codebase path
- Base class / interface files

**Outputs**:
- Abstraction layer assessment
- Dependency injection pattern
- Configuration strategy
- Extension point inventory

**Key Operations**:
1. Identify base classes/protocols (BaseLLM, BaseTool, BaseAgent)
2. Classify abstraction thickness:
   - Thick: Many methods, complex inheritance
   - Thin: Pure interfaces/protocols
3. Analyze DI patterns:
   - Constructor injection
   - Factory patterns
   - Global registries
   - Container-based (e.g., dependency_injector)
4. Identify configuration strategy:
   - Code-first (Python classes)
   - Config-first (YAML/JSON/TOML)
   - Hybrid

**Trigger Phrases**: "extensibility", "base classes", "plugin system", "dependency injection"

---

### Skill 5: `resilience-analysis`

**Purpose**: Assess error handling and isolation boundaries.

**Inputs**:
- Codebase path
- Execution runner files

**Outputs**:
- Error propagation map
- Isolation boundary inventory
- Sandboxing mechanisms
- Recovery patterns

**Key Operations**:
1. Trace exception handling:
   - Locate try/except blocks in runners
   - Identify caught vs. propagated exceptions
   - Map error transformation (wrapping)
2. Identify isolation mechanisms:
   - Subprocess execution
   - Docker/container usage
   - Virtual environments
   - Restricted execution (RestrictedPython, etc.)
3. Catalog recovery patterns:
   - Retry logic
   - Fallback mechanisms
   - Circuit breakers

**Trigger Phrases**: "error handling", "sandboxing", "isolation", "resilience"

---

### Skill 6: `control-loop-extraction`

**Purpose**: Extract and document the core agent reasoning loop.

**Inputs**:
- Agent execution file
- LLM interaction code

**Outputs**:
- Reasoning topology classification
- Step function pseudocode
- Termination condition catalog
- Decision point map

**Key Operations**:
1. Locate the main agent loop (while True, for step in...)
2. Classify reasoning pattern:
   - ReAct: Thought → Action → Observation
   - Plan-and-Solve: Plan → Execute → Verify
   - Reflection: Act → Reflect → Adjust
   - Tree-of-Thoughts: Branch → Evaluate → Select
3. Extract the "step function":
   - LLM call → Parse output → Decide action
   - Tool invocation vs. final response
4. Document termination conditions:
   - Token/step limits
   - Explicit finish signals
   - Loop detection heuristics

**Trigger Phrases**: "reasoning loop", "agent loop", "step function", "ReAct pattern"

---

### Skill 7: `memory-orchestration`

**Purpose**: Analyze context management and memory systems.

**Inputs**:
- Agent/memory module files
- Prompt construction code

**Outputs**:
- Context assembly pattern
- Eviction policy documentation
- Memory tier map (short-term/long-term)
- Token management strategy

**Key Operations**:
1. Trace context assembly:
   - System prompt location
   - History formatting
   - Tool result injection
   - Template/interpolation method
2. Identify eviction policies:
   - FIFO (drop oldest)
   - Summarization chains
   - Vector store swapping
   - Sliding window
3. Map memory tiers:
   - In-memory (conversation state)
   - Vector database integration
   - SQL/document store
4. Analyze token management:
   - Counting mechanisms
   - Truncation strategies
   - Budget allocation

**Trigger Phrases**: "context management", "memory system", "context window", "history management"

---

### Skill 8: `tool-interface-analysis`

**Purpose**: Understand tool registration, schema generation, and error feedback.

**Inputs**:
- Tool definition files
- Tool execution code

**Outputs**:
- Schema generation method
- Tool registration pattern
- Error feedback loop documentation
- Retry/self-correction mechanisms

**Key Operations**:
1. Analyze schema generation:
   - Python introspection (inspect module)
   - Pydantic model → JSON Schema
   - Manual definition
   - Decorator-based
2. Document registration patterns:
   - Declarative (list of tools)
   - Discovery-based (auto-import)
   - Registry pattern
3. Trace error feedback:
   - Exception → LLM message
   - stderr capture
   - Structured error objects
4. Identify retry mechanisms:
   - Automatic retry with error context
   - Max retry limits
   - Backoff strategies

**Trigger Phrases**: "tool interface", "function calling", "schema generation", "tool errors"

---

### Skill 9: `multi-agent-analysis`

**Purpose**: Analyze coordination patterns in multi-agent systems.

**Inputs**:
- Multi-agent orchestration files
- Agent communication code

**Outputs**:
- Coordination topology
- Handoff mechanism documentation
- State sharing pattern
- Communication protocol

**Key Operations**:
1. Identify coordination model:
   - Hierarchical (supervisor → workers)
   - Peer-to-peer
   - Pipeline/sequential
   - Market-based
2. Document handoff mechanisms:
   - Explicit transfer (router)
   - Implicit (state mutation)
   - Message passing
3. Classify state sharing:
   - Blackboard (shared global state)
   - Message passing (isolated state)
   - Hybrid
4. Trace communication:
   - Direct invocation
   - Queue-based
   - Event-driven

**Trigger Phrases**: "multi-agent", "agent handoff", "coordination", "agent communication"

---

### Skill 10: `comparative-matrix`

**Purpose**: Generate structured comparisons across analyzed frameworks.

**Inputs**:
- Analysis outputs from Skills 1-9 for multiple frameworks
- Comparison dimensions (configurable)

**Outputs**:
- Best-of-breed decision matrix
- Dimension-by-dimension comparison
- Recommended approach per dimension
- Trade-off documentation

**Key Operations**:
1. Collect analysis outputs per framework
2. Normalize findings to comparable dimensions:
   - Typing, Async, State, Config, Extensibility, etc.
3. Generate comparison table
4. Apply decision heuristics:
   - Scalability requirements
   - DX priorities
   - Team expertise
5. Document recommendations with rationale

**Trigger Phrases**: "compare frameworks", "decision matrix", "best practices comparison"

---

### Skill 11: `antipattern-catalog`

**Purpose**: Document technical debt and patterns to avoid.

**Inputs**:
- Analysis outputs from Skills 1-9
- Optional: severity thresholds

**Outputs**:
- Categorized anti-pattern list
- Severity assessment
- Remediation suggestions
- "Do Not Repeat" guidelines

**Key Operations**:
1. Identify anti-patterns by category:
   - Structural (deep inheritance, god classes)
   - Behavioral (hidden state, implicit contracts)
   - Observability (swallowed errors, hidden data)
   - Performance (blocking in async, memory leaks)
2. Assign severity levels
3. Generate remediation strategies
4. Create "Do Not Repeat" checklist

**Trigger Phrases**: "anti-patterns", "technical debt", "code smells", "what to avoid"

---

### Skill 12: `architecture-synthesis`

**Purpose**: Generate a reference architecture specification.

**Inputs**:
- Best-of-breed matrix
- Anti-pattern catalog
- Design requirements

**Outputs**:
- Core primitive definitions
- Interface specifications (Protocols)
- Execution loop pseudocode
- Architecture diagram (Mermaid)

**Key Operations**:
1. Define core primitives:
   - Message, State, Result, Tool types
2. Specify interfaces:
   - LLM Protocol
   - Tool Protocol
   - Memory Protocol
3. Design the execution loop:
   - Incorporate best reasoning patterns
   - Include observability hooks
   - Define termination logic
4. Generate architecture diagram
5. Produce implementation roadmap

**Trigger Phrases**: "reference architecture", "design spec", "new framework design"

---

## Skill Chaining Workflows

### Full Protocol Execution

```
1. codebase-mapping (Framework A)
   ↓
2-5. [Engineering Chassis Skills] in parallel
   ↓
6-9. [Cognitive Architecture Skills] in parallel
   ↓
[Repeat 1-9 for Framework B, C, ...]
   ↓
10. comparative-matrix
   ↓
11. antipattern-catalog
   ↓
12. architecture-synthesis
```

### Quick Analysis Workflow

For rapid assessment of a single framework:

```
1. codebase-mapping
   ↓
3. execution-engine-analysis
   ↓
6. control-loop-extraction
   ↓
8. tool-interface-analysis
```

### Extensibility Audit Workflow

For evaluating how easy it is to extend a framework:

```
1. codebase-mapping
   ↓
4. component-model-analysis
   ↓
8. tool-interface-analysis
   ↓
11. antipattern-catalog (extensibility focus)
```

---

## Implementation Priority

| Priority | Skill | Rationale |
|----------|-------|-----------|
| P0 | codebase-mapping | Foundation for all other skills |
| P0 | control-loop-extraction | Core insight for agent architecture |
| P1 | execution-engine-analysis | Critical for scalability decisions |
| P1 | tool-interface-analysis | Essential for interoperability |
| P1 | comparative-matrix | Enables systematic decision-making |
| P2 | data-substrate-analysis | Important but analyzable manually |
| P2 | memory-orchestration | Complex, high value |
| P2 | antipattern-catalog | Prevents known mistakes |
| P3 | component-model-analysis | Valuable for extension work |
| P3 | resilience-analysis | Important for production systems |
| P3 | multi-agent-analysis | Only needed for multi-agent systems |
| P3 | architecture-synthesis | Capstone skill, requires others |
