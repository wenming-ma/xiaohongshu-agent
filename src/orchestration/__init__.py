"""Shared orchestration primitives for Feishu-first content workflows."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ArtifactRef": ".schemas",
    "ArticlePostOrchestrator": ".article_route",
    "ContentRoute": ".conversation",
    "ConversationRequest": ".conversation",
    "DeliveryPackage": ".schemas",
    "DeliveryPackageSender": ".delivery",
    "DeliveryTextBlock": ".schemas",
    "ChoiceOption": ".feishu_translation",
    "AgentEventBridge": ".agent_events",
    "QueuedAgentEvent": ".agent_events",
    "FeishuInteractionTranslator": ".feishu_translation",
    "FeishuInteractionTools": ".feishu_interactions",
    "FeishuSessionResetRequested": ".feishu_interactions",
    "FeishuWorkflowService": ".feishu_workflow",
    "FeishuContentOrchestrator": ".controller",
    "FeishuContentPlanner": ".controller",
    "GroupingItem": ".schemas",
    "GroupingResult": ".schemas",
    "ImagePostOrchestrator": ".image_route",
    "InteractionDecision": ".feishu_interactions",
    "InteractionDecisionAgent": ".feishu_interactions",
    "ManifestStep": ".workspace",
    "PlanningAgent": ".planning_agent",
    "PlanningDecision": ".planning_agent",
    "ProjectSkillRegistry": ".skills",
    "ResultEnvelope": ".schemas",
    "parse_delimited_options": ".feishu_translation",
    "ImagePostRunOptions": ".run_options",
    "ImageRunOptions": ".run_options",
    "ResearchRunOptions": ".run_options",
    "SkillSpec": ".skills",
    "StyleContext": ".style_context",
    "StylePromptRef": ".style_context",
    "VideoPostOrchestrator": ".video_route",
    "WorkflowPlan": ".conversation",
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
