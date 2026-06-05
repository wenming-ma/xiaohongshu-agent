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

    matched_skills = [
        skill for skill in registry.discover()
        if skill.name == "pure-color-single-look"
    ]
    context = StyleContext.from_request(request, matched_skills=matched_skills)

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


def test_style_context_carries_reference_images_as_hard_visual_constraints(tmp_path: Path) -> None:
    ref_path = tmp_path / "outfit-reference.jpg"
    ref_path.write_bytes(b"fake-reference")
    request = ConversationRequest(
        topic="用参考图做一组通勤穿搭图文",
        audience="通勤女生",
        message="参考图里的衣服必须出现在生成图里，背景干净，发飞书",
        reference_images=[str(ref_path)],
    )

    context = StyleContext.from_request(request, matched_skills=[])

    assert context.reference_images[0].path == str(ref_path)
    assert context.reference_images[0].label == "reference_1"
    assert any("参考图" in item and "必须出现在生成图" in item for item in context.hard_constraints)
    assert "reference_images" in context.metadata()
    assert context.reference_image_inputs() == [("reference_1", ref_path)]


def test_style_context_keeps_style_only_reference_images_from_forcing_subject_preservation(
    tmp_path: Path,
) -> None:
    ref_path = tmp_path / "warm-cafe-style.jpg"
    ref_path.write_bytes(b"fake-reference")
    request = ConversationRequest(
        topic="咖啡馆封面图",
        audience="通勤女生",
        message="只参考这张图的暖色咖啡馆窗边光线、胶片颗粒和木桌质感；不要求保留原图物体，不要生成原图里的通勤包。",
        style_constraints=[
            "只参考风格、色调、光线和氛围",
            "不要求保留原图物体",
            "不要保留或生成原图里的通勤包",
        ],
        image_count=1,
        reference_images=[str(ref_path)],
    )

    context = StyleContext.from_request(request, matched_skills=[])
    prompt_text = context.to_prompt_section()

    assert context.reference_intent == "style_reference"
    assert not any("必须出现在生成图" in item for item in context.hard_constraints)
    assert "只参考" in prompt_text
    assert "不要保留参考图中的具体物体" in prompt_text
    assert "必须识别参考图片中的核心衣物" not in prompt_text


def test_style_context_distinguishes_composition_scene_and_material_reference_images(
    tmp_path: Path,
) -> None:
    cases = [
        (
            "composition_reference",
            "只参考这张图的版式、构图比例和留白节奏，不保留原图物体。",
            "reference_role=composition_reference",
            "只参考参考图的构图、版式、镜头角度、画面比例或空间布局",
        ),
        (
            "scene_reference",
            "只参考这张图的室内咖啡馆场景、窗边环境和空间氛围，不保留主体。",
            "reference_role=scene_reference",
            "只参考参考图的场景类型、环境氛围、空间关系或地点线索",
        ),
        (
            "material_color_reference",
            "只参考这张图的面料纹理、材质质感和颜色搭配，不迁移物体。",
            "reference_role=material_color_reference",
            "只参考参考图的材质纹理、面料质感、色彩搭配或表面细节",
        ),
    ]

    for expected_intent, message, expected_role, expected_prompt in cases:
        ref_path = tmp_path / f"{expected_intent}.jpg"
        ref_path.write_bytes(b"fake-reference")
        request = ConversationRequest(
            topic="参考图生成测试",
            audience="通勤女生",
            message=message,
            reference_images=[str(ref_path)],
        )

        context = StyleContext.from_request(request, matched_skills=[])
        prompt_text = context.to_prompt_section()

        assert context.reference_intent == expected_intent
        assert any(expected_role in item for item in context.hard_constraints)
        assert expected_prompt in prompt_text
        assert "必须识别参考图片中的核心衣物" not in prompt_text


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


def test_style_context_does_not_keyword_select_prompt_library() -> None:
    request = ConversationRequest(
        topic="周末甜品探店",
        audience="城市通勤女生",
        message="要温暖胶片感，桌面上有蛋糕、咖啡和自然光",
        style_constraints=["温暖胶片感", "桌面美食摄影", "自然光"],
        image_count=4,
    )

    context = StyleContext.from_request(request, matched_skills=[])

    assert context.prompt_refs == []
    assert context.trace["source"] == "conversation_request_and_project_skills"
    assert context.trace["prompt_ref_count"] == 0
    assert "query" not in context.trace


def test_style_context_default_negative_constraints_prevent_text_cards() -> None:
    request = ConversationRequest(
        topic="雨天通勤鞋包护理",
        audience="通勤女生",
        message="生成真实摄影质感的产品图，干净纯色背景，不要人物",
        style_constraints=[],
        image_count=2,
    )

    context = StyleContext.from_request(request, matched_skills=[])
    negative_text = " ".join(context.negative_constraints)

    assert "标题" in negative_text
    assert "副标题" in negative_text
    assert "文字海报" in negative_text
    assert "任何可读文字" in negative_text
    assert "飞书正文" in negative_text


def test_prompt_library_readme_records_agent_driven_template_selection() -> None:
    readme = (PROJECT_ROOT / ".agents" / "prompt" / "README.md").read_text(encoding="utf-8")

    assert "ImagePromptTemplateAgent" in readme
    assert "`StyleContext`" not in readme
    assert "keyword" not in readme.lower()
