# Design Philosophy

This project favors clear boundaries and predictable orchestration. New agents should be designed
to stay small, composable, and focused on a single responsibility.

## Architecture Principles

- **Vertical slices**: Each capability lives in `src/slices/<slice>/` with its own `agent.py`,
  `prompts.py`, and optional validators/tools.
- **Agent vs workflow**: `agent.py` should execute one task; `workflow.py` owns orchestration,
  persistence, and step-level logging.
- **Shared context**: All workflows accept and return `WorkflowContext` from
  `src/workflows/types.py`. This is the contract for data flow.
- **Async only**: Workflow functions are `async def run(ctx)` and must be awaitable.
- **Prompts in code**: Prompts live in slice `prompts.py` (no YAML). Use
  `src/infra/prompting.py` to render templates.
- **Shared infra**: Cross-cutting utilities (login, prompt rendering) live in `src/infra/`.

## Design Guidelines for New Agents

- **Keep agents small**: Avoid orchestration, file IO, and cross-step flow inside the agent.
- **Expose tools, not flows**: If the agent needs tools, provide them as `Tool` or helper methods.
- **Use validators intentionally**: Put slice-specific validators in the same slice. Reuse shared
  validator bases from `src/validators/`.
- **Preserve message history**: When multi-turn loops are needed, keep history bounded and explicit.
- **Prefer graceful degradation**: If an optional step fails, the workflow should log and continue
  when safe (e.g., image generation).
- **Minimize cross-slice imports**: Flow coordination happens in workflows, not in agents.

## Where to Wire Things

- **Slice workflow**: `src/slices/<slice>/workflow.py` implements `run(ctx)`.
- **Full workflow**: `src/workflows/` orchestrates all slices in order.
- **Entrypoint**: `src/main.py` builds the context and calls `FullWorkflow`.

## Conventions

- **Logging**: Use `get_logger(__name__)` and keep logs structured and phase-based.
- **Paths**: Use `Path` objects; output is under `posts/` via `WorkflowContext.create`.
- **Config**: Read settings from `src/config/settings.py`; avoid hard-coded values.

## Checklist for Adding a New Slice

1. Create `src/slices/<new_slice>/agent.py` and `prompts.py`.
2. Add `src/slices/<new_slice>/workflow.py` with `async def run(ctx)`.
3. Update `src/workflows/__init__.py` to include the new slice.
4. Update `README.md` structure if the slice is user-visible.

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

### 现有 Agent

| Agent | 位置 | 职责 |
|-------|------|------|
| PublisherAgent | `src/slices/publish_agent/` | 发布内容到小红书 |
| ImageAgent | `src/slices/image_agent/` | 生成图片 |
| ContentAgent | `src/slices/content_agent/` | 创作内容 |
| ResearchAgent | `src/slices/research_agent/` | 研究分析 |
| LoginAgent | `src/infra/login_agent.py` | 登录认证 |