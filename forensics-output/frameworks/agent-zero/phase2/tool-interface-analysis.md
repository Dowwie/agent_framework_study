# Tool Interface Analysis: agent-zero

## Summary
- **Tool Modeling**: Abstract base class with inheritance
- **Schema Generation**: Manual markdown documentation (no introspection)
- **Registration Pattern**: File-based lazy loading with fallback hierarchy
- **Error Handling**: Basic exception handling with user feedback via prompts
- **Built-in Tools**: 18 tools across 6 functional categories
- **Parallel Execution**: Not supported (sequential tool calls only)
- **Extension System**: Hook-based extensibility at 4 lifecycle points

## Tool Modeling

### Core Abstraction

Tools inherit from an abstract base class `Tool` defined in `python/helpers/tool.py`:

```python
from dataclasses import dataclass

@dataclass
class Response:
    message: str
    break_loop: bool
    additional: dict[str, Any] | None = None

class Tool:
    def __init__(self, agent: Agent, name: str, method: str | None,
                 args: dict[str,str], message: str, loop_data: LoopData | None,
                 **kwargs) -> None:
        self.agent = agent
        self.name = name
        self.method = method
        self.args = args
        self.loop_data = loop_data
        self.message = message
        self.progress: str = ""

    @abstractmethod
    async def execute(self, **kwargs) -> Response:
        pass

    async def before_execution(self, **kwargs):
        # Logging and progress display
        pass

    async def after_execution(self, response: Response, **kwargs):
        # Add to history, update logs
        pass

    def get_log_object(self):
        # Create structured log entry
        pass
```

### Key Attributes

| Attribute | Type | Purpose |
|-----------|------|---------|
| agent | Agent | Reference to owning agent instance |
| name | str | Tool identifier (e.g., "code_execution_tool") |
| method | str \| None | Optional sub-method (e.g., "scheduler:list_tasks" splits to name="scheduler", method="list_tasks") |
| args | dict[str, str] | Tool arguments from LLM JSON output |
| message | str | Original LLM message containing tool call |
| loop_data | LoopData \| None | Current execution loop context |
| progress | str | Current progress status for UI updates |

**Design Pattern**: Stateful tools with agent coupling and lifecycle hooks.

## Schema Generation

### Method Used

**Manual Documentation (No Introspection)**: Agent-zero does NOT generate tool schemas programmatically. Instead, each tool has a corresponding markdown file that describes its usage to the LLM.

**Location Pattern**: `prompts/agent.system.tool.<tool_name>.md`

**Example**: `prompts/agent.system.tool.code_exe.md`

```markdown
### code_execution_tool

execute terminal commands python nodejs code for computation or software tasks
place code in "code" arg; escape carefully and indent properly
select "runtime" arg: "terminal" "python" "nodejs" "output" "reset"
select "session" number, 0 default, others for multitasking
if code runs long, use "output" to wait, "reset" to kill process
usage:

~~~json
{
    "thoughts": [
        "Need to do...",
        "I can use...",
    ],
    "headline": "Executing Python code to check current directory",
    "tool_name": "code_execution_tool",
    "tool_args": {
        "runtime": "python",
        "session": 0,
        "code": "import os\nprint(os.getcwd())",
    }
}
~~~
```

**Schema Assembly**: Tool descriptions are collected via `prompts/agent.system.tools.py`:

```python
def get_tools_prompt(agent: Agent):
    prompt = agent.read_prompt("agent.system.tools.md")
    # Template expands {{tools}} variable
    return prompt
```

The `CallSubordinate` variables plugin collects all `agent.system.tool.*.md` files:

```python
# python/helpers/files.py - VariablesPlugin pattern
prompt_files = files.get_unique_filenames_in_dirs(folders, "agent.system.tool.*.md")
tools = []
for prompt_file in prompt_files:
    tool = files.read_prompt_file(prompt_file)
    tools.append(tool)
return {"tools": "\n\n".join(tools)}
```

### Generated Schema Example

No JSON schema is generated. The LLM receives natural language documentation and examples. Expected LLM output format:

