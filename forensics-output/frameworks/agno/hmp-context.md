# HMP Context: agno

## Quick Facts

- **Repository**: agno
- **Primary language**: Python
- **Architecture style**: Modular monolith with plugin-based extensibility
- **Core abstraction**: Agent/Team/Workflow as unified execution primitives
- **Philosophy**: Configuration-heavy, feature-rich, batteries-included

### Async/Streaming Model
**Decision**: Separate sync and async code paths (128 sync methods, 56 async methods in Agent)

**Tradeoffs**:
- **Pros**: Maximum flexibility, no forced async
- **Cons**: Code duplication risk, maintenance burden, 184 total methods

**Evidence**:
- Agent has both `run()` and `arun()`, `_reason()` and `_areason()`, etc.

### Streaming Mentions
- Iterator and AsyncIterator for streaming

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `cookbook/02_examples/01_agents/pydantic_model_as_input.py`
- `cookbook/02_examples/03_workflows/company_analysis/models.py`
- `cookbook/02_examples/03_workflows/employee_recruiter_async_stream.py`
- `cookbook/02_examples/03_workflows/investment_analyst/models.py`
- `cookbook/02_examples/04_gemini/__init__.py`
- `cookbook/02_examples/04_gemini/agents/__init__.py`
- `cookbook/02_examples/04_gemini/agents/creative_studio_agent.py`
- `cookbook/02_examples/04_gemini/agents/db.py`
- `cookbook/02_examples/04_gemini/agents/pal_agent.py`
- `cookbook/02_examples/04_gemini/agents/product_comparison_agent.py`
- `cookbook/02_examples/04_gemini/agents/self_learning_agent.py`
- `cookbook/02_examples/04_gemini/agents/self_learning_research_agent.py`
- `cookbook/02_examples/04_gemini/agents/simple_research_agent.py`
- `cookbook/02_examples/04_gemini/db.py`
- `cookbook/02_examples/04_gemini/run.py`
- `cookbook/02_examples/05_streamlit_apps/agentic_rag/agentic_rag.py`
- `cookbook/02_examples/05_streamlit_apps/agentic_rag/app.py`
- `cookbook/02_examples/05_streamlit_apps/chess_team/agents.py`
- `cookbook/02_examples/05_streamlit_apps/chess_team/app.py`
- `cookbook/02_examples/05_streamlit_apps/deep_researcher/agents.py`
- `cookbook/02_examples/05_streamlit_apps/deep_researcher/app.py`
- `cookbook/02_examples/05_streamlit_apps/gemini_tutor/agents.py`
- `cookbook/02_examples/05_streamlit_apps/gemini_tutor/app.py`
- `cookbook/02_examples/05_streamlit_apps/geobuddy/agents.py`
- `cookbook/02_examples/05_streamlit_apps/geobuddy/app.py`
- `cookbook/02_examples/05_streamlit_apps/github_mcp_agent/__init__.py`
- `cookbook/02_examples/05_streamlit_apps/github_mcp_agent/agents.py`
- `cookbook/02_examples/05_streamlit_apps/github_mcp_agent/app.py`
- `cookbook/02_examples/05_streamlit_apps/github_repo_analyzer/agents.py`
- `cookbook/02_examples/05_streamlit_apps/github_repo_analyzer/app.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy