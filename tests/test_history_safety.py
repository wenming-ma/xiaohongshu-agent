import asyncio

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.exceptions import ModelHTTPError

from src.agents.image_post.content.agent import ContentAgent as ImageContentAgent
from src.agents.image_post.content.state import ContentState as ImageContentState
from src.agents.image_post.image.utils import run_grouping_with_review
from src.agents.image_post.schemas import (
    ImageGroupingPlan,
    ImageGroupingReviewResult,
    ResearchItem,
    ResearchResult,
    XHSContent,
)
from src.agents.video_post.content.agent import ContentAgent as VideoContentAgent
from src.agents.video_post.content.state import ContentState as VideoContentState
from src.agents.video_post.research.agent import ResearchAgent as VideoResearchAgent
from src.agents.video_post.research.state import ResearchState as VideoResearchState
from src.agents.video_post.schemas import (
    EngagementMetrics,
    Platform,
    TranscriptionResult,
    VideoResearchResult,
    VideoSource,
    XHSVideoContent,
)


class FakeNewMessagesResult:
    def __init__(self, output, messages):
        self.output = output
        self._messages = messages

    def new_messages(self):
        return self._messages


class FakeContentGenerator:
    def __init__(self, output):
        self.output = output
        self.calls: list[dict[str, object]] = []

    async def run(self, prompt, message_history=None):
        history = list(message_history or [])
        self.calls.append({"prompt": prompt, "message_history": history})
        return FakeNewMessagesResult(
            self.output,
            [
                ModelRequest(parts=[UserPromptPart(content=str(prompt))]),
                ModelResponse(parts=[TextPart(content="updated")]),
            ],
        )


class FakeVideoResearchGenerator:
    def __init__(self, output):
        self.output = output
        self.calls: list[dict[str, object]] = []

    async def run(self, prompt, message_history=None, **kwargs):
        history = list(message_history or [])
        self.calls.append(
            {
                "prompt": prompt,
                "message_history": history,
                "kwargs": kwargs,
            }
        )
        return FakeNewMessagesResult(
            self.output,
            [
                ModelRequest(parts=[UserPromptPart(content=str(prompt))]),
                ModelResponse(parts=[TextPart(content="continued search")]),
            ],
        )


class FakeVideoResearchGeneratorRetryOnce:
    def __init__(self, output):
        self.output = output
        self.calls: list[dict[str, object]] = []
        self._attempt = 0

    async def run(self, prompt, message_history=None, **kwargs):
        history = list(message_history or [])
        self.calls.append(
            {
                "prompt": prompt,
                "message_history": history,
                "kwargs": kwargs,
            }
        )
        self._attempt += 1
        if self._attempt == 1:
            raise ModelHTTPError(
                status_code=400,
                model_name="MiniMax-M2.7",
                body={"error": {"message": "invalid params, tool call id is invalid (2013)"}},
            )
        return FakeNewMessagesResult(
            self.output,
            [
                ModelRequest(parts=[UserPromptPart(content=str(prompt))]),
                ModelResponse(parts=[TextPart(content="continued search")]),
            ],
        )


class FakeGroupingAgent:
    def __init__(self):
        self.calls: list[dict[str, object]] = []
        self.round_messages: list[list[object]] = []

    async def run(self, prompt, message_history=None):
        history = list(message_history or [])
        messages = [
            ModelRequest(parts=[UserPromptPart(content=str(prompt))]),
            ModelResponse(parts=[TextPart(content="grouping ok")]),
        ]
        self.calls.append({"prompt": prompt, "message_history": history})
        self.round_messages.append(messages)
        return FakeNewMessagesResult(
            ImageGroupingPlan(
                groups=[
                    {"title": "穿搭神话", "indices": [0]},
                    {"title": "平台放大", "indices": [1]},
                ]
            ),
            messages,
        )


