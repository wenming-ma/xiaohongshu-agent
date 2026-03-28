# XHS 图文帖子流水线

小红书图文帖子创作和发布流水线。

## 工作流

```
pipeline.py (XHSImagePostPipeline.execute)
    │
    ├── research/  → ResearchAgent.forward()   # 研究主题
    ├── content/   → ContentAgent.forward()    # 创作内容
    ├── image/     → ImageAgent.forward()      # 生成图片
    └── publish/   → PublisherAgent.forward()  # 发布帖子
```

共享能力不放在 `image_post/` 内：
- `src/agents/shared/login/` 供 research 和 publish 复用登录能力
- `src/agents/shared/video_extract/` 供 research 复用视频直链提取与转录能力

## 各 Agent 文件结构

`image_post` 的 phase 目录遵循统一结构，helper 统一收口到 pipeline 根下 `utils/`：

| 文件 | 职责 |
|------|------|
| `agent.py` | Agent 主类 |
| `prompts.py` | 提示词模板 |
| `state.py` | 状态管理（如有） |
| `validator.py` | 验证器（如有） |
| `tools.py` | 子工具（如有） |

`src/agents/image_post/utils/`：
- `research.py`：research 结果持久化与合并
- `content.py`：content phase 的反馈构建 helper
- `image.py`：图片分组和图片规格转换 helper

## 代码规范

- `image_post` 专用 helper 一律放 `src/agents/image_post/utils/`，不在 phase 目录新增 `utils.py`
- 跨 pipeline 复用但仍然带业务语义的 helper 放 `src/agents/shared/utils/`
- `src/utils` 只保留 providers、日志、prompting、重试、文件操作等 infra 代码

## 调用方式

```python
from src.agents.image_post import XHSImagePostPipeline

pipeline = XHSImagePostPipeline()
result = await pipeline.execute(XHSImagePostInput(
    topic="西安美食推荐",
    audience="本地吃货",
    generate_image=True,
    publish=True
))
```
