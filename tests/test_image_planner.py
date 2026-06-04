from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from src.agents.image_post.schemas import (
    GeneratedImage,
    ImageResult,
    ResearchResult,
    XHSContent,
)
from src.orchestration.image_flow import (
    ImageGenerationNode,
    ImagePlannerNode,
    ImagePromptNode,
    ImageRepairRetryNode,
    ImageReviewNode,
    ImageTaskSubgraph,
    ImageWorkflowDeps,
    ImageWorkflowRunner,
    ImageWorkflowState,
    image_workflow_module_graph,
)
from src.orchestration.schemas import (
    ArtifactRef,
    DeliveryPackage,
    GroupingItem,
    GroupingResult,
    ImageReferenceRole,
    ImageTaskPlan,
    ReferenceImagePlan,
    ResultEnvelope,
    WorkflowInvocation,
)
from src.config.settings import ImageConfig


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_image_planner_builds_task_plans_with_reference_roles() -> None:
    invocation = WorkflowInvocation(
        objective="做一组通勤图，保留帽子和衣服",
        route="image_post",
        topic="通勤穿搭",
        artifacts=[
            ArtifactRef(artifact_type="image", label="hat", path="C:/tmp/hat.png"),
            ArtifactRef(artifact_type="image", label="coat", path="C:/tmp/coat.png"),
        ],
        constraints=["strict_object_transfer", "no_people"],
        selected_skills=["reference-image-product-alignment"],
        selected_prompt_templates=["image/reference/object-transfer"],
    )
    groups = GroupingResult(
        groups=[
            GroupingItem(title="帽子和外套组合", indices=[0, 1]),
            GroupingItem(title="细节特写", indices=[2]),
        ]
    )

    plan = ImageTaskPlan.plan_from_groups(
        invocation=invocation,
        groups=groups,
        requested_image_count=2,
        single_item_per_image=False,
        max_auto_images=9,
    )

    assert [task.image_type for task in plan.tasks] == ["cover", "detail_1"]
    assert plan.tasks[0].group_title == "帽子和外套组合"
    assert plan.tasks[0].generation_mode == "object_transfer"
    assert [
        (reference.label, reference.path, reference.role)
        for reference in plan.tasks[0].reference_images
    ] == [
        ("hat", "C:/tmp/hat.png", ImageReferenceRole.OBJECT_TRANSFER),
        ("coat", "C:/tmp/coat.png", ImageReferenceRole.OBJECT_TRANSFER),
    ]
    assert plan.tasks[0].reference_images[0].artifact is not None
    assert plan.tasks[0].reference_images[0].artifact.path == "C:/tmp/hat.png"
    assert "must_preserve_reference_subjects" in plan.tasks[0].qa_rules
    assert "no_people" in plan.tasks[0].hard_constraints


def test_image_workflow_exposes_fixed_module_graph_contract() -> None:
    assert image_workflow_module_graph.module_names == [
        "research",
        "grouping",
        "content",
        "image",
        "delivery",
    ]
    assert image_workflow_module_graph.get("research").subnodes == ["search", "synthesis", "review"]
    assert image_workflow_module_graph.get("grouping").subnodes == ["grouping", "review"]
    assert image_workflow_module_graph.get("content").subnodes == ["generate", "review"]
    assert image_workflow_module_graph.get("image").subnodes == [
        "reference_analysis",
        "image_planner",
        "image_task_subgraph",
        "image_join",
        "image_set_review",
    ]
    assert image_workflow_module_graph.get("image").supports_parallel is True
    assert image_workflow_module_graph.get("delivery").subnodes == ["package", "review", "feishu_delivery"]


def test_image_graph_has_explicit_planner_node_and_task_subgraph() -> None:
    assert ImagePlannerNode.__name__ == "ImagePlannerNode"
    assert ImageTaskSubgraph.__name__ == "ImageTaskSubgraph"
    assert ImagePromptNode.__name__ == "ImagePromptNode"
    assert ImageGenerationNode.__name__ == "ImageGenerationNode"
    assert ImageReviewNode.__name__ == "ImageReviewNode"
    assert ImageRepairRetryNode.__name__ == "ImageRepairRetryNode"


