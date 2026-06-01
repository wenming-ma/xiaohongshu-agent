from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.agents.image_post.schemas import (
    GeneratedImage,
    ImageResult,
    ResearchItem,
    ResearchResult,
    XHSContent,
)
from src.orchestration.image_flow import ImageWorkflowDeps, ImageWorkflowRunner
from src.orchestration.schemas import DeliveryPackage, GroupingItem, GroupingResult, ResultEnvelope


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_image_workflow_runner_passes_envelopes_and_joins_parallel_images(tmp_path: Path) -> None:
    seen: list[str] = []

    async def run_research(
        *,
        topic: str,
        audience: str,
        execution_text: str,
        run_id: str,
        workspace_dir: Path,
    ) -> ResultEnvelope[ResearchResult]:
        assert execution_text == topic
        seen.append(f"research:{topic}:{audience}")
        return ResultEnvelope[ResearchResult].success(
            agent_name="research_agent",
            payload=ResearchResult(
                summary="调研完成",
                items=[
                    ResearchItem(title="look-1", content="纯色背景，单套展示"),
                    ResearchItem(title="look-2", content="服装细节特写"),
                ],
                keywords=["纯色背景"],
                sources=[],
            ),
            summary="research ok",
            run_id=run_id,
            step_id="research",
        )

    async def run_grouping(
        *,
        topic: str,
        execution_text: str,
        research: ResultEnvelope[ResearchResult],
        run_id: str,
        workspace_dir: Path,
    ) -> ResultEnvelope[GroupingResult]:
        assert execution_text == topic
        assert research.payload is not None
        seen.append(f"grouping:{topic}")
        return ResultEnvelope[GroupingResult].success(
            agent_name="grouping_agent",
            payload=GroupingResult(
                groups=[
                    GroupingItem(title="封面", indices=[0]),
                    GroupingItem(title="细节", indices=[1]),
                ]
            ),
            summary="grouping ok",
            run_id=run_id,
            step_id="grouping",
        )

    async def run_content(
        *,
        topic: str,
        execution_text: str,
        research: ResultEnvelope[ResearchResult],
        groups: ResultEnvelope[GroupingResult],
        run_id: str,
        workspace_dir: Path,
    ) -> ResultEnvelope[XHSContent]:
        assert execution_text == topic
        assert research.payload is not None
        assert groups.payload is not None
        seen.append(f"content:{topic}")
        return ResultEnvelope[XHSContent].success(
            agent_name="content_agent",
            payload=XHSContent(
                title="纯色背景通勤穿搭灵感",
                body=(
                    "每张图只展示一套穿搭，整体保持纯色背景与强节奏感。"
                    "封面强调轮廓和配色，细节页聚焦面料、配饰与比例。"
                    "整组内容适合通勤女生快速参考，也适合保存后按场景直接复刻。"
                    "文案节奏要短促，信息层级清楚，避免同一张图塞入过多元素。"
                ),
                hashtags=["穿搭", "纯色背景"],
                call_to_action="喜欢的话可以继续看下一组。",
            ),
            summary="content ok",
            run_id=run_id,
            step_id="content",
        )

    async def run_image_group(
        *,
        topic: str,
        execution_text: str,
        group: dict[str, object],
        group_index: int,
        research: ResultEnvelope[ResearchResult],
        content: ResultEnvelope[XHSContent],
        run_id: str,
        workspace_dir: Path,
    ) -> ResultEnvelope[ImageResult]:
        assert execution_text == topic
        assert research.payload is not None
        assert content.payload is not None
        seen.append(f"image:{group_index}:{topic}:{group['image_type']}")
        image_path = workspace_dir / f"group-{group_index}.png"
        image_path.write_bytes(b"fake-image")
        return ResultEnvelope[ImageResult].success(
            agent_name="image_generation_agent",
            payload=ImageResult(
                images=[
                        GeneratedImage(
                            image_path=str(image_path),
                            prompt_used=f"prompt-{group['image_type']}",
                            image_type=str(group["image_type"]),
                        )
                    ],
                    total_count=1,
                    generated_at="2026-05-30T00:00:00+00:00",
                ),
            summary=f"image ok {group['image_type']}",
            run_id=run_id,
            step_id=f"image-{group_index}",
        )

    async def run_delivery(
        *,
        topic: str,
        execution_text: str,
        research: ResultEnvelope[ResearchResult],
        groups: ResultEnvelope[GroupingResult],
        content: ResultEnvelope[XHSContent],
        images: list[ResultEnvelope[ImageResult]],
        run_id: str,
        workspace_dir: Path,
        ) -> ResultEnvelope[DeliveryPackage]:
        assert execution_text == topic
        assert research.payload is not None
        assert groups.payload is not None
        assert content.payload is not None
        assert len(images) == 3
        seen.append(f"delivery:{topic}")
        return ResultEnvelope[DeliveryPackage].success(
            agent_name="delivery_agent",
            payload=DeliveryPackage(
                route="image_post",
                title=content.payload.title,
                summary="交付完成",
                text_blocks=[],
                artifacts=[],
            ),
            summary="delivery ok",
            run_id=run_id,
            step_id="delivery",
        )

    runner = ImageWorkflowRunner(
        deps=ImageWorkflowDeps(
            run_research=run_research,
            run_grouping=run_grouping,
            run_content=run_content,
            run_image_group=run_image_group,
            run_delivery=run_delivery,
        )
    )

    result = await runner.run(
        topic="纯色背景穿搭",
        audience="通勤女生",
        run_id="run-image-1",
        workspace_dir=tmp_path,
    )

    assert result.payload is not None
    assert result.payload.route == "image_post"
    assert result.payload.title == "纯色背景通勤穿搭灵感"
    assert seen[:3] == [
        "research:纯色背景穿搭:通勤女生",
        "grouping:纯色背景穿搭",
        "content:纯色背景穿搭",
    ]
    assert sorted(item for item in seen if item.startswith("image:")) == [
        "image:0:纯色背景穿搭:cover",
        "image:1:纯色背景穿搭:detail_1",
        "image:2:纯色背景穿搭:detail_2",
    ]
    assert seen[-1] == "delivery:纯色背景穿搭"


