# Agentic Workflow Architecture

This document defines the architecture for autonomous orchestration of the Architectural Forensics Protocol using Claude Code skills and a context-engineered agent hierarchy.

## Project Structure

```
agent_framework_study/
├── .claude/
│   ├── commands/
│   │   └── analyze-frameworks.md         # Entry point command
│   └── skills/
│       ├── architectural-forensics/      # Master orchestration skill
│       │   ├── SKILL.md
│       │   └── references/
│       │       ├── orchestrator-agent.md
│       │       ├── framework-agent.md
│       │       ├── skill-agent.md
│       │       ├── synthesis-agent.md
│       │       ├── phase1-engineering.md
│       │       └── phase2-cognitive.md
│       ├── codebase-mapping/
│       │   ├── SKILL.md
│       │   └── scripts/map_codebase.py
│       ├── data-substrate-analysis/
│       ├── execution-engine-analysis/
│       ├── component-model-analysis/
│       ├── resilience-analysis/
│       ├── control-loop-extraction/
│       ├── memory-orchestration/
│       ├── tool-interface-analysis/
│       ├── multi-agent-analysis/
│       ├── comparative-matrix/
│       ├── antipattern-catalog/
│       └── architecture-synthesis/
├── scripts/
│   └── agents/                           # Agent prompt builders
│       ├── orchestrator.py
│       ├── framework_agent.py
│       ├── skill_agent.py
│       └── synthesis_agent.py
├── repos/                                # INPUT: Clone frameworks here
├── forensics-output/                     # WORKING: Intermediate files
└── reports/                              # OUTPUT: Final deliverables
```

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Execution Model | Autonomous | Minimal human intervention during analysis |
| Runtime | Claude Code Skills | Leverage existing skill system, no custom SDK |
| Parallelism | Fully parallel | Independent agents per framework and per skill |
| Persistence | File-based | Local filesystem per output specification |
| Output Format | Markdown | Human-readable, LLM-interpretable for synthesis |
| Error Handling | Continue others | Graceful degradation if one framework fails |
| Input Source | Local paths | User provides pre-cloned repositories |

---

## Agent Skills Spec Compliance

