from __future__ import annotations

from src.orchestration import (
    article_workflow_module_graph as exported_article_graph,
    image_workflow_module_graph as exported_image_graph,
    video_workflow_module_graph as exported_video_graph,
)
from src.orchestration.article_route import article_workflow_module_graph
from src.orchestration.image_flow import image_workflow_module_graph
from src.orchestration.video_route import video_workflow_module_graph
from src.orchestration.workflow_graph import ModuleGraphSpec, ModuleNodeSpec


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


def test_route_module_graphs_are_public_orchestration_api() -> None:
    assert exported_image_graph is image_workflow_module_graph
    assert exported_article_graph is article_workflow_module_graph
    assert exported_video_graph is video_workflow_module_graph