@pytest.mark.anyio
async def test_image_workflow_uses_first_group_as_cover_for_single_look_requests(tmp_path: Path) -> None:
    seen_groups: list[dict[str, object]] = []

    async def run_research(**kwargs) -> ResultEnvelope[ResearchResult]:
        return ResultEnvelope[ResearchResult].success(
            agent_name="research_agent",
            payload=ResearchResult(
                summary="调研完成",
                items=[
                    ResearchItem(title="look-1", content="第一套"),
                    ResearchItem(title="look-2", content="第二套"),
                    ResearchItem(title="look-3", content="第三套"),
                ],
                keywords=[],
                sources=[],
            ),
            summary="research ok",
            run_id=kwargs["run_id"],
            step_id="research",
        )

    async def run_grouping(**kwargs) -> ResultEnvelope[GroupingResult]:
        return ResultEnvelope[GroupingResult].success(
            agent_name="grouping_agent",
            payload=GroupingResult(
                groups=[
                    GroupingItem(title="第一套", indices=[0]),
                    GroupingItem(title="第二套", indices=[1]),
                    GroupingItem(title="第三套", indices=[2]),
                ]
            ),
            summary="grouping ok",
            run_id=kwargs["run_id"],
            step_id="grouping",
        )

    async def run_content(**kwargs) -> ResultEnvelope[XHSContent]:
        return ResultEnvelope[XHSContent].success(
            agent_name="content_agent",
            payload=XHSContent(
                title="三套纯色平铺穿搭灵感",
                body=(
                    "每张图只展示一套穿搭，封面也使用第一套作为主视觉。"
                    "后续图片分别承接第二套和第三套，背景保持纯色，画面不出现人物。"
                    "正文只围绕三套搭配讲比例、面料和配色，不额外扩写成多套清单。"
                    "这样交付给飞书时，用户能直接检查每张图的主体是否唯一。"
                ),
                hashtags=["穿搭"],
                call_to_action="保存参考。",
            ),
            summary="content ok",
            run_id=kwargs["run_id"],
            step_id="content",
        )

    async def run_image_group(**kwargs) -> ResultEnvelope[ImageResult]:
        seen_groups.append(dict(kwargs["group"]))
        image_path = tmp_path / f"{kwargs['group']['image_type']}.png"
        image_path.write_bytes(b"fake-image")
        return ResultEnvelope[ImageResult].success(
            agent_name="image_generation_agent",
            payload=ImageResult(
                images=[
                    GeneratedImage(
                        image_path=str(image_path),
                        prompt_used="prompt",
                        image_type=str(kwargs["group"]["image_type"]),
                    )
                ],
                total_count=1,
                generated_at="2026-05-30T00:00:00+00:00",
            ),
            summary="image ok",
            run_id=kwargs["run_id"],
            step_id=f"image-{kwargs['group_index']}",
        )

    async def run_delivery(**kwargs) -> ResultEnvelope[DeliveryPackage]:
        return ResultEnvelope[DeliveryPackage].success(
            agent_name="delivery_agent",
            payload=DeliveryPackage(route="image_post", title="三套平铺穿搭", summary="交付完成"),
            summary="delivery ok",
            run_id=kwargs["run_id"],
            step_id="delivery",
        )

    runner = ImageWorkflowRunner(
        deps=ImageWorkflowDeps(
            run_research=run_research,
            run_grouping=run_grouping,
            run_content=run_content,
            run_image_group=run_image_group,
            run_delivery=run_delivery,
        )
    )

    await runner.run(
        topic="纯色背景穿搭",
        audience="通勤女生",
        run_id="run-single-look",
        workspace_dir=tmp_path,
        image_count=3,
        single_item_per_image=True,
    )

    assert [group["image_type"] for group in seen_groups] == ["cover", "detail_1", "detail_2"]
    assert [group["indices"] for group in seen_groups] == [[0], [1], [2]]


