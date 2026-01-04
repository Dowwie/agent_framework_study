# Tool Interface Analysis: MetaGPT

## Summary
- **Tool Modeling**: Pydantic models (Tool, ToolSchema) + decorator-based registration
- **Schema Generation**: AST parsing + introspection (dual-path approach)
- **Registration Pattern**: Decorator-based with global registry singleton
- **Error Handling**: Silent suppression (try/except/pass pattern)
- **Built-in Tools**: 18+ tools across 6 categories (web, ML, file operations, git, dev, multimodal)

## Tool Modeling

### Core Abstractions

MetaGPT uses a simple Pydantic model-based approach with minimal overhead:

**Tool Data Model** (`metagpt/tools/tool_data_type.py:8-14`):
```python
class Tool(BaseModel):
    name: str
    path: str
    schemas: dict = {}
    code: str = ""
    tags: list[str] = []
```

**Schema Validation Model** (`metagpt/tools/tool_data_type.py:4-6`):
```python
class ToolSchema(BaseModel):
    description: str
```

### Key Attributes

| Attribute | Type | Purpose |
|-----------|------|---------|
| name | str | Tool identifier (class/function name) |
| path | str | Source file path (for imports) |
| schemas | dict | Complete schema with type/description/signature/parameters |
| code | str | Source code (captured via `inspect.getsource()`) |
| tags | list[str] | Tags for discovery/recommendation (e.g., "web", "machine learning") |

### Design Philosophy

Tools can be:
1. **Decorated functions** - Simple stateless operations
2. **Decorated classes** - Stateful tools with multiple methods
3. **Selective method exposure** - Classes can expose specific methods only

Example of selective method exposure:
```python
# Usage: "Editor:read,write" exposes only read() and write() methods
# Full class schema still captured, but only specified methods available
```

## Schema Generation

### Dual-Path Approach

MetaGPT employs two complementary schema generation strategies:

#### Method 1: Introspection-Based (Runtime)

**Location**: `metagpt/tools/tool_convert.py:9-28`

Used by the `@register_tool` decorator at import time:

```python
def convert_code_to_tool_schema(obj, include: list[str] = None) -> dict:
    docstring = inspect.getdoc(obj)

    if inspect.isclass(obj):
        schema = {"type": "class", "description": remove_spaces(docstring), "methods": {}}
        for name, method in inspect.getmembers(obj, inspect.isfunction):
            if name.startswith("_") and name != "__init__":
                continue
            if include and name not in include:
                continue
            method_doc = get_class_method_docstring(obj, name)
            schema["methods"][name] = function_docstring_to_schema(method, method_doc)

    elif inspect.isfunction(obj):
        schema = function_docstring_to_schema(obj, docstring)

    return schema
```

**Function Schema Structure**:
```python
{
    "type": "function" | "async_function",
    "description": "Overall description from docstring",
    "signature": "(arg1: str, arg2: int) -> dict",
    "parameters": "Args: ... Returns: ..."
}
```

**Class Schema Structure**:
```python
{
    "type": "class",
    "description": "Class docstring",
    "methods": {
        "method_name": {
            "type": "function",
            "description": "...",
            "signature": "(...)",
            "parameters": "..."
        }
    }
}
```

#### Method 2: AST-Based (Static)

**Location**: `metagpt/tools/tool_convert.py:31-139`

Used for dynamic registration from file paths:

```python
def convert_code_to_tool_schema_ast(code: str) -> list[dict]:
    visitor = CodeVisitor(code)
    parsed_code = ast.parse(code)
    visitor.visit(parsed_code)
    return visitor.get_tool_schemas()
```

The `CodeVisitor` class walks the AST to extract:
- Function/class definitions
- Docstrings via `ast.get_docstring()`
- Signatures by parsing AST nodes (args, defaults, annotations, return types)
- Source code via `ast.get_source_segment()`

**Advantages**:
- Works without importing the code
- Captures tools from arbitrary Python files
- No side effects from imports

### Docstring Parsing

**Location**: `metagpt/utils/parse_docstring.py`

Uses Google-style docstring format:
```python
class GoogleDocstringParser(DocstringParser):
    @staticmethod
    def parse(docstring: str) -> Tuple[str, str]:
        if "Args:" in docstring:
            overall_desc, param_desc = docstring.split("Args:")
            param_desc = "Args:" + param_desc
        else:
            overall_desc = docstring
            param_desc = ""
        return overall_desc, param_desc
```

Splits docstrings into:
1. **Overall description** - Used by LLM for tool selection
2. **Parameter description** - Used by LLM for understanding usage

