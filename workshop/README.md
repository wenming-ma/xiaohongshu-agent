# Workshop

批量创作工作区。按 pipeline 类型分目录组织。

## 目录结构

```text
workshop/
├── image_post/                    # 图文帖子
│   ├── run.py / run.ps1
│   ├── topics.json
│   └── avoid_topics.json
├── article_post/                  # 长文帖子
│   ├── run.py / run.ps1
│   ├── topics.json
│   └── topics_female.json
├── styled_image_post/             # 图文帖子（参考图片模式）
│   ├── run.py / run.ps1
│   └── topics.json
├── video_post/                    # 视频帖子（多平台搜索+下载+发布）
│   ├── run.py / run.ps1
│   └── topics.json
├── mixed/                         # 混合批量（图文+长文）
│   ├── run.py / run.ps1
│   └── .mixed_posts_progress.json
├── topic_research.md
└── README.md
```

## 话题文件格式

```json
[
  {
    "topic": "小个子秋冬穿搭指南",
    "audience": "155-160cm的小个子女生"
  }
]
```

必填 `topic` 和 `audience`。可选字段：`strategy`、`format`、`priority`。

video_post 额外可选字段：`platforms`（数组，如 `["tiktok", "instagram"]`）、`max_videos`（整数）。

## 用法

### Image Post

```powershell
.\workshop\image_post\run.ps1
.\workshop\image_post\run.ps1 -StartIndex 3 -Limit 2
```

```bash
uv run python workshop/image_post/run.py
uv run python workshop/image_post/run.py --start-index 3 --limit 2
```

### Article Post

```powershell
.\workshop\article_post\run.ps1
.\workshop\article_post\run.ps1 -Publish
```

```bash
uv run python workshop/article_post/run.py
uv run python workshop/article_post/run.py --publish
```

### Styled Image Post

通过飞书逐物品收集参考图片，让配图中推荐产品的外观与用户提供的一致。

```powershell
.\workshop\styled_image_post\run.ps1
.\workshop\styled_image_post\run.ps1 -StartIndex 2 -Limit 1
```

```bash
uv run python workshop/styled_image_post/run.py
uv run python workshop/styled_image_post/run.py --start-index 2 --limit 1
```

### Video Post

搜索 X/Instagram/Facebook/TikTok 热门视频，下载后生成小红书适配内容并发布。

```powershell
.\workshop\video_post\run.ps1
.\workshop\video_post\run.ps1 -NoPublish
.\workshop\video_post\run.ps1 -Platforms tiktok,instagram -MaxVideos 3
```

```bash
uv run python workshop/video_post/run.py
uv run python workshop/video_post/run.py --no-publish
uv run python workshop/video_post/run.py --platforms tiktok instagram --max-videos 3
```

### Mixed

```powershell
.\workshop\mixed\run.ps1
.\workshop\mixed\run.ps1 -Reset
```

### 通用参数

| 参数 | 说明 |
|------|------|
| `--start-index N` | 从第 N 个话题开始（1-based） |
| `--limit N` | 最多处理 N 个话题 |
| `--max-retries N` | 单话题最大重试次数（默认 10） |
| `--retry-delay N` | 重试间隔秒数（默认 5） |
| `--sleep N` | 话题间固定休眠秒数 |
| `--no-feishu` | 禁用飞书通知 |

## 输出

产物：`posts/{image,article,video}-posts/<timestamp-topic>/`

汇总：各子目录下 `*_summary_<timestamp>.json` / `*_failed_<timestamp>.json`

## 会话

Playwright 浏览器会话复用 `browser-sessions/shared`。先登录再运行。
