# 小红书内容创作工具（Pydantic-AI）

基于 Pydantic-AI 和 Playwright MCP Server 的小红书内容自动创作工具。

## 核心功能

- **智能研究**：使用 Playwright MCP 自动搜索和分析小红书内容
- **内容创作**：基于研究数据生成高质量的小红书帖子

## 技术栈

- **pydantic-ai**: AI Agent 框架
- **Playwright MCP Server**: 浏览器自动化
- **MiniMax + OpenRouter**: 大语言模型（文本审核用 MiniMax，图片审核用 OpenRouter 的 Gemma）

## 项目结构

```
xiaohongshu-agent/
├── src/
│   ├── slices/
│   │   ├── research/            # 研究切片（Agent/Validator/Prompts/Workflow）
│   │   ├── content/             # 内容切片（Agent/Prompts/Workflow）
│   │   ├── image/               # 图片切片（Agent/Validator/Prompts/Workflow）
│   │   └── publish/             # 发布切片（Agent/Prompts/Workflow）
│   ├── infra/                   # 基础设施（登录、提示词渲染等）
│   ├── workflows/               # 编排入口与上下文定义
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

编辑 `.env` 文件，填入你的 MiniMax / OpenRouter API Key（Claude 不可用时不需要 Anthropic Key）：

```env
MINIMAX_API_KEY=your-api-key-here
OPENROUTER_API_KEY=your-api-key-here
```

### 3. 运行工作流

```bash
python -m src.main --topic "西安公司避坑指南" --audience "求职者"
```

### 4. 查看输出

生成的内容保存在 `posts/` 目录下，包括：
- `research.json`: 研究结果
- `content.json`: 创作的内容
- `image.json`: 配图结果（可选）
- `publish.json`: 发布结果（可选）

## 工作流程

```
1. 研究阶段 (ResearchAgent)
   └─> 搜索小红书 → 阅读帖子和评论 → 提取实体和案例

2. 创作阶段 (ContentAgent)
   └─> 分析研究数据 → 生成标题和正文 → 输出结构化内容

3. 配图阶段 (ImageAgent)
   └─> 语义分组 → 生成图片提示词 → Gemini 生成 → 质量验证

4. 发布阶段 (PublisherAgent)
   └─> 自动登录 → 批量上传图片 → 填写内容 → 发布
```

## 优势

✅ **切片化**: 以业务能力为单位组织代码  
✅ **编排清晰**: 统一的 workflow 接口便于扩展  
✅ **类型安全**: Pydantic 强制类型验证  
✅ **易维护**: 逻辑分层明确、职责更聚焦  

## 许可证

MIT License
