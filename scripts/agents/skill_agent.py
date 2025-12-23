#!/usr/bin/env python3
"""
Build complete Skill Agent prompt with context embedded.

Usage:
    python scripts/agents/skill_agent.py <skill_name> <framework_name> <codebase_map_path> <output_path>

Outputs the full prompt to stdout for use with Task tool.
"""

import sys
from pathlib import Path


def build_prompt(skill_name: str, framework_name: str, codebase_map_path: str, output_path: str) -> str:
    project_root = Path(__file__).parent.parent.parent

    agent_context_file = project_root / ".claude/skills/architectural-forensics/references/skill-agent.md"
    agent_context = agent_context_file.read_text()

    skill_file = project_root / f".claude/skills/{skill_name}/SKILL.md"
    if skill_file.exists():
        skill_content = skill_file.read_text()
    else:
        skill_content = f"[Skill file not found: {skill_file}]"

    phase = "1" if skill_name in ["data-substrate-analysis", "execution-engine-analysis", "component-model-analysis", "resilience-analysis"] else "2"

    phase_ref_file = project_root / f".claude/skills/architectural-forensics/references/phase{phase}-{'engineering' if phase == '1' else 'cognitive'}.md"
    if phase_ref_file.exists():
        phase_reference = phase_ref_file.read_text()
    else:
        phase_reference = ""

    return f"""{agent_context}

---

## Your Assignment

**Skill**: {skill_name}
**Framework**: {framework_name}
**Codebase Map**: {codebase_map_path}
**Output Path**: {output_path}

---

## Skill Definition

{skill_content}

---

## Phase Reference Material

{phase_reference}

---

## Execute Now

1. Read the codebase map at `{codebase_map_path}`
2. Identify and read relevant source files
3. Apply the skill analysis methodology
4. Write your analysis to `{output_path}`
5. Exit immediately after writing
"""


def main():
    if len(sys.argv) != 5:
        print("Usage: python skill_agent.py <skill_name> <framework_name> <codebase_map_path> <output_path>", file=sys.stderr)
        sys.exit(1)

    skill_name = sys.argv[1]
    framework_name = sys.argv[2]
    codebase_map_path = sys.argv[3]
    output_path = sys.argv[4]

    print(build_prompt(skill_name, framework_name, codebase_map_path, output_path))


if __name__ == "__main__":
    main()