@pytest.mark.anyio
async def test_image_workflow_pads_explicit_single_look_count_when_grouping_is_short(tmp_path: Path) -> None:
    seen_groups: list[dict[str, object]] = []

    async def run_research(**kwargs) -> ResultEnvelope[ResearchResult]:
        return ResultEnvelope[ResearchResult].success(
            agent_name="research_agent",
            payload=ResearchResult(
                summary="降级研究只保留了用户约束和受众",
                items=[
                    ResearchItem(title="用户约束", content="用户明确要 3 张单套平铺穿搭图"),
                    ResearchItem(title="受众", content="泛人群"),
                ],
                keywords=[],
                sources=[],
            ),
            summary="research ok",
            run_id=kwargs["run_id"],
            step_id="research",
        )

    async def run_grouping(**kwargs) -> ResultEnvelope[GroupingResult]:
        return ResultEnvelope[GroupingResult].success(
            agent_name="grouping_agent",
            payload=GroupingResult(
                groups=[
                    GroupingItem(title="第一套", indices=[0]),
                    GroupingItem(title="第二套", indices=[1]),
                ]
            ),
            summary="grouping short",
            run_id=kwargs["run_id"],
            step_id="grouping",
        )

    async def run_content(**kwargs) -> ResultEnvelope[XHSContent]:
        return ResultEnvelope[XHSContent].success(
            agent_name="content_agent",
            payload=XHSContent(
                title="3张夏季通勤平铺拍摄灵感",
                body=(
                    "图1是浅蓝背景通勤衬衫套装，图2是奶油白背景针织套装，"
                    "图3是鼠尾草绿背景轻户外通勤套装。每张图只展示一套穿搭。"
                    "不要人物、模特或人台，所有图片都应是真实摄影平铺。"
                    "整体保持小红书图文帖的节奏：封面先给出明确主题，后续图片各自承担一套完整造型，"
                    "并通过不同纯色背景形成区分，避免把研究限制、登录提示或系统诊断文字放进画面。"
                ),
                hashtags=["通勤穿搭"],
                call_to_action="保存参考。",
            ),
            summary="content ok",
            run_id=kwargs["run_id"],
            step_id="content",
        )

    async def run_image_group(**kwargs) -> ResultEnvelope[ImageResult]:
        seen_groups.append(dict(kwargs["group"]))
        image_path = tmp_path / f"{kwargs['group']['image_type']}.png"
        image_path.write_bytes(b"fake-image")
        return ResultEnvelope[ImageResult].success(
            agent_name="image_generation_agent",
            payload=ImageResult(
                images=[
                    GeneratedImage(
                        image_path=str(image_path),
                        prompt_used="prompt",
                        image_type=str(kwargs["group"]["image_type"]),
                    )
                ],
                total_count=1,
                generated_at="2026-05-30T00:00:00+00:00",
            ),
            summary="image ok",
            run_id=kwargs["run_id"],
            step_id=f"image-{kwargs['group_index']}",
        )

    async def run_delivery(**kwargs) -> ResultEnvelope[DeliveryPackage]:
        return ResultEnvelope[DeliveryPackage].success(
            agent_name="delivery_agent",
            payload=DeliveryPackage(route="image_post", title="3张夏季通勤平铺拍摄灵感", summary="交付完成"),
            summary="delivery ok",
            run_id=kwargs["run_id"],
            step_id="delivery",
        )

    runner = ImageWorkflowRunner(
        deps=ImageWorkflowDeps(
            run_research=run_research,
            run_grouping=run_grouping,
            run_content=run_content,
            run_image_group=run_image_group,
            run_delivery=run_delivery,
        )
    )

    await runner.run(
        topic="夏季城市通勤穿搭灵感",
        audience="泛人群",
        run_id="run-single-look-padding",
        workspace_dir=tmp_path,
        execution_text=(
            "图片数量：3 张\n"
            "单图单内容：每张图只展示一个主体/一套穿搭\n"
            "用户原始要求：3 张图，浅蓝、奶油白、鼠尾草绿三种纯色背景。"
        ),
        image_count=3,
        single_item_per_image=True,
    )

    assert [group["image_type"] for group in seen_groups] == ["cover", "detail_1", "detail_2"]
    assert [group["indices"] for group in seen_groups] == [[0], [1], []]
    assert "第3张" in str(seen_groups[2]["title"])
    assert "用户明确要求的第3张单套展示图" in str(seen_groups[2]["desc"])


