from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.orchestration.controller import FeishuContentOrchestrator, FeishuContentPlanner
from src.orchestration.conversation import ContentRoute, ConversationRequest
from src.orchestration.run_options import ImagePostRunOptions, ImageRunOptions, ResearchRunOptions
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope
from src.orchestration.skills import ProjectSkillRegistry


class FakeRunner:
    def __init__(self, route: str) -> None:
        self.route = route
        self.calls: list[dict[str, object]] = []

    async def run(
        self,
        request: ConversationRequest,
        *,
        run_id: str | None = None,
        chat_id: str | None = None,
        send_to_feishu: bool = False,
        style_context=None,
        run_options=None,
    ) -> ResultEnvelope[DeliveryPackage]:
        self.calls.append(
            {
                "topic": request.topic,
                "audience": request.audience,
                "user_message": request.message,
                "style_constraints": list(request.style_constraints),
                "image_count": request.image_count,
                "run_id": run_id,
                "chat_id": chat_id,
                "send_to_feishu": send_to_feishu,
                "style_context": style_context,
                "run_options": run_options,
            }
        )
        return ResultEnvelope[DeliveryPackage].success(
            agent_name=f"{self.route}_runner",
            payload=DeliveryPackage(route=self.route, title=request.topic, summary="ok"),
            summary="ok",
            run_id=run_id or "run-test",
            step_id="delivery",
        )


class FakePlanningAgent:
    def __init__(
        self,
        *,
        route: ContentRoute = ContentRoute.IMAGE_POST,
        selected_skill_names: list[str] | None = None,
        rationale: str = "agent selected the workflow",
    ) -> None:
        self.route = route
        self.selected_skill_names = selected_skill_names or []
        self.rationale = rationale
        self.calls: list[dict[str, object]] = []

    async def decide(self, request: ConversationRequest, *, available_skills: list[object]):
        self.calls.append(
            {
                "request": request,
                "available_skill_names": [getattr(skill, "name") for skill in available_skills],
            }
        )

        return SimpleNamespace(
            route=self.route,
            selected_skill_names=self.selected_skill_names,
            rationale=self.rationale,
        )


def _write_skill(root: Path, slug: str, *, name: str, description: str) -> None:
    skill_dir = root / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_planner_delegates_route_and_skill_selection_to_agent(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "pure-color",
        name="纯色背景单套穿搭",
        description="Use when the user wants a pure-color background and one outfit per image.",
    )
    _write_skill(
        skills_root,
        "feishu-delivery",
        name="飞书交付整理",
        description="Use when final content should be packaged and delivered to Feishu as the formal endpoint.",
    )
    planning_agent = FakePlanningAgent(
        route=ContentRoute.IMAGE_POST,
        selected_skill_names=["纯色背景单套穿搭", "飞书交付整理"],
        rationale="Agent read the request and selected image post with two skills.",
    )
    planner = FeishuContentPlanner(
        skill_registry=ProjectSkillRegistry(skills_root=skills_root),
        planning_agent=planning_agent,
    )

    plan = await planner.plan(
        ConversationRequest(
            topic="纯色背景穿搭",
            audience="通勤女生",
            message="发一组纯色背景图片，每张图只放一套穿搭，最后发到飞书",
            route_hint=ContentRoute.IMAGE_POST,
            style_constraints=["纯色背景", "单套展示"],
        )
    )

    assert plan.route is ContentRoute.IMAGE_POST
    assert "纯色背景单套穿搭" in plan.matched_skills
    assert "飞书交付整理" in plan.matched_skills
    assert plan.style_context is not None
    assert plan.style_context.user_constraints == ["纯色背景", "单套展示"]
    assert "纯色背景单套穿搭" in plan.style_context.matched_skills
    assert planning_agent.calls[0]["available_skill_names"] == ["纯色背景单套穿搭", "飞书交付整理"]
    assert "Agent read the request" in plan.rationale


