from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.article_post.schemas import (
    ArticleBlock,
    ArticleBlockType,
    ArticleClaim,
    ArticleImageResult,
    ArticleResearchResult,
    ArticleSection,
    ArticleSource,
    ArticleSourceType,
    ArticleStrategy,
    GeneratedArticleImage,
    XHSArticleContent,
)
from src.agents.video_post.schemas import (
    CoverImageResult,
    DownloadResult,
    EngagementMetrics,
    Platform,
    VideoResearchResult,
    VideoSource,
    XHSVideoContent,
)
from src.orchestration.article_route import ArticlePostOrchestrator
from src.orchestration.conversation import ConversationRequest
from src.orchestration.video_route import VideoPostOrchestrator


class FakeArticleResearchAgent:
    async def forward(
        self,
        topic: str,
        target_audience: str,
        strategy: ArticleStrategy,
        output_dir: Path | None = None,
    ) -> ArticleResearchResult:
        return ArticleResearchResult(
            summary=f"{topic} 的研究摘要",
            sources=[
                ArticleSource(
                    source_ref="src-1",
                    source_type=ArticleSourceType.ARTICLE,
                    url="https://example.com/article",
                    domain="example.com",
                    title="source title",
                )
            ],
            claims=[ArticleClaim(claim="关键论点", source_refs=["src-1"])],
            keywords=["知识点"],
        )


class FakeArticleContentAgent:
    async def forward(
        self,
        research: ArticleResearchResult,
        topic: str,
        target_audience: str,
        requested_strategy: ArticleStrategy,
        generate_images: bool,
        output_dir: Path | None = None,
    ) -> XHSArticleContent:
        return XHSArticleContent(
            title="长文整理范式",
            lead="这是一段足够长的导语，用来说明这篇长文为什么值得在飞书里审核。",
            sections=[
                ArticleSection(
                    heading="第一章",
                    summary="核心观点",
                    blocks=[
                        ArticleBlock(
                            block_type=ArticleBlockType.PARAGRAPH,
                            text="这是一段正文。",
                        )
                    ],
                ),
                ArticleSection(
                    heading="第二章",
                    summary="执行建议",
                    blocks=[
                        ArticleBlock(
                            block_type=ArticleBlockType.IMAGE_SLOT,
                            image_key="section_2",
                        )
                    ],
                ),
            ],
            closing="最后给出一个明确的收束。",
            hashtags=["知识点", "整理"],
            rendered_body="这是一篇整理后的长文正文。",
        )


class FakeArticleImageAgent:
    async def forward(
        self,
        content: XHSArticleContent,
        research: ArticleResearchResult,
        topic: str,
        target_audience: str,
        output_dir: Path,
    ):
        image_path = output_dir / "cover.png"
        image_path.write_bytes(b"fake-image")
        return ArticleImageResult(
            images=[
                GeneratedArticleImage(
                    image_key="cover",
                    image_path=str(image_path),
                    prompt_used="prompt",
                )
            ],
            total_count=1,
        )


class FakeVideoResearchAgent:
    async def forward(
        self,
        topic: str,
        platforms: list[Platform],
        max_videos: int = 5,
        output_dir: Path | None = None,
    ) -> VideoResearchResult:
        return VideoResearchResult(
            topic=topic,
            summary=f"{topic} 视频研究完成",
            sources=[
                VideoSource(
                    url="https://example.com/video",
                    platform=Platform.YOUTUBE,
                    title="video title",
                    engagement=EngagementMetrics(likes=10),
                )
            ],
            keywords=["视频"],
        )


class FakeDownloadAgent:
    async def forward(
        self,
        sources: list[VideoSource],
        output_dir: Path,
        topic: str = "",
        preselect_top_k: int = 3,
    ) -> DownloadResult:
        video_path = output_dir / "clip.mp4"
        video_path.write_bytes(b"fake-video")
        return DownloadResult(
            success=True,
            source=sources[0],
            local_path=str(video_path),
            file_size_bytes=10,
            format="mp4",
        )


class FakeVideoContentAgent:
    async def forward(
        self,
        research: VideoResearchResult,
        video_source: VideoSource,
        topic: str,
        transcript=None,
    ) -> XHSVideoContent:
        return XHSVideoContent(
            title="视频混剪灵感整理方案",
            body=(
                "这是一条视频笔记的正文整理，已经足够长，可以作为飞书交付包里的正文内容。"
                "它会说明视频亮点、用户保存理由、二次剪辑角度和发布时可以使用的话题方向。"
            ),
            hashtags=["视频", "混剪"],
            call_to_action="保存后再看。",
        )


class FakeCoverAgent:
    async def forward(
        self,
        video_path: Path,
        content: XHSVideoContent,
        topic: str,
        output_dir: Path,
    ):
        cover_path = output_dir / "cover.png"
        cover_path.write_bytes(b"fake-cover")
        return CoverImageResult(success=True, cover_path=str(cover_path))


class FakeSender:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, envelope, chat_id: str | None = None) -> None:
        self.sent.append((envelope, chat_id))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_article_post_orchestrator_runs_specialist_agents_into_delivery_envelope(tmp_path: Path) -> None:
    sender = FakeSender()
    orchestrator = ArticlePostOrchestrator(
        workspace_root=tmp_path,
        delivery_sender=sender,
        research_agent_factory=FakeArticleResearchAgent,
        content_agent_factory=FakeArticleContentAgent,
        image_agent_factory=FakeArticleImageAgent,
    )

    result = await orchestrator.run(
        ConversationRequest(topic="长文整理", audience="职场新人"),
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
async def test_video_post_orchestrator_runs_specialist_agents_into_delivery_envelope(tmp_path: Path) -> None:
    sender = FakeSender()
    orchestrator = VideoPostOrchestrator(
        workspace_root=tmp_path,
        delivery_sender=sender,
        research_agent_factory=FakeVideoResearchAgent,
        download_agent_factory=FakeDownloadAgent,
        content_agent_factory=FakeVideoContentAgent,
        cover_agent_factory=FakeCoverAgent,
    )

    result = await orchestrator.run(
        ConversationRequest(topic="视频混剪灵感", audience="剪辑新手"),
        run_id="run-video-1",
        chat_id="chat-video",
        send_to_feishu=True,
    )

    assert result.payload is not None
    assert result.payload.route == "video_post"
    assert result.payload.title == "视频混剪灵感整理方案"
    assert [artifact.artifact_type for artifact in result.payload.artifacts] == ["video", "image"]
    assert sender.sent[0][1] == "chat-video"
