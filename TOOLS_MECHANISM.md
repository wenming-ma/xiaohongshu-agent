# MCP 工具传递机制详解

## 问题：工具是否完整传递给 LLM？

**答案：是的！** 所有 MCP 工具都会完整传递给 LLM。

## 工作原理

### 1. 工具注册流程

```python
# 步骤 1: 创建 MCP Server
mcp_server = MCPServerStdio(
    command='npx',
    args=['-y', '@playwright/mcp'],
    tool_prefix='playwright'
)

# 步骤 2: 注册到 Agent
agent = Agent(
    model='claude-3-5-sonnet-20241022',
    toolsets=[mcp_server]  # 🔑 关键：注册 toolset
)
```

### 2. 工具发现过程（运行时）

当你调用 `agent.run()` 时，pydantic-ai 会：

```python
# 伪代码：内部流程
async def run(self, prompt: str):
    # 1️⃣ 收集所有工具
    all_tools = {}
    for toolset in self._user_toolsets:
        tools = await toolset.get_tools(ctx)  # MCP Server 实现此方法
        all_tools.update(tools)

    # 2️⃣ 转换为 LLM API 格式
    tool_schemas = [
        {
            "name": tool_name,
            "description": tool.description,
            "input_schema": tool.parameters_json_schema
        }
        for tool_name, tool in all_tools.items()
    ]

    # 3️⃣ 调用 LLM API（以 Anthropic 为例）
    response = await anthropic_client.messages.create(
        model=self.model,
        messages=[{"role": "user", "content": prompt}],
        tools=tool_schemas,  # 🔑 工具定义传给 LLM
        max_tokens=4096
    )
```

### 3. MCP Server 的 `get_tools()` 实现

```python
# pydantic_ai/mcp.py 源码（简化版）
class MCPServer:
    async def get_tools(self, ctx: RunContext[Any]) -> dict[str, ToolsetTool[Any]]:
        # 1. 调用 MCP 协议的 list_tools
        mcp_tools = await self.list_tools()  # 从 Playwright MCP 获取工具列表

        # 2. 转换为 pydantic-ai ToolsetTool
        tools = {}
        for mcp_tool in mcp_tools:
            # 添加前缀（如果设置了 tool_prefix）
            name = f"{self.tool_prefix}_{mcp_tool.name}" if self.tool_prefix else mcp_tool.name

            # 转换为 ToolsetTool
            tools[name] = self.tool_for_tool_def(
                ToolDefinition(
                    name=name,
                    description=mcp_tool.description,
                    parameters_json_schema=mcp_tool.inputSchema
                )
            )

        return tools
```

## 实际传递的工具列表

当你使用 Playwright MCP Server 时，以下工具会被传递给 Claude：

### 基础导航工具
- `playwright_navigate` - 导航到指定 URL
- `playwright_go_back` - 返回上一页
- `playwright_go_forward` - 前进到下一页
- `playwright_reload` - 重新加载当前页面

### 元素交互工具
- `playwright_click` - 点击页面元素
- `playwright_fill` - 填充输入框
- `playwright_type` - 输入文本（带键盘事件）
- `playwright_press` - 按下键盘按键
- `playwright_select_option` - 选择下拉框选项
- `playwright_check` - 勾选复选框
- `playwright_uncheck` - 取消勾选复选框

### 页面内容工具
- `playwright_read_page` - 读取页面可访问性树（核心工具）
- `playwright_find` - 使用自然语言查找元素
- `playwright_get_text` - 获取元素文本
- `playwright_get_attribute` - 获取元素属性

### 页面状态工具
- `playwright_wait` - 等待页面状态变化
- `playwright_wait_for_selector` - 等待元素出现
- `playwright_screenshot` - 截取页面截图
- `playwright_scroll` - 滚动页面

### 高级工具
- `playwright_evaluate` - 执行 JavaScript 代码
- `playwright_hover` - 鼠标悬停

