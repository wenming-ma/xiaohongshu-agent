import asyncio
import json
from pathlib import Path

from src.agents.image_post.research.agent import ResearchAgent
from src.agents.image_post.research.state import ResearchState, build_progress_snapshot
from src.agents.image_post.research.tools import ImageReaderAgent, PostImageReaderAgent
from src.agents.image_post.schemas import PostImageItem, PostImagesReadResult, ResearchItem, ResearchResult
from src.agents.image_post.utils.image import build_compact_items
from src.agents.image_post.utils.research import sanitize_research_for_content


class FailingVisionAgent:
    def __init__(self) -> None:
        self.called = False

    async def run(self, *_args, **_kwargs):
        self.called = True
        raise AssertionError("vision model should not be called")


def test_build_progress_snapshot_does_not_expose_saved_json_paths() -> None:
    state = ResearchState(
        topic="旧衣新穿",
        target_audience="通勤女生",
        output_dir=None,
        iteration_results=[
            ResearchResult(
                summary="摘要",
                items=[ResearchItem(title="搭配", content="西装外套配牛仔裤")],
                keywords=["旧衣新穿"],
                sources=[],
            )
        ],
        saved_files=[
            r"C:\Users\wenming\source\repos\xiaohongshu-agent\output\research_20260318-200728.json"
        ],
        tracked_stats={
            "post_detail_count": 1,
            "post_detail_urls": ["https://www.xiaohongshu.com/explore/demo"],
        },
    )

    snapshot = build_progress_snapshot(state, state.saved_files[0])

    assert "saved_json" not in snapshot
    assert "research_20260318-200728.json" not in snapshot
    assert "不要把 .json" not in snapshot


def test_read_image_tool_description_contains_supported_types() -> None:
    agent = ImageReaderAgent.__new__(ImageReaderAgent)
    tool = agent.get_tool()

    assert "只接受浏览器截图或其他本地图片文件" in tool.description
    assert "research_*.json" in tool.description


def test_read_image_rejects_non_image_file_without_calling_model(tmp_path: Path) -> None:
    bad_file = tmp_path / "research_20260318-200728.json"
    bad_file.write_text('{"ok": true}', encoding="utf-8")

    agent = ImageReaderAgent.__new__(ImageReaderAgent)
    agent._agent = FailingVisionAgent()

    result = asyncio.run(agent.read_image(str(bad_file)))
    payload = json.loads(result)

    assert payload["has_text"] is False
    assert "只接受图片文件" in payload["issues"][0]
    assert agent._agent.called is False


def test_read_image_returns_structured_error_on_preprocess_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bad_image = tmp_path / "broken.jpg"
    bad_image.write_bytes(b"not a real image")

    async def fake_compress(_path: Path, max_size_mb: float = 5.0) -> bytes:
        raise ValueError(f"cannot decode image under {max_size_mb}MB")

    monkeypatch.setattr(
        "src.agents.image_post.research.tools.compress_image_for_review",
        fake_compress,
    )

    agent = ImageReaderAgent.__new__(ImageReaderAgent)
    agent._agent = FailingVisionAgent()

    result = asyncio.run(agent.read_image(str(bad_image)))
    payload = json.loads(result)

    assert "图片预处理失败" in payload["issues"][0]
    assert "ValueError" in payload["issues"][0]
    assert agent._agent.called is False


def test_research_agent_wires_post_image_reader_through_navigate_tracker(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeLoginAgent:
        def __init__(self, mcp_server):
            captured["login_mcp_server"] = mcp_server

        def get_tool(self):
            return object()

    class FakeImageReaderAgent:
        def get_tool(self):
            return object()

    class FakePostImageReaderAgent:
        def __init__(self, mcp_server):
            captured["post_reader_mcp_server"] = mcp_server

        def get_tool(self):
            return object()

    class FakeVideoExtractTool:
        def get_extract_tool(self):
            return object()

        def get_read_tool(self):
            return object()

    monkeypatch.setattr("src.agents.image_post.research.agent.RednoteLoginAgent", FakeLoginAgent)
    monkeypatch.setattr("src.agents.image_post.research.agent.ImageReaderAgent", FakeImageReaderAgent)
    monkeypatch.setattr(
        "src.agents.image_post.research.agent.PostImageReaderAgent",
        FakePostImageReaderAgent,
    )
    monkeypatch.setattr(
        "src.agents.image_post.research.agent.create_video_extract_tool",
        lambda mcp_server: FakeVideoExtractTool(),
    )

    agent = ResearchAgent.__new__(ResearchAgent)
    agent.mcp_server = object()
    agent.navigate_tracker = object()

    agent.init_tools()

    assert captured["login_mcp_server"] is agent.mcp_server
    assert captured["post_reader_mcp_server"] is agent.navigate_tracker


def test_post_image_reader_applies_image_and_tool_budgets() -> None:
    captured: dict[str, object] = {}

    class FakeAgent:
        async def run(self, prompt, *, usage_limits):
            captured["prompt"] = prompt
            captured["usage_limits"] = usage_limits

            class Result:
                output = PostImagesReadResult(
                    post_type="normal",
                    image_count=4,
                    images=[
                        PostImageItem(index=1, description="one"),
                        PostImageItem(index=2, description="two"),
                        PostImageItem(index=3, description="three"),
                    ],
                )

            return Result()

    reader = PostImageReaderAgent.__new__(PostImageReaderAgent)
    reader._agent = FakeAgent()
    reader._max_images = 2
    reader._request_limit = 5
    reader._tool_calls_limit = 7

    result = asyncio.run(reader.read_post_images("只看食材"))
    payload = json.loads(result)

    assert "最多分析 2 张图片" in captured["prompt"]
    assert captured["usage_limits"].request_limit == 5
    assert captured["usage_limits"].tool_calls_limit == 7
    assert len(payload["images"]) == 2
    assert "仅保留前 2 张" in payload["issues"][0]


def test_sanitize_research_removes_operational_login_diagnostics() -> None:
    result = ResearchResult(
        summary=(
            "【第1轮研究】\n研究限制说明：研究过程中遇到多次登录弹窗限制。\n\n---\n\n"
            "【第2轮研究】\n通勤穿搭核心趋势：低饱和配色、单套平铺展示。"
        ),
        items=[
            ResearchItem(title="研究限制说明", content="登录工具返回'共享 session已登录'但页面仍显示登录要求"),
            ResearchItem(title="低饱和通勤套装", content="灰蓝衬衫配卡其裤，适合面试场景"),
        ],
        keywords=[],
        sources=[],
    )

    sanitized = sanitize_research_for_content(result)

    assert len(sanitized.items) == 1
    assert sanitized.items[0].title == "低饱和通勤套装"
    assert "研究限制说明" not in sanitized.summary
    assert "登录弹窗" not in sanitized.summary
    assert "通勤穿搭核心趋势" in sanitized.summary


def test_build_compact_items_filters_operational_entries_and_keeps_original_index() -> None:
    items = [
        ResearchItem(title="研究限制说明", content="登录弹窗限制导致搜索结果无法正常显示"),
        ResearchItem(title="优雅通勤", content="浅蓝针织Polo衫 + 卡其高腰阔腿裤"),
    ]

    compact = build_compact_items(items)

    assert compact == [
        {
            "index": 1,
            "type": None,
            "name": "优雅通勤",
            "text": "优雅通勤: 浅蓝针织Polo衫 + 卡其高腰阔腿裤",
        }
    ]