### Generated Schema Example

For the `magic_function` example:
```python
@register_tool()
def magic_function(arg1: str, arg2: int) -> dict:
    """
    The magic function that does something.

    Args:
        arg1 (str): ...
        arg2 (int): ...

    Returns:
        dict: ...
    """
    return {"arg1": arg1 * 3, "arg2": arg2 * 5}
```

Generates:
```python
{
    "type": "function",
    "description": "The magic function that does something.",
    "signature": "(arg1: str, arg2: int) -> dict",
    "parameters": "Args: arg1 (str): ... arg2 (int): ... Returns: dict: ..."
}
```

## Built-in Tool Inventory

### Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| File Operations | Editor | Read, write, edit, search files (16 methods) |
| Web Browsing | Browser | Navigate, click, type, scroll web pages |
| Web Scraping | view_page_element_to_scrape | Extract HTML content with RAG |
| Terminal | Terminal, Bash | Execute shell commands |
| Version Control | git_create_pull, git_create_issue | GitHub/GitLab operations |
| ML Data Processing | FillMissingValue, MinMaxScale, StandardScale, etc. | 6 preprocessing tools |
| ML Feature Engineering | PolynomialExpansion, CatCount, TargetMeanEncoder | 3+ feature tools |
| Multimodal | SDEngine | Stable Diffusion text-to-image |

### Complete Tool List

| Tool Name | Location | Methods/Functions | Schema Method | Category |
|-----------|----------|-------------------|---------------|----------|
| Editor | `metagpt/tools/libs/editor.py` | write, read, open_file, goto_line, scroll_down, scroll_up, create_file, edit_file_by_replace, insert_content_at_line, append_file, search_dir, search_file, find_file, similarity_search | Introspection | File Operations |
| Browser | `metagpt/tools/libs/browser.py` | click, close_tab, go_back, go_forward, goto, hover, press, scroll, tab_focus, type | Introspection | Web Browsing |
| Terminal | `metagpt/tools/libs/terminal.py` | run_command, execute_in_conda_env, get_stdout_output | Introspection | Terminal |
| Bash | `metagpt/tools/libs/terminal.py` | run (with custom shell functions) | Introspection | Terminal |
| view_page_element_to_scrape | `metagpt/tools/libs/web_scraping.py` | Single function | Introspection | Web Scraping |
| git_create_pull | `metagpt/tools/libs/git.py` | Single function | Introspection | Version Control |
| git_create_issue | `metagpt/tools/libs/git.py` | Single function | Introspection | Version Control |
| FillMissingValue | `metagpt/tools/libs/data_preprocess.py` | fit, transform, fit_transform | Introspection | ML Preprocessing |
| MinMaxScale | `metagpt/tools/libs/data_preprocess.py` | fit, transform, fit_transform | Introspection | ML Preprocessing |
| StandardScale | `metagpt/tools/libs/data_preprocess.py` | fit, transform, fit_transform | Introspection | ML Preprocessing |
| MaxAbsScale | `metagpt/tools/libs/data_preprocess.py` | fit, transform, fit_transform | Introspection | ML Preprocessing |
| RobustScale | `metagpt/tools/libs/data_preprocess.py` | fit, transform, fit_transform | Introspection | ML Preprocessing |
| OrdinalEncode | `metagpt/tools/libs/data_preprocess.py` | fit, transform, fit_transform | Introspection | ML Preprocessing |
| OneHotEncode | `metagpt/tools/libs/data_preprocess.py` | fit, transform | Introspection | ML Preprocessing |
| LabelEncode | `metagpt/tools/libs/data_preprocess.py` | fit, transform | Introspection | ML Preprocessing |
| PolynomialExpansion | `metagpt/tools/libs/feature_engineering.py` | fit, transform, fit_transform | Introspection | Feature Engineering |
| CatCount | `metagpt/tools/libs/feature_engineering.py` | fit, transform, fit_transform | Introspection | Feature Engineering |
| TargetMeanEncoder | `metagpt/tools/libs/feature_engineering.py` | fit, transform, fit_transform | Introspection | Feature Engineering |
| SDEngine | `metagpt/tools/libs/sd_engine.py` | __init__, simple_run_t2i, run_t2i, construct_payload, save | Introspection | Multimodal |

Additional tools in codebase: `deployer.py`, `gpt_v_generator.py`, `image_getter.py`, `index_repo.py`, `linter.py`, etc.

## Registration & Discovery

### Pattern: Decorator-Based with Global Singleton Registry

