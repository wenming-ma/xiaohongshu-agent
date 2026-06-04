# 小红书风格内容 Agent OS

这是一个 Feishu-first 的内容创作系统。用户通过飞书和常驻主 Agent 对话，主 Agent 负责理解目标、追问缺失信息、选择 Skill 和 Prompt 模板，并把任务启动为后台专项工作流。最终交付统一回到飞书，不直接向小红书发布。

## 核心能力

- **常驻主 Agent**：持续接收飞书文本、图片、按钮和快捷操作，负责对话、任务规划和后台任务管理。
- **原子专项 Agent**：Research、Grouping、Content、Image、Video、Article、Login、ReviewDelivery 等能力保持专项职责，通过模块节点或子图组合。
- **统一数据协议**：跨 Agent 信息使用 `WorkflowInvocation`、`WorkflowState` 和 `ResultEnvelope`；文件与图片只作为 envelope artifacts 暴露。
- **Skill 与 Prompt 模板**：`.agents/skills/` 保存经验、流程和检查清单；`.agents/prompt/` 保存版本化提示词模板。选择过程由 Agent 根据语义完成，不靠关键词表。
- **飞书交付**：所有正式内容都生成 `DeliveryPackage` 并发送到飞书，供用户审核、下载或继续反馈。

## 项目结构

```text
xiaohongshu-agent/
├── .agents/
│   ├── skills/                 # Skill Protocol 文档
│   └── prompt/                 # 版本化 Prompt 模板库
├── src/
│   ├── apps/feishu_agent_os/   # 正式 Feishu 常驻入口
│   ├── agent_os/               # 主 Agent、工具注册、任务管理、会话运行时
│   ├── agents/                 # 原子专项 Agent
│   ├── orchestration/          # WorkflowInvocation、模块图、路线编排
│   ├── config/                 # 默认配置与密钥读取
│   └── utils/                  # Provider、飞书通知、浏览器和文件工具
├── scripts/                    # 登录预热、服务辅助和开发脚本
├── tests/                      # 单元、契约和集成测试
├── output/                     # 运行日志、会话缓存、临时产物
└── posts/                      # 工作流生成的本地产物
```

## 运行方式

安装依赖：

```bash
uv sync
```

配置 `.env`，至少提供飞书和模型相关密钥。图片生成默认走 Vertex/Gemini 配置，飞书服务通过 `FEISHU_CHAT_ID` 指定目标会话。

预热研究访问或外部站点登录态：

```bash
uv run python scripts/open_browser_for_login.py
```

启动正式常驻服务：

```bash
uv run python -m src.apps.feishu_agent_os.serve
```

主 Agent 会通过飞书接收用户输入。用户可以随意描述主题、风格、图片数量、参考图片、元素迁移、订阅主题或自主探索需求；缺少关键信息时，主 Agent 使用飞书工具发送点选或多选交互。

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

其中 ImageModule 内部包含 ReferenceAnalysis、ImagePlanner、并发 ImageTaskSubgraph、ImageJoin 和 ImageSetReview。每个单图任务再包含 Prompt、Generation、Review 和 Retry 边界。

## 设计原则

- 主 Agent 是调度中心，不做 Graph。
- 专项 Agent 做通用能力，不做一次性产品线。
- 用户要求进入 `WorkflowInvocation.run_options`、`constraints`、`preferences` 或 artifacts。
- 配置文件只提供默认值，用户在飞书里指定的参数优先。
- 文件路径不是独立协议，只能作为 `ArtifactRef` 进入 envelope。
- 登录能力只服务研究和访问，不服务平台发布。
- 小红书风格表示内容形态，不表示自动提交到小红书。

## 测试

运行全量测试：

```bash
uv run pytest
```

关键测试覆盖 Feishu Agent OS、ResultEnvelope、模块图契约、Prompt 模板库、Skill 发现、图片规划、参考图角色、后台任务并发与恢复，以及 Feishu-first 架构边界。