@pytest.mark.anyio
async def test_image_workflow_pads_explicit_image_count_when_grouping_is_short(tmp_path: Path) -> None:
    seen_groups: list[dict[str, object]] = []

    async def run_research(**kwargs) -> ResultEnvelope[ResearchResult]:
        return ResultEnvelope[ResearchResult].success(
            agent_name="research_agent",
            payload=ResearchResult(
                summary="降级研究只保留了用户约束和受众",
                items=[
                    ResearchItem(title="用户约束", content="用户明确要 5 张末日废土风留学图，每张都有人物"),
                    ResearchItem(title="受众", content="准备出国留学的人群"),
                ],
                keywords=[],
                sources=[],
            ),
            summary="research ok",
            run_id=kwargs["run_id"],
            step_id="research",
        )

    async def run_grouping(**kwargs) -> ResultEnvelope[GroupingResult]:
        return ResultEnvelope[GroupingResult].success(
            agent_name="grouping_agent",
            payload=GroupingResult(groups=[GroupingItem(title="创作总览", indices=[0, 1])]),
            summary="grouping short",
            run_id=kwargs["run_id"],
            step_id="grouping",
        )

    async def run_content(**kwargs) -> ResultEnvelope[XHSContent]:
        return ResultEnvelope[XHSContent].success(
            agent_name="content_agent",
            payload=XHSContent(
                title="5张废土风留学图文内容测试",
                body=(
                    "这是一条用于测试图片数量策略的内容。用户明确要求五张图片，"
                    "每张图片都必须是末日废土风格，并且每张图片都要有人物出现。"
                    "即使调研或分组降级只给出一个总览分组，执行层也要补足五个图片任务槽位，"
                    "让图片 Agent 根据用户原始要求、正文和风格约束生成不同画面。"
                ),
                hashtags=["测试"],
                call_to_action="查看即可。",
            ),
            summary="content ok",
            run_id=kwargs["run_id"],
            step_id="content",
        )

    async def run_image_group(**kwargs) -> ResultEnvelope[ImageResult]:
        seen_groups.append(dict(kwargs["group"]))
        image_path = tmp_path / f"{kwargs['group']['image_type']}.png"
        image_path.write_bytes(b"fake-image")
        return ResultEnvelope[ImageResult].success(
            agent_name="image_generation_agent",
            payload=ImageResult(
                images=[
                    GeneratedImage(
                        image_path=str(image_path),
                        prompt_used="prompt",
                        image_type=str(kwargs["group"]["image_type"]),
                    )
                ],
                total_count=1,
                generated_at="2026-05-30T00:00:00+00:00",
            ),
            summary="image ok",
            run_id=kwargs["run_id"],
            step_id=f"image-{kwargs['group_index']}",
        )

    async def run_delivery(**kwargs) -> ResultEnvelope[DeliveryPackage]:
        return ResultEnvelope[DeliveryPackage].success(
            agent_name="delivery_agent",
            payload=DeliveryPackage(route="image_post", title="核心信息图文内容测试", summary="交付完成"),
            summary="delivery ok",
            run_id=kwargs["run_id"],
            step_id="delivery",
        )

    runner = ImageWorkflowRunner(
        deps=ImageWorkflowDeps(
            run_research=run_research,
            run_grouping=run_grouping,
            run_content=run_content,
            run_image_group=run_image_group,
            run_delivery=run_delivery,
        )
    )

    await runner.run(
        topic="出国留学废土风图文",
        audience="准备出国留学的人群",
        run_id="run-explicit-padding",
        workspace_dir=tmp_path,
        image_count=5,
    )

    assert [group["image_type"] for group in seen_groups] == [
        "cover",
        "detail_1",
        "detail_2",
        "detail_3",
        "detail_4",
    ]
    assert seen_groups[2]["indices"] == []
    assert "第3张" in str(seen_groups[2]["title"])
    assert "用户明确要求的第3张图片" in str(seen_groups[2]["desc"])


