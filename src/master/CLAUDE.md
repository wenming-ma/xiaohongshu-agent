# Master 目录

顶层 AI Agent，负责理解用户意图并调用对应流水线。

## MasterAgent

```python
from src.master.agent import MasterAgent

agent = MasterAgent()
result = await agent.forward("帮我发一篇关于西安美食的小红书帖子")
```

## 职责

1. 解析用户自然语言输入
2. 选择合适的平台流水线（通过 PipelineRegistry）
3. 构造流水线输入参数
4. 调用流水线执行
5. 返回结果给用户
