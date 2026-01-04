# Analyze Harness-Model Protocol Across All Frameworks

Run the `harness-model-protocol` skill across all framework repositories using pre-extracted lean context.

## Prerequisites

Generate context summaries first:
```bash
python scripts/extract_hmp_context.py
```

This creates `forensics-output/frameworks/{framework}/hmp-context.md` (~60-80 lines each).

## Frameworks

```
agent-zero, agno, autogen, aws-strands, camel, crewAI, google-adk,
langgraph, llama_index, MetaGPT, ms-agent-framework, openai-agents-python,
pydantic-ai, swarm
```

## Execution Strategy

For each framework, spawn a background agent that:

1. **Reads lean context** (~60-80 lines):
   - `forensics-output/frameworks/{framework}/hmp-context.md`

2. **Reads identified HMP files** from the context (listed in the file)

3. **Writes output** to:
   ```
   forensics-output/frameworks/{framework}/phase2/harness-model-protocol.md
   ```

## Agent Prompt Template

For each framework, use the Task tool with `subagent_type: general-purpose`:

```
You are analyzing the harness-model protocol for {FRAMEWORK}.

## Context (READ THIS FIRST)

Read: forensics-output/frameworks/{FRAMEWORK}/hmp-context.md

This file contains:
- Framework overview and streaming model
- List of HMP-relevant files to examine
- Analysis focus areas

## Your Task

1. Read the hmp-context.md file
2. Read the HMP-relevant files listed in it (in repos/{FRAMEWORK}/)
3. Analyze the harness-model protocol layer
4. Write analysis to: forensics-output/frameworks/{FRAMEWORK}/phase2/harness-model-protocol.md

## Output Format

# Harness-Model Protocol Analysis: {FRAMEWORK}

## Summary
- **Key Finding 1**: ...
- **Key Finding 2**: ...
- **Classification**: ...

## Detailed Analysis

### Message Protocol
- Wire format family
- Providers supported
- Abstraction strategy

### Tool Call Encoding
- Request method
- Response parsing
- Tool choice support

### Streaming Implementation
- Protocol type
- Partial tool call handling

### Agentic Primitives
- System prompt assembly
- Scratchpad/HITL mechanisms

### Provider Abstraction
- Provider matrix
- Graceful degradation

## Code References
## Implications for New Framework
## Anti-Patterns Observed
```

## Parallel Execution

Launch in batches of 4-5:

**Batch 1**: langgraph, pydantic-ai, google-adk, openai-agents-python
**Batch 2**: autogen, crewAI, camel, MetaGPT
**Batch 3**: aws-strands, llama_index, agno, ms-agent-framework
**Batch 4**: agent-zero, swarm

## Quick Start

```bash
# 1. Generate lean context files
python scripts/extract_hmp_context.py

# 2. Run analysis
# Tell Claude: "Run /analyze-hmp"
```

## Context Budget

| Input | Lines |
|-------|-------|
| hmp-context.md | ~70 |
| 5-10 source files | ~500-1000 |
| **Total per agent** | **~600-1100** |

vs. previous approach: ~2000+ lines per agent
