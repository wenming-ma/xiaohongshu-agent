# 小红书内容创作工具（Pydantic-AI）

基于 Pydantic-AI 和 Playwright MCP Server 的小红书内容自动创作工具。

## 核心功能

- **智能研究**：支持站内研究、跨站深搜、文章精读和视频转录
- **内容创作**：基于研究数据生成图文、视频文案和小红书长文

## 技术栈

- **pydantic-ai**: AI Agent 框架
- **Playwright MCP Server**: 浏览器自动化
- **Anthropic + MiniMax + OpenRouter**: 文本生成、审核与路由
- **Gemini**: 图像生成

## 项目结构

```
xiaohongshu-agent/
├── src/
│   ├── main.py                  # CLI 入口
│   ├── orchestrator/            # 顶层路由（MasterAgent）
│   ├── core/                    # BaseAgent、BasePlatformTool、ToolRegistry
│   ├── config/                  # 配置定义
│   ├── utils/                   # 共享工具和 provider 封装
│   └── tools/                   # 平台工具，按 平台/内容类型 组织
│       └── xiaohongshu/
│           ├── image_post/      # 小红书图文工具
│           │   ├── tool.py
│           │   ├── schemas.py
│           │   ├── research/
│           │   ├── content/
│           │   ├── image/
│           │   ├── publish/
│           │   └── login/
│           ├── video_post/      # 小红书视频工具
│           └── article_post/    # 小红书长文工具
├── scripts/                     # 辅助脚本
├── tests/                       # 测试与集成脚本
├── workshop/                    # 选题与实验资料
├── submodules/
│   ├── pydantic-ai/             # Pydantic-AI 子模块
│   └── playwright-mcp/          # Playwright MCP 子模块
├── pyproject.toml
├── uv.lock
└── setup.py
```

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置 API 密钥

编辑 `.env` 文件。当前工作流至少需要以下环境变量：

```env
ANTHROPIC_API_KEY=your-api-key-here
MINIMAX_API_KEY=your-api-key-here
GEMINI_API_KEY=your-api-key-here
# 可选：控制默认文本模型提供方（视频工作流会使用）
MODEL_PROVIDER=minimax
```

如果你使用自建或代理 Anthropic 端点，也可以额外配置：

```env
ANTHROPIC_BASE_URL=https://your-primary-endpoint
ANTHROPIC_FALLBACK_BASE_URL=https://your-fallback-endpoint
ANTHROPIC_FALLBACK_API_KEY=your-fallback-key
```

### 3. 预热浏览器登录态（可选但推荐）

```bash
uv run python scripts/open_browser_for_login.py
```

可通过 `ARTICLE_LOGIN_URLS` 追加需要预登录的站点，例如 `Medium` 或其它有会员登录要求的媒体站。

### 4. 运行工作流

```bash
uv run python -m src.main --topic "西安公司避坑指南" --audience "求职者"
```

### 5. 查看输出

生成的内容保存在 `posts/` 目录下，包括：
- `research.json`: 研究结果
- `content.json`: 创作的内容
- `image.json`: 配图结果（可选）
- `publish.json`: 发布结果（可选）

## 工作流程

```
1. 研究阶段 (ResearchAgent)
   └─> 小红书站内研究 / 海外女性向媒体深搜 / 视频转录

2. 创作阶段 (ContentAgent)
   └─> 分析研究数据 → 生成标题和正文 → 输出结构化内容

3. 配图阶段 (ImageAgent)
   └─> 基于内容结构生成头图和章节配图

4. 发布阶段 (PublisherAgent)
   └─> 自动登录 / 复用缓存会话 → 填写内容 → 发布
```

## 优势

✅ **工具隔离**: 按 `平台/内容类型` 组织代码  
✅ **阶段清晰**: 每个工具内部按研究、创作、生成、发布拆分  
✅ **类型安全**: Pydantic 强制类型验证  
✅ **易维护**: 逻辑分层明确、职责更聚焦  

## 许可证

MIT License