@pytest.mark.anyio
async def test_image_workflow_caps_unspecified_image_count_with_runtime_default(tmp_path: Path) -> None:
    seen_groups: list[dict[str, object]] = []

    async def run_research(**kwargs) -> ResultEnvelope[ResearchResult]:
        return ResultEnvelope[ResearchResult].success(
            agent_name="research_agent",
            payload=ResearchResult(summary="调研完成", items=[], keywords=[], sources=[]),
            summary="research ok",
            run_id=kwargs["run_id"],
            step_id="research",
        )

    async def run_grouping(**kwargs) -> ResultEnvelope[GroupingResult]:
        return ResultEnvelope[GroupingResult].success(
            agent_name="grouping_agent",
            payload=GroupingResult(
                groups=[GroupingItem(title=f"分组 {index}", indices=[index]) for index in range(1, 8)]
            ),
            summary="grouping ok",
            run_id=kwargs["run_id"],
            step_id="grouping",
        )

    async def run_content(**kwargs) -> ResultEnvelope[XHSContent]:
        return ResultEnvelope[XHSContent].success(
            agent_name="content_agent",
            payload=XHSContent(
                title="自动图数上限测试内容标题",
                body=(
                    "自动图数上限测试正文，确保模糊请求不会扩展成过重的图片生成任务。"
                    "当用户没有明确指定图片数量时，编排器应该使用运行参数里的默认上限，"
                    "只生成足够表达主题的少量图片，再把完整分组信息保留在 envelope 中。"
                    "这样既不破坏专项 Agent 的分组能力，也能避免供应商侧瞬时并发过高。"
                ),
                hashtags=[],
                call_to_action="查看即可。",
            ),
            summary="content ok",
            run_id=kwargs["run_id"],
            step_id="content",
        )

    async def run_image_group(**kwargs) -> ResultEnvelope[ImageResult]:
        seen_groups.append(dict(kwargs["group"]))
        image_path = tmp_path / f"{kwargs['group']['image_type']}.png"
        image_path.write_bytes(b"fake-image")
        return ResultEnvelope[ImageResult].success(
            agent_name="image_generation_agent",
            payload=ImageResult(
                images=[
                    GeneratedImage(
                        image_path=str(image_path),
                        prompt_used="prompt",
                        image_type=str(kwargs["group"]["image_type"]),
                    )
                ],
                total_count=1,
                generated_at="2026-05-30T00:00:00+00:00",
            ),
            summary="image ok",
            run_id=kwargs["run_id"],
            step_id=f"image-{kwargs['group_index']}",
        )

    async def run_delivery(**kwargs) -> ResultEnvelope[DeliveryPackage]:
        return ResultEnvelope[DeliveryPackage].success(
            agent_name="delivery_agent",
            payload=DeliveryPackage(route="image_post", title="自动图数上限测试", summary="交付完成"),
            summary="delivery ok",
            run_id=kwargs["run_id"],
            step_id="delivery",
        )

    runner = ImageWorkflowRunner(
        deps=ImageWorkflowDeps(
            run_research=run_research,
            run_grouping=run_grouping,
            run_content=run_content,
            run_image_group=run_image_group,
            run_delivery=run_delivery,
        )
    )

    await runner.run(
        topic="模糊探索任务",
        audience="测试受众",
        run_id="run-auto-cap",
        workspace_dir=tmp_path,
        max_auto_images=3,
    )

    assert [group["image_type"] for group in seen_groups] == ["cover", "detail_1", "detail_2"]


