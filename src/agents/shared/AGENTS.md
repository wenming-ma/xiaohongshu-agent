# Shared Agents

供多个业务流水线复用的共享 agent、tool 和业务 helper。

## 目录约定

- `login/`、`video_extract/` 等共享能力保持独立目录
- `src/agents/shared/utils/` 用于跨多个 pipeline 复用、但仍带业务语义的 helper
- 不把这类业务 helper 放回 `src/utils`

## 代码规范

- `src/agents/shared/utils/` 适合放转录、图片压缩、导航追踪、Playwright artifact 保护、图片后处理等业务共享能力
- `src/utils` 只用于 provider、logger、prompting、retry、file_ops、通知器等基础 infra
- shared agent 自身仍应保持单一职责，不承担完整 pipeline 编排

## 共享工具

| 文件 | 职责 |
|------|------|
| `utils/message_history.py` | `truncate_history_by_rounds()` — 按轮次截断 message history，自动处理 tool call/return 配对。审核修订循环必须使用，见 `src/core/AGENTS.md` |
