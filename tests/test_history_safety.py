import asyncio
from types import SimpleNamespace

from pydantic_ai import FunctionToolset
from pydantic_ai.messages import (
    BaseToolCallPart,
    BaseToolReturnPart,
    BuiltinToolCallPart,
    BuiltinToolReturnPart,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.test import TestModel

from src.agents.image_post.content.agent import ContentAgent as ImageContentAgent
from src.agents.image_post.content.state import ContentState as ImageContentState
from src.agents.image_post.research.agent import ResearchAgent as ImageResearchAgent
from src.agents.image_post.utils.image import run_grouping_with_review
from src.agents.image_post.schemas import (
    ImageGroupingPlan,
    ImageGroupingReviewResult,
    ResearchItem,
    ResearchResult,
    XHSContent,
)
from src.agents.article_post.research.agent import ResearchAgent as ArticleResearchAgent
from src.agents.article_post.research.tools import LocalEvidenceStore
from src.agents.shared.utils.asr.schemas import TranscriptionResult
from src.agents.shared.utils.tail_soft_limit import (
    build_soft_limit_message,
    build_tail_soft_limit_history_processor,
)
from src.agents.video_post.content.agent import ContentAgent as VideoContentAgent
from src.agents.video_post.content.state import ContentState as VideoContentState
from src.agents.video_post.research.agent import ResearchAgent as VideoResearchAgent
from src.agents.video_post.research.state import ResearchState as VideoResearchState
from src.agents.video_post.schemas import (
    EngagementMetrics,
    Platform,
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


def _collect_tool_call_ids(messages: list[object]) -> tuple[set[str], set[str]]:
    tool_call_ids: set[str] = set()
    tool_return_ids: set[str] = set()
    for message in messages:
        for part in message.parts:
            if isinstance(part, BaseToolCallPart):
                tool_call_ids.add(part.tool_call_id)
            elif isinstance(part, BaseToolReturnPart):
                tool_return_ids.add(part.tool_call_id)
            elif isinstance(part, RetryPromptPart) and part.tool_name:
                tool_return_ids.add(part.tool_call_id)
    return tool_call_ids, tool_return_ids


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


def _make_named_tool(name: str):
    def tool() -> str:
        return name

    tool.__name__ = name
    return tool


class _FakeToolGetter:
    def __init__(self, tool_name: str):
        self.tool_name = tool_name

    def get_tool(self):
        return _make_named_tool(self.tool_name)


class _FakeVideoExtractTool:
    def get_extract_tool(self):
        return _make_named_tool("extract_video")

    def get_read_tool(self):
        return _make_named_tool("read_video")


def _build_research_agent_for_soft_limit(agent_cls):
    agent = agent_cls.__new__(agent_cls)
    agent.navigate_tracker = FunctionToolset()
    agent.login_tool = _make_named_tool("login")
    agent.image_reader_agent = _FakeToolGetter("read_image")
    agent.post_image_reader = _FakeToolGetter("read_post_image")
    agent.video_extract_tool = _FakeVideoExtractTool()
    agent.init_agent()
    return agent


def test_image_content_state_keeps_last_complete_runs() -> None:
    state = ImageContentState(
        research=_build_image_research(),
        topic="法式穿搭",
    )
    state.message_history = _build_complete_run_history()

    filtered = state.get_recent_history(1)

    assert filtered == state.message_history[4:]


def test_tail_soft_limit_hooks_appends_tail_user_prompt_at_threshold() -> None:
    processor = build_tail_soft_limit_history_processor(output_name="ResearchResult", threshold=50)
    messages = [
        ModelRequest(parts=[UserPromptPart(content="first prompt")]),
        ModelResponse(parts=[ToolCallPart(tool_name="playwright_browser_click", args={}, tool_call_id="call_1")]),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="playwright_browser_click",
                    content={"ok": True},
                    tool_call_id="call_1",
                )
            ]
        ),
    ]

    updated = asyncio.run(
        processor(
            SimpleNamespace(usage=SimpleNamespace(requests=50)),
            messages,
        )
    )

    assert len(messages) == 3
    assert len(updated) == 4
    assert isinstance(updated[-1], ModelRequest)
    assert len(updated[-1].parts) == 1
    assert isinstance(updated[-1].parts[0], UserPromptPart)
    assert updated[-1].parts[0].content == build_soft_limit_message("ResearchResult")