@pytest.mark.anyio
async def test_image_workflow_honors_explicit_image_count_over_auto_cap(tmp_path: Path) -> None:
    seen_groups: list[dict[str, object]] = []

    async def run_research(**kwargs) -> ResultEnvelope[ResearchResult]:
        return ResultEnvelope[ResearchResult].success(
            agent_name="research_agent",
            payload=ResearchResult(summary="调研完成", items=[], keywords=[], sources=[]),
            summary="research ok",
            run_id=kwargs["run_id"],
            step_id="research",
        )

    async def run_grouping(**kwargs) -> ResultEnvelope[GroupingResult]:
        return ResultEnvelope[GroupingResult].success(
            agent_name="grouping_agent",
            payload=GroupingResult(
                groups=[GroupingItem(title=f"分组 {index}", indices=[index]) for index in range(1, 8)]
            ),
            summary="grouping ok",
            run_id=kwargs["run_id"],
            step_id="grouping",
        )

    async def run_content(**kwargs) -> ResultEnvelope[XHSContent]:
        return ResultEnvelope[XHSContent].success(
            agent_name="content_agent",
            payload=XHSContent(
                title="显式图数优先测试内容标题",
                body=(
                    "显式图数测试正文，确保用户明确指定数量时不会被自动上限截断。"
                    "当用户已经说清楚需要五张图片，编排器必须尊重这个需求，"
                    "只在实际分组数量不足时停止，不能因为默认自动上限更小就提前截断。"
                    "这可以保证用户指定、Agent 自主和运行参数之间的职责边界清晰。"
                ),
                hashtags=[],
                call_to_action="查看即可。",
            ),
            summary="content ok",
            run_id=kwargs["run_id"],
            step_id="content",
        )

    async def run_image_group(**kwargs) -> ResultEnvelope[ImageResult]:
        seen_groups.append(dict(kwargs["group"]))
        image_path = tmp_path / f"{kwargs['group']['image_type']}.png"
        image_path.write_bytes(b"fake-image")
        return ResultEnvelope[ImageResult].success(
            agent_name="image_generation_agent",
            payload=ImageResult(
                images=[
                    GeneratedImage(
                        image_path=str(image_path),
                        prompt_used="prompt",
                        image_type=str(kwargs["group"]["image_type"]),
                    )
                ],
                total_count=1,
                generated_at="2026-05-30T00:00:00+00:00",
            ),
            summary="image ok",
            run_id=kwargs["run_id"],
            step_id=f"image-{kwargs['group_index']}",
        )

    async def run_delivery(**kwargs) -> ResultEnvelope[DeliveryPackage]:
        return ResultEnvelope[DeliveryPackage].success(
            agent_name="delivery_agent",
            payload=DeliveryPackage(route="image_post", title="显式图数测试", summary="交付完成"),
            summary="delivery ok",
            run_id=kwargs["run_id"],
            step_id="delivery",
        )

    runner = ImageWorkflowRunner(
        deps=ImageWorkflowDeps(
            run_research=run_research,
            run_grouping=run_grouping,
            run_content=run_content,
            run_image_group=run_image_group,
            run_delivery=run_delivery,
        )
    )

    await runner.run(
        topic="明确五张图任务",
        audience="测试受众",
        run_id="run-explicit-count",
        workspace_dir=tmp_path,
        image_count=5,
        max_auto_images=3,
    )

    assert [group["image_type"] for group in seen_groups] == [
        "cover",
        "detail_1",
        "detail_2",
        "detail_3",
        "detail_4",
    ]


