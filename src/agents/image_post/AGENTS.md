# XHS 图文帖子工具

小红书图文帖子创作和发布工具。

## 工作流

```
tool.py (XHSImagePostTool.execute)
    │
    ├── research/  → ResearchAgent.forward()   # 研究主题
    ├── content/   → ContentAgent.forward()    # 创作内容
    ├── image/     → ImageAgent.forward()      # 生成图片
    └── publish/   → PublisherAgent.forward()  # 发布帖子
```

共享能力不放在 `image_post/` 内：
- `src/tools/xiaohongshu/shared/login/` 供 research 和 publish 复用登录能力
- `src/tools/xiaohongshu/shared/video_extract/` 供 research 复用视频直链提取与转录能力

## 各 Agent 文件结构

每个 Agent 目录遵循统一结构：

| 文件 | 职责 |
|------|------|
| `agent.py` | Agent 主类 |
| `prompts.py` | 提示词模板 |
| `state.py` | 状态管理（如有） |
| `utils.py` | 工具函数（如有） |
| `validator.py` | 验证器（如有） |
| `tools.py` | 子工具（如有） |

## 调用方式

```python
from src.tools.xiaohongshu.image_post import XHSImagePostTool

tool = XHSImagePostTool()
result = await tool.execute(XHSImagePostInput(
    topic="西安美食推荐",
    audience="本地吃货",
    generate_image=True,
    publish=True
))
```
