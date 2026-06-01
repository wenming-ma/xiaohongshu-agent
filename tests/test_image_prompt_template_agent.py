import asyncio
from pathlib import Path

from src.agents.image_post.image.agent import ImageAgent
from src.agents.image_post.image.template_agent import (
    ImagePromptTemplateAgent,
    TemplateSelectionResult,
    build_template_selection_prompt,
)
from src.agents.image_post.image.prompts import image_system_prompt
from src.agents.image_post.schemas import ImageGenContext, ImageQualityReview, ResearchItem, ResearchResult, XHSContent
from src.agents.image_post.utils.image import calculate_grouping_params, groups_to_image_specs
from src.orchestration.run_options import ImageRunOptions


class _EchoPromptGenerator:
    async def run(self, prompt, deps):
        class _Result:
            output = prompt

        return _Result()


class _RecordingTemplateSelector:
    def __init__(self) -> None:
        self.calls = []

    async def select_template(self, *, topic, content, research, image_spec, style_context):
        self.calls.append(
            {
                "topic": topic,
                "content": content,
                "research": research,
                "image_spec": image_spec,
                "style_context": style_context,
            }
        )
        return TemplateSelectionResult(
            source_paths=["repo/prompt.md"],
            selected_template_excerpt="editorial food template",
            why_this_template="matches current group",
            group_content_fit="covers the selected group items",
            prompt_guidance="Use the local template as a warm editorial tabletop visual direction.",
            fallback_used=False,
        )


class _FailingTemplateSelector:
    async def select_template(self, **_kwargs):
        raise RuntimeError("template directory missing")


def test_calculate_grouping_params_uses_requested_count_for_general_image_posts() -> None:
    target_groups, target_group_size, max_group_size_cap, require_all_items = calculate_grouping_params(
        20,
        requested_image_count=10,
        single_item_per_image=False,
    )

    assert target_groups == 9
    assert target_group_size >= 3
    assert max_group_size_cap >= target_group_size
    assert require_all_items is True


class _RecordingImageClient:
    def __init__(self, image_path: Path) -> None:
        self.image_path = image_path
        self.calls = []

    async def generate_image(self, **kwargs):
        self.calls.append(kwargs)
        self.image_path.write_bytes(b"fake-image")
        return self.image_path


class _PassingImageValidator:
    async def validate(self, image_path: Path, context: dict):
        return ImageQualityReview(
            passed=True,
            text_clarity_score=95,
            style_score=95,
            aspect_ratio_correct=True,
            text_is_chinese=True,
            issues=[],
            summary="ok",
        )


def _content() -> XHSContent:
    return XHSContent(
        title="西安周末美食路线这样安排",
        body="这是一段用于测试的正文内容。" * 10,
        hashtags=["#西安美食"],
    )


def _research() -> ResearchResult:
    return ResearchResult(
        summary="summary",
        items=[
            ResearchItem(title="肉夹馍", content="适合放在早餐路线里，热乎、顶饱"),
            ResearchItem(title="冰峰", content="适合搭配小吃，画面可以出现橙色汽水"),
        ],
        keywords=[],
        sources=[],
    )


def test_generate_prompt_lets_template_agent_explore_for_current_group() -> None:
    agent = ImageAgent.__new__(ImageAgent)
    agent.prompt_generator = _EchoPromptGenerator()
    selector = _RecordingTemplateSelector()
    agent.template_selector = selector

    prompt = asyncio.run(
        agent.generate_prompt(
            content=_content(),
            research=_research(),
            topic="西安周末美食路线",
            image_spec={
                "type": "detail_1",
                "desc": "详情图1 - 语义分组：早餐路线",
                "group_title": "早餐路线",
                "indices": [0],
            },
            gen_ctx=ImageGenContext(topic="西安周末美食路线", image_type="detail_1"),
        )
    )

    assert selector.calls[0]["image_spec"]["indices"] == [0]
    assert selector.calls[0]["style_context"] is None
    assert "本图主题板块：早餐路线" in prompt
    assert "肉夹馍" in prompt
    assert "冰峰" not in prompt
    assert "Use the local template as a warm editorial tabletop visual direction." in prompt
    assert "repo/prompt.md" in prompt


