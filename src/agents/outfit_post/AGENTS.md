# Outfit Post 流水线

小红书穿搭搭配图文流水线，核心目标是先确定单品与参考图，再围绕这些单品生成研究、内容、配图和发布结果。

## 工作流

```text
pipeline.py (OutfitPostPipeline.execute)
    │
    ├── discuss/   → DiscussAgent.forward()   # 讨论搭配单品、风格方向、收集参考图
    ├── research/  → ResearchAgent.forward()  # 研究穿法灵感
    ├── image/     → ImageAgent.compute_groups() / forward()  # 语义分组 + 配图生成
    ├── content/   → ContentAgent.forward()   # 创作标题、正文、话题
    └── publish/   → PublisherAgent.forward() # 发布到小红书
```

## 目录约定

- phase 目录保持职责边界清晰：`discuss/`、`research/`、`content/`、`image/`、`publish/`
- pipeline 专用 helper 统一放在 `src/agents/outfit_post/utils/`
- 不在 phase 目录下新增 `utils.py`
- 共享业务能力放 `src/agents/shared/utils/`
- `src/utils` 仅保留 infra 能力，如 provider、日志、重试、文件操作、飞书通知

## 关键数据流

1. `DiscussAgent` 先确定 `OutfitItem[]`
2. 再收集 `ReferenceImageResult`，按 `item_name -> image_paths` 组织
3. `build_research_topic()` 用单品列表和可选 `topic_hint` 生成研究主题
4. `ImageAgent.compute_groups()` 基于研究结果分组，并把有参考图的单品名映射到 `ref_items`
5. `ImageAgent.forward()` 再按 `ref_items` 将参考图传入最终图片生成

## 关键规则

1. **先保单品与参考图，再动后续 phase**：`discuss/` 是整个流水线的输入边界，后续 phase 不要绕过它私自重建单品或参考图状态。
2. **参考图始终按物品组织**：不要把参考图直接绑死到研究分组；分组阶段只分配 `ref_items`，真正图片路径仍保留在 `ReferenceImageResult`。
3. **多轮飞书交互要注意 phase 边界**：`DiscussAgent` 的文本/图片输入是多轮对话状态，修改 notifier 或交互流程时要避免旧消息、旧图片泄漏到新一轮执行。
4. **提示词只放 `prompts.py`**：phase 内的 system/user prompt 模板统一放本目录的 `prompts.py`。
5. **validator 放 `validator.py`**：研究和图片审核逻辑放各自 phase 的 `validator.py`，不要把 reviewer agent 直接塞回主 `agent.py` 的业务流程里。
6. **模型统一从 providers 获取**：通过 `src/utils/providers` 获取模型，不要在 phase 中硬编码模型名。
7. **pipeline 决定降级与继续**：跨 phase 的跳过、降级、重试策略归 `pipeline.py` 或 orchestration helper，单个 agent 只处理本阶段闭环。

## 文件结构约定

| 文件 | 职责 |
|------|------|
| `agent.py` | phase 主逻辑 |
| `prompts.py` | 提示词模板 |
| `state.py` | phase 状态（如有） |
| `validator.py` | phase 验证器（如有） |
| `tools.py` | 子工具（如有） |

`src/agents/outfit_post/utils/`：
- `research.py`：研究结果整理与持久化 helper
- `content.py`：内容阶段反馈与上下文 helper
- `image.py`：分组参数、image spec 转换等 helper

## 设计约束

- `topic` 对 outfit_post 是可选的；当用户未提供时，由 `discuss/` 阶段补问风格方向
- 输出目录下的 `discuss.json`、`research.json`、`groups.json`、`content.json`、`image.json`、`publish.json` 是排障和回溯的主依据
- 修改参考图链路时，优先检查 `ReferenceImageResult.get_image_map()`、`get_item_names_with_images()`、`groups_to_image_specs()`、图片生成入参是否仍然连通
