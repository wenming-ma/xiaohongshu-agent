from __future__ import annotations

import pytest

from src.agent_os.schemas import ImageRunOptionsSpec, ResearchRunOptionsSpec, RunOptions, TaskRunSpec
from src.agent_os.specialist_tools import (
    build_route_tool_registry,
    conversation_request_from_task_spec,
    workflow_invocation_from_task_spec,
)
from src.agent_os.tools import AgentToolContext
from src.orchestration.conversation import ContentRoute, ConversationRequest
from src.orchestration.run_options import ArticlePostRunOptions, ImagePostRunOptions, VideoPostRunOptions
from src.orchestration.schemas import ArtifactRef, DeliveryPackage, ResultEnvelope
from src.config.settings import ArticleResearchConfig, ImageConfig, ResearchConfig


class FakeRouteRunner:
    def __init__(self, route: str) -> None:
        self.route = route
        self.calls = []

    async def run(self, request, **kwargs):
        self.calls.append({"request": request, "kwargs": kwargs})
        return ResultEnvelope[DeliveryPackage].success(
            agent_name=f"{self.route}_runner",
            payload=DeliveryPackage(
                route=self.route,
                title=request.topic,
                summary="done",
            ),
            summary="done",
            run_id=kwargs["run_id"],
            step_id="delivery",
        )


def test_conversation_request_from_task_spec_preserves_runtime_requirements() -> None:
    spec = TaskRunSpec(
        objective="做留学图文",
        route=ContentRoute.IMAGE_POST,
        topic="出国留学",
        audience="准留学生",
        user_requirements=["用户原始消息：新图主体必须包含米色笔记本和银色钥匙，不要数据线"],
        style_constraints=["末日废土风格"],
        run_options=RunOptions(image=ImageRunOptionsSpec(count=10, concurrency=2)),
    )

    request = conversation_request_from_task_spec(spec)

    assert isinstance(request, ConversationRequest)
    assert request.topic == "出国留学"
    assert request.audience == "准留学生"
    assert request.style_constraints == ["末日废土风格"]
    assert request.image_count == 10
    assert "做留学图文" in request.message
    assert "新图主体必须包含米色笔记本和银色钥匙，不要数据线" in request.message


def test_workflow_invocation_from_task_spec_carries_dynamic_context() -> None:
    spec = TaskRunSpec(
        objective="把参考图里的帽子和衣服迁移到通勤场景",
        route=ContentRoute.IMAGE_POST,
        topic="通勤穿搭",
        audience="上班族",
        user_requirements=["用户原始消息：新图主体必须包含米色笔记本和银色钥匙，不要数据线"],
        constraints=["strict_object_transfer"],
        style_constraints=["真实摄影"],
        selected_skills=["reference-image-product-alignment"],
        selected_prompt_templates=["image/reference/object-transfer"],
        reference_images=[
            ArtifactRef(artifact_type="image", label="hat", path="C:/tmp/hat.png"),
        ],
    )

    invocation = workflow_invocation_from_task_spec(spec)

    assert invocation.route == "image_post"
    assert invocation.objective == "把参考图里的帽子和衣服迁移到通勤场景"
    assert invocation.user_requirements == [
        "用户原始消息：新图主体必须包含米色笔记本和银色钥匙，不要数据线"
    ]
    assert invocation.constraints == ["strict_object_transfer", "真实摄影"]
    assert invocation.selected_skills == ["reference-image-product-alignment"]
    assert invocation.selected_prompt_templates == ["image/reference/object-transfer"]
    assert invocation.artifacts[0].path == "C:/tmp/hat.png"


