# Analyze Agent Frameworks

Run the Architectural Forensics Protocol on all framework repositories found in `repos/`.

## Getting Started

First, generate your complete orchestrator prompt with embedded context:

```bash
python scripts/agents/orchestrator.py
```

Read and execute the output. The prompt includes:
- Your role and mission context
- Step-by-step execution workflow
- Instructions for spawning sub-agents

## How Prompt Building Works

Each agent type has a prompt builder script that embeds all necessary context:

| Agent | Script | Arguments |
|-------|--------|-----------|
| Orchestrator | `scripts/agents/orchestrator.py` | (none) |
| Framework Agent | `scripts/agents/framework_agent.py` | `<name> <source_path> <output_dir>` |
| Skill Agent | `scripts/agents/skill_agent.py` | `<skill> <framework> <map_path> <output_path>` |
| Synthesis Agent | `scripts/agents/synthesis_agent.py` | `<framework1> [framework2] ...` |

When spawning a sub-agent:
1. Run the appropriate script to generate the prompt
2. Use the output as the prompt for the Task tool

## Directory Structure

```
agent_framework_study/
├── repos/                          # INPUT: Clone frameworks here
│   ├── langchain/
│   ├── autogen/
│   └── crewai/
│
├── forensics-output/               # WORKING: Intermediate analysis
│   ├── .state/
│   │   ├── manifest.json
│   │   └── {framework}.state.json
│   └── frameworks/
│       └── {framework}/
│           ├── codebase-map.json
│           ├── phase1/
│           └── phase2/
│
└── reports/                        # OUTPUT: Final deliverables
    ├── frameworks/
    │   ├── langchain.md
    │   ├── autogen.md
    │   └── crewai.md
    └── synthesis/
        ├── comparison-matrix.md
        ├── antipatterns.md
        ├── reference-architecture.md
        └── executive-summary.md
```

## Quick Reference

### Spawning a Framework Agent

```bash
# Generate prompt
python scripts/agents/framework_agent.py langchain repos/langchain forensics-output/frameworks/langchain

# Use output with Task tool (subagent_type: general-purpose, run_in_background: true)
```

### Spawning a Skill Agent

```bash
# Generate prompt
python scripts/agents/skill_agent.py control-loop-extraction langchain forensics-output/frameworks/langchain/codebase-map.json forensics-output/frameworks/langchain/phase2/control-loop.md

# Use output with Task tool (subagent_type: general-purpose, run_in_background: true)
```

### Spawning a Synthesis Agent

```bash
# Generate prompt
python scripts/agents/synthesis_agent.py langchain autogen crewai

# Use output with Task tool (subagent_type: general-purpose)
```
