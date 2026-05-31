from __future__ import annotations

from src.config.settings import PathConfig

from .autonomous import resolve_autonomous_request
from .article_route import ArticlePostOrchestrator
from .conversation import ContentRoute, ConversationRequest, WorkflowPlan
from .image_route import ImagePostOrchestrator
from .route_runner import RouteRunner
from .skills import ProjectSkillRegistry
from .style_context import StyleContext
from .video_route import VideoPostOrchestrator


class FeishuContentPlanner:
    def __init__(self, *, skill_registry: ProjectSkillRegistry | None = None):
        self.skill_registry = skill_registry or ProjectSkillRegistry(
            skills_root=PathConfig.AGENT_SKILLS_DIR
        )

    def plan(self, request: ConversationRequest) -> WorkflowPlan:
        route = request.route_hint or self._infer_route(request)
        query = " ".join(
            [
                request.topic,
                request.message,
                request.audience,
                *request.style_constraints,
                route.value,
            ]
        )
        skill_matches = self.skill_registry.match(query)
        matched_skills = [skill.name for skill in skill_matches]
        style_context = StyleContext.from_request(request, matched_skills=skill_matches)
        rationale = (
            f"对话线索指向 {route.value}"
            if request.route_hint is not None
            else f"根据对话上下文动态选择 {route.value}"
        )
        return WorkflowPlan(
            route=route,
            matched_skills=matched_skills,
            rationale=rationale,
            style_constraints=list(request.style_constraints),
            style_context=style_context,
        )

    def _infer_route(self, request: ConversationRequest) -> ContentRoute:
        text = " ".join([request.topic, request.message, *request.style_constraints]).lower()
        if any(keyword in text for keyword in ("视频", "video", "短片", "混剪", "reel", "clip")):
            return ContentRoute.VIDEO_POST
        if any(keyword in text for keyword in ("长文", "文章", "article", "深度", "解读")):
            return ContentRoute.ARTICLE_POST
        return ContentRoute.IMAGE_POST


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
        plan = self.planner.plan(request)
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
