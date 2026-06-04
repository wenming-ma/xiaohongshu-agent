from __future__ import annotations

from src.agent_os.schemas import RunOptions, TaskRunSpec
from src.orchestration import WorkflowInvocation as ExportedWorkflowInvocation
from src.orchestration.schemas import (
    ArtifactRef,
    WorkflowInvocation,
    WorkflowState,
)


def test_workflow_invocation_is_public_orchestration_api() -> None:
    assert ExportedWorkflowInvocation is WorkflowInvocation


def test_workflow_invocation_preserves_user_requirements_and_artifacts() -> None:
    reference = ArtifactRef(
        artifact_type="image",
        label="hat-reference",
        path="C:/tmp/hat.png",
        mime_type="image/png",
        metadata={"source": "feishu"},
    )

    invocation = WorkflowInvocation(
        objective="生成 8+1 张通勤穿搭图文",
        route="image_post",
        topic="雨天通勤穿搭",
        audience="通勤女生",
        selected_skills=[
            "pure-color-single-look-image-post",
            "reference-image-product-alignment",
        ],
        selected_prompt_templates=["image/flatlay/pure-color"],
        user_requirements=[
            "每张图只展示一套穿搭",
            "保留参考图中的帽子",
        ],
        constraints=["no_people", "pure_color_background"],
        preferences=["真实摄影感"],
        artifacts=[reference],
        run_options=RunOptions(),
        delivery={"target": "feishu", "chat_id": "oc_test"},
    )

    state = WorkflowState.from_invocation(
        invocation,
        run_id="run-1",
        workspace_dir="C:/tmp/run-1",
    )

    assert state.invocation.topic == "雨天通勤穿搭"
    assert state.invocation.selected_skills == [
        "pure-color-single-look-image-post",
        "reference-image-product-alignment",
    ]
    assert state.invocation.artifacts[0].label == "hat-reference"
    assert state.run_id == "run-1"
    assert state.workspace_dir == "C:/tmp/run-1"


def test_workflow_invocation_can_be_built_from_task_run_spec() -> None:
    spec = TaskRunSpec(
        objective="根据两张参考图生成图文",
        route="image_post",
        topic="城市通勤包",
        audience="上班族",
        constraints=["不出现人物"],
        style_constraints=["纯色背景"],
        selected_skills=["reference-image-product-alignment"],
        selected_prompt_templates=["image/reference/object-transfer"],
        reference_images=[
            ArtifactRef(
                artifact_type="image",
                label="bag",
                path="C:/tmp/bag.jpg",
                mime_type="image/jpeg",
            )
        ],
    )

    invocation = WorkflowInvocation.from_task_spec(spec)

    assert invocation.objective == "根据两张参考图生成图文"
    assert invocation.route == "image_post"
    assert invocation.constraints == ["不出现人物", "纯色背景"]
    assert invocation.artifacts[0].label == "bag"
    assert invocation.selected_skills == ["reference-image-product-alignment"]
