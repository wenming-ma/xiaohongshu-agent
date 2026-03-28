# XHS 视频帖子流水线

小红书视频创作、字幕、封面和发布流水线。

## 工作流

```text
pipeline.py (XHSVideoPostPipeline.execute)
    │
    ├── research/  → ResearchAgent.forward()
    ├── download/  → DownloadAgent.forward()
    ├── content/   → ContentAgent.forward()
    ├── cover/     → CoverAgent.forward()
    └── publish/   → PublisherAgent.forward()
```

## 目录约定

- phase 代码继续放在各自目录：`research/`、`download/`、`content/`、`cover/`、`publish/`
- `src/agents/video_post/utils/` 统一承载视频专用 helper，例如配音、字幕 tag、抽帧
- 不在 phase 目录下新增 `utils.py`

## 代码规范

- 视频专用 helper 放 `src/agents/video_post/utils/`
- 跨多个 pipeline 复用的业务 helper 放 `src/agents/shared/utils/`
- `src/utils` 只保留 infra；provider 不做去水印、去 AI 这类业务后处理
