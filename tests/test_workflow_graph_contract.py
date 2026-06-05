from __future__ import annotations

import pytest

from src.orchestration import (
    article_workflow_module_graph as exported_article_graph,
    ArticleWorkflowRunner as exported_article_runner,
    image_workflow_module_graph as exported_image_graph,
    video_workflow_module_graph as exported_video_graph,
    VideoWorkflowRunner as exported_video_runner,
)
from src.orchestration.article_route import ArticleWorkflowRunner, article_workflow_module_graph
from src.orchestration.image_flow import image_workflow_module_graph
from src.orchestration.schemas import ResultEnvelope, WorkflowInvocation, WorkflowState
from src.orchestration.video_route import VideoWorkflowRunner, video_workflow_module_graph
from src.orchestration.workflow_graph import (
    FunctionModuleNode,
    ModuleGraph,
    ModuleGraphSpec,
    ModuleNodeSpec,
)


def test_module_graph_spec_documents_public_module_boundary() -> None:
    graph = ModuleGraphSpec(
        name="image_post_workflow",
        modules=[
            ModuleNodeSpec(
                name="research",
                input_refs=["workflow_invocation"],
                output_ref="research",
                subnodes=["search", "synthesis", "review"],
            ),
            ModuleNodeSpec(
                name="image",
                input_refs=["workflow_invocation", "grouping", "content"],
                output_ref="images",
                subnodes=[
                    "reference_analysis",
                    "image_planner",
                    "image_task_subgraph",
                    "image_join",
                    "image_set_review",
                ],
                supports_parallel=True,
            ),
        ],
    )

    assert graph.module_names == ["research", "image"]
    assert graph.get("image").supports_parallel is True
    assert graph.get("image").subnodes[1] == "image_planner"
    assert graph.describe() == [
        {
            "name": "research",
            "input_refs": ["workflow_invocation"],
            "output_ref": "research",
            "subnodes": ["search", "synthesis", "review"],
            "supports_parallel": False,
        },
        {
            "name": "image",
            "input_refs": ["workflow_invocation", "grouping", "content"],
            "output_ref": "images",
            "subnodes": [
                "reference_analysis",
                "image_planner",
                "image_task_subgraph",
                "image_join",
                "image_set_review",
            ],
            "supports_parallel": True,
        },
    ]


def test_module_graph_rejects_duplicate_module_names() -> None:
    try:
        ModuleGraphSpec(
            name="bad_graph",
            modules=[
                ModuleNodeSpec(name="research", output_ref="research"),
                ModuleNodeSpec(name="research", output_ref="research_again"),
            ],
        )
    except ValueError as exc:
        assert "Duplicate module node" in str(exc)
    else:
        raise AssertionError("duplicate module names should fail")


def test_formal_content_routes_publish_module_graph_specs() -> None:
    assert image_workflow_module_graph.module_names == [
        "research",
        "grouping",
        "content",
        "image",
        "delivery",
    ]
    assert article_workflow_module_graph.module_names == [
        "research",
        "content",
        "image",
        "delivery",
    ]
    assert video_workflow_module_graph.module_names == [
        "research",
        "download",
        "content",
        "cover",
        "delivery",
    ]


def test_article_video_module_specs_expose_internal_review_boundaries() -> None:
    assert article_workflow_module_graph.get("research").subnodes == [
        "search",
        "synthesis",
        "review",
    ]
    assert article_workflow_module_graph.get("content").subnodes == ["generate", "review"]
    assert article_workflow_module_graph.get("image").subnodes == [
        "image_planner",
        "image_generation",
        "image_review",
    ]
    assert video_workflow_module_graph.get("research").subnodes == [
        "search",
        "selection",
        "review",
    ]
    assert video_workflow_module_graph.get("download").subnodes == [
        "source_selection",
        "download",
        "transcription",
    ]
    assert video_workflow_module_graph.get("cover").subnodes == [
        "frame_selection",
        "cover_generation",
        "review",
    ]


def test_image_task_subgraph_exposes_internal_node_sequence() -> None:
    image_module = image_workflow_module_graph.get("image")

    assert image_module.subgraphs["image_task_subgraph"] == [
        "prompt",
        "image_generation",
        "image_review",
        "repair_retry",
    ]
    described = image_module.describe()
    assert described["subgraphs"] == {
        "image_task_subgraph": [
            "prompt",
            "image_generation",
            "image_review",
            "repair_retry",
        ]
    }


def test_route_module_graphs_are_public_orchestration_api() -> None:
    assert exported_image_graph is image_workflow_module_graph
    assert exported_article_graph is article_workflow_module_graph
    assert exported_video_graph is video_workflow_module_graph
    assert exported_article_runner is ArticleWorkflowRunner
    assert exported_video_runner is VideoWorkflowRunner


@pytest.mark.anyio
async def test_module_graph_executes_ordered_nodes_through_workflow_state(tmp_path) -> None:
    spec = ModuleGraphSpec(
        name="demo_workflow",
        modules=[
            ModuleNodeSpec(
                name="research",
                input_refs=["workflow_invocation"],
                output_ref="research",
            ),
            ModuleNodeSpec(
                name="delivery",
                input_refs=["workflow_invocation", "research"],
                output_ref="delivery",
            ),
        ],
    )
    state = WorkflowState.from_invocation(
        WorkflowInvocation(objective="做一组飞书图文", route="image_post"),
        run_id="run-module-graph",
        workspace_dir=str(tmp_path),
    )

    async def run_research(workflow_state: WorkflowState) -> ResultEnvelope[dict]:
        return ResultEnvelope[dict].success(
            agent_name="research_module",
            payload={"objective": workflow_state.invocation.objective},
            summary="research ok",
            run_id=workflow_state.run_id,
            step_id="research",
        )

    async def run_delivery(workflow_state: WorkflowState) -> ResultEnvelope[dict]:
        upstream = workflow_state.module_results["research"]
        return ResultEnvelope[dict].success(
            agent_name="delivery_module",
            payload={"upstream": upstream.summary},
            summary="delivery ok",
            run_id=workflow_state.run_id,
            step_id="delivery",
        )

    graph = ModuleGraph(
        spec=spec,
        nodes=[
            FunctionModuleNode(spec=spec.get("research"), handler=run_research),
            FunctionModuleNode(spec=spec.get("delivery"), handler=run_delivery),
        ],
    )

    result_state = await graph.run(state)

    assert result_state.module_results["research"].summary == "research ok"
    assert result_state.module_results["delivery"].payload == {"upstream": "research ok"}


@pytest.mark.anyio
async def test_module_graph_rejects_missing_input_refs(tmp_path) -> None:
    spec = ModuleGraphSpec(
        name="bad_workflow",
        modules=[
            ModuleNodeSpec(
                name="delivery",
                input_refs=["research"],
                output_ref="delivery",
            ),
        ],
    )
    state = WorkflowState.from_invocation(
        WorkflowInvocation(objective="缺少上游"),
        run_id="run-module-missing",
        workspace_dir=str(tmp_path),
    )

    async def run_delivery(workflow_state: WorkflowState) -> ResultEnvelope[dict]:
        raise AssertionError("node should not run with missing input refs")

    graph = ModuleGraph(
        spec=spec,
        nodes=[FunctionModuleNode(spec=spec.get("delivery"), handler=run_delivery)],
    )

    with pytest.raises(ValueError, match="missing input refs"):
        await graph.run(state)
