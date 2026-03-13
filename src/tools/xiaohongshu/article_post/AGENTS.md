# XHS 长文工具

小红书长文创作和发布工具。

## 工作流

```text
tool.py (XHSArticlePostTool.execute)
    │
    ├── research/  → ResearchAgent.forward()   # 跨站深度研究（文章 + 视频）
    ├── content/   → ContentAgent.forward()    # 长文创作 / 搬运改写
    ├── image/     → ImageAgent.forward()      # 头图和章节配图
    └── publish/   → PublisherAgent.forward()  # 发布到小红书长文编辑器
```

## 设计约束

- 研究源以海外女性向数字媒体为主，不以小红书站内研究为主。
- 视频信息优先复用本地 Whisper 转录链路。
- 浏览器登录态统一复用 `browser-sessions/shared`。
- 不直接跨工具依赖 `image_post` / `video_post` 的业务 schema。
