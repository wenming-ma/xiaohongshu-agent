# Design Philosophy

This project favors clear boundaries and predictable orchestration. New agents should be designed
to stay small, composable, and focused on a single responsibility.

## Architecture Principles

- **Platform tools**: Each capability lives in `src/tools/<platform>/<content_type>/` with a
  `tool.py`, `schemas.py`, and optional phase directories such as `research/`, `content/`,
  `image/`, `publish/`, and `login/`.
- **Tool vs agent**: `tool.py` owns end-to-end orchestration, persistence, and phase-level
  logging. `agent.py` should execute one phase inside a tool.
- **Async only**: Tool execution and agent entrypoints must be awaitable.
- **Prompts in code**: Prompts live beside the phase agent in `prompts.py` (no YAML).
- **Local-first organization**: Keep code inside the tool directory unless it is reused across
  multiple tools. Shared abstractions belong in `src/core/`, `src/config/`, or `src/utils/`.
- **No legacy layout**: Do not add new code under the retired `src/slices/`, `src/infra/`, or
  `src/workflows/` structure.

## Design Guidelines for New Agents

- **Keep agents small**: Avoid routing across platforms or owning the full tool flow inside a
  phase agent.
- **Expose tools, not flows**: If the agent needs tools, provide them as `Tool` or helper methods.
- **Use validators intentionally**: Put tool-local validators beside the phase that uses them.
  Reuse shared validator primitives from `src/core/base_validator.py` when needed.
- **Preserve message history**: When multi-turn loops are needed, keep history bounded and explicit.
- **Prefer graceful degradation**: If an optional phase fails, `tool.py` should decide whether to
  log and continue when safe.
- **Minimize cross-tool imports**: Reuse shared modules only after a pattern is proven in more than
  one tool.

## Where to Wire Things

- **New platform tool**: `src/tools/<platform>/<content_type>/`
- **Tool entrypoint**: `tool.py` implements `BasePlatformTool.execute`
- **Phase agent**: `src/tools/<platform>/<content_type>/<phase>/agent.py`
- **Top-level routing**: `src/orchestrator/master_agent.py`
- **CLI entrypoint**: `src/main.py`

## Conventions

- **Logging**: Use `get_logger(__name__)` and keep logs structured and phase-based.
- **Paths**: Use `Path` objects; output is under `posts/`, intermediate artifacts under `output/`.
- **Config**: Read settings from `src/config/settings.py`; avoid hard-coded values.
- **Registration**: New tools must inherit `BasePlatformTool` and register via `ToolRegistry`.

## Checklist for Adding a New Tool

1. Create `src/tools/<platform>/<content_type>/` with `tool.py` and `schemas.py`.
2. Add phase directories such as `research/`, `content/`, `image/`, `publish/`, or `login/` as
   needed.
3. Register the tool in `ToolRegistry` and export it from the package `__init__.py`.
4. Update `README.md` and any local `AGENTS.md` files if the tool is user-visible.

---

# Migrated From CLAUDE.md

# Claude Instructions

Always use Context7 MCP when I need library/API documentation, code generation, setup or configuration steps without me having to explicitly ask.

When necessary, always refer to and use information from code repositories in the submodules directory.

Use uv to manage the project and run python code

Always keep comments minimal in code

## Agent 设计规范

所有 Agent 必须继承 `BaseAgent` 抽象基类（`src/core/base_agent.py`），实现以下方法：

```python
class BaseAgent(ABC):
    def __init__(self):
        self.init_tools()
        self.init_agent()

    def init_tools(self) -> None: ...      # 初始化工具（MCP、验证器等）
    def init_agent(self) -> None: ...      # 初始化 pydantic_ai.Agent
    async def forward(self, ...) -> Any: ...   # 主执行入口
    async def step(self, ...) -> Any: ...      # 工作流子步骤
    async def validate(self, output: Any) -> ValidationResult: ...  # 验证输出
```

### ValidationResult

统一的验证返回类型：

```python
class ValidationResult(BaseModel):
    passed: bool
    feedback: str = ""

    @classmethod
    def success(cls, feedback: str = "") -> "ValidationResult": ...

    @classmethod
    def failure(cls, feedback: str) -> "ValidationResult": ...
```

### 命名规范

- 除 `__init__` 外，公开方法不加下划线前缀
- 私有辅助方法使用下划线前缀（如 `_check_images`）
- 验证失败回调统一命名为 `on_validation_failed`

### 现有 Agent（示例）

| Agent | 位置 | 职责 |
|-------|------|------|
| ResearchAgent | `src/tools/xiaohongshu/image_post/research/agent.py` | 研究小红书图文选题 |
| ContentAgent | `src/tools/xiaohongshu/image_post/content/agent.py` | 创作小红书图文内容 |
| ImageAgent | `src/tools/xiaohongshu/image_post/image/agent.py` | 生成图文配图 |
| PublisherAgent | `src/tools/xiaohongshu/image_post/publish/agent.py` | 发布图文到小红书 |
| LoginAgent | `src/tools/xiaohongshu/image_post/login/agent.py` | 登录认证 |
| DownloadAgent | `src/tools/xiaohongshu/video_post/download/agent.py` | 下载和处理视频素材 |