def test_tail_soft_limit_hooks_do_not_append_below_threshold() -> None:
    processor = build_tail_soft_limit_history_processor(output_name="ResearchResult", threshold=50)
    messages = [ModelRequest(parts=[UserPromptPart(content="first prompt")])]

    updated = asyncio.run(
        processor(
            SimpleNamespace(usage=SimpleNamespace(requests=49)),
            messages,
        )
    )

    assert updated == messages


def test_image_research_agent_uses_tail_soft_limit_hooks(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.agents.image_post.research.agent.get_text_model",
        lambda: TestModel(),
    )

    agent = _build_research_agent_for_soft_limit(ImageResearchAgent)

    assert len(agent.generator.history_processors) == 1
    assert not any(callable(item) for item in agent.generator._instructions)


def test_article_research_synthesizer_uses_tail_soft_limit_history_processor(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "src.agents.article_post.research.agent.get_text_model",
        lambda: TestModel(),
    )

    agent = ArticleResearchAgent()
    synthesizer = agent.synthesizer._create_synthesizer(LocalEvidenceStore(tmp_path))

    assert len(synthesizer.history_processors) == 1

    updated = asyncio.run(
        synthesizer.history_processors[0](
            SimpleNamespace(usage=SimpleNamespace(requests=50)),
            [ModelRequest(parts=[UserPromptPart(content="prompt")])],
        )
    )

    assert isinstance(updated[-1], ModelRequest)
    assert isinstance(updated[-1].parts[0], UserPromptPart)
    assert updated[-1].parts[0].content == build_soft_limit_message("ArticleResearchResult")


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


def test_video_content_state_drops_unmatched_tool_call_when_truncating() -> None:
    state = VideoContentState(
        research=_build_video_research(),
        video_source=_build_video_research().sources[0],
        topic="city walk",
        transcript=TranscriptionResult(success=True, transcript="walk transcript"),
    )
    state.message_history = [
        ModelRequest(parts=[UserPromptPart(content="初稿")], instructions="sys"),
        ModelResponse(parts=[TextPart(content="初稿结果")]),
        ModelRequest(parts=[UserPromptPart(content="请根据反馈修订")]),
        ModelResponse(parts=[ToolCallPart(tool_name="read_excerpt", args={}, tool_call_id="call_orphan")]),
    ]

    filtered = state.get_recent_history(1)
    tool_call_ids, tool_return_ids = _collect_tool_call_ids(filtered)

    assert filtered == [state.message_history[2]]
    assert tool_call_ids == set()
    assert tool_return_ids == set()


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


class FakeVideoResearchGeneratorRetryOnToolResultNotFound:
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
                body={"error": {"message": "invalid params, tool result's tool id(call_function_x) not found (2013)"}},
            )
        return FakeNewMessagesResult(
            self.output,
            [
                ModelRequest(parts=[UserPromptPart(content=str(prompt))]),
                ModelResponse(parts=[TextPart(content="continued search")]),
            ],
        )


def test_video_research_state_drops_unmatched_tool_return_from_retained_history() -> None:
    state = VideoResearchState(
        topic="city walk",
        platforms=[Platform.X],
        max_videos=3,
        output_dir=None,
    )
    state.message_history = [
        ModelRequest(parts=[UserPromptPart(content="第一次搜索")]),
        ModelResponse(parts=[TextPart(content="初轮完成")]),
        ModelRequest(parts=[UserPromptPart(content="第二次搜索")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="playwright_search", content="{}", tool_call_id="orphan_return")]),
        ModelResponse(parts=[TextPart(content="继续搜索")]),
    ]

    filtered = state.get_recent_history(2)
    tool_call_ids, tool_return_ids = _collect_tool_call_ids(filtered)

    assert filtered == [
        state.message_history[0],
        state.message_history[1],
        state.message_history[2],
        state.message_history[4],
    ]
    assert tool_call_ids == set()
    assert tool_return_ids == set()