class FakeGroupingReviewer:
    def __init__(self):
        self.calls: list[dict[str, object]] = []
        self._attempt = 0

    async def run(self, prompt, message_history=None):
        history = list(message_history or [])
        self.calls.append({"prompt": prompt, "message_history": history})
        self._attempt += 1
        passed = self._attempt > 1
        return FakeNewMessagesResult(
            ImageGroupingReviewResult(
                passed=passed,
                score=88.0 if passed else 42.0,
                issues=[] if passed else ["第 1 组标题和内容不匹配"],
                summary="通过" if passed else "语义错配",
            ),
            [
                ModelRequest(parts=[UserPromptPart(content=str(prompt))]),
                ModelResponse(parts=[TextPart(content="reviewed")]),
            ],
        )


def _build_complete_run_history() -> list:
    return [
        ModelRequest(parts=[UserPromptPart(content="初稿")], instructions="sys"),
        ModelResponse(parts=[ToolCallPart(tool_name="list_sources", args={}, tool_call_id="call_1")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="list_sources", content="[]", tool_call_id="call_1")]),
        ModelResponse(parts=[TextPart(content="初稿结果")]),
        ModelRequest(parts=[UserPromptPart(content="请根据反馈修订")]),
        ModelResponse(parts=[ToolCallPart(tool_name="read_excerpt", args={}, tool_call_id="call_2")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="read_excerpt", content="片段", tool_call_id="call_2")]),
        ModelResponse(parts=[TextPart(content="修订稿")]),
    ]


def _build_image_research() -> ResearchResult:
    return ResearchResult(
        summary="关于法式穿搭神话的研究摘要。",
        items=[
            ResearchItem(title="工业起源", content="高定和媒体共同塑造了巴黎女人叙事。"),
            ResearchItem(title="平台放大", content="社交平台不断重复 effortless 叙事。"),
        ],
        keywords=["法式穿搭", "时尚产业"],
        sources=[],
    )


def _build_video_research() -> VideoResearchResult:
    return VideoResearchResult(
        topic="city walk",
        summary="城市徒步视频研究摘要。",
        keywords=["city walk"],
        sources=[
            VideoSource(
                url="https://example.com/video",
                platform=Platform.X,
                title="City walk",
                description="A relaxed city walk",
                engagement=EngagementMetrics(likes=10, comments=2, shares=1),
            )
        ],
    )


def test_image_content_state_keeps_last_complete_runs() -> None:
    state = ImageContentState(
        research=_build_image_research(),
        topic="法式穿搭",
    )
    state.message_history = _build_complete_run_history()

    filtered = state.get_recent_history(1)

    assert filtered == state.message_history[4:]


def test_image_content_step_uses_revision_prompt_without_mutating_history() -> None:
    state = ImageContentState(
        research=_build_image_research(),
        topic="法式穿搭",
    )
    initial_history = [
        ModelRequest(parts=[UserPromptPart(content="初稿")], instructions="sys"),
        ModelResponse(parts=[TextPart(content="初稿结果")]),
    ]
    state.message_history = initial_history[:]
    state.inject_feedback("请修复数量不一致和分组顺序问题。")

    agent = ImageContentAgent.__new__(ImageContentAgent)
    agent.generator = FakeContentGenerator(
        XHSContent(
            title="法式穿搭神话怎么被制造出来",
            body="这是一段足够长的正文。" * 10,
            hashtags=["法式穿搭", "时尚产业"],
            call_to_action="欢迎理性讨论。",
        )
    )

    asyncio.run(agent.step(state, 1))

    assert agent.generator.calls[0]["message_history"] == initial_history
    assert "请修复数量不一致和分组顺序问题" in str(agent.generator.calls[0]["prompt"])
    assert state.message_history[:2] == initial_history
    assert len(state.message_history) == 4


def test_video_content_state_keeps_last_complete_runs() -> None:
    state = VideoContentState(
        research=_build_video_research(),
        video_source=_build_video_research().sources[0],
        topic="city walk",
        transcript=TranscriptionResult(success=True, transcript="walk transcript"),
    )
    state.message_history = _build_complete_run_history()

    filtered = state.get_recent_history(1)

    assert filtered == state.message_history[4:]