```json
{
    "thoughts": ["reasoning step 1", "reasoning step 2"],
    "headline": "Human-readable action description",
    "tool_name": "memory_save",
    "tool_args": {
        "text": "Information to remember",
        "area": "main"
    }
}
```

**Validation**: None at schema level. The framework uses "dirty JSON" parsing (`DirtyJson.parse_string`) to handle malformed LLM outputs.

## Built-in Tool Inventory

### Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| **Code Execution** | code_execution_tool, input | Execute Python/Node.js/shell commands |
| **Memory Management** | memory_load, memory_save, memory_delete, memory_forget | Vector-based long-term memory |
| **Agent Orchestration** | call_subordinate, a2a_chat | Hierarchical and peer agent communication |
| **Task Scheduling** | scheduler (8 methods) | Cron/planned/adhoc task management |
| **Data Access** | document_query, browser_agent | Document Q&A and web automation |
| **User Interaction** | response, wait, notify_user | Final response and user notifications |
| **Behavior Tuning** | behaviour_adjustment | Dynamic prompt modification |
| **External Tools** | search_engine, vision_load | Web search and image analysis |

### Complete Tool List

| Tool Name | Location | Method Support | Category |
|-----------|----------|----------------|----------|
| code_execution_tool | python/tools/code_execution_tool.py | No | Code Execution |
| input | python/tools/input.py | No | Code Execution |
| memory_load | python/tools/memory_load.py | No | Memory |
| memory_save | python/tools/memory_save.py | No | Memory |
| memory_delete | python/tools/memory_delete.py | No | Memory |
| memory_forget | python/tools/memory_forget.py | No | Memory |
| call_subordinate | python/tools/call_subordinate.py | No | Orchestration |
| a2a_chat | python/tools/a2a_chat.py | No | Orchestration |
| scheduler | python/tools/scheduler.py | Yes (8 methods) | Task Scheduling |
| document_query | python/tools/document_query.py | No | Data Access |
| browser_agent | python/tools/browser_agent.py | No | Data Access |
| response | python/tools/response.py | No | User Interaction |
| wait | python/tools/wait.py | No | User Interaction |
| notify_user | python/tools/notify_user.py | No | User Interaction |
| behaviour_adjustment | python/tools/behaviour_adjustment.py | No | Behavior |
| search_engine | python/tools/search_engine.py | No | External |
| vision_load | python/tools/vision_load.py | No | External |
| unknown | python/tools/unknown.py | No | Error Handling |

**Total**: 18 distinct tools (scheduler provides 8 sub-methods via method dispatch)

### Notable Tool Features

**code_execution_tool**:
- Supports 5 runtimes: `python`, `nodejs`, `terminal`, `output`, `reset`
- Multi-session support for parallel command execution
- SSH remote execution capability
- Timeout handling with dialog/prompt detection

**scheduler** (method-based dispatch):
- Methods: `list_tasks`, `find_task_by_name`, `show_task`, `run_task`, `delete_task`, `create_scheduled_task`, `create_adhoc_task`, `create_planned_task`, `wait_for_task`
- Supports cron scheduling, planned execution, and manual adhoc tasks
- Task isolation via dedicated contexts

**browser_agent**:
- Built on browser-use library
- Asynchronous task execution with screenshot feedback
- Secrets masking for credential safety

## Registration & Discovery

### Pattern

**File-Based Lazy Loading with Fallback Hierarchy**

Tools are NOT pre-registered. Discovery happens on-demand when the LLM requests a tool.

### Discovery Flow

```python
# agent.py - get_tool method
def get_tool(self, name: str, method: str | None, args: dict,
             message: str, loop_data: LoopData | None, **kwargs):
    from python.tools.unknown import Unknown
    from python.helpers.tool import Tool

    classes = []

    # 1. Try agent-specific tools first (profile override)
    if self.config.profile:
        try:
            classes = extract_tools.load_classes_from_file(
                f"agents/{self.config.profile}/tools/{name}.py", Tool
            )
        except Exception:
            pass

    # 2. Fallback to default tools
    if not classes:
        try:
            classes = extract_tools.load_classes_from_file(
                f"python/tools/{name}.py", Tool
            )
        except Exception:
            pass

    # 3. Use Unknown tool if not found
    tool_class = classes[0] if classes else Unknown
    return tool_class(agent=self, name=name, method=method, args=args,
                      message=message, loop_data=loop_data, **kwargs)
```

