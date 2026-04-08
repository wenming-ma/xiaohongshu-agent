import asyncio
from pathlib import Path

from src.agents.outfit_post.image.agent import ImageAgent
from src.agents.outfit_post.image.prompts import image_grouping_review_system_prompt
from src.agents.outfit_post.utils.image import run_grouping_with_review
from src.agents.outfit_post.schemas import (
    GeneratedImage,
    ImageGenContext,
    ImageGroupingPlan,
    ImageGroupingReviewResult,
    OutfitItem,
    ReferenceImageResult,
    ItemReferenceImages,
    ResearchItem,
    ResearchResult,
    XHSContent,
)


class _EchoPromptGenerator:
    async def run(self, prompt, deps):
        class _Result:
            output = prompt

        return _Result()


class _FakeGroupingAgentWithRefItems:
    def __init__(self):
        self.calls = []
        self.round_messages = []

    async def run(self, prompt, message_history=None):
        history = list(message_history or [])
        self.calls.append({"prompt": prompt, "message_history": history})
        messages = []
        self.round_messages.append(messages)

        class _Result:
            def __init__(self, output, messages):
                self.output = output
                self._messages = messages

            def new_messages(self):
                return self._messages

        return _Result(
            ImageGroupingPlan(
                groups=[
                    {
                        "title": "上半身",
                        "indices": [0],
                        "ref_items": ["白色衬衫", "白色衬衫", "黑色西裤"],
                    },
                    {
                        "title": "下半身",
                        "indices": [1],
                        "ref_items": ["黑色西裤"],
                    },
                ]
            ),
            messages,
        )


class _PassingGroupingReviewer:
    def __init__(self):
        self.calls = []

    async def run(self, prompt, message_history=None):
        self.calls.append({"prompt": prompt, "message_history": list(message_history or [])})

        class _Result:
            def __init__(self, output):
                self.output = output

            def new_messages(self):
                return []

        return _Result(
            ImageGroupingReviewResult(
                passed=True,
                score=96.0,
                issues=[],
                summary="通过",
            )
        )


def test_grouping_review_prompt_allows_same_reference_item_across_groups() -> None:
    prompt = image_grouping_review_system_prompt()

    assert "同一个参考图物品名不应出现在多个分组" not in prompt
    assert "同一个参考图物品可以出现在多个分组" in prompt


def test_generate_prompt_deeply_integrates_group_content_with_reference_images() -> None:
    agent = ImageAgent.__new__(ImageAgent)
    agent.prompt_generator = _EchoPromptGenerator()

    content = XHSContent(
        title="法式通勤穿搭这样搭更显气质",
        body="这是一段用于测试的正文。" * 10,
        hashtags=["#法式通勤"],
    )
    research = ResearchResult(
        summary="summary",
        items=[
            ResearchItem(title="通勤风格", content="西装外套配衬衫和直筒裤，强调利落感"),
        ],
        keywords=[],
        sources=[],
    )
    gen_ctx = ImageGenContext(
        topic="法式通勤",
        image_type="detail_1",
        reference_image_map={"白色衬衫": ["/tmp/shirt.jpg"]},
    )

    prompt = asyncio.run(
        agent.generate_prompt(
            content=content,
            research=research,
            topic="法式通勤",
            image_spec={
                "type": "detail_1",
                "desc": "详情图1 - 通勤风格",
                "group_title": "通勤风格",
                "indices": [0],
                "ref_items": ["白色衬衫"],
            },
            gen_ctx=gen_ctx,
            has_reference_images=True,
        )
    )

    assert "本图主题板块：通勤风格" in prompt
    assert "当前分组的视觉表达必须围绕这些参考单品展开" in prompt
    assert "白色衬衫" in prompt
    assert "必须结合当前分组中的关键信息与场景" in prompt


def test_run_grouping_with_review_normalizes_duplicate_ref_items_and_allows_cross_group_reuse() -> None:
    grouping_agent = _FakeGroupingAgentWithRefItems()
    reviewer = _PassingGroupingReviewer()

    groups = asyncio.run(
        run_grouping_with_review(
            grouping_agent=grouping_agent,
            grouping_reviewer=reviewer,
            topic="法式通勤",
            research=ResearchResult(
                summary="summary",
                items=[
                    ResearchItem(title="look 1", content="alpha"),
                    ResearchItem(title="look 2", content="beta"),
                ],
                keywords=[],
                sources=[],
            ),
            compact_items=[
                {"index": 0, "type": "claim", "name": "上半身", "text": "白色衬衫"},
                {"index": 1, "type": "claim", "name": "下半身", "text": "黑色西裤"},
            ],
            target_groups=2,
            target_group_size=1,
            max_group_size_cap=2,
            ref_item_names=["白色衬衫", "黑色西裤"],
        )
    )

    assert groups == [
        {"title": "上半身", "indices": [0], "ref_items": ["白色衬衫", "黑色西裤"]},
        {"title": "下半身", "indices": [1], "ref_items": ["黑色西裤"]},
    ]
    assert len(reviewer.calls) == 1


def test_forward_rejects_unknown_group_reference_items_before_generation() -> None:
    agent = ImageAgent.__new__(ImageAgent)

    async def _fake_validate(output):
        return type("_Validation", (), {"passed": True, "feedback": ""})()

    async def _unexpected_step(**kwargs):
        raise AssertionError("step should not run when groups reference unknown items")

    agent.validate = _fake_validate
    agent.step = _unexpected_step

    content = XHSContent(
        title="法式通勤穿搭这样搭更显气质",
        body="这是一段用于测试的正文。" * 10,
        hashtags=["#法式通勤"],
    )
    research = ResearchResult(
        summary="summary",
        items=[ResearchItem(title="look", content="alpha")],
        keywords=[],
        sources=[],
    )
    ref_images = ReferenceImageResult(
        items=[ItemReferenceImages(item_name="白色衬衫", image_paths=["/tmp/shirt.jpg"])],
        skipped=False,
    )

    try:
        asyncio.run(
            agent.forward(
                content=content,
                research=research,
                topic="法式通勤",
                output_dir=Path("/tmp"),
                groups=[{"title": "通勤风格", "indices": [0], "ref_items": ["未知外套"]}],
                reference_images=ref_images,
            )
        )
    except ValueError as exc:
        assert "未知外套" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown ref_items")