**Registry Singleton** (`metagpt/tools/tool_registry.py:27-91`):
```python
class ToolRegistry(BaseModel):
    tools: dict = {}  # {tool_name: Tool}
    tools_by_tags: dict = defaultdict(dict)  # {tag: {tool_name: Tool}}

    def register_tool(
        self,
        tool_name: str,
        tool_path: str,
        schemas: dict = None,
        schema_path: str = "",
        tool_code: str = "",
        tags: list[str] = None,
        tool_source_object=None,
        include_functions: list[str] = None,
        verbose: bool = False,
    ):
        if self.has_tool(tool_name):
            return  # Silent duplicate prevention

        schema_path = schema_path or TOOL_SCHEMA_PATH / f"{tool_name}.yml"

        if not schemas:
            schemas = make_schema(tool_source_object, include_functions, schema_path)

        if not schemas:
            return  # Silent failure if schema generation fails

        schemas["tool_path"] = tool_path
        try:
            ToolSchema(**schemas)  # Validation
        except Exception:
            pass  # Silent validation failure

        tags = tags or []
        tool = Tool(name=tool_name, path=tool_path, schemas=schemas, code=tool_code, tags=tags)
        self.tools[tool_name] = tool
        for tag in tags:
            self.tools_by_tags[tag].update({tool_name: tool})

TOOL_REGISTRY = ToolRegistry()  # Global singleton
```

**Decorator** (`metagpt/tools/tool_registry.py:94-118`):
```python
def register_tool(tags: list[str] = None, schema_path: str = "", **kwargs):
    """register a tool to registry"""

    def decorator(cls):
        # Get the file path where the function/class is defined
        file_path = inspect.getfile(cls)
        if "metagpt" in file_path:
            file_path = "metagpt" + file_path.split("metagpt")[-1]

        source_code = ""
        with contextlib.suppress(OSError):
            source_code = inspect.getsource(cls)

        TOOL_REGISTRY.register_tool(
            tool_name=cls.__name__,
            tool_path=file_path,
            schema_path=schema_path,
            tool_code=source_code,
            tags=tags,
            tool_source_object=cls,
            **kwargs,
        )
        return cls

    return decorator
```

### Registration Flow

```
Import time:
  1. Module imports libs/__init__.py
  2. libs/__init__.py imports all tool modules (editor, browser, etc.)
  3. @register_tool decorator executes
  4. Decorator calls TOOL_REGISTRY.register_tool()
  5. Schema generated via introspection
  6. Tool added to global registry
  7. Tool indexed by tags

Runtime:
  1. Agent initializes with tools=["Editor", "Browser"] or tags=["web"]
  2. validate_tool_names() called
  3. Validation supports:
     - Tool names: "Editor"
     - Tool tags: "web" (returns all tools with that tag)
     - Selective methods: "Editor:read,write"
     - File paths: "/path/to/custom_tool.py" (triggers AST-based registration)
  4. Returns dict[str, Tool] of validated tools
```

### Dynamic Registration from File Paths

**Location**: `metagpt/tools/tool_registry.py:131-194`

```python
def validate_tool_names(tools: list[str]) -> dict[str, Tool]:
    valid_tools = {}
    for key in tools:
        if os.path.isdir(key) or os.path.isfile(key):
            # Register tools from file path on-the-fly
            valid_tools.update(register_tools_from_path(key))
        elif TOOL_REGISTRY.has_tool(key.split(":")[0]):
            # Handle "ClassName:method1,method2" syntax
            if ":" in key:
                class_tool_name = key.split(":")[0]
                method_names = key.split(":")[1].split(",")
                class_tool = TOOL_REGISTRY.get_tool(class_tool_name)

                # Filter to only specified methods
                methods_filtered = {}
                for method_name in method_names:
                    if method_name in class_tool.schemas["methods"]:
                        methods_filtered[method_name] = class_tool.schemas["methods"][method_name]

                class_tool_filtered = class_tool.model_copy(deep=True)
                class_tool_filtered.schemas["methods"] = methods_filtered
                valid_tools.update({class_tool_name: class_tool_filtered})
            else:
                valid_tools.update({key: TOOL_REGISTRY.get_tool(key)})
        elif TOOL_REGISTRY.has_tool_tag(key):
            # Tag-based lookup
            valid_tools.update(TOOL_REGISTRY.get_tools_by_tag(key))
```

### Discovery Methods

