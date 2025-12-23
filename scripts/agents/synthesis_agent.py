#!/usr/bin/env python3
"""
Build complete Synthesis Agent prompt with context embedded.

Usage:
    python scripts/agents/synthesis_agent.py [framework1] [framework2] ...

Outputs the full prompt to stdout for use with Task tool.
"""

import sys
from pathlib import Path


def build_prompt(frameworks: list[str]) -> str:
    project_root = Path(__file__).parent.parent.parent

    context_file = project_root / ".claude/skills/architectural-forensics/references/synthesis-agent.md"
    context = context_file.read_text()

    framework_list = "\n".join(f"- {fw}" for fw in frameworks)

    return f"""{context}

---

## Your Assignment

**Frameworks to synthesize**:
{framework_list}

**Framework summaries location**: `reports/frameworks/`
**Skill outputs location**: `forensics-output/frameworks/`
**Output location**: `reports/synthesis/`

---

## Execute Now

1. Read all framework summaries from `reports/frameworks/*.md`
2. Generate `reports/synthesis/comparison-matrix.md`
3. Generate `reports/synthesis/antipatterns.md`
4. Generate `reports/synthesis/reference-architecture.md`
5. Generate `reports/synthesis/executive-summary.md`

Follow the output structures defined in your context above.
"""


def main():
    if len(sys.argv) < 2:
        print("Usage: python synthesis_agent.py <framework1> [framework2] ...", file=sys.stderr)
        sys.exit(1)

    frameworks = sys.argv[1:]
    print(build_prompt(frameworks))


if __name__ == "__main__":
    main()
