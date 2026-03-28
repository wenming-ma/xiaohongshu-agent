# XHS 长文工具

小红书长文创作和发布工具。

## 工作流

```text
pipeline.py (XHSArticlePostPipeline.execute)
    │
    ├── research/  → ResearchAgent.forward()   # 跨站深度研究（文章 + 视频）
    ├── content/   → ContentAgent.forward()    # 长文创作 / 搬运改写
    ├── image/     → ImageAgent.forward()      # 头图和章节配图
    └── publish/   → PublisherAgent.forward()  # 发布到小红书长文编辑器
```

## 各 Agent 文件结构

`article_post` 的 phase 目录遵循统一结构，helper 统一收口到 pipeline 根下 `utils/`：

| 文件 | 职责 |
|------|------|
| `agent.py` | Agent 主类：`init_agent()` 创建生成器，`init_validators()` 创建验证器，`forward()` / `step()` / `validate()` 驱动工作流 |
| `prompts.py` | 纯提示词常量 + `render_template` 薄包装函数，不含业务逻辑 |
| `state.py` | 运行时状态 dataclass |
| `validator.py` | 验证器类，继承 `InternalValidator`，内部懒加载创建 reviewer Agent |
| `tools.py` | 子工具（如有） |

`src/agents/article_post/utils/`：
- `research.py`：research phase 的持久化和数据整理 helper
- `publish.py`：长文编辑器注入脚本和确定性 publish helper

### 关键规则

1. **提示词只在 `prompts.py`**：所有 system prompt 常量、user prompt 模板、`render_template` 包装函数都放在 `prompts.py`。不在 `agent.py` 或 `validator.py` 中硬编码提示词。
2. **验证器在 `validator.py`**：审核用的 Agent 实例由 validator 类自己创建和管理（懒加载 `@property`），不在 `agent.py` 的 `init_agent()` 中创建。`agent.py` 通过 `init_validators()` 实例化验证器，`validate()` 委托给验证器。
3. **业务 helper 不进 `src/utils`**：`article_post` 专用 helper 放 `src/agents/article_post/utils/`；跨 pipeline 复用的业务 helper 放 `src/agents/shared/utils/`。
4. **模型获取用 `get_text_model()`**：统一从 `src/utils/providers` 获取模型，不硬编码模型名。

当前状态：
- `research/validator.py` 负责长文研究阶段的规则校验和多维审核，失败反馈会回流到下一轮 research。

## 设计约束

- 研究源以海外女性向数字媒体为主，不以小红书站内研究为主。
- 视频信息优先复用本地音频转录链路。
- 浏览器登录态统一复用 `browser-sessions/shared`。
- 不直接跨工具依赖 `image_post` / `video_post` 的业务 schema。
