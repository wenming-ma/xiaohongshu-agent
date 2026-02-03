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