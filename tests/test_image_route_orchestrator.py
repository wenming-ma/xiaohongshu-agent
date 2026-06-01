from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.image_post.schemas import GeneratedImage, ResearchItem, ResearchResult, XHSContent
from src.agents.shared.login import AuthResult
from src.orchestration.conversation import ConversationRequest
from src.orchestration.image_route import ImagePostOrchestrator
from src.orchestration.run_options import ImagePostRunOptions, ImageRunOptions, ResearchRunOptions
from src.orchestration.style_context import StyleContext


class FakeResearchAgent:
    async def forward(self, topic: str, target_audience: str, output_dir: Path | None = None) -> ResearchResult:
        return ResearchResult(
            summary=f"{topic} 调研完成",
            items=[
                ResearchItem(title="look-1", content="纯色背景，单套展示"),
                ResearchItem(title="look-2", content="面料与配色细节"),
            ],
            keywords=["纯色背景", "单套展示"],
            sources=[],
        )


class FakeContentAgent:
    async def forward(
        self,
        research: ResearchResult,
        topic: str,
        groups: list[dict[str, object]] | None = None,
    ) -> XHSContent:
        assert groups is not None
        assert len(groups) == 2
        return XHSContent(
            title="纯色背景通勤穿搭灵感",
            body=(
                "每张图只展示一套穿搭，整体保持纯色背景与强节奏感。"
                "封面突出轮廓与主色调，详情页拆开讲面料、配色、比例和配饰。"
                "整组内容聚焦通勤女生的真实场景，让用户可以快速保存并照着搭配。"
                "文字节奏保持轻快，避免冗长解释，让每张图承担一个明确的信息重点。"
            ),
            hashtags=["穿搭", "纯色背景"],
            call_to_action="喜欢这组的话就继续看下一组。",
        )


class FakeImageAgent:
    compute_group_calls: list[dict[str, object]] = []

    async def compute_groups(
        self,
        research: ResearchResult,
        topic: str,
        *,
        requested_image_count: int | None = None,
        single_item_per_image: bool = False,
    ) -> list[dict[str, object]]:
        assert research.items_count == 2
        self.compute_group_calls.append(
            {
                "requested_image_count": requested_image_count,
                "single_item_per_image": single_item_per_image,
                "topic": topic,
            }
        )
        return [
            {"title": "封面穿搭", "indices": [0]},
            {"title": "细节拆解", "indices": [1]},
        ]

    async def step(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        output_dir: Path,
        image_spec: dict[str, object],
        style_context: StyleContext | None = None,
    ) -> GeneratedImage:
        image_type = str(image_spec["type"])
        if style_context is not None and style_context.hard_constraints:
            assert "纯色背景" in style_context.hard_constraints
        if style_context is not None and style_context.reference_images:
            assert style_context.reference_images[0].label == "reference_1"
        image_path = output_dir / f"{image_type}.png"
        image_path.write_bytes(b"fake-image")
        return GeneratedImage(
            image_path=str(image_path),
            prompt_used=f"prompt:{topic}:{image_type}",
            image_type=image_type,
        )


class FakeSender:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, envelope, chat_id: str | None = None) -> None:
        self.sent.append((envelope, chat_id))


class PreflightResearchAgent(FakeResearchAgent):
    prepare_calls = 0
    forward_calls = 0

    async def prepare_research_access(self) -> AuthResult:
        type(self).prepare_calls += 1
        return AuthResult(
            success=True,
            auth_type="session",
            message="共享 session 已就绪",
            url="https://www.rednote.com/explore",
            timestamp="2026-05-31T00:00:00Z",
        )

    async def forward(self, topic: str, target_audience: str, output_dir: Path | None = None) -> ResearchResult:
        type(self).forward_calls += 1
        assert type(self).prepare_calls == 1
        return await super().forward(topic=topic, target_audience=target_audience, output_dir=output_dir)


