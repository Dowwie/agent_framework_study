# Analyze Tool Interface Across All Frameworks

Run the `tool-interface-analysis` skill across all framework repositories using pre-extracted lean context.

## Prerequisites

Generate context summaries first:
```bash
python scripts/extract_tool_context.py
```

This creates `forensics-output/frameworks/{framework}/tool-context.md` (~60-100 lines each).

## Frameworks

```
agent-zero, agno, autogen, aws-strands, camel, crewAI, google-adk,
langgraph, llama_index, MetaGPT, ms-agent-framework, openai-agents-python,
pydantic-ai, swarm
```

## Execution Strategy

For each framework, spawn a background agent that:

1. **Reads lean context** (~60-100 lines):
   - `forensics-output/frameworks/{framework}/tool-context.md`

2. **Reads identified tool files** from the context (listed in the file)

3. **Writes output** to:
   ```
   forensics-output/frameworks/{framework}/phase2/tool-interface-analysis.md
   ```

## Agent Prompt Template

For each framework, use the Task tool with `subagent_type: general-purpose`:

```
You are analyzing the tool interface layer for {FRAMEWORK}.

## Context (READ THIS FIRST)

Read: forensics-output/frameworks/{FRAMEWORK}/tool-context.md

This file contains:
- Framework overview and tool modeling approach
- List of tool-relevant files to examine
- Analysis focus areas

## Your Task

1. Read the tool-context.md file
2. Read the tool-relevant files listed in it (in repos/{FRAMEWORK}/)
3. Analyze the tool interface layer following the skill template
4. Write analysis to: forensics-output/frameworks/{FRAMEWORK}/phase2/tool-interface-analysis.md

## Analysis Focus

Examine each of these dimensions:

### 1. Tool Modeling
- How is a "tool" represented? (base class, protocol, decorated function)
- What attributes define a tool? (name, description, parameters, return type)
- What inheritance/composition patterns are used?

### 2. Schema Generation
- How are tool schemas derived? (introspection, Pydantic, decorator, manual)
- Where is the schema generation code?
- What type mappings are used (Python -> JSON Schema)?

### 3. Built-in Inventory
- What tools ship with the framework?
- How are they organized (by category, package)?
- Document at least 5-10 representative tools

### 4. Registration & Discovery
- How are tools registered with the agent?
- Is discovery automatic or explicit?
- Can tools be added/removed dynamically?

### 5. Execution Flow
- How are tools invoked?
- What validation occurs before execution?
- How are errors handled and fed back to the LLM?

### 6. Parallel Execution
- Are concurrent tool calls supported?
- What pattern is used (asyncio, threads, processes)?

## Output Format

# Tool Interface Analysis: {FRAMEWORK}

## Summary
- **Tool Modeling**: [Base class / Protocol / Decorated functions / Pydantic models]
- **Schema Generation**: [Introspection / Pydantic / Decorator / Manual]
- **Registration Pattern**: [Declarative / Registry / Discovery / Factory]
- **Error Handling**: [Silent / Basic / Detailed / Structured]
- **Built-in Tools**: [Count] tools in [N] categories

## Tool Modeling

### Core Abstraction
[Show the core tool type/class/protocol with code]

### Key Attributes
| Attribute | Type | Purpose |
|-----------|------|---------|
| ... | ... | ... |

## Schema Generation

### Method Used
[Describe with code examples]

### Generated Schema Example
[Show example JSON schema output]

## Built-in Tool Inventory

### Categories
| Category | Tools | Purpose |
|----------|-------|---------|
| ... | ... | ... |

### Complete Tool List
| Tool Name | Location | Schema Method | Category |
|-----------|----------|---------------|----------|
| ... | ... | ... | ... |

## Registration & Discovery

### Pattern
[Describe with code]

### Registration Flow
[Show the lifecycle]

## Execution Flow

### Invocation Pattern
[Show with code]

### Error Handling
| Error Type | Handling | Feedback to LLM |
|------------|----------|-----------------|
| ... | ... | ... |

### Retry Mechanisms
[Describe if present]

## Parallel Execution
[Describe if supported]

## Code References
[List key file:line references]

## Implications for New Framework
### Positive Patterns
### Considerations

## Anti-Patterns Observed
[List any concerning patterns]
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
python scripts/extract_tool_context.py

# 2. Run analysis
# Tell Claude: "Run /analyze-tools"
```

## Context Budget

| Input | Lines |
|-------|-------|
| tool-context.md | ~80 |
| 5-15 source files | ~500-1500 |
| **Total per agent** | **~600-1600** |

## Synthesis

After all analyses complete, create:
```
reports/synthesis/tool-interface-synthesis.md
```

Containing:
- Comparison table across all 14 frameworks
- Common patterns identified
- Best practices to adopt
- Anti-patterns to avoid
- Recommendations for new framework design
