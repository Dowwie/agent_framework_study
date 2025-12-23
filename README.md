# Architectural Forensics Skills

A modular skill library for software engineering agents to analyze, compare, and synthesize agent framework architectures.

## Mission

We are analyzing 14 of the most popular agent frameworks to deconstruct their architectures and inform the design of a new, optimized derivative system.

This strategy prioritizes understanding:
*   **Software Engineering Decisions** (how it runs): The "Engineering Chassis" (Data, Execution, Component Model, Resilience).
*   **Cognitive Architecture Decisions** (how it thinks): The "Cognitive Core" (Control Loop, Memory, Tooling, Coordination).

The ultimate goal is to extract reusable "best-of-breed" patterns and document critical anti-patterns to guide the development of robust, scalable agentic software.

## Target Frameworks

The `repos/` directory contains clones of major agent frameworks for analysis:

| Framework | Source | Focus |
|-----------|--------|-------|
| **autogen** | Microsoft | Multi-agent conversation patterns |
| **langgraph** | LangChain | Graph-based agent orchestration |
| **crewAI** | CrewAI | Role-based multi-agent teams |
| **openai-agents-python** | OpenAI | Swarm-inspired lightweight agents |
| **pydantic-ai** | Pydantic | Type-safe agent interfaces |
| **llama_index** | LlamaIndex | Data-augmented agents |
| **google-adk** | Google | Agent Development Kit |
| **aws-strands** | AWS | Strands agent framework |
| **ms-agent-framework** | Microsoft | Semantic Kernel agents |
| **MetaGPT** | DeepWisdom | Software dev team simulation |
| **camel** | CAMEL-AI | Communicative agent framework |
| **agno** | Agno | Lightweight agent runtime |
| **agent-zero** | FrdLnd | Personal assistant framework |
| **swarm** | OpenAI | Educational multi-agent patterns |

## Quick Start

```bash
# 1. Download install-skills.sh and files.zip to your project directory

# 2. Make the installer executable
chmod +x install-skills.sh

# 3. Run the installer
./install-skills.sh

# Skills are now available at .claude/skills/
```

## Usage

### 1. Preparation
Clone the target frameworks you wish to analyze into the `repos/` directory:
```bash
git clone https://github.com/microsoft/autogen repos/autogen
git clone https://github.com/langchain-ai/langgraph repos/langgraph
# ... other frameworks
```

### 2. Running the Analysis
Trigger the analysis protocol directly using the Claude Code command:
```bash
/analyze-frameworks
```
This command auto-discovers all frameworks in the `repos/` directory and executes the full architectural forensics protocol.

### 3. Interruption and Resumption
The analysis process is stateful and supports interruption and resumption. State is tracked in `forensics-output/.state/manifest.json`.

#### Checking Progress
To see the current status of all frameworks:
```bash
python scripts/state_manager.py status
```

#### Resuming After Interruption
If the process crashes or is manually stopped, some frameworks may be left in `in_progress` status. To safely resume:

1. **Reset Stalled Jobs**: This moves frameworks from `in_progress` back to `pending`.
   ```bash
   python scripts/state_manager.py reset-running
   ```
2. **Restart the Analysis**: Re-issue the command:
   ```bash
   /analyze-frameworks
   ```
   The protocol will skip completed frameworks and resume from the next pending ones.

### 4. Manual State Management
For advanced users, the `state_manager.py` script provides fine-grained control:
- `python scripts/state_manager.py init`: Refresh the manifest based on the current contents of the `repos/` directory.
- `python scripts/state_manager.py mark <framework> <status>`: Manually set a framework's status (`pending`, `in_progress`, `completed`, `failed`).

## Skills Taxonomy

```
.claude/skills/
├── Phase 1: Engineering Chassis
│   ├── codebase-mapping/           # Repository structure & dependencies
│   ├── data-substrate-analysis/    # Types, state, serialization
│   ├── execution-engine-analysis/  # Async, control flow, events
│   ├── component-model-analysis/   # Extensibility, DI, configuration
│   └── resilience-analysis/        # Error handling, sandboxing
│
├── Phase 2: Cognitive Architecture
│   ├── control-loop-extraction/    # Reasoning patterns, step functions
│   ├── memory-orchestration/       # Context management, eviction
│   ├── tool-interface-analysis/    # Schema generation, feedback loops
│   └── multi-agent-analysis/       # Coordination, handoffs, state
│
├── Phase 3: Synthesis
│   ├── comparative-matrix/         # Best-of-breed decisions
│   ├── antipattern-catalog/        # Technical debt documentation
│   └── architecture-synthesis/     # Reference architecture spec
│
└── Orchestration
    └── architectural-forensics/    # Master protocol
```

## Workflow

### Full Protocol Execution

```
┌─────────────────────────────────────────────────────────────┐
│                    For Each Framework                        │
├─────────────────────────────────────────────────────────────┤
│  1. codebase-mapping                                        │
│       ↓                                                     │
│  2. Phase 1 Analysis (parallel)                             │
│     ├── data-substrate-analysis                             │
│     ├── execution-engine-analysis                           │
│     ├── component-model-analysis                            │
│     └── resilience-analysis                                 │
│       ↓                                                     │
│  3. Phase 2 Analysis (parallel)                             │
│     ├── control-loop-extraction                             │
│     ├── memory-orchestration                                │
│     ├── tool-interface-analysis                             │
│     └── multi-agent-analysis                                │
└─────────────────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────────────────┐
│                      Synthesis                               │
├─────────────────────────────────────────────────────────────┤
│  4. comparative-matrix                                       │
│  5. antipattern-catalog                                      │
│  6. architecture-synthesis                                   │
└─────────────────────────────────────────────────────────────┘
```