1. **Direct name**: `tools=["Editor"]`
2. **Tag-based**: `tools=["web"]` returns Browser + web_scraping tools
3. **Selective methods**: `tools=["Editor:read,write"]`
4. **All tools**: `tools=["<all>"]`
5. **Path-based**: `tools=["/path/to/custom_tool.py"]`

## Execution Flow

MetaGPT does NOT have a centralized tool execution layer. Tools are invoked directly as Python objects/functions.

### Invocation Pattern

**From DataInterpreter** (`metagpt/roles/di/data_interpreter.py:43-56`):

```python
class DataInterpreter(Role):
    tools: list[str] = []
    tool_recommender: ToolRecommender = None

    @model_validator(mode="after")
    def set_plan_and_tool(self) -> "Interpreter":
        if self.tools and not self.tool_recommender:
            self.tool_recommender = BM25ToolRecommender(tools=self.tools)
        return self
```

**Tool Recommendation Flow** (`metagpt/tools/tool_recommend.py:77-121`):

```python
async def recommend_tools(
    self, context: str = "", plan: Plan = None, recall_topk: int = 20, topk: int = 5
) -> list[Tool]:
    # Stage 1: Recall - BM25 search over tool descriptions
    recalled_tools = await self.recall_tools(context=context, plan=plan, topk=recall_topk)

    # Stage 2: Rank - LLM selects final candidates
    ranked_tools = await self.rank_tools(recalled_tools=recalled_tools, context=context, plan=plan, topk=topk)

    return ranked_tools

async def get_recommended_tool_info(self, fixed: list[str] = None, **kwargs) -> str:
    recommended_tools = await self.recommend_tools(**kwargs)
    tool_schemas = {tool.name: tool.schemas for tool in recommended_tools}

    # Returns formatted prompt with tool info
    return TOOL_INFO_PROMPT.format(tool_schemas=tool_schemas)
```

**Tool Info Injected into Prompt**:
```python
TOOL_INFO_PROMPT = """
## Capabilities
- You can utilize pre-defined tools in any code lines from 'Available Tools' in the form of Python class or function.
- You can freely combine the use of any other public packages, like sklearn, numpy, pandas, etc..

## Available Tools:
Each tool is described in JSON format. When you call a tool, import the tool from its path first.
{tool_schemas}
"""
```

### LLM-Driven Invocation

MetaGPT uses a **code generation approach**:

1. LLM receives tool schemas in prompt
2. LLM generates Python code that imports and uses tools
3. Code executed in Jupyter notebook environment
4. Tool invocation is direct Python method/function call

**Example**:
```python
# LLM generates code like:
from metagpt.tools.libs.editor import Editor

editor = Editor()
content = await editor.read("/path/to/file.txt")
```

### Validation

**Schema-level validation** (`metagpt/tools/tool_registry.py:55-61`):
```python
try:
    ToolSchema(**schemas)  # Pydantic validation
except Exception:
    pass  # Validation failure silently ignored
```

**No runtime validation** - Tools are plain Python objects. Type errors occur naturally during execution.

### Error Handling

| Error Type | Handling | Feedback to LLM |
|------------|----------|-----------------|
| Schema generation failure | Silent (returns without registering) | None - tool unavailable |
| Schema validation failure | Silent (still registers tool) | None - tool still usable |
| Tool execution errors | Natural Python exceptions | Passed to LLM in next turn as execution output |
| File not found | Python FileNotFoundError | Exception message in execution output |
| Invalid arguments | Python TypeError/ValueError | Exception message in execution output |

**Pattern**: MetaGPT relies on **natural Python error handling** rather than custom error types. Errors bubble up as execution output for the LLM to observe and correct.

### Retry Mechanisms

**No built-in retry at tool layer**. Retry happens at the agent loop level:
- LLM sees error in execution output
- LLM generates corrected code
- New execution attempt

**React Mode** (`metagpt/roles/di/data_interpreter.py:65-84`):
```python
async def _think(self) -> bool:
    """Use LLM to decide whether and what to do next."""
    context = self.working_memory.get()  # Includes previous errors

    prompt = REACT_THINK_PROMPT.format(user_requirement=..., context=context)
    rsp = await self.llm.aask(prompt)
    rsp_dict = json.loads(CodeParser.parse_code(text=rsp))

    need_action = rsp_dict["state"]  # LLM decides if retry needed
    return need_action
```

## Parallel Execution

**No explicit parallel tool execution support** in the core framework.

Tools can be:
- **Async** (Browser, Editor.read, git_create_pull) - use `async/await`
- **Sync** (data preprocessing tools) - blocking