## 工具定义示例

每个工具传递给 LLM 时的格式：

```json
{
  "name": "playwright_navigate",
  "description": "Navigate to a URL",
  "input_schema": {
    "type": "object",
    "properties": {
      "url": {
        "type": "string",
        "description": "The URL to navigate to"
      },
      "wait_until": {
        "type": "string",
        "enum": ["load", "domcontentloaded", "networkidle"],
        "description": "When to consider navigation succeeded"
      }
    },
    "required": ["url"]
  }
}
```

## LLM 如何使用工具

### 1. Claude 接收到工具定义
```
System: 你拥有以下工具：
- playwright_navigate(url: str, wait_until?: str)
- playwright_click(selector: str)
- playwright_type(selector: str, text: str)
- ...（20+ 个工具）

User: 搜索小红书关于"西安公司避坑"的内容
```

### 2. Claude 决定使用哪个工具
```json
{
  "role": "assistant",
  "content": [
    {
      "type": "tool_use",
      "id": "toolu_123",
      "name": "playwright_navigate",
      "input": {
        "url": "https://www.xiaohongshu.com"
      }
    }
  ]
}
```

### 3. pydantic-ai 执行工具调用
```python
# 自动调用 MCP Server
result = await mcp_server.call_tool(
    name="navigate",  # 去掉前缀
    arguments={"url": "https://www.xiaohongshu.com"}
)
```

### 4. 结果返回给 Claude
```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_123",
      "content": "Successfully navigated to xiaohongshu.com"
    }
  ]
}
```

### 5. Claude 继续下一步
```json
{
  "role": "assistant",
  "content": [
    {
      "type": "tool_use",
      "id": "toolu_124",
      "name": "playwright_find",
      "input": {
        "query": "search box"
      }
    }
  ]
}
```

## 验证工具是否完整

运行程序时会看到：

```
📚 Phase 1: 小红书研究
============================================================

   🔧 正在检查可用工具...

   📋 发现 20+ 个 Playwright MCP 工具:
      ✅ playwright_navigate
         Navigate to a URL
      ✅ playwright_click
         Click on an element
      ✅ playwright_type
         Type text into an element
      ✅ playwright_read_page
         Read the page accessibility tree
      ... (更多工具)
```

## 关键要点

1. ✅ **所有工具都传给 LLM**：通过 API 的 `tools` 参数
2. ✅ **工具带有完整描述**：LLM 知道每个工具的用途
3. ✅ **工具带有参数 schema**：LLM 知道如何正确调用
4. ✅ **工具前缀避免冲突**：`playwright_` 前缀区分不同来源
5. ✅ **动态发现**：MCP Server 启动时自动列出所有可用工具
6. ✅ **缓存优化**：`cache_tools=True` 避免重复查询

## 工具是否足够？

**答案：完全足够！**

Playwright MCP Server 提供的工具涵盖了：
- 页面导航
- 元素定位和交互
- 内容读取
- 状态等待
- JavaScript 执行

这些已经足以完成小红书搜索、阅读笔记、提取评论等所有任务。

## 如果 LLM 看不到工具怎么办？

**可能原因**：
1. MCP Server 未正确启动
2. 工具注册失败
3. API 调用时工具未传递

**调试方法**：
```python
# 添加日志查看工具列表
await research_agent.list_tools()

# 检查 Agent 运行日志
result = await agent.run(prompt, debug=True)  # 如果支持
```

## 总结

✅ **工具是全的**：Playwright MCP 提供 20+ 个浏览器自动化工具
✅ **工具会传给 LLM**：通过 Anthropic Messages API 的 `tools` 参数
✅ **LLM 可以看到所有工具**：包括名称、描述、参数 schema
✅ **LLM 会自主选择工具**：根据任务需求决定使用哪个工具

运行程序时的工具列表输出会确认这一切是否正常工作！
