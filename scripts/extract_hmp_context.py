#!/usr/bin/env python3
"""
Extract HMP-relevant context from existing analyses into lean summary files.

Usage:
    python scripts/extract_hmp_context.py [framework]  # Single framework
    python scripts/extract_hmp_context.py              # All frameworks

Output:
    forensics-output/frameworks/{framework}/hmp-context.md (~50-100 lines)
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
REPOS_DIR = PROJECT_ROOT / "repos"
REPORTS_DIR = PROJECT_ROOT / "reports/frameworks"
FORENSICS_DIR = PROJECT_ROOT / "forensics-output/frameworks"

HMP_FILE_PATTERNS = [
    r"llm", r"model", r"openai", r"anthropic", r"gemini", r"claude",
    r"stream", r"message", r"chat", r"adapter", r"provider", r"client",
    r"request", r"response", r"wire", r"protocol"
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


def extract_hmp_files_from_map(codebase_map: dict) -> list[str]:
    """Extract only HMP-relevant files from codebase map."""
    pattern = re.compile("|".join(HMP_FILE_PATTERNS), re.IGNORECASE)

    all_files = []
    file_tree = codebase_map.get("file_tree", {})
    walk_file_tree(file_tree, all_files)

    hmp_files = [f for f in all_files if pattern.search(f) and f.endswith(".py")]

    return sorted(hmp_files)[:30]  # Cap at 30 most relevant


def extract_section(content: str, header: str) -> str:
    """Extract a section from markdown by header."""
    pattern = rf"^#+\s*{re.escape(header)}.*?$(.*?)(?=^#+\s|\Z)"
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def extract_from_report(report_path: Path) -> dict:
    """Extract HMP-relevant info from framework report."""
    if not report_path.exists():
        return {}

    content = report_path.read_text()

    extracted = {
        "overview": "",
        "async_model": "",
        "tool_interface": "",
        "streaming": ""
    }

    # Extract overview (first ~10 lines after ## Overview)
    overview = extract_section(content, "Overview")
    if overview:
        lines = overview.split("\n")[:10]
        extracted["overview"] = "\n".join(lines)

    # Look for async/streaming mentions
    async_section = extract_section(content, "Async Model")
    if async_section:
        lines = async_section.split("\n")[:8]
        extracted["async_model"] = "\n".join(lines)

    # Tool interface
    tool_section = extract_section(content, "Tool Interface")
    if tool_section:
        lines = tool_section.split("\n")[:8]
        extracted["tool_interface"] = "\n".join(lines)

    # Look for streaming mentions anywhere
    streaming_matches = re.findall(r"^.*stream.*$", content, re.MULTILINE | re.IGNORECASE)
    if streaming_matches:
        extracted["streaming"] = "\n".join(streaming_matches[:5])

    return extracted


def extract_from_tool_interface(analysis_path: Path) -> dict:
    """Extract HMP-relevant info from tool-interface-analysis."""
    if not analysis_path.exists():
        return {}

    content = analysis_path.read_text()

    extracted = {
        "schema_generation": "",
        "registration": ""
    }

    # Schema generation method
    schema_section = extract_section(content, "Schema Generation")
    if schema_section:
        lines = schema_section.split("\n")[:6]
        extracted["schema_generation"] = "\n".join(lines)

    # Registration pattern
    reg_section = extract_section(content, "Registration")
    if reg_section:
        lines = reg_section.split("\n")[:6]
        extracted["registration"] = "\n".join(lines)

    return extracted


def generate_hmp_context(framework: str) -> str:
    """Generate compact HMP context for a framework."""
    framework_dir = FORENSICS_DIR / framework

    # Load codebase map
    map_path = framework_dir / "codebase-map.json"
    codebase_map = {}
    if map_path.exists():
        codebase_map = json.loads(map_path.read_text())

    # Extract HMP-relevant files
    hmp_files = extract_hmp_files_from_map(codebase_map)

    # Extract from existing analyses
    report_info = extract_from_report(REPORTS_DIR / f"{framework}.md")
    tool_info = extract_from_tool_interface(
        framework_dir / "phase2" / "tool-interface-analysis.md"
    )

    # Build compact context
    lines = [
        f"# HMP Context: {framework}",
        "",
        "## Quick Facts",
        ""
    ]

    if report_info.get("overview"):
        lines.append(report_info["overview"])
        lines.append("")

    if report_info.get("async_model"):
        lines.append("### Async/Streaming Model")
        lines.append(report_info["async_model"])
        lines.append("")

    if tool_info.get("schema_generation"):
        lines.append("### Schema Generation (from tool-interface-analysis)")
        lines.append(tool_info["schema_generation"])
        lines.append("")

    if report_info.get("streaming"):
        lines.append("### Streaming Mentions")
        lines.append(report_info["streaming"])
        lines.append("")

    # Key files to examine
    lines.append("## HMP-Relevant Files")
    lines.append("")
    lines.append("Priority files for harness-model protocol analysis:")
    lines.append("")
    for f in hmp_files:
        lines.append(f"- `{f}`")

    if not hmp_files:
        lines.append("- (no files matched HMP patterns - examine codebase manually)")

    lines.append("")
    lines.append("## Analysis Focus")
    lines.append("")
    lines.append("When analyzing this framework for HMP, determine:")
    lines.append("1. Wire format family (OpenAI-compatible, Anthropic, custom)")
    lines.append("2. Tool call encoding (function calling API vs prompt injection)")
    lines.append("3. Streaming protocol (SSE events, partial tool calls)")
    lines.append("4. Agentic primitives (scratchpad, interrupt, HITL)")
    lines.append("5. Provider abstraction strategy")

    return "\n".join(lines)


def main():
    if len(sys.argv) > 1:
        frameworks = [sys.argv[1]]
    else:
        frameworks = FRAMEWORKS

    for framework in frameworks:
        print(f"Extracting HMP context for {framework}...")

        context = generate_hmp_context(framework)

        output_dir = FORENSICS_DIR / framework
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / "hmp-context.md"
        output_path.write_text(context)

        line_count = len(context.split("\n"))
        print(f"  → {output_path} ({line_count} lines)")

    print("\nDone. HMP context files ready.")


if __name__ == "__main__":
    main()
