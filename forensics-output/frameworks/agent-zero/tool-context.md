# Tool Interface Context: agent-zero

## Quick Facts

- **Repository**: repos/agent-zero
- **Primary Language**: Python
- **Architecture Style**: Monolithic with extension-based modularity
- **Key Dependencies**: LiteLLM (multi-provider LLM access), LangChain (message handling), FAISS (vector memory), Browser-Use (web automation)
- **Lines of Code**: 205 Python files, 1175 total files

### Tool Interface Overview
**Tool Definition Method**: Class-based with abstract base

```python

### Error Handling Mentions
The framework's design philosophy prioritizes **practical deployment** with features like rate limiting, retry logic, Docker sandboxing, and web UI access. However, this comes at the cost of tight coupling and complex state management.
  - Runtime validation absent
- **Weakness**: Nested loops complex to reason about, intervention mechanism (InterventionException) uses exceptions for control flow
**Error Handling Strategy**: Layered propagation with retry at LLM layer
**Exception Taxonomy**:

## Tool-Relevant Files

Priority files for tool interface analysis:

- `agents/_example/tools/example_tool.py`
- `agents/_example/tools/response.py`
- `prompts/agent.system.tool.call_sub.py`
- `prompts/agent.system.tools.py`
- `python/extensions/hist_add_tool_result/_90_save_tool_call_file.py`
- `python/extensions/tool_execute_after/_10_mask_secrets.py`
- `python/extensions/tool_execute_before/_10_replace_last_tool_output.py`
- `python/extensions/tool_execute_before/_10_unmask_secrets.py`
- `python/helpers/extract_tools.py`
- `python/helpers/tool.py`
- `python/tools/a2a_chat.py`
- `python/tools/behaviour_adjustment.py`
- `python/tools/browser_agent.py`
- `python/tools/call_subordinate.py`
- `python/tools/code_execution_tool.py`
- `python/tools/document_query.py`
- `python/tools/input.py`
- `python/tools/memory_delete.py`
- `python/tools/memory_forget.py`
- `python/tools/memory_load.py`
- `instruments/default/yt_download/download_video.py`
- `python/api/backup_get_defaults.py`
- `python/extensions/error_format/_10_mask_errors.py`
- `python/helpers/errors.py`

## Analysis Focus

When analyzing this framework for tool interface, determine:
1. Tool modeling (base class, protocol, decorated function, Pydantic)
2. Schema generation method (introspection, Pydantic, decorator, manual)
3. Built-in tool inventory (categories and count)
4. Registration pattern (declarative, registry, discovery, factory)
5. Execution flow (validation, invocation, error feedback)
6. Retry/self-correction mechanisms
7. Parallel execution support