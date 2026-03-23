# Core 模块

核心抽象层，包含所有基类和数据模型。

## 文件说明

| 文件 | 职责 |
|------|------|
| `base_agent.py` | Agent 基类，定义 `forward()`, `step()`, `validate()` 接口 |
| `base_tool.py` | 平台工具基类 `BasePlatformTool`，泛型支持输入输出 schema |
| `base_validator.py` | 验证器基类：`InternalValidator`（循环内）、`ExternalValidator`（装饰器） |
| `tool_registry.py` | 工具注册表，`@ToolRegistry.register` 装饰器 |
| `schemas.py` | Pydantic 数据模型（ResearchResult, XHSContent, ImageResult 等） |

## Agent 设计规范

```python
class MyAgent(BaseAgent):
    def init_tools(self) -> None: ...      # 初始化工具
    def init_agent(self) -> None: ...      # 初始化 pydantic_ai.Agent
    async def forward(self, ...) -> Any: ...   # 主入口
    async def step(self, ...) -> Any: ...      # 工作流子步骤
    async def validate(self, output) -> ValidationResult: ...  # 验证
```

## 验证器类型

- **InternalValidator**: 返回反馈继续探索（研究任务）
- **ExternalValidator**: 装饰器模式，失败重试整个函数（图片生成）
