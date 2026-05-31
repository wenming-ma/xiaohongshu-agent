from __future__ import annotations

from src.config.settings import PathConfig

from .autonomous import resolve_autonomous_request
from .article_route import ArticlePostOrchestrator
from .conversation import ContentRoute, ConversationRequest, WorkflowPlan
from .image_route import ImagePostOrchestrator
from .planning_agent import PlanningAgent
from .route_runner import RouteRunner
from .skills import ProjectSkillRegistry
from .style_context import StyleContext
from .video_route import VideoPostOrchestrator


class FeishuContentPlanner:
    def __init__(
        self,
        *,
        skill_registry: ProjectSkillRegistry | None = None,
        planning_agent: object | None = None,
    ):
        self.skill_registry = skill_registry or ProjectSkillRegistry(
            skills_root=PathConfig.AGENT_SKILLS_DIR
        )
        self.planning_agent = planning_agent or PlanningAgent()

    async def plan(self, request: ConversationRequest) -> WorkflowPlan:
        available_skills = self.skill_registry.discover()
        decision = await self.planning_agent.decide(
            request,
            available_skills=available_skills,
        )
        route = decision.route
        selected_names = list(dict.fromkeys(getattr(decision, "selected_skill_names", []) or []))
        available_by_name = {skill.name: skill for skill in available_skills}
        skill_matches = [
            available_by_name[name]
            for name in selected_names
            if name in available_by_name
        ]
        matched_skills = [skill.name for skill in skill_matches]
        style_context = StyleContext.from_request(request, matched_skills=skill_matches)
        return WorkflowPlan(
            route=route,
            matched_skills=matched_skills,
            rationale=getattr(decision, "rationale", "") or f"Planner Agent selected {route.value}",
            style_constraints=list(request.style_constraints),
            style_context=style_context,
        )


class FeishuContentOrchestrator:
    def __init__(
        self,
        *,
        planner: FeishuContentPlanner | None = None,
        image_runner: RouteRunner | None = None,
        article_runner: RouteRunner | None = None,
        video_runner: RouteRunner | None = None,
    ) -> None:
        self.planner = planner or FeishuContentPlanner()
        self.image_runner = image_runner or ImagePostOrchestrator()
        self.article_runner = article_runner or ArticlePostOrchestrator()
        self.video_runner = video_runner or VideoPostOrchestrator()

    async def run_request(
        self,
        request: ConversationRequest,
        *,
        chat_id: str | None = None,
        run_id: str | None = None,
        send_to_feishu: bool = False,
    ):
        request = self.prepare_request(request)
        plan = await self.planner.plan(request)
        runner = self._get_runner(plan.route)
        return await runner.run(
            request,
            run_id=run_id,
            chat_id=chat_id,
            send_to_feishu=send_to_feishu,
            style_context=plan.style_context,
        )

    def prepare_request(self, request: ConversationRequest) -> ConversationRequest:
        return resolve_autonomous_request(request)

    def _get_runner(self, route: ContentRoute) -> RouteRunner:
        if route is ContentRoute.IMAGE_POST:
            return self.image_runner
        if route is ContentRoute.ARTICLE_POST and self.article_runner is not None:
            return self.article_runner
        if route is ContentRoute.VIDEO_POST and self.video_runner is not None:
            return self.video_runner
        raise ValueError(f"Route runner not configured: {route.value}")
