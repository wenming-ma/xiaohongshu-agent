# Design Philosophy

This project favors clear boundaries and predictable orchestration. New agents should be designed
to stay small, composable, and focused on a single responsibility.

## Architecture Principles

- **Platform pipelines**: Each capability lives in `src/agents/<content_type>/` with a
  `pipeline.py`, `schemas.py`, and optional phase directories such as `research/`, `content/`,
  `image/`, `publish/`, and `login/`.
- **Pipeline-local utils**: Each top-level agent package owns a `utils/` package for helpers that
  belong to that pipeline. Do not add new business helpers under phase directories as `utils.py`.
- **Pipeline vs agent**: `pipeline.py` owns end-to-end orchestration, persistence, and phase-level
  logging. `agent.py` should execute one phase inside a pipeline.
- **Async only**: Pipeline execution and agent entrypoints must be awaitable.
- **Prompts in code**: Prompts live beside the phase agent in `prompts.py` (no YAML).
- **Local-first organization**: Keep code inside the pipeline directory unless it is reused across
  multiple pipelines. Cross-pipeline business helpers belong in `src/agents/shared/utils/`.
  Infra-only shared abstractions belong in `src/core/`, `src/config/`, or `src/utils/`.
- **No legacy layout**: Do not add new code under the retired `src/slices/`, `src/infra/`, or
  `src/workflows/` structure.

## Design Guidelines for New Agents

- **Keep agents small**: Avoid routing across platforms or owning the full pipeline flow inside a
  phase agent.
- **Separate business closure from orchestration**: An agent should own the quality loop for a
  single business unit of work, such as generate-review-revise for one item or one batch. Batch
  splitting, concurrency limits, ordering, retries across units, and end-to-end scheduling belong
  to the pipeline or orchestration layer, not inside the agent itself.
- **Expose tools, not flows**: If the agent needs tools, provide them as `Tool` or helper methods.
- **Use validators intentionally**: Put pipeline-local validators beside the phase that uses them.
  Reuse shared validator primitives from `src/core/base_validator.py` when needed.
- **Preserve message history**: When multi-turn loops are needed, keep history bounded and explicit.
- **Prefer graceful degradation**: If an optional phase fails, `pipeline.py` should decide whether to
  log and continue when safe.
- **Minimize cross-pipeline imports**: Reuse shared modules only after a pattern is proven in more than
  one pipeline.
- **Keep `src/utils` infra-only**: `src/utils/` is reserved for providers, logging, prompting,
  file/retry helpers, and notifier integrations. Business helpers must not be added there.

## Design Guidelines for Shared Capabilities

- **Start from a stable contract**: Shared business capabilities under `src/agents/shared/utils/`
  must define a fixed public input/output contract before choosing models, providers, or runtime
  frameworks. Callers should depend on the contract, not on backend-specific parameters.
- **Depend on abstractions, not implementations**: Pipeline code and phase agents should call a
  capability through its public interface. Backend selection, implementation details, and
  compatibility logic should stay behind that boundary.
- **Separate orchestration from execution**: Service modules should handle selection, coordination,
  validation, and result normalization. Implementation modules should only own the work specific
  to one backend or strategy.
- **Keep variation points isolated**: When a capability supports multiple backends or strategies,
  isolate them behind adapters, providers, or registries instead of scattering conditional logic
  across callers.
- **Organize modules by responsibility**: Split public services, concrete implementations, and
  internal helpers into separate modules once a capability has more than one backend or more than
  one major responsibility.
- **Keep the public surface minimal**: Expose only the configuration and methods that are part of
  the product contract. Internal tuning knobs and implementation details should remain private by
  default.

## Where to Wire Things

- **New platform pipeline**: `src/agents/<content_type>/`
- **Pipeline entrypoint**: `pipeline.py` implements `BasePipeline.execute`
- **Phase agent**: `src/agents/<content_type>/<phase>/agent.py`
- **Pipeline helpers**: `src/agents/<content_type>/utils/`
- **Shared business helpers**: `src/agents/shared/utils/`
- **Top-level routing**: `src/master/agent.py`
- **CLI entrypoint**: `src/main.py`

## Conventions

- **Logging**: Use `get_logger(__name__)` and keep logs structured and phase-based.
- **Paths**: Use `Path` objects; output is under `posts/`, intermediate artifacts under `output/`.
- **Config**: Read settings from `src/config/settings.py`; avoid hard-coded values.
- **Registration**: New pipelines must inherit `BasePipeline` and register via `PipelineRegistry`.

## Checklist for Adding a New Pipeline

1. Create `src/agents/<content_type>/` with `pipeline.py` and `schemas.py`.
2. Add phase directories such as `research/`, `content/`, `image/`, `publish/`, or `login/` as
   needed.
3. Add `utils/` only when the pipeline needs local helpers; do not add phase-local `utils.py`.
4. Register the pipeline in `PipelineRegistry` and export it from the package `__init__.py`.
5. Update `README.md` and any local `AGENTS.md` files if the pipeline is user-visible.

---

# Migrated From CLAUDE.md

# Claude Instructions

Always use Context7 MCP when I need library/API documentation, code generation, setup or configuration steps without me having to explicitly ask.

When necessary, always refer to and use information from code repositories in the submodules directory.

Treat `submodules/` top-level entries as managed submodules and `submodules/reference/` as reference-only repositories.
Do not import runtime code from `submodules/reference/` unless the current task explicitly migrates it into the main project.

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

### 职责边界

- Agent 只负责单个业务单元的闭环处理，例如一条内容、一张图、一个字幕批次的生成、审核、修订。
- 批次切分、并发控制、执行顺序、跨批重试、整体调度属于 pipeline 或 orchestration 层，不应塞进 agent 内部。
- 如果某个能力既需要“单元内闭环”又需要“多单元调度”，优先拆成两层：
  上层负责拆分和调度，下层 agent 只负责把传入的单元处理到可用为止。

### 共享能力设计

- `src/agents/shared/utils/` 下的共享业务能力必须先定义稳定的输入输出契约，再决定具体模型、provider 或推理框架。
- pipeline 和 agent 只能依赖共享能力的公开契约，不应直接依赖底层实现细节。
- service 层负责选择、编排、校验和统一收口；具体实现层只负责某一种后端或策略的执行细节。
- 一个共享能力存在多种实现方式时，应通过 provider、adapter、registry 等边界隔离差异，而不是把分支判断散落到调用方。
- 当一个模块同时承担公开接口、实现细节和辅助逻辑时，应按职责拆分，避免单文件持续膨胀。
- 对外接口和配置面应尽量小且稳定；默认不暴露内部调优参数，除非它们本身就是产品契约的一部分。

### 现有 Agent（示例）

| Agent | 位置 | 职责 |
|-------|------|------|
| ResearchAgent | `src/agents/image_post/research/agent.py` | 研究小红书图文选题 |
| ContentAgent | `src/agents/image_post/content/agent.py` | 创作小红书图文内容 |
| ImageAgent | `src/agents/image_post/image/agent.py` | 生成图文配图 |
| PublisherAgent | `src/agents/image_post/publish/agent.py` | 发布图文到小红书 |
| LoginAgent | `src/agents/shared/login/agent.py` | 登录认证 |
| DownloadAgent | `src/agents/video_post/download/agent.py` | 下载和处理视频素材 |
