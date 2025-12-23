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

### Step 1: Initialize & Auto-Recover State

Invoke the **run_shell_command** tool to initialize the manifest and automatically reset any interrupted jobs from previous sessions:

```bash
python scripts/state_manager.py init && python scripts/state_manager.py reset-running
```
*Note: `reset-running` will detect any frameworks left in `in_progress` state (e.g., from a crash), move them back to `pending`, and clean up their partial output directories to ensure a fresh start.*

### Step 2: Analyze Frameworks (Execution Loop)

You must process frameworks in batches of 2 until finished. For each iteration:

1.  **Check for Work**: Invoke **run_shell_command** to get the next batch:
    ```bash
    python scripts/state_manager.py next --limit 2
    ```
    *   If the output is empty, **STOP** this loop and proceed to **Step 3**.
    *   If the output contains framework names (e.g., `autogen langgraph`), proceed to the next sub-step.

2.  **Mark and Spawn**: For each framework in the batch:
    a. Invoke **run_shell_command** to mark it as `in_progress`:
       ```bash
       python scripts/state_manager.py mark <framework_name> in_progress
       ```
    b. Invoke **run_shell_command** to generate the agent prompt:
       ```bash
       python scripts/agents/framework_agent.py <framework_name> repos/<framework_name> forensics-output/frameworks/<framework_name>
       ```
    c. Use the output prompt to call the **Task** tool (`subagent_type: "general-purpose"`, `run_in_background: true`).

3.  **Monitor Completion**: 
    Wait for the spawned background tasks to finish. Once they are done:
    - Invoke **run_shell_command** to mark each as `completed`:
      ```bash
      python scripts/state_manager.py mark <framework_name> completed
      ```
    - **Return to Sub-step 1** to fetch the next batch.

### Step 3: Synthesis

After the loop finishes, verify all frameworks are analyzed by checking the status:
```bash
python scripts/state_manager.py status
```

Then, generate and execute the synthesis prompt:
```bash
python scripts/agents/synthesis_agent.py $(ls repos/)
```

### Step 4: Final Report

Inform the user that the analysis is complete and provide paths to the generated reports.
"""


def main():
    print(build_prompt())


if __name__ == "__main__":
    main()
