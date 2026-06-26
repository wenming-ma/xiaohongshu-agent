# 小红书风格内容 Agent OS

![Xiaohongshu Agent OS 封面](docs/assets/readme-cover.png)

<p>
  <a href="README.md">English README</a>
  ·
  <a href="#快速开始">快速开始</a>
  ·
  <a href="#架构模型">架构模型</a>
  ·
  <a href="#安全与密钥">安全与密钥</a>
</p>

这是一个 Feishu-first 的内容创作系统。用户通过飞书和常驻主 Agent 对话，主 Agent 负责理解目标、追问缺失信息、选择 Skill 和 Prompt 模板，并把任务启动为后台专项工作流。最终结果统一回到飞书，形成可审核、可下载、可继续反馈的交付包。

它不是小红书自动发布器。系统的边界是生成和整理小红书/Rednote 风格内容，并把内容交回飞书让人审核；不会直接把帖子提交到小红书。

## 核心能力

- **飞书优先交互**：接收飞书文本、图片、按钮、快捷操作和后续反馈。
- **常驻主 Agent**：把开放式需求翻译成结构化 `WorkflowInvocation`，再启动后台任务。
- **原子专项 Agent**：Research、Grouping、Content、Image、Video、Article、Login、ReviewDelivery 等能力保持专项职责。
- **图文 / 文章 / 视频路线**：支持图文帖、长文交付包和视频内容相关工作流。
- **参考图感知规划**：保留用户给定的商品、风格、元素迁移、图数、禁忌和审核要求。
- **统一交付协议**：通过 `ResultEnvelope[DeliveryPackage]` 把正文、图片、文件和元数据交回飞书。
- **Skill 与 Prompt 模板库**：`.agents/skills/` 保存流程经验和检查清单，`.agents/prompt/` 保存版本化提示词模板。

## 仓库状态

该仓库已经公开，但当前没有声明开源许可证。因此它是 public/source-available 仓库，不代表已经授予标准开源复用、再分发或派生权利。

仓库不会包含真实凭证。实际运行需要你在本地配置：

- 飞书应用凭证和目标 chat id
- Anthropic、MiniMax、Gemini/Vertex AI、OpenRouter 或兼容 Provider 的模型密钥
- 可选的搜索、Logfire、Telegram、Android/小红书登录配置

## 快速开始

安装依赖：

```bash
uv sync
```

创建本地环境文件：

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`。如果要启动常驻飞书服务，至少需要：

```dotenv
FEISHU_APP_ID=your-feishu-app-id
FEISHU_APP_SECRET=your-feishu-app-secret
FEISHU_RUNTIME_ENV=dev
FEISHU_CHAT_DEV_ID=your-dev-feishu-chat-id
FEISHU_CHAT_DEPLOY_ID=your-deploy-feishu-chat-id
```

模型 Provider、图片生成、搜索、Logfire、Telegram 等配置都写在 `.env.example` 中。图片生成通常需要 Gemini 或 Vertex AI 配置；文本流程会根据 `MODEL_PROVIDER` 使用 Anthropic、MiniMax 或 OpenAI-compatible Provider。

启动正式常驻服务：

```bash
uv run python -m src.apps.feishu_agent_os.serve
```

可选：预热研究访问或外部站点登录态：

```bash
uv run python scripts/open_browser_for_login.py
```

## 工作流模型

```text
飞书事件
  -> Feishu 翻译层
  -> 常驻主 Agent 会话
  -> WorkflowInvocation
  -> 后台任务管理器
  -> 专项模块图
  -> ResultEnvelope[DeliveryPackage]
  -> 飞书交付
```

图片路线的标准模块图为：

```text
ResearchModule
  -> GroupingModule
  -> ContentModule
  -> ImageModule
  -> ReviewDeliveryModule
```

其中 `ImageModule` 内部包含 ReferenceAnalysis、ImagePlanner、并发 ImageTaskSubgraph、ImageJoin 和 ImageSetReview。每个单图任务再包含 Prompt、Generation、Review 和 Retry 边界。

## 架构模型

```text
xiaohongshu-agent/
├── .agents/
│   ├── skills/                 # Skill Protocol 文档和检查清单
│   └── prompt/                 # 版本化 Prompt 模板库
├── src/
│   ├── apps/feishu_agent_os/   # 正式 Feishu 常驻入口
│   ├── agent_os/               # 主 Agent、工具注册、任务管理、会话运行时
│   ├── agents/                 # 原子专项 Agent
│   ├── orchestration/          # WorkflowInvocation、模块图、路线编排
│   ├── config/                 # 默认配置与环境变量读取
│   └── utils/                  # Provider、飞书通知、浏览器和文件工具
├── scripts/                    # 登录预热、服务辅助和开发脚本
├── tests/                      # 单元、契约和集成测试
├── docs/                       # 设计说明和工作流笔记
└── requirements/               # 可选依赖集合
```

## 设计原则

- 主 Agent 是调度中心，不做单体 Graph。
- 专项 Agent 做通用能力，不做一次性产品线逻辑。
- 用户要求进入 `WorkflowInvocation.run_options`、`constraints`、`preferences` 或 artifacts。
- 配置文件只提供默认值，飞书对话里明确指定的参数优先。
- 文件路径不是独立协议，只能作为 `ArtifactRef` 进入 envelope。
- 登录能力只服务研究和访问，不服务平台发布。
- 小红书风格表示内容形态，不表示自动提交到小红书。

## 测试

运行全量测试：

```bash
uv run pytest
```

关键测试覆盖 Feishu Agent OS、`ResultEnvelope`、模块图契约、Prompt 模板库、Skill 发现、图片规划、参考图角色、后台任务并发与恢复，以及 Feishu-first 架构边界。

## 安全与密钥

- 真实凭证只放在 `.env` 或本机环境变量中。
- 不要提交 `.env`、service-account 文件、私钥、浏览器 session、生成产物或下载媒体。
- `.env.example` 只保留占位符。
- 如果某些 key 曾经用于本地实验，公开部署前应在服务后台撤销或轮换。
- 飞书 chat id、浏览器 session、Android 设备标识都应视为私有运行数据。

## 相关文档

- [English README](README.md)
- [Article research workflow notes](docs/article_post_research_workflow/README.md)
- [Android QR login notes](docs/android-qr-login-agent-notes.md)
- [Logfire query notes](docs/logfire-query.md)

## 许可证

当前仓库没有包含许可证文件。这意味着仓库是公开可见的，但还没有通过标准开源许可证授予复用、再分发或派生作品权利。