**Fallback Priority**:
1. MCP tools (if MCP server configured)
2. Agent profile tools (`agents/<profile>/tools/<name>.py`)
3. Default tools (`python/tools/<name>.py`)
4. Unknown tool (error handler)

### Tool Loading Mechanism

```python
# python/helpers/extract_tools.py
def load_classes_from_file(file: str, base_class: type[T],
                           one_per_file: bool = True) -> list[type[T]]:
    module = import_module(file)
    class_list = inspect.getmembers(module, inspect.isclass)

    # Filter for subclasses, iterate backwards to skip imports
    for cls in reversed(class_list):
        if cls[1] is not base_class and issubclass(cls[1], base_class):
            classes.append(cls[1])
            if one_per_file:
                break
    return classes
```

**Convention**: One tool class per file, named after the tool (e.g., `CodeExecution` in `code_execution_tool.py`).

### Extension Override Pattern

Agent profiles can override default tools by creating a file with the same name:

```
agents/_example/tools/
├── example_tool.py      # New tool
└── response.py          # Overrides python/tools/response.py
```

## Execution Flow

### Invocation Pattern

```python
# agent.py - process_tools method
async def process_tools(self, msg: str):
    # 1. Parse LLM response for tool call
    tool_request = extract_tools.json_parse_dirty(msg)

    if tool_request is not None:
        raw_tool_name = tool_request.get("tool_name", "")
        tool_args = tool_request.get("tool_args", {})

        # 2. Split method notation (e.g., "scheduler:list_tasks")
        tool_name = raw_tool_name
        tool_method = None
        if ":" in raw_tool_name:
            tool_name, tool_method = raw_tool_name.split(":", 1)

        # 3. Try MCP tools first, fallback to local
        tool = mcp_helper.MCPConfig.get_instance().get_tool(self, tool_name)
        if not tool:
            tool = self.get_tool(name=tool_name, method=tool_method,
                                args=tool_args, message=msg,
                                loop_data=self.loop_data)

        if tool:
            try:
                # 4. Lifecycle hooks
                await tool.before_execution(**tool_args)

                # 5. Extension point: preprocess args
                await self.call_extensions("tool_execute_before",
                                          tool_args=tool_args,
                                          tool_name=tool_name)

                # 6. Execute tool
                response = await tool.execute(**tool_args)

                # 7. Extension point: postprocess response
                await self.call_extensions("tool_execute_after",
                                          response=response,
                                          tool_name=tool_name)

                # 8. After execution hook
                await tool.after_execution(response)

                # 9. Break loop if requested
                if response.break_loop:
                    return response.message
            except Exception as e:
                # Error handling (see below)
                pass
```

### Validation

**Pre-Execution**: None. Arguments are passed directly from LLM output to `execute(**kwargs)`.

**Post-Execution**: Tools return `Response` dataclass with:
- `message`: Result text to add to conversation
- `break_loop`: Whether to stop agent loop (used by `response` tool)
- `additional`: Optional metadata (e.g., hints for next step)

### Error Handling

| Error Type | Handling | Feedback to LLM |
|------------|----------|-----------------|
| Tool not found | `Unknown` tool executed | Prompt from `fw.tool_not_found.md` with available tools list |
| Invalid JSON | DirtyJson parser attempts repair | If parse fails, no tool extracted |
| Execution exception | Caught in `process_tools` | Error logged, warning added to history |
| Timeout (code_execution_tool) | Configurable timeouts with system messages | System prompt injected: `[SYSTEM: Timeout after X seconds]` |
| Dialog detected (code_execution_tool) | Regex pattern matching | System prompt: `[SYSTEM: Dialog detected, use input tool]` |

