import asyncio

from src.agents.image_post.image.agent import ImageAgent
from src.agents.image_post.image.template_agent import TemplateSelectionResult
from src.agents.image_post.schemas import ImageGenContext, ResearchItem, ResearchResult, XHSContent
from src.orchestration.conversation import ConversationRequest
from src.orchestration.style_context import StyleContext


class _EchoPromptGenerator:
    async def run(self, prompt, deps):
        class _Result:
            output = prompt

        return _Result()


class _DomainPromptSelector:
    def __init__(self, guidance_by_topic: dict[str, tuple[str, str]]) -> None:
        self.guidance_by_topic = guidance_by_topic
        self.calls = []

    async def select_template(self, *, topic, content, research, image_spec, style_context):
        self.calls.append(
            {
                "topic": topic,
                "image_spec": image_spec,
                "style_context": style_context,
            }
        )
        source_path, guidance = self.guidance_by_topic[topic]
        return TemplateSelectionResult(
            source_paths=[source_path],
            why_this_template="template selector agent chose this prompt from the user's current need",
            group_content_fit="fits the current detail group",
            prompt_guidance=guidance,
        )


def _content(topic: str) -> XHSContent:
    return XHSContent(
        title=f"{topic}灵感清单",
        body="这是一段用于测试动态风格提示词注入的正文，需要足够长以满足内容 schema 的最小长度。" * 8,
        hashtags=["#小红书灵感"],
    )


def _research(*items: tuple[str, str]) -> ResearchResult:
    return ResearchResult(
        summary="multi-domain style prompt test",
        items=[
            ResearchItem(title=title, content=content, item_type="idea")
            for title, content in items
        ],
        keywords=[],
        sources=[],
    )


def test_image_prompt_injects_dynamic_prompt_library_for_multiple_domains() -> None:
    cases = [
        {
            "request": ConversationRequest(
                topic="登山轻量化穿搭",
                audience="户外新手女生",
                message="衣服平铺在纯色背景上，不要人物",
                style_constraints=["纯色背景", "平铺", "不要人物", "单套穿搭"],
                image_count=5,
            ),
            "research": _research(
                ("防风外套", "轻量冲锋衣、速干裤和抓地徒步鞋组成一套登山 look"),
                ("甜品店", "这条内容不属于当前穿搭分组"),
            ),
            "image_spec": {"type": "detail_1", "desc": "详情图1", "group_title": "登山 look", "indices": [0]},
            "selected": (
                ".agents/prompt/image/fashion/pure-color-single-look.md",
                "Use pure-color-single-look guidance: pure color background and one flat-lay outfit.",
            ),
            "expected": ["pure-color-single-look", "pure color background", "轻量冲锋衣"],
            "unexpected": ["甜品店"],
        },
        {
            "request": ConversationRequest(
                topic="周末甜品探店",
                audience="城市通勤女生",
                message="温暖胶片感，桌面上有蛋糕、咖啡和自然光",
                style_constraints=["温暖胶片感", "桌面美食摄影", "自然光"],
                image_count=4,
            ),
            "research": _research(("柠檬塔和拿铁", "木桌、陶瓷盘、自然光下的甜品组合")),
            "image_spec": {"type": "detail_1", "desc": "详情图1", "group_title": "甜品桌面", "indices": [0]},
            "selected": (
                ".agents/prompt/image/food/editorial-tabletop.md",
                "Use editorial-tabletop guidance: food editorial photography with warm film color.",
            ),
            "expected": ["editorial-tabletop", "food editorial photography", "柠檬塔"],
            "unexpected": ["冲锋衣"],
        },
        {
            "request": ConversationRequest(
                topic="敏感肌精华测评",
                audience="护肤新手",
                message="参考产品图做成干净的货架感，弱化品牌名",
                style_constraints=["产品参考图对齐", "干净货架感", "弱化品牌名"],
                image_count=3,
            ),
            "research": _research(("屏障精华", "半透明瓶身、白色标签、浴室货架感陈列")),
            "image_spec": {"type": "detail_1", "desc": "详情图1", "group_title": "产品陈列", "indices": [0]},
            "selected": (
                ".agents/prompt/image/product/reference-alignment.md",
                "Use reference-alignment guidance: reference image alignment and clean shelf composition.",
            ),
            "expected": ["reference-alignment", "reference image alignment", "半透明瓶身"],
            "unexpected": ["蛋糕"],
        },
    ]

    agent = ImageAgent.__new__(ImageAgent)
    agent.prompt_generator = _EchoPromptGenerator()
    selector = _DomainPromptSelector(
        {
            case["request"].topic: case["selected"]
            for case in cases
        }
    )
    agent.template_selector = selector

    for case in cases:
        request = case["request"]
        style_context = StyleContext.from_request(request, matched_skills=[])
        assert not any(".agents/prompt" in ref.source for ref in style_context.prompt_refs)
        prompt = asyncio.run(
            agent.generate_prompt(
                content=_content(request.topic),
                research=case["research"],
                topic=request.topic,
                image_spec=case["image_spec"],
                gen_ctx=ImageGenContext(topic=request.topic, image_type=case["image_spec"]["type"]),
                style_context=style_context,
            )
        )

        for expected in case["expected"]:
            assert expected in prompt
        for unexpected in case["unexpected"]:
            assert unexpected not in prompt

    assert len(selector.calls) == len(cases)
    assert all(call["style_context"] is not None for call in selector.calls)
