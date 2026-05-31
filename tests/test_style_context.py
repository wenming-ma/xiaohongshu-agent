from __future__ import annotations

from pathlib import Path

from src.config.settings import PathConfig
from src.orchestration.conversation import ConversationRequest
from src.orchestration.skills import ProjectSkillRegistry
from src.orchestration.style_context import StyleContext


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_skill(
    root: Path,
    slug: str,
    *,
    name: str,
    description: str,
    body: str,
    reference_name: str = "style.md",
    reference_body: str = "",
) -> None:
    skill_dir = root / slug
    refs_dir = skill_dir / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    (refs_dir / reference_name).write_text(reference_body or body, encoding="utf-8")


def test_style_context_uses_user_constraints_and_repository_skill_references(tmp_path: Path) -> None:
    skills_root = tmp_path / ".agents" / "skills"
    _write_skill(
        skills_root,
        "pure-color-single-look",
        name="pure-color-single-look",
        description="纯色背景，单套展示，不要人物；Pure color background, single outfit per image, no model.",
        body="# Pure color\n\nKeep each image focused on one outfit.",
        reference_body=(
            "# Runtime Style Notes\n\n"
            "- Use a flat pure-color background.\n"
            "- Show exactly one outfit per image.\n"
            "- Avoid people, mannequins, app screenshots, login dialogs, and diagnostic cards.\n"
        ),
    )
    registry = ProjectSkillRegistry(skills_root=skills_root)
    request = ConversationRequest(
        topic="登山穿搭",
        audience="户外新手",
        message="做 5 张图，不要人物，衣服平铺在纯色背景上",
        style_constraints=["纯色背景", "平铺", "不要人物"],
        image_count=5,
    )

    context = StyleContext.from_request(
        request,
        matched_skills=registry.match("纯色背景 单套展示 不要人物"),
    )

    assert context.user_constraints == ["纯色背景", "平铺", "不要人物"]
    assert context.matched_skills == ["pure-color-single-look"]
    assert context.prompt_refs
    assert context.prompt_refs[0].source.endswith(
        ".agents/skills/pure-color-single-look/references/style.md"
    )
    assert "flat pure-color background" in context.prompt_refs[0].excerpt
    assert "app screenshots" in " ".join(context.negative_constraints)


def test_style_context_is_stable_without_local_prompt_template_repository(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROMPT_TEMPLATE_ROOT", str(tmp_path / "missing-template-repos"))
    request = ConversationRequest(
        topic="约会穿搭",
        audience="通勤女生",
        message="柔和、干净、不要人物",
        style_constraints=["柔和色块", "不要人物"],
    )

    context = StyleContext.from_request(request, matched_skills=[])

    assert context.prompt_refs == []
    assert context.user_constraints == ["柔和色块", "不要人物"]
    assert "不要人物" in context.hard_constraints
    assert context.trace["source"] == "conversation_request_and_project_skills"


def test_style_context_formats_prompt_without_runtime_schema_leaking_into_skill() -> None:
    context = StyleContext(
        user_constraints=["纯色背景"],
        matched_skills=["pure-color-single-look"],
        prompt_refs=[],
        hard_constraints=["纯色背景"],
        negative_constraints=["不要生成登录弹窗或研究限制说明"],
        trace={"source": "test"},
    )

    prompt_text = context.to_prompt_section()

    assert "## 风格上下文" in prompt_text
    assert "pure-color-single-look" in prompt_text
    assert "纯色背景" in prompt_text
    assert "ResultEnvelope" not in prompt_text


def test_prompt_library_lives_in_agents_prompt_without_legacy_root() -> None:
    legacy_root_name = "." + "prompt" + "-template" + "-repos"
    assert PathConfig.PROMPT_TEMPLATE_ROOT == PROJECT_ROOT / ".agents" / "prompt"
    assert PathConfig.PROMPT_TEMPLATE_ROOT.is_dir()
    assert not (PROJECT_ROOT / legacy_root_name).exists()
    assert legacy_root_name not in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")


def test_style_context_loads_repository_prompt_library_for_multiple_domains() -> None:
    registry = ProjectSkillRegistry(skills_root=PathConfig.AGENT_SKILLS_DIR)
    cases = [
        (
            ConversationRequest(
                topic="登山轻量化穿搭",
                audience="户外新手女生",
                message="做 5 张图，衣服平铺在纯色背景上，不要人物",
                style_constraints=["纯色背景", "平铺", "不要人物", "单套穿搭"],
                image_count=5,
            ),
            "pure color",
            "fashion",
        ),
        (
            ConversationRequest(
                topic="周末甜品探店",
                audience="城市通勤女生",
                message="要温暖胶片感，桌面上有蛋糕、咖啡和自然光",
                style_constraints=["温暖胶片感", "桌面美食摄影", "自然光"],
                image_count=4,
            ),
            "food editorial",
            "food",
        ),
        (
            ConversationRequest(
                topic="敏感肌精华测评",
                audience="护肤新手",
                message="参考产品图做成干净的货架感，不要把品牌名放太大",
                style_constraints=["产品参考图对齐", "干净货架感", "弱化品牌名"],
                image_count=3,
            ),
            "reference image",
            "product",
        ),
    ]

    for request, expected_excerpt, expected_source_marker in cases:
        matched_skills = registry.match(" ".join([request.topic, request.message, *request.style_constraints]))
        context = StyleContext.from_request(request, matched_skills=matched_skills)
        prompt_section = context.to_prompt_section().lower()
        sources = " ".join(ref.source.lower() for ref in context.prompt_refs)

        assert context.prompt_refs
        assert ".agents/prompt" in sources
        assert expected_source_marker in sources
        assert expected_excerpt in prompt_section
        assert request.topic in context.trace["query"]