**Error Feedback Mechanism**: `agent.read_prompt("fw.<error_type>.md", **vars)`

Example - tool not found:
```python
class Unknown(Tool):
    async def execute(self, **kwargs):
        tools = get_tools_prompt(self.agent)
        return Response(
            message=self.agent.read_prompt(
                "fw.tool_not_found.md",
                tool_name=self.name,
                tools_prompt=tools
            ),
            break_loop=False,
        )
```

### Retry Mechanisms

**No Built-in Retry**: Tools do not automatically retry on failure. The agent loop continues with error feedback, allowing the LLM to:
1. Read error message from tool response
2. Adjust arguments
3. Call tool again

**Exception**: `code_execution_tool` retries once on connection loss:

```python
for i in range(2):  # Try twice
    try:
        await session.send_command(command)
        return await get_terminal_output(...)
    except Exception as e:
        if i == 1:  # Second attempt
            await prepare_state(reset=True, session=session)  # Reset
            continue
        else:
            raise e
```

## Parallel Execution

**Not Supported**

Agent-zero executes tools sequentially. The LLM is instructed to call only one tool per response (with exception for `thoughts` field).

From `prompts/agent.system.tool.code_exe.md`:
```
don't use with other tools except thoughts; wait for response before using others
```

**Architectural Constraint**: The agent loop processes one tool call per iteration:

```python
async def process_tools(self, msg: str):
    tool_request = extract_tools.json_parse_dirty(msg)  # Parses single JSON object
    if tool_request is not None:
        # ... execute single tool
```

**Workaround**: The `scheduler` tool enables asynchronous task execution in dedicated contexts, allowing pseudo-parallel execution of multi-step workflows.

## Extension System

### Hook Points

Tools support 4 extension points for cross-cutting concerns:

| Extension Point | Location | Purpose | Example Extension |
|----------------|----------|---------|-------------------|
| `tool_execute_before` | Before `execute()` | Modify arguments | `_10_unmask_secrets.py`, `_10_replace_last_tool_output.py` |
| `tool_execute_after` | After `execute()` | Modify response | `_10_mask_secrets.py` |
| `hist_add_tool_result` | After history update | Intercept tool results | `_90_save_tool_call_file.py` (saves large outputs to files) |
| `system_prompt` | Before agent loop | Inject tool docs | `_10_system_prompt.py` |

### Extension Example: Secret Masking

```python
# python/extensions/tool_execute_after/_10_mask_secrets.py
class MaskToolSecrets(Extension):
    async def execute(self, response: Response | None = None, **kwargs):
        if not response:
            return
        secrets_mgr = get_secrets_manager(self.agent.context)
        response.message = secrets_mgr.mask_values(response.message)
```

Extensions are discovered via file naming convention (`_<priority>_<name>.py`) and executed in priority order.

## Code References

| Component | File | Key Lines |
|-----------|------|-----------|
| Tool base class | `python/helpers/tool.py` | 16-67 |
| Tool discovery | `agent.py` | 891-919 |
| Tool execution | `agent.py` | 782-856 |
| Tool loading | `python/helpers/extract_tools.py` | 104-120 |
| Schema injection | `prompts/agent.system.tools.py` | 8-31 |
| Extension system | `python/helpers/extension.py` | (imported) |
| Code execution tool | `python/tools/code_execution_tool.py` | 43-483 |
| Scheduler tool | `python/tools/scheduler.py` | 18-281 |
| Unknown handler | `python/tools/unknown.py` | 7-15 |

## Implications for New Framework

### Positive Patterns

1. **Lifecycle Hooks**: `before_execution` and `after_execution` provide clean extension points
2. **Stateful Tools**: Tools maintain context (agent, args, progress) enabling sophisticated multi-step operations
3. **Extension System**: Hook-based extensions enable cross-cutting concerns without modifying tool code
4. **Method Dispatch**: `scheduler:list_tasks` notation allows single tool class to expose multiple operations
5. **Fallback Hierarchy**: Profile-specific tool overrides enable customization without framework modification
6. **Unknown Handler**: Graceful degradation with informative error messages to LLM
7. **Progress Tracking**: `set_progress()` and log updates provide real-time feedback
8. **Secrets Masking**: Automatic secret redaction via extensions prevents credential leakage

