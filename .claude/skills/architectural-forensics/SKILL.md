---
name: architectural-forensics
description: Master protocol for deconstructing agent frameworks to inform derivative system architecture. Use when (1) analyzing an agent framework's codebase comprehensively, (2) comparing multiple frameworks to select best practices, (3) designing a new agent system based on prior art, (4) documenting architectural decisions with evidence, or (5) conducting technical due diligence on AI agent implementations. This skill orchestrates sub-skills for data substrate, execution engine, cognitive architecture, and synthesis phases.
---

# Architectural Forensics Protocol

Deconstruct agent frameworks to inform derivative system architecture.

## Mission

Distinguish between **software engineering decisions** (how it runs) and **cognitive architecture decisions** (how it thinks) to extract reusable patterns for new systems.

## Quick Start

```bash
# 1. Map the codebase
python scripts/map_codebase.py /path/to/framework

# 2. Run analysis (creates structured output)
# Follow the phase-by-phase process below
```

## Protocol Phases

### Phase 1: Engineering Chassis

Analyze the software substrate. See `references/phase1-engineering.md` for detailed guidance.

| Analysis | Focus Files | Output |
|----------|-------------|--------|
| Data Substrate | types.py, schema.py, state.py | Typing strategy, mutation patterns |
| Execution Engine | runner.py, executor.py, agent.py | Async model, control flow topology |
| Component Model | base_*.py, interfaces.py | Abstraction depth, DI patterns |
| Resilience | executor.py, try/except blocks | Error propagation, sandboxing |

### Phase 2: Cognitive Architecture

Extract agent "business logic". See `references/phase2-cognitive.md` for detailed guidance.

| Analysis | Focus Files | Output |
|----------|-------------|--------|
| Control Loop | agent.py, loop.py | Reasoning pattern, step function |
| Memory | memory.py, context.py | Context assembly, eviction policies |
| Tool Interface | tool.py, functions.py | Schema generation, error feedback |
| Multi-Agent | orchestrator.py, router.py | Coordination model, state sharing |

### Phase 3: Synthesis

Generate actionable outputs:

1. **Best-of-Breed Matrix** → Framework comparison table
2. **Anti-Pattern Catalog** → "Do Not Repeat" list
3. **Reference Architecture** → New framework specification

## Execution Workflow

```
┌─────────────────────────────────────────────────────────┐
│                    For Each Framework                    │
├─────────────────────────────────────────────────────────┤
│  1. codebase-mapping                                    │
│       ↓                                                 │
│  2. Phase 1 Analysis (parallel)                         │
│     ├── data-substrate-analysis                         │
│     ├── execution-engine-analysis                       │
│     ├── component-model-analysis                        │
│     └── resilience-analysis                             │
│       ↓                                                 │
│  3. Phase 2 Analysis (parallel)                         │
│     ├── control-loop-extraction                         │
│     ├── memory-orchestration                            │
│     ├── tool-interface-analysis                         │
│     └── multi-agent-analysis (if applicable)            │
└─────────────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────────────┐
│                      Synthesis                           │
├─────────────────────────────────────────────────────────┤
│  4. comparative-matrix                                   │
│  5. antipattern-catalog                                  │
│  6. architecture-synthesis                               │
└─────────────────────────────────────────────────────────┘
```

## Quick Analysis (Single Framework)

For rapid assessment, run the minimal path:

```
codebase-mapping → execution-engine-analysis → control-loop-extraction → tool-interface-analysis
```

## Output Directory Structure

```
forensics-output/
├── frameworks/
│   ├── framework-a/
│   │   ├── codebase-map.json
│   │   ├── phase1/
│   │   │   ├── data-substrate.md
│   │   │   ├── execution-engine.md
│   │   │   ├── component-model.md
│   │   │   └── resilience.md
│   │   └── phase2/
│   │       ├── control-loop.md
│   │       ├── memory.md
│   │       ├── tool-interface.md
│   │       └── multi-agent.md
│   └── framework-b/
│       └── ...
├── synthesis/
│   ├── comparison-matrix.md
│   ├── antipatterns.md
│   └── reference-architecture.md
└── README.md
```

## Sub-Skill Reference

| Skill | Purpose | Key Outputs |
|-------|---------|-------------|
| `codebase-mapping` | Repository structure | File tree, dependencies, entry points |
| `data-substrate-analysis` | Type system | Typing strategy, serialization |
| `execution-engine-analysis` | Control flow | Async model, event architecture |
| `component-model-analysis` | Extensibility | Abstraction patterns, DI |
| `resilience-analysis` | Error handling | Error propagation, sandboxing |
| `control-loop-extraction` | Reasoning loop | Pattern classification, step function |
| `memory-orchestration` | Context management | Assembly, eviction, tiers |
| `tool-interface-analysis` | Tool system | Schema gen, error feedback |
| `multi-agent-analysis` | Coordination | Handoffs, state sharing |
| `comparative-matrix` | Comparison | Decision tables |
| `antipattern-catalog` | Tech debt | Do-not-repeat list |
| `architecture-synthesis` | New design | Reference spec |