**Concurrency model**:
- Agent execution is async
- Multiple async tools can be awaited concurrently if LLM generates code with `asyncio.gather()`
- No framework-level orchestration of parallel tool calls
- Concurrency is implicit in the generated Python code

**Example of LLM-generated parallel execution**:
```python
# LLM could generate:
import asyncio
from metagpt.tools.libs.browser import Browser
from metagpt.tools.libs.editor import Editor

browser = Browser()
editor = Editor()

results = await asyncio.gather(
    browser.goto("https://example.com"),
    editor.read("/path/to/file.txt")
)
```

## Code References

### Core Implementation
- `metagpt/tools/tool_registry.py:27-194` - Registry and registration
- `metagpt/tools/tool_data_type.py:1-14` - Tool models
- `metagpt/tools/tool_convert.py:1-140` - Schema generation
- `metagpt/utils/parse_docstring.py:1-44` - Docstring parsing

### Tool Recommendation
- `metagpt/tools/tool_recommend.py:1-244` - Recall/rank system
- `metagpt/tools/tool_recommend.py:195-228` - BM25 recommender

### Built-in Tools
- `metagpt/tools/libs/editor.py:84-1140` - File operations (16 methods)
- `metagpt/tools/libs/browser.py:32-212` - Web browsing (10 methods)
- `metagpt/tools/libs/terminal.py:15-270` - Shell execution
- `metagpt/tools/libs/data_preprocess.py:88-252` - ML preprocessing (8 tools)
- `metagpt/tools/libs/feature_engineering.py:26-100+` - Feature engineering

### Usage Examples
- `examples/di/custom_tool.py:13-26` - Custom tool registration
- `metagpt/roles/di/data_interpreter.py:36-99` - Tool integration in agent

## Implications for New Framework

### Positive Patterns

1. **Dual schema generation** (introspection + AST) enables both decorated and dynamic registration
2. **Tag-based discovery** enables semantic tool grouping and recommendation
3. **Selective method exposure** (`ClassName:method1,method2`) provides fine-grained control
4. **Tool recommendation system** (recall + rank) scales to large tool sets
5. **Zero-overhead decorator** - just add `@register_tool()` and tags
6. **LLM-driven invocation** via code generation is highly flexible
7. **Natural error handling** - Python exceptions are inherently informative

### Considerations

1. **Silent failures** - Schema generation/validation failures are swallowed
   - **Implication**: Hard to debug registration issues
   - **Fix**: Add verbose logging or fail-fast mode

2. **No schema standardization** - Just a freeform dict
   - **Implication**: No JSON Schema output, unclear type mappings
   - **Fix**: Generate OpenAPI/JSON Schema from type hints

3. **No centralized execution** - Tools invoked as plain Python
   - **Implication**: No observability, no retry logic, no timeout handling
   - **Fix**: Optional ExecutionContext with hooks

4. **Tool path handling** - String-based paths fragile across deployments
   - **Implication**: `metagpt/tools/libs/editor.py` may not resolve correctly
   - **Fix**: Use module paths or entry points

5. **Code-generation dependency** - Requires notebook execution environment
   - **Implication**: Can't use with structured function calling
   - **Fix**: Add alternative executor that maps tool calls to function invocations

## Anti-Patterns Observed

1. **Silent exception suppression** (`try/except: pass`)
   - `tool_registry.py:57-61` - Validation failure ignored
   - `tool_registry.py:104` - `contextlib.suppress(OSError)` for source code capture

2. **Global mutable singleton** - `TOOL_REGISTRY` is a global variable
   - Precludes isolated testing
   - Makes state unpredictable in concurrent scenarios

3. **No version tracking** - Tools registered without version metadata
   - Can't handle schema evolution
   - Breaking changes invisible

4. **Docstring as schema source** - Informal, no validation
   - Typos in docstrings break schema
   - No enforcement of completeness

5. **String-based tool references** - `tools=["Editor"]`
   - No IDE autocomplete
   - Typos caught only at runtime
   - Refactoring unfriendly

6. **Implicit import-time registration** - Side effects on import
   - Tools registered even if unused
   - Circular import risks

### Recommended Improvements

1. **Explicit error modes**: Add `strict=True` flag to fail loudly on schema issues
2. **Structured schemas**: Generate Pydantic models or TypedDict from tool signatures
3. **Execution hooks**: Optional pre/post execution callbacks for logging/monitoring
4. **Tool versioning**: Add `version` field to Tool model
5. **Type-safe tool references**: Use Protocol or ABC for tool definitions
6. **Lazy registration**: Register tools on first use, not import
