# Orchestrator 目录

顶层 AI Agent，负责理解用户意图并调用对应工具。

## MasterAgent

```python
from src.orchestrator.master_agent import MasterAgent

agent = MasterAgent()
result = await agent.forward("帮我发一篇关于西安美食的小红书帖子")
```

## 职责

1. 解析用户自然语言输入
2. 选择合适的平台工具（通过 ToolRegistry）
3. 构造工具输入参数
4. 调用工具执行
5. 返回结果给用户
