#!/usr/bin/env python3
"""
Build complete Orchestrator prompt with context embedded.

Usage:
    python scripts/agents/orchestrator.py

Outputs the full prompt to stdout. This is used by the /analyze-frameworks command.
"""

from pathlib import Path


def build_prompt() -> str:
    project_root = Path(__file__).parent.parent.parent

    context_file = project_root / ".claude/skills/architectural-forensics/references/orchestrator-agent.md"
    context = context_file.read_text()

    return f"""{context}

---

## Execute Now

### Step 1: Discover Frameworks

Scan the `repos/` directory for subdirectories. Each subdirectory is a framework to analyze.

```bash
ls -d repos/*/
```

If `repos/` is empty or missing, report error and exit.

### Step 2: Initialize

Create the output directory structure:

```bash
mkdir -p forensics-output/.state
mkdir -p reports/frameworks reports/synthesis
```

Write `forensics-output/.state/manifest.json` with the discovered frameworks.

### Step 3: Analyze Frameworks (Parallel)

For each framework, generate the prompt and spawn an agent:

```bash
python scripts/agents/framework_agent.py <framework_name> repos/<framework_name> forensics-output/frameworks/<framework_name>
```

Use the output as the prompt for a Task tool call with:
- `subagent_type`: "general-purpose"
- `run_in_background`: true

### Step 4: Monitor Completion

Wait for all framework agents using TaskOutput.
Update manifest.json as frameworks complete or fail.

### Step 5: Synthesize (if 2+ completed)

Generate the synthesis prompt:

```bash
python scripts/agents/synthesis_agent.py <framework1> <framework2> ...
```

Use the output as the prompt for the Synthesis Agent Task.

### Step 6: Report

Update manifest.json with final status.
Report completion to user with paths to reports.
"""


def main():
    print(build_prompt())


if __name__ == "__main__":
    main()
