from __future__ import annotations

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
async def test_image_workflow_does_not_fabricate_images_when_requested_count_exceeds_groups(tmp_path: Path) -> None:
    seen_groups: list[dict[str, object]] = []

    async def run_research(**kwargs) -> ResultEnvelope[ResearchResult]:
        return ResultEnvelope[ResearchResult].success(
            agent_name="research_agent",
            payload=ResearchResult(
                summary="调研完成",
                items=[ResearchItem(title="item-1", content="核心信息")],
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
            payload=GroupingResult(groups=[GroupingItem(title="核心图", indices=[0])]),
            summary="grouping ok",
            run_id=kwargs["run_id"],
            step_id="grouping",
        )

    async def run_content(**kwargs) -> ResultEnvelope[XHSContent]:
        return ResultEnvelope[XHSContent].success(
            agent_name="content_agent",
            payload=XHSContent(
                title="核心信息图文内容测试",
                body=(
                    "这是一条用于测试图片数量策略的内容。"
                    "当用户要求的图片数量超过实际分组数量时，系统应尊重分组结果，"
                    "只生成已有分组可以支撑的图片，不应该额外补充空白或虚构图片。"
                    "这样可以避免下游图片提示词缺少素材，也避免交付包看起来凑数。"
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
        topic="测试主题",
        audience="测试受众",
        run_id="run-no-filler",
        workspace_dir=tmp_path,
        image_count=5,
    )

    assert [group["image_type"] for group in seen_groups] == ["cover", "detail_1"]
