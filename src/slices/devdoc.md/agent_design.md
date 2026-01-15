# Agent 设计哲学

## 核心理念

采用 **ML 模型风格**（类似 PyTorch `nn.Module`）设计 Agent，统一代码结构，提高可读性。

## 统一结构

```python
class XxxAgent:
    """
    使用方式：
        agent = XxxAgent()
        result = await agent.forward(...)
    """

    # ========== 初始化 ==========
    def __init__(self):
        self._init_xxx()
        self._init_yyy()
        ...

    def _init_xxx(self):
        """初始化组件 X"""
        ...

    # ========== 主入口 ==========
    async def forward(self, ...) -> Result:
        """
        主执行入口（唯一公开方法）
        """
        state = self._init_state(...)

        for iteration in range(max_iter):
            await self._step(state, iteration)
            if self._validate(state):
                return self._finalize(state)
            self._update_state(state)

        return self._finalize(state)

    # ========== 核心方法 ==========
    def _init_state(self, ...) -> State:
        """初始化运行状态"""
        ...

    async def _step(self, state, iteration):
        """单次迭代"""
        ...

    async def _validate(self, state) -> bool:
        """验证结果"""
        ...

    def _finalize(self, state) -> Result:
        """最终化结果"""
        ...
```

## 设计原则

| 原则 | 说明 |
|------|------|
| **单一入口** | `forward()` 是唯一公开执行方法 |
| **状态封装** | 用 `@dataclass State` 封装运行时状态 |
| **初始化拆分** | `__init__` 调用多个 `_init_*` 方法 |
| **方法分组** | 按功能用注释分隔：初始化 / 主入口 / 核心 / 辅助 |
| **命名一致** | `_step` / `_validate` / `_finalize` / `_update_state` |

## Agent 清单

| Agent | 职责 | 入口签名 |
|-------|------|----------|
| `ResearchAgent` | 小红书研究 | `forward(topic, audience, output_dir)` |
| `ContentAgent` | 内容创作 | `forward(research, topic)` |
| `ImageAgent` | 配图生成 | `forward(content, research, topic, output_dir)` |
| `PublisherAgent` | 发布内容 | `forward(content, images, output_dir)` |
| `LoginAgent` | 登录认证 | `forward(url, action, hint)` |

## 为什么选择这种风格

1. **熟悉度**：ML 从业者熟悉 `forward()` 模式
2. **可预测**：统一结构降低认知负担
3. **可测试**：`_step` / `_validate` 可独立测试
4. **可扩展**：新增 Agent 只需复制结构