def test_generate_prompt_passes_style_context_to_template_agent() -> None:
    from src.orchestration.style_context import StyleContext

    agent = ImageAgent.__new__(ImageAgent)
    agent.prompt_generator = _EchoPromptGenerator()
    selector = _RecordingTemplateSelector()
    agent.template_selector = selector
    style_context = StyleContext(
        user_constraints=["温暖胶片感", "桌面美食摄影"],
        matched_skills=[],
        prompt_refs=[],
        hard_constraints=["温暖胶片感"],
        negative_constraints=[],
        trace={"source": "test"},
    )

    prompt = asyncio.run(
        agent.generate_prompt(
            content=_content(),
            research=_research(),
            topic="西安周末美食路线",
            image_spec={
                "type": "detail_1",
                "desc": "详情图1 - 语义分组：早餐路线",
                "group_title": "早餐路线",
                "indices": [0],
            },
            gen_ctx=ImageGenContext(topic="西安周末美食路线", image_type="detail_1"),
            style_context=style_context,
        )
    )

    assert selector.calls[0]["style_context"] is style_context
    assert "温暖胶片感" in prompt
    assert "## 图片提示词增强关键词" in prompt
    assert "subject:" in prompt
    assert "action:" in prompt
    assert "location:" in prompt
    assert "camera_control:" in prompt
    assert "lighting:" in prompt
    assert "style:" in prompt
    assert "所有关键词都必须被纳入最终 Gemini 图片提示词" in prompt


def test_generate_prompt_keyword_expansion_uses_call_time_image_size() -> None:
    agent = ImageAgent.__new__(ImageAgent)
    agent.run_options = ImageRunOptions(image_size="2K", aspect_ratio="3:4")
    agent.prompt_generator = _EchoPromptGenerator()
    agent.template_selector = _FailingTemplateSelector()

    prompt = asyncio.run(
        agent.generate_prompt(
            content=_content(),
            research=_research(),
            topic="西安周末美食路线",
            image_spec={
                "type": "detail_1",
                "desc": "详情图1 - 语义分组：早餐路线",
                "group_title": "早餐路线",
                "indices": [0],
            },
            gen_ctx=ImageGenContext(topic="西安周末美食路线", image_type="detail_1"),
        )
    )

    assert "target_resolution: 2K" in prompt
    assert "target_aspect_ratio: 3:4" in prompt
    assert "4K ultra-high resolution" not in image_system_prompt()


def test_generate_prompt_falls_back_when_template_agent_fails() -> None:
    agent = ImageAgent.__new__(ImageAgent)
    agent.prompt_generator = _EchoPromptGenerator()
    agent.template_selector = _FailingTemplateSelector()

    prompt = asyncio.run(
        agent.generate_prompt(
            content=_content(),
            research=_research(),
            topic="西安周末美食路线",
            image_spec={
                "type": "detail_1",
                "desc": "详情图1 - 语义分组：早餐路线",
                "group_title": "早餐路线",
                "indices": [0],
            },
            gen_ctx=ImageGenContext(topic="西安周末美食路线", image_type="detail_1"),
        )
    )

    assert "本图主题板块：早餐路线" in prompt
    assert "Use the local template" not in prompt


def test_template_agent_skips_model_when_template_root_missing(tmp_path: Path) -> None:
    selector = ImagePromptTemplateAgent.__new__(ImagePromptTemplateAgent)
    selector.toolset = type("_Toolset", (), {"root": tmp_path / "missing"})()
    selector.agent = type(
        "_UnexpectedAgent",
        (),
        {"run": lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("model should not run"))},
    )()

    result = asyncio.run(
        selector.select_template(
            topic="西安周末美食路线",
            content=_content(),
            research=_research(),
            image_spec={"type": "cover", "desc": "封面图"},
        )
    )

    assert result.fallback_used is True
    assert result.prompt_guidance == ""


