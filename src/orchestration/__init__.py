"""Shared orchestration primitives for Feishu-first content workflows."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ArtifactRef": ".schemas",
    "ArticlePostOrchestrator": ".article_route",
    "ArticleWorkflowRunner": ".article_route",
    "ContentRoute": ".conversation",
    "ConversationInputTranslator": ".session_input",
    "ConversationRequest": ".conversation",
    "DeliveryPackage": ".schemas",
    "DeliveryPackageSender": ".delivery",
    "DeliveryTextBlock": ".schemas",
    "ChoiceOption": ".feishu_translation",
    "AgentEventBridge": ".agent_events",
    "article_workflow_module_graph": ".article_route",
    "QueuedAgentEvent": ".agent_events",
    "FeishuInteractionTranslator": ".feishu_translation",
    "FeishuInputTranslator": ".feishu_translation",
    "FeishuInteractionTools": ".feishu_interactions",
    "FeishuSessionResetRequested": ".feishu_interactions",
    "GroupingItem": ".schemas",
    "GroupingResult": ".schemas",
    "ImageReferenceRole": ".schemas",
    "ImageTaskPlan": ".schemas",
    "ImagePostOrchestrator": ".image_route",
    "image_workflow_module_graph": ".image_flow",
    "InteractionDecision": ".feishu_interactions",
    "InteractionDecisionAgent": ".feishu_interactions",
    "ManifestStep": ".workspace",
    "PlanningAgent": ".planning_agent",
    "PlanningDecision": ".planning_agent",
    "ProjectSkillRegistry": ".skills",
    "ResultEnvelope": ".schemas",
    "ReferenceImagePlan": ".schemas",
    "SingleImageTaskPlan": ".schemas",
    "parse_delimited_options": ".feishu_translation",
    "ArticlePostRunOptions": ".run_options",
    "ArticleContentRunOptions": ".run_options",
    "ArticleImageRunOptions": ".run_options",
    "ArticleResearchRunOptions": ".run_options",
    "ImagePostRunOptions": ".run_options",
    "ImageRunOptions": ".run_options",
    "ResearchRunOptions": ".run_options",
    "VideoPostRunOptions": ".run_options",
    "VideoResearchRunOptions": ".run_options",
    "SkillSpec": ".skills",
    "StyleContext": ".style_context",
    "StylePromptRef": ".style_context",
    "VideoPostOrchestrator": ".video_route",
    "VideoWorkflowRunner": ".video_route",
    "video_workflow_module_graph": ".video_route",
    "WorkflowInvocation": ".schemas",
    "WorkflowRunContext": ".schemas",
    "WorkflowState": ".schemas",
    "WorkflowPlan": ".conversation",
    "ModuleGraphSpec": ".workflow_graph",
    "ModuleNodeSpec": ".workflow_graph",
    "WorkflowWorkspace": ".workspace",
    "WorkspaceManifest": ".workspace",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
