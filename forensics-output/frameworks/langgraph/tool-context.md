# Tool Interface Context: langgraph

## Quick Facts

- **Repository**: https://github.com/langchain-ai/langgraph
- **Primary language**: Python (with TypeScript SDK)
- **Architecture style**: Modular monorepo (multiple libraries)
- **Core paradigm**: Graph-based workflow orchestration using Bulk Synchronous Parallel (BSP) model

### Tool Interface Overview
- **Schema generation**: Pydantic-based (via LangChain's `@tool` decorator)
- **Registration**: Declarative list passed to `ToolNode` or `create_react_agent`
- **Error feedback**: Detailed (full exception message in `ToolMessage`)
- **Retry**: Node-level retry policy (not per-tool)
- **Tradeoff**: Leverages ecosystem vs bound to LangChain

**Example**:
```python
from langchain_core.tools import tool

@tool
def search(query: str) -> str:

### Error Handling Mentions
#### Error Handling: Layered Propagation with Checkpoints
- **Node errors**: Captured in `PregelTask.error`, execution stops
- **Tool errors**: Configurable (propagate or feed back to LLM as `ToolMessage`)
- **Retry logic**: Per-node `RetryPolicy` with exponential backoff
- **Checkpointing**: State saved even on error, enables recovery

## Tool-Relevant Files

Priority files for tool interface analysis:

- `docs/docs/tutorials/llm-compiler/math_tools.py`
- `libs/cli/generate_schema.py`
- `libs/cli/langgraph_cli/schemas.py`
- `libs/prebuilt/langgraph/prebuilt/tool_node.py`
- `libs/prebuilt/langgraph/prebuilt/tool_validator.py`
- `libs/prebuilt/tests/test_on_tool_call.py`
- `libs/prebuilt/tests/test_tool_node.py`
- `libs/prebuilt/tests/test_tool_node_interceptor_unregistered.py`
- `libs/prebuilt/tests/test_tool_node_validation_error_filtering.py`
- `libs/sdk-py/langgraph_sdk/schema.py`
- `libs/sdk-py/tests/test_serde_schema.py`
- `libs/langgraph/bench/pydantic_state.py`
- `libs/langgraph/langgraph/_internal/_pydantic.py`
- `libs/langgraph/langgraph/errors.py`
- `libs/langgraph/langgraph/pregel/_executor.py`
- `libs/langgraph/langgraph/pregel/_runner.py`
- `libs/langgraph/tests/test_pydantic.py`
- `libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py`
- `libs/prebuilt/tests/test_validation_node.py`
- `libs/sdk-py/langgraph_sdk/auth/exceptions.py`
- `libs/sdk-py/langgraph_sdk/errors.py`
- `libs/sdk-py/tests/test_errors.py`

## Analysis Focus

When analyzing this framework for tool interface, determine:
1. Tool modeling (base class, protocol, decorated function, Pydantic)
2. Schema generation method (introspection, Pydantic, decorator, manual)
3. Built-in tool inventory (categories and count)
4. Registration pattern (declarative, registry, discovery, factory)
5. Execution flow (validation, invocation, error feedback)
6. Retry/self-correction mechanisms
7. Parallel execution support