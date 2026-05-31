# Video Post Agents

Video post is a formal route for sourcing, processing, scripting, and packaging
video-based content for Feishu review.

## Phases

- `research/`: finds candidate videos for a topic.
- `download/`: selects, downloads, transcribes, and subtitles source video.
- `content/`: writes the Xiaohongshu-style video note copy.
- `cover/`: generates a cover image from frames and content context.
- `utils/`: video-specific helpers for frames, dubbing, subtitles, and TTS.

## Boundaries

- Feishu orchestration is handled by `src/orchestration/video_route.py`.
- Downloaded video and cover image files are exposed as `ArtifactRef` entries.
- Final output is a `DeliveryPackage` envelope for Feishu review.