def test_template_selection_prompt_includes_style_context_for_agent_choice() -> None:
    from src.orchestration.style_context import StyleContext

    prompt = build_template_selection_prompt(
        topic="周末甜品探店",
        content=_content(),
        research=_research(),
        image_spec={
            "type": "detail_1",
            "desc": "详情图1 - 语义分组：早餐路线",
            "group_title": "早餐路线",
            "indices": [0],
        },
        style_context=StyleContext(
            user_constraints=["温暖胶片感", "桌面美食摄影"],
            matched_skills=["feishu-review-delivery"],
            prompt_refs=[],
            hard_constraints=["自然光"],
            negative_constraints=["不要菜单板"],
            trace={"source": "test"},
        ),
    )

    assert "style_context" in prompt
    assert "温暖胶片感" in prompt
    assert "桌面美食摄影" in prompt
    assert "不要菜单板" in prompt


def test_template_selection_prompt_defaults_to_pure_visual_not_title_card() -> None:
    prompt = build_template_selection_prompt(
        topic="雨天通勤鞋包护理",
        content=_content(),
        research=_research(),
        image_spec={"type": "cover", "desc": "封面图"},
    )

    assert "优先纯视觉" in prompt
    assert "不生成标题字卡" in prompt
    assert "明确需要文字海报或信息图" in prompt


def test_image_system_prompt_keeps_text_optional_for_realistic_images() -> None:
    prompt = image_system_prompt()

    assert "普通写实、产品、穿搭、生活方式图片优先做纯视觉图" in prompt
    assert "不生成标题、副标题、海报字卡或大段文字" in prompt
    assert "只有当前任务明确要求文字海报、信息图、知识卡或图内文字时" in prompt


def test_cover_image_spec_no_longer_requests_big_title_card() -> None:
    specs = groups_to_image_specs([{"title": "护理组合", "indices": [0]}])
    cover_desc = str(specs[0]["desc"])

    assert specs[0]["type"] == "cover"
    assert "纯视觉主图" in cover_desc
    assert "不要生成标题文字" in cover_desc
    assert "大标题风格" not in cover_desc


def test_generate_via_api_passes_reference_images_to_image_client(tmp_path: Path) -> None:
    from src.orchestration.style_context import StyleContext

    agent = ImageAgent.__new__(ImageAgent)
    agent.prompt_generator = _EchoPromptGenerator()
    agent.template_selector = _FailingTemplateSelector()
    output_image = tmp_path / "detail_1.png"
    image_client = _RecordingImageClient(output_image)
    agent.image_client = image_client
    agent.image_quality_validator = _PassingImageValidator()
    reference = tmp_path / "reference-outfit.jpg"
    reference.write_bytes(b"reference-bytes")
    style_context = StyleContext.from_request(
        type(
            "_Request",
            (),
            {
                "style_constraints": ["参考图里的衣服必须出现"],
                "image_count": 1,
                "reference_images": [str(reference)],
            },
        )(),
        matched_skills=[],
    )

    image_path, final_prompt = asyncio.run(
        agent.generate_via_api(
            output_dir=tmp_path,
            image_type="detail_1",
            topic="参考图通勤穿搭",
            gen_ctx=ImageGenContext(topic="参考图通勤穿搭", image_type="detail_1"),
            content=_content(),
            research=_research(),
            image_spec={
                "type": "detail_1",
                "desc": "详情图1 - 参考图穿搭",
                "group_title": "参考图穿搭",
                "indices": [0],
            },
            style_context=style_context,
            max_retries=1,
        )
    )

    assert image_path == output_image
    assert image_client.calls[0]["reference_images"] == [("reference_1", reference)]
    assert image_client.calls[0]["reference_mode"] == "gemini_content"
    assert image_client.calls[0]["image_size"]
    assert image_client.calls[0]["aspect_ratio"] == "3:4"
    assert "用户参考图片" in final_prompt
    assert "必须出现在生成图" in final_prompt
