import asyncio
from pathlib import Path

from src.agents.image_post.image.agent import ImageAgent
from src.agents.image_post.image.template_agent import (
    ImagePromptTemplateAgent,
    TemplateSelectionResult,
    build_template_selection_prompt,
)
from src.agents.image_post.schemas import ImageGenContext, ResearchItem, ResearchResult, XHSContent


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
