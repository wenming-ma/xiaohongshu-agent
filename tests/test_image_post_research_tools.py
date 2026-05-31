import asyncio
import json
from pathlib import Path

from src.agents.image_post.research.agent import ResearchAgent
from src.agents.image_post.research.state import ResearchState, build_progress_snapshot
from src.agents.image_post.research.tools import ImageReaderAgent
from src.agents.image_post.schemas import ResearchItem, ResearchResult


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
