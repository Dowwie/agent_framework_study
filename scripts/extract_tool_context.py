#!/usr/bin/env python3
"""
Extract tool-interface-relevant context from existing analyses into lean summary files.

Usage:
    python scripts/extract_tool_context.py [framework]  # Single framework
    python scripts/extract_tool_context.py              # All frameworks

Output:
    forensics-output/frameworks/{framework}/tool-context.md (~60-100 lines)
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
REPOS_DIR = PROJECT_ROOT / "repos"
REPORTS_DIR = PROJECT_ROOT / "reports/frameworks"
FORENSICS_DIR = PROJECT_ROOT / "forensics-output/frameworks"

TOOL_FILE_PATTERNS = [
    r"tool", r"function", r"callable", r"action", r"skill",
    r"schema", r"registry", r"register", r"executor", r"runner",
    r"builtin", r"default", r"error", r"exception", r"validation",
    r"pydantic", r"parameter", r"argument"
]

FRAMEWORKS = [
    "agent-zero", "agno", "autogen", "aws-strands", "camel", "crewAI",
    "google-adk", "langgraph", "llama_index", "MetaGPT", "ms-agent-framework",
    "openai-agents-python", "pydantic-ai", "swarm"
]


def walk_file_tree(node: dict, files: list[str]):
    """Recursively walk file tree and collect file paths."""
    if node.get("type") == "file":
        files.append(node.get("path", ""))
    for child in node.get("children", []):
        walk_file_tree(child, files)


def extract_tool_files_from_map(codebase_map: dict) -> list[str]:
    """Extract only tool-relevant files from codebase map."""
    pattern = re.compile("|".join(TOOL_FILE_PATTERNS), re.IGNORECASE)

    all_files = []
    file_tree = codebase_map.get("file_tree", {})
    walk_file_tree(file_tree, all_files)

    tool_files = [f for f in all_files if pattern.search(f) and f.endswith(".py")]

    prioritized = []
    secondary = []
    for f in tool_files:
        lower = f.lower()
        if "tool" in lower or "function" in lower or "schema" in lower:
            prioritized.append(f)
        else:
            secondary.append(f)

    return sorted(prioritized)[:20] + sorted(secondary)[:15]


def extract_section(content: str, header: str) -> str:
    """Extract a section from markdown by header."""
    pattern = rf"^#+\s*{re.escape(header)}.*?$(.*?)(?=^#+\s|\Z)"
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def extract_from_report(report_path: Path) -> dict:
    """Extract tool-relevant info from framework report."""
    if not report_path.exists():
        return {}

    content = report_path.read_text()

    extracted = {
        "overview": "",
        "tool_interface": "",
        "schema": "",
        "error_handling": ""
    }

    overview = extract_section(content, "Overview")
    if overview:
        lines = overview.split("\n")[:10]
        extracted["overview"] = "\n".join(lines)

    tool_section = extract_section(content, "Tool")
    if tool_section:
        lines = tool_section.split("\n")[:12]
        extracted["tool_interface"] = "\n".join(lines)

    schema_section = extract_section(content, "Schema")
    if schema_section:
        lines = schema_section.split("\n")[:8]
        extracted["schema"] = "\n".join(lines)

    error_matches = re.findall(
        r"^.*(?:error|exception|retry|validation).*$",
        content,
        re.MULTILINE | re.IGNORECASE
    )
    if error_matches:
        extracted["error_handling"] = "\n".join(error_matches[:5])

    return extracted


def extract_from_existing_analysis(analysis_path: Path) -> dict:
    """Extract info from existing tool-interface-analysis if present."""
    if not analysis_path.exists():
        return {}

    content = analysis_path.read_text()

    extracted = {
        "modeling": "",
        "registration": "",
        "builtin_tools": ""
    }

    modeling = extract_section(content, "Tool Modeling")
    if modeling:
        lines = modeling.split("\n")[:10]
        extracted["modeling"] = "\n".join(lines)

    registration = extract_section(content, "Registration")
    if registration:
        lines = registration.split("\n")[:8]
        extracted["registration"] = "\n".join(lines)

    builtin = extract_section(content, "Built-in")
    if builtin:
        lines = builtin.split("\n")[:10]
        extracted["builtin_tools"] = "\n".join(lines)

    return extracted


def generate_tool_context(framework: str) -> str:
    """Generate compact tool context for a framework."""
    framework_dir = FORENSICS_DIR / framework

    map_path = framework_dir / "codebase-map.json"
    codebase_map = {}
    if map_path.exists():
        codebase_map = json.loads(map_path.read_text())

    tool_files = extract_tool_files_from_map(codebase_map)

    report_info = extract_from_report(REPORTS_DIR / f"{framework}.md")
    existing_analysis = extract_from_existing_analysis(
        framework_dir / "phase2" / "tool-interface-analysis.md"
    )

    lines = [
        f"# Tool Interface Context: {framework}",
        "",
        "## Quick Facts",
        ""
    ]

    if report_info.get("overview"):
        lines.append(report_info["overview"])
        lines.append("")

    if report_info.get("tool_interface"):
        lines.append("### Tool Interface Overview")
        lines.append(report_info["tool_interface"])
        lines.append("")

    if existing_analysis.get("modeling"):
        lines.append("### Tool Modeling (from previous analysis)")
        lines.append(existing_analysis["modeling"])
        lines.append("")

    if report_info.get("schema"):
        lines.append("### Schema Generation")
        lines.append(report_info["schema"])
        lines.append("")

    if existing_analysis.get("builtin_tools"):
        lines.append("### Built-in Tools")
        lines.append(existing_analysis["builtin_tools"])
        lines.append("")

    if report_info.get("error_handling"):
        lines.append("### Error Handling Mentions")
        lines.append(report_info["error_handling"])
        lines.append("")

    lines.append("## Tool-Relevant Files")
    lines.append("")
    lines.append("Priority files for tool interface analysis:")
    lines.append("")

    if tool_files:
        for f in tool_files:
            lines.append(f"- `{f}`")
    else:
        lines.append("- (no files matched tool patterns - examine codebase manually)")
        lines.append("")
        lines.append("Try searching for:")
        lines.append("- Base tool/function classes")
        lines.append("- Tool registration code")
        lines.append("- Schema generation utilities")
        lines.append("- Built-in/default tools directory")

    lines.append("")
    lines.append("## Analysis Focus")
    lines.append("")
    lines.append("When analyzing this framework for tool interface, determine:")
    lines.append("1. Tool modeling (base class, protocol, decorated function, Pydantic)")
    lines.append("2. Schema generation method (introspection, Pydantic, decorator, manual)")
    lines.append("3. Built-in tool inventory (categories and count)")
    lines.append("4. Registration pattern (declarative, registry, discovery, factory)")
    lines.append("5. Execution flow (validation, invocation, error feedback)")
    lines.append("6. Retry/self-correction mechanisms")
    lines.append("7. Parallel execution support")

    return "\n".join(lines)


def main():
    if len(sys.argv) > 1:
        frameworks = [sys.argv[1]]
    else:
        frameworks = FRAMEWORKS

    for framework in frameworks:
        print(f"Extracting tool context for {framework}...")

        context = generate_tool_context(framework)

        output_dir = FORENSICS_DIR / framework
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / "tool-context.md"
        output_path.write_text(context)

        line_count = len(context.split("\n"))
        print(f"  -> {output_path} ({line_count} lines)")

    print("\nDone. Tool context files ready.")


if __name__ == "__main__":
    main()