def test_video_research_step_retries_with_cleared_history_on_tool_result_id_not_found() -> None:
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
    agent.generator = FakeVideoResearchGeneratorRetryOnToolResultNotFound(_build_video_research())

    asyncio.run(agent.step(state, 1))

    assert len(agent.generator.calls) == 2
    assert agent.generator.calls[0]["message_history"] == initial_history
    assert agent.generator.calls[1]["message_history"] == []
    assert "需要更多高质量视频" in str(agent.generator.calls[1]["prompt"])


def test_video_research_agent_uses_tail_soft_limit_history_processor(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.agents.video_post.research.agent.get_text_model",
        lambda: TestModel(),
    )
    monkeypatch.setattr(
        "src.agents.video_post.research.agent.create_shared_playwright_mcp_server",
        lambda **_kwargs: FunctionToolset(),
    )

    agent = VideoResearchAgent()
    assert len(agent.generator.history_processors) == 1
    assert not any(callable(item) for item in agent.generator._instructions)


def test_video_research_state_drops_out_of_order_tool_result_even_if_id_matches_later_call() -> None:
    state = VideoResearchState(
        topic="city walk",
        platforms=[Platform.X],
        max_videos=3,
        output_dir=None,
    )
    state.message_history = [
        ModelRequest(parts=[UserPromptPart(content="第一次搜索")]),
        ModelResponse(parts=[TextPart(content="首轮完成")]),
        ModelRequest(
            parts=[
                UserPromptPart(content="第二次搜索"),
                ToolReturnPart(tool_name="playwright_search", content="{}", tool_call_id="call_bad"),
            ]
        ),
        ModelResponse(parts=[ToolCallPart(tool_name="playwright_search", args={}, tool_call_id="call_bad")]),
        ModelResponse(parts=[TextPart(content="继续搜索")]),
    ]

    filtered = state.get_recent_history(2)
    tool_call_ids, tool_return_ids = _collect_tool_call_ids(filtered)

    assert filtered[0] == state.message_history[0]
    assert filtered[1] == state.message_history[1]
    assert isinstance(filtered[2], ModelRequest)
    assert [getattr(part, "content", None) for part in filtered[2].parts] == ["第二次搜索"]
    assert filtered[3] == state.message_history[4]
    assert tool_call_ids == set()
    assert tool_return_ids == set()


def test_video_research_state_keeps_builtin_tool_pairs_when_complete() -> None:
    state = VideoResearchState(
        topic="city walk",
        platforms=[Platform.X],
        max_videos=3,
        output_dir=None,
    )
    state.message_history = [
        ModelRequest(parts=[UserPromptPart(content="第一次搜索")]),
        ModelResponse(parts=[BuiltinToolCallPart(tool_name="web_search", args={"q": "city walk"}, tool_call_id="builtin_1", provider_name="anthropic")]),
        ModelResponse(parts=[BuiltinToolReturnPart(tool_name="web_search_tool_result", content={"hits": []}, tool_call_id="builtin_1", provider_name="anthropic")]),
        ModelResponse(parts=[TextPart(content="继续搜索")]),
    ]

    filtered = state.get_recent_history(1)
    tool_call_ids, tool_return_ids = _collect_tool_call_ids(filtered)

    assert tool_call_ids == {"builtin_1"}
    assert tool_return_ids == {"builtin_1"}


def test_video_research_state_drops_retry_prompt_without_matching_tool_call() -> None:
    state = VideoResearchState(
        topic="city walk",
        platforms=[Platform.X],
        max_videos=3,
        output_dir=None,
    )
    state.message_history = [
        ModelRequest(parts=[UserPromptPart(content="第一次搜索")]),
        ModelRequest(parts=[RetryPromptPart(content="retry", tool_name="playwright_search", tool_call_id="retry_1")]),
        ModelResponse(parts=[TextPart(content="继续搜索")]),
    ]

    filtered = state.get_recent_history(1)
    tool_call_ids, tool_return_ids = _collect_tool_call_ids(filtered)

    assert filtered == [
        state.message_history[0],
        state.message_history[2],
    ]
    assert tool_call_ids == set()
    assert tool_return_ids == set()


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
