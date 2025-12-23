#!/usr/bin/env python3
"""
Build complete Framework Agent prompt with context embedded.

Usage:
    python scripts/agents/framework_agent.py <framework_name> <source_path> <output_dir>

Outputs the full prompt to stdout for use with Task tool.
"""

import sys
from pathlib import Path


def build_prompt(framework_name: str, source_path: str, output_dir: str) -> str:
    project_root = Path(__file__).parent.parent.parent

    context_file = project_root / ".claude/skills/architectural-forensics/references/framework-agent.md"
    context = context_file.read_text()

    return f"""{context}

---

## Your Assignment

**Framework**: {framework_name}
**Source Path**: {source_path}
**Output Directory**: {output_dir}

Execute the workflow described above. Remember:
- Run codebase mapping first
- Spawn Skill Agents for all analysis (do not read source code yourself)
- Write your summary to `reports/frameworks/{framework_name}.md`
- Update state file when complete
"""


def main():
    if len(sys.argv) != 4:
        print("Usage: python framework_agent.py <framework_name> <source_path> <output_dir>", file=sys.stderr)
        sys.exit(1)

    framework_name = sys.argv[1]
    source_path = sys.argv[2]
    output_dir = sys.argv[3]

    print(build_prompt(framework_name, source_path, output_dir))


if __name__ == "__main__":
    main()
