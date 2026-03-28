import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.agents.video_post.cover.agent import CoverAgent
from src.agents.video_post.cover.gemini_web_agent import GeminiWebAgent, SaveImageTool
from src.agents.video_post.schemas import XHSVideoContent


class _FakeMCPServer:
    def __init__(self, responses: dict[str, list[object] | object]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def direct_call_tool(self, name: str, args: dict):
        self.calls.append((name, args))
        response = self.responses[name]
        if isinstance(response, list):
            if not response:
                raise AssertionError(f"tool response queue exhausted for {name}")
            return response.pop(0)
        return response


class _FakeImageClient:
    def __init__(self, returned_path: Path):
        self.returned_path = returned_path

    async def generate_image(self, **kwargs) -> Path:
        self.returned_path.parent.mkdir(parents=True, exist_ok=True)
        self.returned_path.write_bytes(b"processed-cover")
        return self.returned_path


def _make_data_url(size: int = 2048) -> tuple[str, bytes]:
    raw = b"x" * size
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{encoded}", raw


def _build_content() -> XHSVideoContent:
    return XHSVideoContent(
        title="韩式自然妆完整视频教程",
        body="这是一段足够长的视频封面文案内容，用来满足模型约束并覆盖测试场景。" * 2,
        hashtags=["#妆容", "#教程"],
    )


def test_save_image_to_disk_prefers_request_download_for_http_sources(tmp_path) -> None:
    data_url, raw = _make_data_url()
    mcp_server = _FakeMCPServer(
        {
            "browser_evaluate": [
                {
                    "content": [
                        {"type": "text", "text": "metadata"},
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "ok": True,
                                    "src": "https://lh3.googleusercontent.com/generated-image=s2048",
                                    "width": 1280,
                                    "height": 720,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ]
                }
            ],
            "browser_run_code": {
                "ok": True,
                "dataUrl": data_url,
                "downloadSource": "request",
            },
        }
    )
    tool = SaveImageTool(mcp_server)
    output_path = tmp_path / "cover.png"
    tool.bind(output_path)

    result = json.loads(asyncio.run(tool.save_image_to_disk()))

    assert result["ok"] is True
    assert result["download_source"] == "request"
    assert output_path.read_bytes() == raw
    assert tool.saved_path == output_path
    assert [name for name, _ in mcp_server.calls] == ["browser_evaluate", "browser_run_code"]


def test_save_image_to_disk_accepts_data_url_without_extra_download(tmp_path) -> None:
    data_url, raw = _make_data_url()
    mcp_server = _FakeMCPServer(
        {
            "browser_evaluate": {
                "ok": True,
                "src": data_url,
                "width": 1080,
                "height": 1350,
            }
        }
    )
    tool = SaveImageTool(mcp_server)
    output_path = tmp_path / "cover.png"
    tool.bind(output_path)

    result = json.loads(asyncio.run(tool.save_image_to_disk()))

    assert result["ok"] is True
    assert result["download_source"] == "data-url"
    assert result["width"] == 1080
    assert result["height"] == 1350
    assert output_path.read_bytes() == raw
    assert [name for name, _ in mcp_server.calls] == ["browser_evaluate"]


def test_save_image_to_disk_uses_canvas_for_blob_sources(tmp_path) -> None:
    data_url, raw = _make_data_url()
    mcp_server = _FakeMCPServer(
        {
            "browser_evaluate": [
                {
                    "ok": True,
                    "src": "blob:https://gemini.google.com/test-image",
                    "width": 1024,
                    "height": 559,
                },
                {
                    "ok": True,
                    "dataUrl": data_url,
                    "width": 1024,
                    "height": 559,
                },
            ]
        }
    )
    tool = SaveImageTool(mcp_server)
    output_path = tmp_path / "cover.png"
    tool.bind(output_path)

    result = json.loads(asyncio.run(tool.save_image_to_disk()))

    assert result["ok"] is True
    assert result["download_source"] == "canvas"
    assert output_path.read_bytes() == raw
    assert [name for name, _ in mcp_server.calls] == ["browser_evaluate", "browser_evaluate"]


def test_gemini_web_agent_post_processes_saved_image_in_order(tmp_path) -> None:
    raw_path = tmp_path / "cover.png"
    raw_path.write_bytes(b"raw-image")
    processed_path = tmp_path / "cover.jpg"
    call_order: list[str] = []

    agent = object.__new__(GeminiWebAgent)

    def _remove(path: Path) -> Path:
        call_order.append(f"watermark:{path.name}")
        return path

    async def _sanitize(path: Path) -> Path:
        call_order.append(f"sanitize:{path.name}")
        processed_path.write_bytes(b"processed-image")
        return processed_path

    with (
        patch("src.agents.video_post.cover.gemini_web_agent.remove_gemini_watermark", side_effect=_remove),
        patch("src.agents.video_post.cover.gemini_web_agent.sanitize_image", AsyncMock(side_effect=_sanitize)),
    ):
        final_path = asyncio.run(agent._post_process_saved_image(raw_path))

    assert final_path == processed_path
    assert call_order == ["watermark:cover.png", "sanitize:cover.png"]


def test_cover_agent_uses_processed_path_returned_by_api_client(tmp_path) -> None:
    agent = object.__new__(CoverAgent)
    agent._use_api = True
    agent._use_web_fallback = False
    agent.image_client = _FakeImageClient(tmp_path / "cover.jpg")
    agent._generate_cover_prompt = AsyncMock(return_value="cover prompt")

    with patch(
        "src.agents.video_post.cover.agent.extract_frames",
        AsyncMock(return_value=[tmp_path / "frame_001.png"]),
    ):
        result = asyncio.run(
            agent.forward(
                video_path=tmp_path / "video.mp4",
                content=_build_content(),
                topic="韩式自然妆教程",
                output_dir=tmp_path,
            )
        )

    assert result.success is True
    assert result.cover_path.endswith("cover.jpg")