def test_video_content_step_uses_revision_prompt_without_mutating_history() -> None:
    research = _build_video_research()
    state = VideoContentState(
        research=research,
        video_source=research.sources[0],
        topic="city walk",
        transcript=TranscriptionResult(success=True, transcript="walk transcript"),
    )
    initial_history = [
        ModelRequest(parts=[UserPromptPart(content="初稿")], instructions="sys"),
        ModelResponse(parts=[TextPart(content="初稿结果")]),
    ]
    state.message_history = initial_history[:]
    state.inject_feedback("请补足互动引导，并让正文更自然。")

    agent = VideoContentAgent.__new__(VideoContentAgent)
    agent.generator = FakeContentGenerator(
        XHSVideoContent(
            title="城市徒步这条路线真的很舒服",
            body="这条路线从街角咖啡馆开始，一路走到河边公园，节奏很慢也很适合周末。" * 2,
            hashtags=["城市徒步", "周末路线"],
            call_to_action="",
        )
    )

    asyncio.run(agent.step(state, 1))

    assert agent.generator.calls[0]["message_history"] == initial_history
    assert "请补足互动引导，并让正文更自然" in str(agent.generator.calls[0]["prompt"])
    assert state.message_history[:2] == initial_history
    assert len(state.message_history) == 4


def test_video_research_step_uses_revision_prompt_without_feedback_message_in_history() -> None:
    state = VideoResearchState(
        topic="city walk",
        platforms=[Platform.X],
        max_videos=3,
        output_dir=None,
    )
    initial_history = [
        ModelRequest(parts=[UserPromptPart(content="第一次搜索")]),
        ModelResponse(parts=[ToolCallPart(tool_name="playwright_search", args={}, tool_call_id="call_1")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="playwright_search", content="{}", tool_call_id="call_1")]),
    ]
    state.message_history = initial_history[:]
    state.inject_feedback("需要更多高质量视频")

    agent = VideoResearchAgent.__new__(VideoResearchAgent)
    agent.generator = FakeVideoResearchGenerator(_build_video_research())

    asyncio.run(agent.step(state, 1))

    call = agent.generator.calls[0]
    assert call["message_history"] == initial_history
    assert "需要更多高质量视频" in str(call["prompt"])


def test_video_research_step_retries_with_cleared_history_on_invalid_tool_call_id() -> None:
    state = VideoResearchState(
        topic="city walk",
        platforms=[Platform.X],
        max_videos=3,
        output_dir=None,
    )
    initial_history = [
        ModelRequest(parts=[UserPromptPart(content="第一次搜索")]),
        ModelResponse(parts=[ToolCallPart(tool_name="playwright_search", args={}, tool_call_id="call_1")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="playwright_search", content="{}", tool_call_id="call_1")]),
    ]
    state.message_history = initial_history[:]
    state.inject_feedback("需要更多高质量视频")

    agent = VideoResearchAgent.__new__(VideoResearchAgent)
    agent.generator = FakeVideoResearchGeneratorRetryOnce(_build_video_research())

    asyncio.run(agent.step(state, 1))

    assert len(agent.generator.calls) == 2
    assert agent.generator.calls[0]["message_history"] == initial_history
    assert agent.generator.calls[1]["message_history"] == []
    assert "需要更多高质量视频" in str(agent.generator.calls[1]["prompt"])


def test_image_grouping_retry_uses_revision_prompt_without_feedback_message_in_history() -> None:
    grouping_agent = FakeGroupingAgent()
    reviewer = FakeGroupingReviewer()
    compact_items = [
        {"index": 0, "type": "claim", "name": "工业起源", "text": "高定和媒体塑造叙事"},
        {"index": 1, "type": "claim", "name": "平台放大", "text": "社交平台反复放大 myth"},
    ]

    groups = asyncio.run(
        run_grouping_with_review(
            grouping_agent=grouping_agent,
            grouping_reviewer=reviewer,
            topic="法式穿搭",
            research=_build_image_research(),
            compact_items=compact_items,
            target_groups=2,
            target_group_size=1,
            max_group_size_cap=2,
        )
    )

    assert len(grouping_agent.calls) == 2
    assert grouping_agent.calls[1]["message_history"] == grouping_agent.round_messages[0]
    assert "第 1 组标题和内容不匹配" in str(grouping_agent.calls[1]["prompt"])
    assert groups == [
        {"title": "穿搭神话", "indices": [0]},
        {"title": "平台放大", "indices": [1]},
    ]