@pytest.mark.anyio
async def test_route_tool_registry_executes_image_route_with_spec_params() -> None:
    image_runner = FakeRouteRunner("image_post")
    registry = build_route_tool_registry(image_runner=image_runner)
    spec = TaskRunSpec(
        objective="做留学图文",
        route=ContentRoute.IMAGE_POST,
        topic="出国留学",
        audience="准留学生",
        style_constraints=["末日废土风格"],
        run_options=RunOptions(image=ImageRunOptionsSpec(count=10, concurrency=2)),
    )

    result = await registry.execute(
        "execute_image_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        spec=spec.model_dump(mode="json"),
    )

    assert result.envelope.payload is not None
    assert result.envelope.payload.route == "image_post"
    assert image_runner.calls[0]["request"].image_count == 10
    assert image_runner.calls[0]["kwargs"]["workflow_invocation"].objective == "做留学图文"
    assert image_runner.calls[0]["kwargs"]["workflow_invocation"].route == "image_post"
    assert image_runner.calls[0]["kwargs"]["send_to_feishu"] is True
    assert image_runner.calls[0]["kwargs"]["chat_id"] == "chat-1"


@pytest.mark.anyio
async def test_route_tool_tolerates_agent_extra_context_params() -> None:
    image_runner = FakeRouteRunner("image_post")
    registry = build_route_tool_registry(image_runner=image_runner)

    result = await registry.execute(
        "execute_image_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        spec={"objective": "面试穿搭 5 图", "style_constraints": ["纯色背景"]},
        skill="pure-color-single-look-image-post",
        prompt_template="fashion_flatlay",
    )

    assert result.envelope.status == "success"
    assert image_runner.calls[0]["request"].topic == "面试穿搭 5 图"


@pytest.mark.anyio
async def test_route_tool_adapts_agent_os_run_options_to_image_route_options() -> None:
    image_runner = FakeRouteRunner("image_post")
    registry = build_route_tool_registry(image_runner=image_runner)
    spec = TaskRunSpec(
        objective="做面试通勤穿搭图",
        route=ContentRoute.IMAGE_POST,
        topic="面试通勤穿搭",
        run_options=RunOptions(
            image=ImageRunOptionsSpec(
                count=5,
                concurrency=2,
                size="2K",
                aspect_ratio="3:4",
                model="gemini-3-pro-image-preview",
            )
        ),
    )

    result = await registry.execute(
        "execute_image_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        spec=spec.model_dump(mode="json"),
    )

    route_options = image_runner.calls[0]["kwargs"]["run_options"]
    assert result.envelope.status == "success"
    assert isinstance(route_options, ImagePostRunOptions)
    assert route_options.image_generation_concurrency == 2
    assert route_options.image.model == "gemini-3-pro-image-preview"
    assert route_options.image.image_size == "2K"
    assert route_options.image.aspect_ratio == "3:4"


@pytest.mark.anyio
async def test_route_tool_maps_reference_intent_reference_mode_to_gemini_content() -> None:
    image_runner = FakeRouteRunner("image_post")
    registry = build_route_tool_registry(image_runner=image_runner)
    spec = TaskRunSpec(
        objective="把实物参考图迁移到新场景",
        route=ContentRoute.IMAGE_POST,
        topic="通勤装备平铺",
        run_options=RunOptions(
            image=ImageRunOptionsSpec(reference_mode="object_transfer")
        ),
    )

    result = await registry.execute(
        "execute_image_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        spec=spec.model_dump(mode="json"),
    )

    route_options = image_runner.calls[0]["kwargs"]["run_options"]
    assert result.envelope.status == "success"
    assert route_options.image.reference_mode == "gemini_content"


@pytest.mark.anyio
async def test_route_tool_applies_research_max_items_as_fast_budget() -> None:
    image_runner = FakeRouteRunner("image_post")
    registry = build_route_tool_registry(image_runner=image_runner)
    spec = TaskRunSpec(
        objective="低预算图片实测",
        route=ContentRoute.IMAGE_POST,
        topic="周末徒步轻量装备",
        run_options=RunOptions(research=ResearchRunOptionsSpec(max_items=2)),
    )

    result = await registry.execute(
        "execute_image_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        spec=spec.model_dump(mode="json"),
    )

    route_options = image_runner.calls[0]["kwargs"]["run_options"]
    assert result.envelope.status == "success"
    assert route_options.research.min_posts_researched == 2
    assert route_options.research.validation_max_retries == 2
    assert route_options.research.min_key_infos == 2
    assert route_options.research.min_cases == 2
    assert route_options.research.max_new_posts_per_iteration == 2


