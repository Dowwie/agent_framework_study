# HMP Context: autogen

## Quick Facts

- **Repository**: microsoft/autogen
- **Primary Language**: Python (546 files) with .NET support (cross-platform)
- **Architecture Style**: Multi-layered modular architecture with clean separation between core runtime, agent chat abstractions, and extensions
- **Total Files**: 1,837 files across documentation, Python packages, .NET implementations, and samples
- **Key Packages**:
  - `autogen-core`: Low-level runtime and agent primitives
  - `autogen-agentchat`: High-level conversational agent abstractions
  - `autogen-ext`: Extensions for models, agents, and tools
  - `autogen-studio`: Web UI and configuration management
  - `autogen-magentic-one`: Specialized multi-agent orchestration

### Async/Streaming Model
**Strategy**: Pure async/await with asyncio queue-based message processing

**Core Runtime**:
```python
class SingleThreadedAgentRuntime:
    async def send_message(self, message: Any, recipient: AgentId, ...) -> Any
    async def publish_message(self, message: Any, topic_id: TopicId, ...) -> None
    async def _process_next(self) -> None  # Processes messages from queue

### Streaming Mentions
- (+) Supports streaming tools (`BaseStreamTool`)

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `python/packages/agbench/benchmarks/GAIA/Templates/SelectorGroupChat/scenario.py`
- `python/packages/agbench/benchmarks/HumanEval/Templates/AgentChat/custom_code_executor.py`
- `python/packages/agbench/benchmarks/HumanEval/Templates/AgentChat/reasoning_model_context.py`
- `python/packages/agbench/benchmarks/HumanEval/Templates/AgentChat/scenario.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/__init__.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/agents/__init__.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/agents/_assistant_agent.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/agents/_base_chat_agent.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/agents/_code_executor_agent.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/agents/_message_filter_agent.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/agents/_society_of_mind_agent.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/agents/_user_proxy_agent.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/base/__init__.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/base/_chat_agent.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/base/_handoff.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/base/_task.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/base/_team.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/base/_termination.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/conditions/__init__.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/conditions/_terminations.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/messages.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/state/__init__.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/state/_states.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/teams/__init__.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/__init__.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_base_group_chat.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_base_group_chat_manager.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_chat_agent_container.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_events.py`
- `python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_graph/__init__.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy