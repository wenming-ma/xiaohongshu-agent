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
    "AgentEventBridge": ".agent_events",
    "QueuedAgentEvent": ".agent_events",
    "FeishuInteractionTools": ".feishu_interactions",
    "FeishuWorkflowService": ".feishu_workflow",
    "FeishuContentOrchestrator": ".controller",
    "FeishuContentPlanner": ".controller",
    "GroupingItem": ".schemas",
    "GroupingResult": ".schemas",
    "ImagePostOrchestrator": ".image_route",
    "ManifestStep": ".workspace",
    "PlanningAgent": ".planning_agent",
    "PlanningDecision": ".planning_agent",
    "ProjectSkillRegistry": ".skills",
    "ResultEnvelope": ".schemas",
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