@pytest.mark.anyio
async def test_route_tool_applies_research_max_items_to_article_route_options() -> None:
    article_runner = FakeRouteRunner("article_post")
    registry = build_route_tool_registry(article_runner=article_runner)
    spec = TaskRunSpec(
        objective="低预算文章实测",
        route=ContentRoute.ARTICLE_POST,
        topic="雨天通勤包必备清单",
        run_options=RunOptions(research=ResearchRunOptionsSpec(max_items=1)),
    )

    result = await registry.execute(
        "execute_article_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        spec=spec.model_dump(mode="json"),
    )

    route_options = article_runner.calls[0]["kwargs"]["run_options"]
    assert result.envelope.status == "success"
    assert isinstance(route_options, ArticlePostRunOptions)
    assert route_options.research.max_iterations == 1
    assert route_options.research.max_source_pages == 1
    assert route_options.research.min_source_pages == 1
    assert route_options.research.min_unique_domains == 1


@pytest.mark.anyio
async def test_route_tool_applies_research_max_items_to_video_route_options() -> None:
    video_runner = FakeRouteRunner("video_post")
    registry = build_route_tool_registry(video_runner=video_runner)
    spec = TaskRunSpec(
        objective="低预算视频实测",
        route=ContentRoute.VIDEO_POST,
        topic="雨天通勤包必备清单短视频",
        run_options=RunOptions(research=ResearchRunOptionsSpec(max_items=1)),
    )

    result = await registry.execute(
        "execute_video_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        spec=spec.model_dump(mode="json"),
    )

    route_options = video_runner.calls[0]["kwargs"]["run_options"]
    assert result.envelope.status == "success"
    assert isinstance(route_options, VideoPostRunOptions)
    assert route_options.research.max_iterations == 1
    assert route_options.research.max_videos == 1


@pytest.mark.anyio
async def test_route_tool_preserves_default_runtime_options_when_unspecified() -> None:
    image_runner = FakeRouteRunner("image_post")
    article_runner = FakeRouteRunner("article_post")
    video_runner = FakeRouteRunner("video_post")
    registry = build_route_tool_registry(
        image_runner=image_runner,
        article_runner=article_runner,
        video_runner=video_runner,
    )

    await registry.execute(
        "execute_image_post",
        AgentToolContext(run_id="run-image-default"),
        spec={"objective": "默认图文调研", "route": "image_post"},
    )
    await registry.execute(
        "execute_article_post",
        AgentToolContext(run_id="run-article-default"),
        spec={"objective": "默认文章调研", "route": "article_post"},
    )
    await registry.execute(
        "execute_video_post",
        AgentToolContext(run_id="run-video-default"),
        spec={"objective": "默认视频调研", "route": "video_post"},
    )

    image_options = image_runner.calls[0]["kwargs"]["run_options"]
    assert image_runner.calls[0]["request"].image_count is None
    assert image_options.max_auto_images == ImageConfig.MAX_AUTO_IMAGES == 9
    assert image_options.research.min_posts_researched == ResearchConfig.MIN_POSTS_RESEARCHED
    assert image_options.research.validation_max_retries == ResearchConfig.VALIDATION_MAX_RETRIES
    assert image_options.research.min_key_infos == ResearchConfig.MIN_KEY_INFOS
    assert image_options.research.min_cases == ResearchConfig.MIN_CASES

    article_options = article_runner.calls[0]["kwargs"]["run_options"]
    assert article_options.research.max_iterations == ArticleResearchConfig.MAX_ITERATIONS
    assert article_options.research.max_source_pages == ArticleResearchConfig.MAX_SOURCE_PAGES
    assert article_options.research.min_source_pages == ArticleResearchConfig.MIN_SOURCE_PAGES

    video_options = video_runner.calls[0]["kwargs"]["run_options"]
    assert video_options.research.max_iterations == 10
    assert video_options.research.max_videos == 5
    assert video_options.research.min_quality_videos == 10