@pytest.mark.anyio
async def test_planner_does_not_keyword_match_skills_when_agent_selects_another_skill(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "pure-color",
        name="纯色背景单套穿搭",
        description="Use when the user wants a pure-color background and one outfit per image.",
    )
    _write_skill(
        skills_root,
        "food-editorial",
        name="美食编辑摄影",
        description="Use when food images need tabletop editorial photography.",
    )
    planner = FeishuContentPlanner(
        skill_registry=ProjectSkillRegistry(skills_root=skills_root),
        planning_agent=FakePlanningAgent(
            route=ContentRoute.IMAGE_POST,
            selected_skill_names=["美食编辑摄影"],
        ),
    )

    plan = await planner.plan(
        ConversationRequest(
            topic="纯色背景穿搭",
            audience="通勤女生",
            message="这句话里有纯色背景和单套展示，但测试要求只信任 Planner Agent 的选择",
            style_constraints=["纯色背景", "单套展示"],
        )
    )

    assert plan.route is ContentRoute.IMAGE_POST
    assert plan.matched_skills == ["美食编辑摄影"]


@pytest.mark.anyio
async def test_orchestrator_dispatches_to_selected_route_runner(tmp_path: Path) -> None:
    planner = FeishuContentPlanner(
        skill_registry=ProjectSkillRegistry(skills_root=tmp_path),
        planning_agent=FakePlanningAgent(route=ContentRoute.VIDEO_POST),
    )
    image_runner = FakeRunner("image_post")
    article_runner = FakeRunner("article_post")
    video_runner = FakeRunner("video_post")
    orchestrator = FeishuContentOrchestrator(
        planner=planner,
        image_runner=image_runner,
        article_runner=article_runner,
        video_runner=video_runner,
    )

    result = await orchestrator.run_request(
        ConversationRequest(
            topic="短视频混剪灵感",
            audience="剪辑新手",
            message="做一个视频混剪选题发到飞书",
        ),
        chat_id="chat-1",
        run_id="run-controller-1",
        send_to_feishu=True,
    )

    assert result.payload is not None
    assert result.payload.route == "video_post"
    assert len(video_runner.calls) == 1
    assert video_runner.calls[0]["chat_id"] == "chat-1"
    assert video_runner.calls[0]["send_to_feishu"] is True
    assert not image_runner.calls
    assert not article_runner.calls


@pytest.mark.anyio
async def test_orchestrator_passes_dynamic_constraints_to_route_runner(tmp_path: Path) -> None:
    planner = FeishuContentPlanner(
        skill_registry=ProjectSkillRegistry(skills_root=tmp_path),
        planning_agent=FakePlanningAgent(route=ContentRoute.IMAGE_POST),
    )
    image_runner = FakeRunner("image_post")
    orchestrator = FeishuContentOrchestrator(planner=planner, image_runner=image_runner)

    await orchestrator.run_request(
        ConversationRequest(
            topic="登山穿搭",
            audience="户外新手",
            message="做 5 张图，不要人物，衣服平铺在纯色背景上",
            route_hint=ContentRoute.IMAGE_POST,
            style_constraints=["纯色背景", "平铺", "不要人物"],
            image_count=5,
        ),
        chat_id="chat-1",
        run_id="run-controller-constraints",
        send_to_feishu=True,
    )

    assert image_runner.calls[0]["user_message"] == "做 5 张图，不要人物，衣服平铺在纯色背景上"
    assert image_runner.calls[0]["style_constraints"] == ["纯色背景", "平铺", "不要人物"]
    assert image_runner.calls[0]["image_count"] == 5
    style_context = image_runner.calls[0]["style_context"]
    assert style_context is not None
    assert style_context.user_constraints == ["纯色背景", "平铺", "不要人物"]
    assert "不要人物" in " ".join(style_context.hard_constraints)


@pytest.mark.anyio
async def test_orchestrator_passes_call_time_run_options_to_route_runner(tmp_path: Path) -> None:
    planner = FeishuContentPlanner(
        skill_registry=ProjectSkillRegistry(skills_root=tmp_path),
        planning_agent=FakePlanningAgent(route=ContentRoute.IMAGE_POST),
    )
    image_runner = FakeRunner("image_post")
    orchestrator = FeishuContentOrchestrator(planner=planner, image_runner=image_runner)
    run_options = ImagePostRunOptions(
        research=ResearchRunOptions(min_posts_researched=5, validation_max_retries=2),
        image=ImageRunOptions(max_retries=2, image_size="4K"),
    )

    await orchestrator.run_request(
        ConversationRequest(
            topic="参考图穿搭",
            audience="通勤女生",
            message="参考图里的衣服必须出现",
            route_hint=ContentRoute.IMAGE_POST,
            image_count=2,
        ),
        chat_id="chat-1",
        run_id="run-controller-runtime-options",
        send_to_feishu=True,
        run_options=run_options,
    )

    assert image_runner.calls[0]["run_options"] is run_options