class FailedPreflightResearchAgent(FakeResearchAgent):
    prepare_calls = 0
    forward_calls = 0

    async def prepare_research_access(self) -> AuthResult:
        type(self).prepare_calls += 1
        return AuthResult(
            success=False,
            auth_type="login_qr",
            message="需要登录但自动扫码失败",
            url="https://www.rednote.com/explore",
            timestamp="2026-05-31T00:00:00Z",
        )

    async def forward(self, topic: str, target_audience: str, output_dir: Path | None = None) -> ResearchResult:
        type(self).forward_calls += 1
        return await super().forward(topic=topic, target_audience=target_audience, output_dir=output_dir)


class RaisingResearchAgent(FakeResearchAgent):
    async def forward(self, topic: str, target_audience: str, output_dir: Path | None = None) -> ResearchResult:
        raise RuntimeError("Exceeded maximum retries for output validation")


class OptionsRecordingResearchAgent(FakeResearchAgent):
    seen_run_options = None

    def __init__(self, run_options=None) -> None:
        type(self).seen_run_options = run_options


class OptionsRecordingImageAgent(FakeImageAgent):
    seen_run_options = None

    def __init__(self, run_options=None) -> None:
        type(self).seen_run_options = run_options


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_image_post_default_auto_image_cap_is_cover_plus_eight_details() -> None:
    run_options = ImagePostRunOptions()

    assert run_options.max_auto_images == 9


@pytest.mark.anyio
async def test_image_post_orchestrator_runs_real_flow_with_unified_envelopes(tmp_path: Path) -> None:
    sender = FakeSender()
    orchestrator = ImagePostOrchestrator(
        workspace_root=tmp_path,
        delivery_sender=sender,
        research_agent_factory=FakeResearchAgent,
        content_agent_factory=FakeContentAgent,
        image_agent_factory=FakeImageAgent,
    )

    result = await orchestrator.run(
        ConversationRequest(topic="纯色背景穿搭", audience="通勤女生"),
        run_id="run-image-route-1",
        send_to_feishu=True,
        chat_id="chat-demo",
    )

    assert result.status == "success"
    assert result.payload is not None
    assert result.payload.route == "image_post"
    assert result.payload.title == "纯色背景通勤穿搭灵感"
    assert len(result.payload.artifacts) == 3
    assert [artifact.label for artifact in result.payload.artifacts] == [
        "cover",
        "detail_1",
        "detail_2",
    ]

    manifest_path = tmp_path / "run-image-route-1" / "manifest.json"
    assert manifest_path.exists()
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert "research" in manifest_text
    assert "grouping" in manifest_text
    assert "content" in manifest_text
    assert "image-0" in manifest_text
    assert "image-1" in manifest_text
    assert "image-2" in manifest_text
    assert "delivery" in manifest_text

    assert len(sender.sent) == 1
    sent_envelope, sent_chat_id = sender.sent[0]
    assert sent_envelope.step_id == "delivery"
    assert sent_chat_id == "chat-demo"


@pytest.mark.anyio
async def test_image_post_orchestrator_honors_request_image_count_and_requirements(tmp_path: Path) -> None:
    FakeImageAgent.compute_group_calls = []
    orchestrator = ImagePostOrchestrator(
        workspace_root=tmp_path,
        research_agent_factory=FakeResearchAgent,
        content_agent_factory=FakeContentAgent,
        image_agent_factory=FakeImageAgent,
    )

    result = await orchestrator.run(
        ConversationRequest(
            topic="登山穿搭",
            audience="户外新手",
            message="做 2 张图，不要人物，衣服平铺在纯色背景上",
            style_constraints=["纯色背景", "不要人物", "平铺"],
            image_count=2,
        ),
        run_id="run-image-route-constraints",
        send_to_feishu=False,
    )

    assert result.payload is not None
    assert len(result.payload.artifacts) == 2
    assert result.payload.metadata["image_count"] == 2
    requirements = next(block.text for block in result.payload.text_blocks if block.label == "requirements")
    assert "图片数量：2 张" in requirements
    assert "不要人物" in requirements
    assert FakeImageAgent.compute_group_calls[0]["requested_image_count"] == 2