### Quick Analysis (Single Framework)

For rapid assessment:

```
codebase-mapping → execution-engine-analysis → control-loop-extraction → tool-interface-analysis
```

## Skill Reference

| Skill | Trigger Phrases | Key Outputs |
|-------|-----------------|-------------|
| `codebase-mapping` | "map the codebase", "dependency analysis" | File tree, import graph, entry points |
| `data-substrate-analysis` | "analyze types", "state management" | Typing strategy, mutation patterns |
| `execution-engine-analysis` | "control flow", "async analysis" | Concurrency model, event architecture |
| `component-model-analysis` | "extensibility", "base classes" | Abstraction depth, DI patterns |
| `resilience-analysis` | "error handling", "sandboxing" | Error propagation, isolation mechanisms |
| `control-loop-extraction` | "reasoning loop", "ReAct pattern" | Pattern classification, step function |
| `memory-orchestration` | "context management", "memory system" | Assembly order, eviction policies |
| `tool-interface-analysis` | "tool interface", "schema generation" | Schema methods, error feedback |
| `multi-agent-analysis` | "agent handoff", "coordination" | Coordination model, state sharing |
| `comparative-matrix` | "compare frameworks", "decision matrix" | Best-of-breed table |
| `antipattern-catalog` | "anti-patterns", "technical debt" | Categorized issues, remediation |
| `architecture-synthesis` | "reference architecture", "design spec" | Primitives, protocols, loop design |

## File Structure

After installation:

```
.claude/
└── skills/
    ├── MANIFEST.md                    # Index of installed skills
    ├── SKILL_DECOMPOSITION.md         # Detailed skill definitions
    ├── SKILL_FLOW.md                  # Visual workflow diagram
    │
    ├── architectural-forensics/       # Master orchestration skill
    │   ├── SKILL.md
    │   └── references/
    │       ├── phase1-engineering.md
    │       └── phase2-cognitive.md
    │
    ├── codebase-mapping/
    │   ├── SKILL.md
    │   └── scripts/
    │       └── map_codebase.py        # Python analysis script
    │
    └── [other-skills]/
        └── SKILL.md
```

## Skill Anatomy

Each skill follows a consistent structure:

```markdown
---
name: skill-name
description: What the skill does and when to trigger it.
---

# Skill Name

## Process
1. Step one
2. Step two
...

## Detection Patterns
[How to identify relevant code patterns]

## Output Template
[Standardized output format]

## Integration
- Prerequisites: [required skills]
- Feeds into: [downstream skills]
```

## Example Use Cases

### Analyzing LangChain vs AutoGen

1. Run `codebase-mapping` on both repositories
2. Execute Phase 1 & 2 skills on each
3. Use `comparative-matrix` to generate comparison
4. Document issues with `antipattern-catalog`
5. Design new framework with `architecture-synthesis`

### Quick Framework Assessment

```
User: "Analyze the agent loop in this codebase"
Agent: [triggers control-loop-extraction]
       → Classifies as ReAct pattern
       → Extracts step function pseudocode
       → Documents termination conditions
```

### Extensibility Audit

```
User: "How easy is it to add custom tools?"
Agent: [triggers component-model-analysis + tool-interface-analysis]
       → Evaluates abstraction depth
       → Documents registration patterns
       → Assesses schema generation approach
```

## Installation Options

### Standard Installation

```bash
./install-skills.sh
```

### Custom Zip Location

```bash
./install-skills.sh /path/to/custom-skills.zip
```

### Manual Installation

```bash
unzip files.zip
mkdir -p .claude/skills
cp -r architectural-forensics-skills/skills/* .claude/skills/
```

## Requirements

- Bash shell
- `unzip` command
- Write access to create `.claude/` directory

## Roadmap

- [ ] Add agents that utilize these skills
- [ ] Create example analysis reports
- [ ] Add more framework-specific detection patterns
- [ ] Build interactive comparison tool

## Contributing

Skills follow the format defined in the `skill-creator` reference. Key principles:

1. **Concise is key** - Only include what Claude doesn't already know
2. **Progressive disclosure** - SKILL.md for core workflow, references for details
3. **Clear triggers** - Description should specify when the skill activates
4. **Standardized outputs** - Use consistent templates across skills

## License

See LICENSE file for details.

---

## Quick Reference Card

```
┌────────────────────────────────────────────────────────────────┐
│                 ARCHITECTURAL FORENSICS                         │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PHASE 1: ENGINEERING          PHASE 2: COGNITIVE              │
│  ├─ codebase-mapping           ├─ control-loop-extraction      │
│  ├─ data-substrate             ├─ memory-orchestration         │
│  ├─ execution-engine           ├─ tool-interface               │
│  ├─ component-model            └─ multi-agent                  │
│  └─ resilience                                                 │
│                                                                 │
│  PHASE 3: SYNTHESIS                                            │
│  ├─ comparative-matrix  →  antipattern-catalog                 │
│  └─ architecture-synthesis                                     │
│                                                                 │
├────────────────────────────────────────────────────────────────┤
│  Install: ./install-skills.sh                                  │
│  Location: .claude/skills/                                     │
└────────────────────────────────────────────────────────────────┘
```