### Considerations

1. **No Type Safety**: Manual markdown schemas lack compile-time validation
2. **Tight Coupling**: Tools directly reference `Agent` and `AgentContext`, limiting reusability
3. **No Parallel Execution**: Sequential tool calls may bottleneck complex workflows
4. **Validation Gap**: No argument validation before execution (relies on LLM correctness)
5. **DirtyJson Parser**: Tolerates malformed JSON but may mask LLM output issues
6. **Hard-Coded Paths**: Tool discovery uses string concatenation (not robust to refactoring)
7. **Stateful Design**: Mutable tool state (self.progress, self.log) complicates concurrent execution
8. **Method String Parsing**: Runtime string splitting (`"scheduler:list_tasks".split(":")`) error-prone

## Anti-Patterns Observed

### 1. Stateful Tool Instances

**Issue**: Tools store mutable state (`self.progress`, `self.log`, `self.args`) making them non-reusable and unsafe for concurrent execution.

```python
class Tool:
    def __init__(self, agent, name, args, ...):
        self.args = args  # Mutable state
        self.progress = ""  # Mutable state
```

**Better Approach**: Functional tools that receive all inputs as parameters and return structured outputs.

### 2. String-Based Tool Discovery

**Issue**: File path construction via string concatenation is brittle:

```python
classes = load_classes_from_file(f"python/tools/{name}.py", Tool)
```

**Better Approach**: Registry pattern with explicit registration or annotation-based discovery.

### 3. No Schema Validation

**Issue**: Tool arguments pass directly from LLM to `execute(**kwargs)` with no validation:

```python
response = await tool.execute(**tool_args)  # No validation
```

**Better Approach**: Pydantic models for argument validation with automatic error messages.

### 4. Manual Documentation Burden

**Issue**: Every tool requires hand-written markdown with usage examples. Changes to tool signatures require manual doc updates.

**Better Approach**: Generate schemas from type annotations or Pydantic models.

### 5. Extension Naming Convention

**Issue**: Extensions discovered via file name patterns (`_10_mask_secrets.py`) are fragile:

```python
# Must follow exact naming: _<priority>_<name>.py
```

**Better Approach**: Explicit registration via decorators or module-level declarations.

### 6. Error Handling via Templates

**Issue**: Error messages constructed from markdown templates obscure the error handling logic:

```python
return Response(message=self.agent.read_prompt("fw.tool_not_found.md", ...))
```

**Better Approach**: Structured error types with centralized formatting.

### 7. Progress Mutation

**Issue**: Tools mutate shared state for progress updates:

```python
self.progress = "some update"
self.agent.context.log.set_progress(progress)
```

**Better Approach**: Yield progress events or use callback functions.

### 8. Method Dispatch via String Splitting

**Issue**: Sub-method routing uses runtime string parsing:

```python
if ":" in raw_tool_name:
    tool_name, tool_method = raw_tool_name.split(":", 1)
```

**Better Approach**: Explicit method registration or reflection-based routing.

## Recommendations for Elixir Framework

**Adopt**:
- Lifecycle hooks (before/after execution)
- Extension system for cross-cutting concerns
- Progress tracking mechanism
- Fallback/override hierarchy
- Unknown tool handler

**Avoid**:
- Stateful tool instances (use pure functions or processes)
- String-based discovery (use Registry or behavior-based discovery)
- Manual documentation (generate from typespecs)
- Mutable progress state (use message passing)

**Adapt**:
- Method dispatch: Use pattern matching on `{tool, method}` tuples
- Schema generation: Leverage Ecto.Schema or typespecs for automatic schema derivation
- Validation: Use changesets for argument validation before execution
- Error handling: Use tagged tuples `{:ok, result} | {:error, reason}` instead of exceptions
- Parallel execution: Support concurrent tool calls via `Task.async_stream/2`