@pytest.mark.anyio
async def test_image_workflow_limits_parallel_image_generation(tmp_path: Path) -> None:
    active = 0
    max_active = 0

    async def run_research(**kwargs) -> ResultEnvelope[ResearchResult]:
        return ResultEnvelope[ResearchResult].success(
            agent_name="research_agent",
            payload=ResearchResult(summary="调研完成", items=[], keywords=[], sources=[]),
            summary="research ok",
            run_id=kwargs["run_id"],
            step_id="research",
        )

    async def run_grouping(**kwargs) -> ResultEnvelope[GroupingResult]:
        return ResultEnvelope[GroupingResult].success(
            agent_name="grouping_agent",
            payload=GroupingResult(
                groups=[GroupingItem(title=f"分组 {index}", indices=[index]) for index in range(1, 6)]
            ),
            summary="grouping ok",
            run_id=kwargs["run_id"],
            step_id="grouping",
        )

    async def run_content(**kwargs) -> ResultEnvelope[XHSContent]:
        return ResultEnvelope[XHSContent].success(
            agent_name="content_agent",
            payload=XHSContent(
                title="图片生成并发阀门测试标题",
                body=(
                    "并发阀门测试正文，确保图片生成任务不会一次性把供应商打爆。"
                    "编排器仍然可以把每个图片任务看成独立原子任务，但执行层必须提供"
                    "可配置的并发控制，避免 Vertex 或其他图像供应商因为瞬时请求过多"
                    "返回限流错误，同时保持结果 join 的顺序稳定。"
                ),
                hashtags=[],
                call_to_action="查看即可。",
            ),
            summary="content ok",
            run_id=kwargs["run_id"],
            step_id="content",
        )

    async def run_image_group(**kwargs) -> ResultEnvelope[ImageResult]:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        image_path = tmp_path / f"{kwargs['group']['image_type']}.png"
        image_path.write_bytes(b"fake-image")
        return ResultEnvelope[ImageResult].success(
            agent_name="image_generation_agent",
            payload=ImageResult(
                images=[
                    GeneratedImage(
                        image_path=str(image_path),
                        prompt_used="prompt",
                        image_type=str(kwargs["group"]["image_type"]),
                    )
                ],
                total_count=1,
                generated_at="2026-05-30T00:00:00+00:00",
            ),
            summary="image ok",
            run_id=kwargs["run_id"],
            step_id=f"image-{kwargs['group_index']}",
        )

    async def run_delivery(**kwargs) -> ResultEnvelope[DeliveryPackage]:
        return ResultEnvelope[DeliveryPackage].success(
            agent_name="delivery_agent",
            payload=DeliveryPackage(route="image_post", title="并发阀门测试", summary="交付完成"),
            summary="delivery ok",
            run_id=kwargs["run_id"],
            step_id="delivery",
        )

    runner = ImageWorkflowRunner(
        deps=ImageWorkflowDeps(
            run_research=run_research,
            run_grouping=run_grouping,
            run_content=run_content,
            run_image_group=run_image_group,
            run_delivery=run_delivery,
        )
    )

    await runner.run(
        topic="并发阀门任务",
        audience="测试受众",
        run_id="run-concurrency",
        workspace_dir=tmp_path,
        image_count=6,
        image_generation_concurrency=2,
    )

    assert max_active == 2