@pytest.mark.anyio
async def test_image_post_orchestrator_passes_single_look_constraint_to_grouping(tmp_path: Path) -> None:
    FakeImageAgent.compute_group_calls = []
    orchestrator = ImagePostOrchestrator(
        workspace_root=tmp_path,
        research_agent_factory=FakeResearchAgent,
        content_agent_factory=FakeContentAgent,
        image_agent_factory=FakeImageAgent,
    )

    result = await orchestrator.run(
        ConversationRequest(
            topic="登山通勤穿搭",
            audience="通勤女生",
            message="做 5 张图，每张图只展示一套穿搭，衣服平铺在纯色背景上",
            style_constraints=["纯色背景", "单套展示", "平铺"],
            image_count=5,
        ),
        run_id="run-image-route-single-look",
        send_to_feishu=False,
    )

    call = FakeImageAgent.compute_group_calls[0]
    assert call["requested_image_count"] == 5
    assert call["single_item_per_image"] is True
    assert result.payload is not None
    assert result.payload.metadata["single_item_per_image"] is True
    requirements = next(block.text for block in result.payload.text_blocks if block.label == "requirements")
    assert "单图单内容：每张图只展示一个主体/一套穿搭" in requirements


@pytest.mark.anyio
async def test_image_post_orchestrator_records_style_context_in_image_artifacts(tmp_path: Path) -> None:
    orchestrator = ImagePostOrchestrator(
        workspace_root=tmp_path,
        research_agent_factory=FakeResearchAgent,
        content_agent_factory=FakeContentAgent,
        image_agent_factory=FakeImageAgent,
    )
    style_context = StyleContext(
        user_constraints=["纯色背景", "不要人物"],
        matched_skills=["pure-color-single-look"],
        prompt_refs=[],
        hard_constraints=["纯色背景", "不要人物"],
        negative_constraints=["不要生成登录弹窗或研究限制说明"],
        trace={"source": "test"},
    )

    result = await orchestrator.run(
        ConversationRequest(
            topic="登山穿搭",
            audience="户外新手",
            style_constraints=["纯色背景", "不要人物"],
            image_count=1,
        ),
        run_id="run-image-route-style-context",
        send_to_feishu=False,
        style_context=style_context,
    )

    assert result.payload is not None
    artifact = result.payload.artifacts[0]
    assert artifact.metadata["style_context"]["matched_skills"] == ["pure-color-single-look"]
    assert artifact.metadata["style_context"]["hard_constraints"] == ["纯色背景", "不要人物"]


@pytest.mark.anyio
async def test_image_post_orchestrator_carries_reference_images_into_style_context_and_artifacts(tmp_path: Path) -> None:
    reference = tmp_path / "reference-outfit.jpg"
    reference.write_bytes(b"reference")
    orchestrator = ImagePostOrchestrator(
        workspace_root=tmp_path,
        research_agent_factory=FakeResearchAgent,
        content_agent_factory=FakeContentAgent,
        image_agent_factory=FakeImageAgent,
    )

    result = await orchestrator.run(
        ConversationRequest(
            topic="参考图通勤穿搭",
            audience="通勤女生",
            message="参考图里的衣服必须出现在生成图里，背景干净",
            style_constraints=["纯色背景"],
            image_count=1,
            reference_images=[str(reference)],
        ),
        run_id="run-image-route-reference",
        send_to_feishu=False,
    )

    assert result.payload is not None
    artifact = result.payload.artifacts[0]
    style_metadata = artifact.metadata["style_context"]
    assert style_metadata["reference_images"][0]["path"] == str(reference)
    assert any("参考图" in item for item in style_metadata["hard_constraints"])
    assert result.payload.metadata["style_context"]["reference_images"][0]["label"] == "reference_1"