This project follows the [Agent Skills specification](https://agentskills.io/specification).

### Skill Structure

```
.claude/skills/{skill-name}/
├── SKILL.md              # Required: frontmatter + instructions (<500 lines)
├── references/           # Optional: on-demand loaded documentation
├── scripts/              # Optional: executable code
└── assets/               # Optional: static resources
```

### Required Frontmatter

```yaml
---
name: skill-name          # Lowercase, hyphens, must match directory
description: What it does and when to use it (1-1024 chars)
---
```

### Progressive Disclosure

1. **Metadata** (~100 tokens): name + description loaded at startup
2. **Instructions** (<5000 tokens): SKILL.md body loaded on activation
3. **Resources** (on-demand): references/ loaded only when needed

---

## Agent Hierarchy

The architecture uses a 3-tier agent hierarchy optimized for context management:

```
┌────────────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATOR                                    │
│  Context: ~10K tokens                                                   │
│  Reads: manifest.json, state files                                      │
│  Writes: manifest.json                                                  │
│  Never reads: Source code, skill outputs                                │
└────────────────────────────────────────────────────────────────────────┘
                    │               │               │
         ┌──────────┘               │               └──────────┐
         ▼                          ▼                          ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ FRAMEWORK AGENT  │    │ FRAMEWORK AGENT  │    │ FRAMEWORK AGENT  │
│ Context: ~70K    │    │ Context: ~70K    │    │ Context: ~70K    │
│──────────────────│    │──────────────────│    │──────────────────│
│ Reads:           │    │                  │    │                  │
│ - codebase-map   │    │                  │    │                  │
│ - skill outputs  │    │                  │    │                  │
│ Writes:          │    │                  │    │                  │
│ - summary.md     │    │                  │    │                  │
│ - state file     │    │                  │    │                  │
│ Never reads:     │    │                  │    │                  │
│ - Source code    │    │                  │    │                  │
└──────────────────┘    └──────────────────┘    └──────────────────┘
         │
         ├── Spawns skill agents (parallel)
         ▼
┌──────────────────────────────────────────────────────────────────┐
│                    SKILL AGENTS (per skill)                       │
│  Context: ~45K tokens each                                        │
├──────────────────┬──────────────────┬──────────────────┬─────────┤
│ data-substrate   │ execution-engine │ control-loop     │ ...     │
│──────────────────│──────────────────│──────────────────│─────────│
│ Reads:           │ Reads:           │ Reads:           │         │
│ - codebase-map   │ - codebase-map   │ - codebase-map   │         │
│   (key_files)    │   (key_files)    │   (key_files)    │         │
│ - types.py       │ - runner.py      │ - agent.py       │         │
│ - models.py      │ - executor.py    │ - loop.py        │         │
│                  │                  │                  │         │
│ Writes:          │ Writes:          │ Writes:          │         │
│ - output .md     │ - output .md     │ - output .md     │         │
│                  │                  │                  │         │
│ Exits after write│                  │                  │         │
└──────────────────┴──────────────────┴──────────────────┴─────────┘
         │
         ▼ (after all frameworks complete)
┌────────────────────────────────────────────────────────────────────────┐
│                       SYNTHESIS AGENT                                   │
│  Context: ~80K tokens                                                   │
│  Reads: summary.md files, selective skill outputs                       │
│  Writes: synthesis/*.md                                                 │
│  Never reads: Source code, full codebase-map                           │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Context Engineering Principles

1. **Skill agents are ephemeral** — Read targeted files, write output, exit immediately
2. **Framework agents never see source code** — Only structural map + skill outputs
3. **Outputs are compression artifacts** — Each tier writes summaries for the tier above
4. **Parallel execution = parallel context isolation** — Agents don't share context
5. **File system is the coordination bus** — Agents communicate via files, not shared memory

### Context Budget Analysis

| Agent | Context Budget | Sources |
|-------|---------------|---------|
| Orchestrator | ~10K | Instructions, manifest, state files |
| Framework Agent | ~70K | Instructions, codebase-map, 9 skill outputs (~5K each) |
| Skill Agent | ~45K | Instructions, codebase-map (partial), target source files |
| Synthesis Agent | ~80K | Instructions, summaries, selective skill outputs |

---

## Directory Structure

```
agent_framework_study/
│
├── repos/                            # INPUT: Clone target frameworks here
│   ├── langchain/
│   ├── autogen/
│   └── crewai/
│
├── forensics-output/                 # WORKING: Intermediate analysis
│   ├── .state/                       # Orchestration state tracking
│   │   ├── manifest.json             # Framework list, overall status
│   │   └── {framework}.state.json    # Per-framework completion state
│   │
│   └── frameworks/
│       └── {framework-name}/
│           ├── codebase-map.json     # Structural analysis (JSON)
│           ├── phase1/
│           │   ├── data-substrate.md
│           │   ├── execution-engine.md
│           │   ├── component-model.md
│           │   └── resilience.md
│           └── phase2/
│               ├── control-loop.md
│               ├── memory.md
│               ├── tool-interface.md
│               └── multi-agent.md
│
└── reports/                          # OUTPUT: Final deliverables
    ├── frameworks/
    │   ├── langchain.md              # Framework summary report
    │   ├── autogen.md
    │   └── crewai.md
    └── synthesis/
        ├── comparison-matrix.md
        ├── antipatterns.md
        ├── reference-architecture.md
        └── executive-summary.md
```

---

## State File Schemas

### manifest.json

```json
{
  "created_at": "2025-12-23T10:00:00Z",
  "frameworks": ["langchain", "autogen", "crewai"],
  "status": "in_progress",
  "completed": ["langchain"],
  "failed": [],
  "pending": ["autogen", "crewai"]
}
```

### {framework}.state.json

```json
{
  "name": "langchain",
  "source_path": "/path/to/langchain",
  "status": "complete",
  "started_at": "2025-12-23T10:00:00Z",
  "completed_at": "2025-12-23T10:15:00Z",
  "phases": {
    "codebase_mapping": {"status": "complete", "output": "codebase-map.json"},
    "phase1": {
      "data_substrate": {"status": "complete"},
      "execution_engine": {"status": "complete"},
      "component_model": {"status": "complete"},
      "resilience": {"status": "complete"}
    },
    "phase2": {
      "control_loop": {"status": "complete"},
      "memory": {"status": "complete"},
      "tool_interface": {"status": "complete"},
      "multi_agent": {"status": "skipped", "reason": "single-agent framework"}
    }
  },
  "error": null
}
```

---

## Usage

```bash
# 1. Clone frameworks to analyze into repos/
git clone https://github.com/langchain-ai/langchain repos/langchain
git clone https://github.com/microsoft/autogen repos/autogen

# 2. Run the analysis command
/analyze-frameworks
```

The command auto-discovers all subdirectories in `repos/` and analyzes each as a framework.

Defined in: `.claude/commands/analyze-frameworks.md`

---

## Prompt Building

Each agent receives its context via **prompt building scripts** that embed all necessary information directly into the prompt. This guarantees context delivery rather than relying on agents to read reference files.

### How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  python scripts/agents/framework_agent.py langchain repos/...   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Reads: references/framework-agent.md                           │
│  Reads: (any other needed context)                              │
│  Injects: framework_name, source_path, output_dir               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Outputs: Complete prompt with embedded context                  │
│           Ready to use with Task tool                           │
└─────────────────────────────────────────────────────────────────┘
```

### Scripts

| Script | Embeds | Arguments |
|--------|--------|-----------|
| `orchestrator.py` | orchestrator-agent.md | (none) |
| `framework_agent.py` | framework-agent.md | name, source, output |
| `skill_agent.py` | skill-agent.md + SKILL.md + phase ref | skill, framework, map, output |
| `synthesis_agent.py` | synthesis-agent.md | framework list |

### Benefit

Context is **guaranteed** in every agent prompt. No reliance on agents following "read this file first" instructions.

---

## Agent Responsibilities

### Orchestrator

**Trigger**: `/analyze-frameworks [paths...]` or "Analyze [framework1], [framework2], ..."

**Responsibilities**:
- Parse framework list from user input
- Create `forensics-output/` directory structure
- Write `manifest.json` with framework list
- Delegate framework analysis (one agent per framework, parallel)
- Monitor completion via state files
- Trigger synthesis when frameworks complete

**Context Boundaries**:
- Reads: manifest.json, state files only
- Never reads: source code, skill outputs

**Prompt**: Generated by `scripts/agents/orchestrator.py`

---

### Framework Agent

**Inputs**: Framework name, source path, output directory

**Responsibilities**:
- Run codebase mapping, write `forensics-output/frameworks/{name}/codebase-map.json`
- Delegate skill execution (one agent per skill, parallel within phase)
- Phase 1 skills: data-substrate, execution-engine, component-model, resilience
- Phase 2 skills: control-loop, memory, tool-interface, multi-agent
- Synthesize skill outputs into `reports/frameworks/{name}.md`
- Update state file on completion

**Context Boundaries**:
- Reads: codebase-map.json, skill outputs
- Writes to: forensics-output (working), reports (final)
- Never reads: source code directly (delegates to skill agents)

**Prompt**: Generated by `scripts/agents/framework_agent.py`

---

### Skill Agent

**Inputs**: Skill name, framework path, codebase-map path, output path

**Responsibilities**:
- Load minimal context from codebase-map (key_files only)
- Read ONLY files relevant to the skill's focus area
- Execute analysis per skill instructions
- Write structured output to designated path
- Exit immediately after writing (ephemeral)

**File Focus Map**:

| Skill | key_files category | Typical files |
|-------|-------------------|---------------|
| data-substrate | types | types.py, schema.py, models.py |
| execution-engine | execution | runner.py, executor.py, engine.py |
| component-model | agents + tools | base_*.py, interfaces.py |
| resilience | execution | Error handling patterns |
| control-loop | agents | agent.py, loop.py |
| memory | (search) | memory.py, context.py |
| tool-interface | tools | tool.py, functions.py |
| multi-agent | agents | orchestrator.py, router.py |

**Prompt**: Generated by `scripts/agents/skill_agent.py` (embeds skill definition + phase reference)

---

### Synthesis Agent

**Inputs**: Output directory path

**Responsibilities**:
- Read framework summaries from `reports/frameworks/*.md`
- Selectively load skill outputs for cross-framework comparison
- Generate `reports/synthesis/comparison-matrix.md`
- Generate `reports/synthesis/antipatterns.md`
- Generate `reports/synthesis/reference-architecture.md`
- Generate `reports/synthesis/executive-summary.md`

**Context Boundaries**:
- Reads: reports/frameworks/*.md, selective skill outputs from forensics-output
- Writes to: reports/synthesis/
- Never reads: source code, full codebase-map.json

**Prompt**: Generated by `scripts/agents/synthesis_agent.py`

---

## Skill Output Template

Each skill agent should produce consistent output for aggregation:

```markdown
# {Skill Name} Analysis: {Framework Name}

## Summary
- **Key Finding 1**: Brief description
- **Key Finding 2**: Brief description
- **Classification**: {Pattern type if applicable}

## Detailed Analysis

### {Subsection 1}
{Analysis with code references in format `file_path:line_number`}

### {Subsection 2}
{Analysis}

## Code References
- `path/to/file.py:42` - Description of what's at this location

## Implications for New Framework
- {Recommendation 1}
- {Recommendation 2}

## Anti-patterns Observed
- {Anti-pattern if any, or "None observed"}
```

---

## Implementation Checklist

### Documentation
| Component | File | Status |
|-----------|------|--------|
| Architecture doc | `docs/ARCHITECTURE.md` | Created |
| Slash command | `.claude/commands/analyze-frameworks.md` | Created |
| Orchestrator context | `.claude/skills/architectural-forensics/references/orchestrator-agent.md` | Created |
| Framework Agent context | `.claude/skills/architectural-forensics/references/framework-agent.md` | Created |
| Skill Agent context | `.claude/skills/architectural-forensics/references/skill-agent.md` | Created |
| Synthesis Agent context | `.claude/skills/architectural-forensics/references/synthesis-agent.md` | Created |
| Master skill | `.claude/skills/architectural-forensics/SKILL.md` | Updated |
| Skill output templates | Individual skill SKILL.md files | To update |
| State file schemas | Documented above | Done |

### Prompt Building Scripts
| Script | Purpose | Status |
|--------|---------|--------|
| `scripts/agents/orchestrator.py` | Builds orchestrator prompt with context | Created |
| `scripts/agents/framework_agent.py` | Builds framework agent prompt with context | Created |
| `scripts/agents/skill_agent.py` | Builds skill agent prompt with context + skill definition | Created |
| `scripts/agents/synthesis_agent.py` | Builds synthesis agent prompt with context | Created |
| `.claude/skills/codebase-mapping/scripts/map_codebase.py` | Codebase mapping utility | Exists |

### Principle
- **Skills** (`.claude/skills/`) define WHAT to analyze (domain knowledge, patterns, outputs)
- **Context docs** (`references/*.md`) define WHO each agent is and their boundaries
- **Prompt scripts** (`scripts/agents/`) guarantee context is embedded in every agent prompt

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Task agents may not follow protocols precisely | Add explicit output contracts to each skill |
| Large frameworks may timeout | Add progress checkpoints within framework agent |
| Synthesis quality depends on consistent outputs | Enforce output templates, validate before synthesis |
| Parallel agents may conflict on writes | Each agent writes only to its own directory |
| Context overflow in skill agents | File focus map limits what each skill reads |

---

## Future Enhancements

- [ ] Add progress reporting during long-running analysis
- [ ] Support incremental analysis (add frameworks to existing study)
- [ ] Interactive mode for exploring specific findings
- [ ] Export to other formats (JSON, HTML report)