def test_image_workflow_default_auto_cap_is_cover_plus_eight_details(tmp_path: Path) -> None:
    run_signature = inspect.signature(ImageWorkflowRunner.run)

    assert run_signature.parameters["max_auto_images"].default == ImageConfig.MAX_AUTO_IMAGES == 9
    assert (
        ImageWorkflowState(
            topic="默认 8+1 测试",
            audience="内容团队",
            run_id="run-default-cap",
            workspace_dir=tmp_path,
        ).max_auto_images
        == ImageConfig.MAX_AUTO_IMAGES
        == 9
    )


@pytest.mark.anyio
async def test_image_workflow_uses_image_planner_tasks_for_fan_out(tmp_path: Path) -> None:
    seen_tasks: list[ImageTaskPlan] = []

    async def run_research(**kwargs) -> ResultEnvelope[ResearchResult]:
        return ResultEnvelope[ResearchResult].success(
            agent_name="research_agent",
            payload=ResearchResult(summary="ok", items=[], keywords=[], sources=[]),
            summary="research ok",
            run_id=kwargs["run_id"],
            step_id="research",
        )

    async def run_grouping(**kwargs) -> ResultEnvelope[GroupingResult]:
        return ResultEnvelope[GroupingResult].success(
            agent_name="grouping_agent",
            payload=GroupingResult(groups=[GroupingItem(title="帽子和衣服", indices=[0, 1])]),
            summary="grouping ok",
            run_id=kwargs["run_id"],
            step_id="grouping",
        )

    async def run_content(**kwargs) -> ResultEnvelope[XHSContent]:
        return ResultEnvelope[XHSContent].success(
            agent_name="content_agent",
            payload=XHSContent(
                title="通勤穿搭参考图元素迁移方案",
                body=(
                    "保留参考图里的帽子和衣服，换成新的通勤场景。"
                    "封面需要让两件参考物体都清楚出现，详情页可以围绕材质、色彩和搭配关系展开。"
                    "整体画面保持小红书图文的真实摄影感，不要生成无关物品、登录弹窗、系统诊断文字或研究限制说明。"
                ),
                hashtags=[],
                call_to_action="保存。",
            ),
            summary="content ok",
            run_id=kwargs["run_id"],
            step_id="content",
        )

    async def run_image_group(**kwargs) -> ResultEnvelope[ImageResult]:
        seen_tasks.append(kwargs["image_task"])
        image_path = tmp_path / f"{kwargs['image_task'].image_type}.png"
        image_path.write_bytes(b"fake-image")
        return ResultEnvelope[ImageResult].success(
            agent_name="image_generation_agent",
            payload=ImageResult(
                images=[
                    GeneratedImage(
                        image_path=str(image_path),
                        prompt_used="prompt",
                        image_type=kwargs["image_task"].image_type,
                    )
                ],
                total_count=1,
                generated_at="2026-06-05T00:00:00+00:00",
            ),
            summary="image ok",
            run_id=kwargs["run_id"],
            step_id=f"image-{kwargs['group_index']}",
        )

    async def run_delivery(**kwargs) -> ResultEnvelope[DeliveryPackage]:
        return ResultEnvelope[DeliveryPackage].success(
            agent_name="delivery_agent",
            payload=DeliveryPackage(route="image_post", title="通勤穿搭参考图元素迁移方案", summary="done"),
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

    invocation = WorkflowInvocation(
        objective="保留帽子和衣服，生成通勤图文",
        route="image_post",
        topic="通勤穿搭",
        constraints=["strict_object_transfer"],
        artifacts=[
            ArtifactRef(artifact_type="image", label="hat", path="C:/tmp/hat.png"),
            ArtifactRef(artifact_type="image", label="coat", path="C:/tmp/coat.png"),
        ],
    )

    await runner.run(
        topic="通勤穿搭",
        audience="上班族",
        run_id="run-image-planner",
        workspace_dir=tmp_path,
        invocation=invocation,
        image_count=2,
    )

    assert [task.image_type for task in seen_tasks] == ["cover", "detail_1"]
    assert all(task.generation_mode == "object_transfer" for task in seen_tasks)
    assert seen_tasks[0].reference_images[0].role == ImageReferenceRole.OBJECT_TRANSFER


@pytest.mark.anyio
async def test_image_task_subgraph_runs_prompt_generation_review_and_retry(tmp_path: Path) -> None:
    attempts = 0

    async def run_image_group(**kwargs) -> ResultEnvelope[ImageResult]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return ResultEnvelope[ImageResult].error(
                agent_name="image_generation_agent",
                summary="review rejected unrelated image",
                error_message="image did not match current group",
                run_id=kwargs["run_id"],
                step_id="image-0",
            )

        image_path = tmp_path / "cover.png"
        image_path.write_bytes(b"fake-image")
        return ResultEnvelope[ImageResult].success(
            agent_name="image_generation_agent",
            payload=ImageResult(
                images=[
                    GeneratedImage(
                        image_path=str(image_path),
                        prompt_used="prompt",
                        image_type="cover",
                    )
                ],
                total_count=1,
                generated_at="2026-06-05T00:00:00+00:00",
            ),
            summary="image ok after retry",
            run_id=kwargs["run_id"],
            step_id="image-0",
        )

    async def unused(**kwargs):
        raise AssertionError("not used by this subgraph test")

    subgraph = ImageTaskSubgraph(
        deps=ImageWorkflowDeps(
            run_research=unused,
            run_grouping=unused,
            run_content=unused,
            run_image_group=run_image_group,
            run_delivery=unused,
        )
    )
    workflow_state = ImageWorkflowState(
        topic="通勤穿搭",
        audience="上班族",
        run_id="run-image-task-subgraph",
        workspace_dir=tmp_path,
        image_task_max_retries=1,
    )
    research = ResultEnvelope[ResearchResult].success(
        agent_name="research_agent",
        payload=ResearchResult(summary="ok", items=[], keywords=[], sources=[]),
        summary="research ok",
        run_id=workflow_state.run_id,
        step_id="research",
    )
    content = ResultEnvelope[XHSContent].success(
        agent_name="content_agent",
        payload=XHSContent(
            title="通勤穿搭封面图片生成子图测试",
            body=(
                "每张图必须匹配当前分组，不要生成无关 UI、登录提示、流程说明或系统诊断图。"
                "如果第一次生成结果被审核拒绝，单图任务子图应该进入修复重试节点，"
                "重新调用图片生成能力，并且把 Prompt、Generation、Review、Retry 的执行轨迹记录下来，"
                "方便后续任务恢复和质量审计。"
            ),
            hashtags=[],
            call_to_action="保存。",
        ),
        summary="content ok",
        run_id=workflow_state.run_id,
        step_id="content",
    )
    image_plan = ImageTaskPlan.plan_from_groups(
        invocation=WorkflowInvocation(
            objective="生成通勤穿搭封面",
            route="image_post",
            topic="通勤穿搭",
            constraints=["no_unrelated_ui"],
        ),
        groups=GroupingResult(groups=[GroupingItem(title="封面", indices=[0])]),
        requested_image_count=1,
        single_item_per_image=False,
        max_auto_images=9,
    )

    result = await subgraph.run(
        state=workflow_state,
        research=research,
        content=content,
        image_task=image_plan.tasks[0],
        index=0,
    )

    assert result.status == "success"
    assert attempts == 2
    assert subgraph.last_state is not None
    assert subgraph.last_state.executed_nodes == [
        "prompt",
        "image_generation",
        "image_review",
        "repair_retry",
        "prompt",
        "image_generation",
        "image_review",
    ]