@pytest.mark.anyio
async def test_image_post_orchestrator_runs_research_access_preflight_before_research(tmp_path: Path) -> None:
    PreflightResearchAgent.prepare_calls = 0
    PreflightResearchAgent.forward_calls = 0

    orchestrator = ImagePostOrchestrator(
        workspace_root=tmp_path,
        research_agent_factory=PreflightResearchAgent,
        content_agent_factory=FakeContentAgent,
        image_agent_factory=FakeImageAgent,
    )

    result = await orchestrator.run(
        ConversationRequest(topic="纯色背景穿搭", audience="通勤女生"),
        run_id="run-image-route-auth",
        send_to_feishu=False,
    )

    assert result.status == "success"
    assert PreflightResearchAgent.prepare_calls == 1
    assert PreflightResearchAgent.forward_calls == 1

    manifest_text = (tmp_path / "run-image-route-auth" / "manifest.json").read_text(encoding="utf-8")
    assert "research_access" in manifest_text


@pytest.mark.anyio
async def test_image_post_orchestrator_stops_when_research_access_preflight_fails(tmp_path: Path) -> None:
    FailedPreflightResearchAgent.prepare_calls = 0
    FailedPreflightResearchAgent.forward_calls = 0

    orchestrator = ImagePostOrchestrator(
        workspace_root=tmp_path,
        research_agent_factory=FailedPreflightResearchAgent,
        content_agent_factory=FakeContentAgent,
        image_agent_factory=FakeImageAgent,
    )

    result = await orchestrator.run(
        ConversationRequest(topic="纯色背景穿搭", audience="通勤女生"),
        run_id="run-image-route-auth-failed",
        send_to_feishu=False,
    )

    assert result.status == "error"
    assert "登录预检失败" in result.summary
    assert FailedPreflightResearchAgent.prepare_calls == 1
    assert FailedPreflightResearchAgent.forward_calls == 0

    manifest_text = (tmp_path / "run-image-route-auth-failed" / "manifest.json").read_text(encoding="utf-8")
    assert "research_access" in manifest_text
    assert '"step_id": "research"' not in manifest_text


@pytest.mark.anyio
async def test_image_post_orchestrator_passes_run_options_to_specialist_agents(tmp_path: Path) -> None:
    OptionsRecordingResearchAgent.seen_run_options = None
    OptionsRecordingImageAgent.seen_run_options = None
    run_options = ImagePostRunOptions(
        research=ResearchRunOptions(
            min_posts_researched=6,
            validation_max_retries=2,
            min_key_infos=8,
            min_cases=5,
        ),
        image=ImageRunOptions(
            max_retries=2,
            image_size="2K",
            aspect_ratio="3:4",
            reference_mode="gemini_content",
        ),
    )
    orchestrator = ImagePostOrchestrator(
        workspace_root=tmp_path,
        research_agent_factory=OptionsRecordingResearchAgent,
        content_agent_factory=FakeContentAgent,
        image_agent_factory=OptionsRecordingImageAgent,
    )

    result = await orchestrator.run(
        ConversationRequest(
            topic="轻量化测试主题",
            audience="内容团队",
            image_count=1,
            style_constraints=["纯色背景"],
        ),
        run_id="run-image-route-options",
        run_options=run_options,
        send_to_feishu=False,
    )

    assert result.status == "success"
    assert OptionsRecordingResearchAgent.seen_run_options is run_options.research
    assert OptionsRecordingImageAgent.seen_run_options is run_options.image
    assert result.payload is not None
    assert result.payload.metadata["run_options"]["research"]["min_posts_researched"] == 6
    assert result.payload.metadata["run_options"]["image"]["max_retries"] == 2


@pytest.mark.anyio
async def test_image_post_orchestrator_returns_error_envelope_when_specialist_agent_raises(tmp_path: Path) -> None:
    orchestrator = ImagePostOrchestrator(
        workspace_root=tmp_path,
        research_agent_factory=RaisingResearchAgent,
        content_agent_factory=FakeContentAgent,
        image_agent_factory=FakeImageAgent,
    )

    result = await orchestrator.run(
        ConversationRequest(topic="异常调研", audience="内容团队", image_count=1),
        run_id="run-image-route-specialist-error",
        send_to_feishu=False,
    )

    assert result.status == "error"
    assert result.step_id == "workflow"
    assert "Exceeded maximum retries" in (result.error_message or "")
    manifest_text = (tmp_path / "run-image-route-specialist-error" / "manifest.json").read_text(encoding="utf-8")
    assert "workflow-error" in manifest_text
