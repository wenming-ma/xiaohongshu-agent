# 小红书内容创作工具（Pydantic-AI）

基于 Pydantic-AI 和 Playwright MCP Server 的小红书内容自动创作工具。

## 核心功能

- **智能研究**：使用 Playwright MCP 自动搜索和分析小红书内容
- **内容创作**：基于研究数据生成高质量的小红书帖子

## 技术栈

- **pydantic-ai**: AI Agent 框架
- **Playwright MCP Server**: 浏览器自动化
- **Claude 3.5 Sonnet**: 大语言模型

## 项目结构

```
xiaohongshu-agent/
├── src/
│   ├── agents/
│   │   ├── research.py          # 研究 Agent（包含 MCP 配置）
│   │   └── content.py           # 内容 Agent
│   ├── models/
│   │   └── schemas.py           # 数据模型
│   ├── utils/
│   │   └── file_ops.py          # 文件操作
│   └── main.py                  # 主程序
├── submodules/
│   ├── pydantic-ai/             # Pydantic-AI 子模块
│   └── playwright-mcp/          # Playwright MCP 子模块
├── requirements.txt
├── pyproject.toml
└── setup.py
```

## 快速开始

### 1. 安装依赖

```bash
python setup.py
```

### 2. 配置 API 密钥

编辑 `.env` 文件，填入你的 Anthropic API Key：

```env
ANTHROPIC_API_KEY=your-api-key-here
```

### 3. 运行工作流

```bash
python -m src.main --topic "西安公司避坑指南" --audience "求职者"
```

### 4. 查看输出

生成的内容保存在 `posts/` 目录下，包括：
- `research.json`: 研究结果
- `content.json`: 创作的内容

## 工作流程

```
1. 研究阶段 (ResearchAgent)
   └─> 搜索小红书 → 阅读帖子和评论 → 提取实体和案例

2. 创作阶段 (ContentAgent)
   └─> 分析研究数据 → 生成标题和正文 → 输出结构化内容
```

## 代码统计

- **总代码**: ~500 行（相比原来减少 82%）
- **依赖数**: 4 个（相比原来减少 75%）
- **Agent 数**: 2 个（ResearchAgent + ContentAgent）

## 优势

✅ **简洁**: 从 2,785 行减少到 500 行
✅ **现代**: 使用 Pydantic-AI 和 MCP 标准
✅ **类型安全**: Pydantic 强制类型验证
✅ **易维护**: 清晰的模块化架构

## 许可证

MIT License
