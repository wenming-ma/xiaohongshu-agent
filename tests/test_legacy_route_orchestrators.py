from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.article_post.schemas import XHSArticlePostOutput
from src.agents.video_post.schemas import XHSVideoPostOutput
from src.orchestration.conversation import ConversationRequest
from src.orchestration.legacy_routes import ArticlePostOrchestrator, VideoPostOrchestrator


class FakeArticlePipeline:
    async def execute(self, input_data) -> XHSArticlePostOutput:
        topic_path = input_data.topic.splitlines()[0].removeprefix("主题：")
        output_dir = Path(topic_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "content.json").write_text(
            json.dumps(
                {
                    "rendered_body": "这是一篇整理后的长文正文。",
                    "hashtags": ["知识点", "整理"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        image_path = output_dir / "cover.png"
        image_path.write_bytes(b"fake-image")
        return XHSArticlePostOutput(
            success=True,
            title="长文整理范式",
            body_preview="这是一篇整理后的长文正文。",
            hashtags=["知识点", "整理"],
            image_count=1,
            image_paths=[str(image_path)],
            published=False,
            output_dir=str(output_dir),
        )


class FakeVideoPipeline:
    async def execute(self, input_data) -> XHSVideoPostOutput:
        topic_path = input_data.topic.splitlines()[0].removeprefix("主题：")
        output_dir = Path(topic_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "content.json").write_text(
            json.dumps(
                {
                    "body": "这是一条视频笔记的正文整理。",
                    "hashtags": ["视频", "混剪"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        video_path = output_dir / "clip.mp4"
        video_path.write_bytes(b"fake-video")
        return XHSVideoPostOutput(
            success=True,
            title="视频混剪灵感整理",
            body_preview="这是一条视频笔记的正文整理。",
            hashtags=["视频", "混剪"],
            video_path=str(video_path),
            published=False,
            output_dir=str(output_dir),
        )


class FakeSender:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, envelope, chat_id: str | None = None) -> None:
        self.sent.append((envelope, chat_id))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_article_post_orchestrator_wraps_pipeline_output_into_delivery_envelope(tmp_path: Path) -> None:
    sender = FakeSender()
    orchestrator = ArticlePostOrchestrator(
        workspace_root=tmp_path,
        delivery_sender=sender,
        pipeline_factory=FakeArticlePipeline,
    )

    result = await orchestrator.run(
        ConversationRequest(topic=str(tmp_path / "article-source"), audience="职场新人"),
        run_id="run-article-1",
        chat_id="chat-article",
        send_to_feishu=True,
    )

    assert result.payload is not None
    assert result.payload.route == "article_post"
    assert result.payload.title == "长文整理范式"
    assert len(result.payload.artifacts) == 1
    assert result.payload.artifacts[0].artifact_type == "image"
    assert sender.sent[0][1] == "chat-article"


@pytest.mark.anyio
async def test_video_post_orchestrator_wraps_pipeline_output_into_delivery_envelope(tmp_path: Path) -> None:
    sender = FakeSender()
    orchestrator = VideoPostOrchestrator(
        workspace_root=tmp_path,
        delivery_sender=sender,
        pipeline_factory=FakeVideoPipeline,
    )

    result = await orchestrator.run(
        ConversationRequest(topic=str(tmp_path / "video-source"), audience="剪辑新手"),
        run_id="run-video-1",
        chat_id="chat-video",
        send_to_feishu=True,
    )

    assert result.payload is not None
    assert result.payload.route == "video_post"
    assert result.payload.title == "视频混剪灵感整理"
    assert len(result.payload.artifacts) == 1
    assert result.payload.artifacts[0].artifact_type == "video"
    assert sender.sent[0][1] == "chat-video"
