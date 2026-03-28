# Styled Image 流水线

带参考图与风格控制的图文配图流水线。

## 工作流

```text
pipeline.py (StyledImagePostPipeline.execute)
    │
    ├── collect/   → CollectAgent.forward()
    ├── research/  → ResearchAgent.forward()
    ├── content/   → ContentAgent.forward()
    ├── image/     → ImageAgent.forward()
    └── publish/   → PublisherAgent.forward()
```

## 目录约定

- phase 保持各自职责边界
- `src/agents/styled_image_post/utils/` 承载本流水线专用 helper
- 不在 `collect/`、`research/`、`content/`、`image/` 目录下继续新增 `utils.py`

## 代码规范

- pipeline 专用 helper 放本 pipeline 根下的 `utils/`
- 参考图后处理、图片压缩、导航追踪等跨 pipeline 业务 helper 放 `src/agents/shared/utils/`
- `src/utils` 仅保留 infra
