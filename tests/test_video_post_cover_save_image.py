import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.agents.video_post.cover.agent import CoverAgent
from src.agents.video_post.cover.gemini_web_agent import GeminiWebAgent
from src.agents.video_post.schemas import XHSVideoContent
from src.utils.providers.gemini_web import GeminiWebImageClient


class _FakeDownload:
    def __init__(self, suggested_filename: str, data: bytes):
        self.suggested_filename = suggested_filename
        self._data = data

    async def save_as(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self._data)


class _FakeExpectDownload:
    def __init__(self, download: _FakeDownload | None, error: Exception | None = None):
        self._download = download
        self._error = error

    async def __aenter__(self):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        if self._download is not None:
            future.set_result(self._download)
        return SimpleNamespace(value=future)

    async def __aexit__(self, exc_type, exc, tb):
        if self._error is not None:
            raise self._error
        return False


class _FakeAPIResponse:
    def __init__(self, status: int, headers: dict[str, str], data: bytes):
        self.status = status
        self.headers = headers
        self._data = data

    async def body(self) -> bytes:
        return self._data


class _FakeRequest:
    def __init__(self, response: _FakeAPIResponse):
        self._response = response
        self.urls: list[str] = []

    async def get(self, url: str):
        self.urls.append(url)
        return self._response


class _FakePage:
    def __init__(
        self,
        *,
        evaluate_results: list[object] | None = None,
        download: _FakeDownload | None = None,
        download_error: Exception | None = None,
        response: _FakeAPIResponse | None = None,
    ):
        self._evaluate_results = list(evaluate_results or [])
        self._download = download
        self._download_error = download_error
        self.evaluate_calls: list[tuple[str, object]] = []
        self.context = SimpleNamespace(request=_FakeRequest(response or _FakeAPIResponse(200, {}, b"")))

    def expect_download(self, *args, **kwargs):
        return _FakeExpectDownload(self._download, self._download_error)

    async def evaluate(self, script: str, arg=None):
        self.evaluate_calls.append((script, arg))
        if not self._evaluate_results:
            raise AssertionError("unexpected evaluate call")
        result = self._evaluate_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _FakeImageClient:
    def __init__(self, returned_path: Path):
        self.returned_path = returned_path

    async def generate_image(self, **kwargs) -> Path:
        self.returned_path.parent.mkdir(parents=True, exist_ok=True)
        self.returned_path.write_bytes(b"processed-cover")
        return self.returned_path


def _make_webp(size: int = 2048) -> bytes:
    payload = b"x" * size
    return b"RIFF" + len(payload).to_bytes(4, "little") + b"WEBP" + payload


def _build_content() -> XHSVideoContent:
    return XHSVideoContent(
        title="韩式自然妆完整视频教程",
        body="这是一段足够长的视频封面文案内容，用来满足模型约束并覆盖测试场景。" * 2,
        hashtags=["#妆容", "#教程"],
    )


def test_download_generated_image_prefers_native_download_control(tmp_path) -> None:
    client = object.__new__(GeminiWebImageClient)
    native_path = tmp_path / "cover.webp"

    with (
        patch.object(client, "_download_via_native_control", AsyncMock(return_value=native_path)) as native_mock,
        patch.object(client, "_download_via_object_url", AsyncMock()) as object_mock,
        patch.object(client, "_download_via_request", AsyncMock()) as request_mock,
    ):
        result = asyncio.run(
            client._download_generated_image(
                page=object(),
                image_meta={"src": "blob:https://gemini.google.com/generated"},
                output_path=tmp_path / "cover.png",
            )
        )

    assert result == native_path
    native_mock.assert_awaited_once()
    object_mock.assert_not_called()
    request_mock.assert_not_called()


def test_download_generated_image_uses_object_url_fallback_for_blob_sources(tmp_path) -> None:
    client = object.__new__(GeminiWebImageClient)
    blob_path = tmp_path / "cover.webp"

    with (
        patch.object(client, "_download_via_native_control", AsyncMock(side_effect=ValueError("native failed"))),
        patch.object(client, "_download_via_object_url", AsyncMock(return_value=blob_path)) as object_mock,
        patch.object(client, "_download_via_request", AsyncMock()) as request_mock,
    ):
        result = asyncio.run(
            client._download_generated_image(
                page=object(),
                image_meta={"src": "blob:https://gemini.google.com/generated"},
                output_path=tmp_path / "cover.png",
            )
        )

    assert result == blob_path
    object_mock.assert_awaited_once()
    request_mock.assert_not_called()


def test_download_generated_image_uses_request_fallback_for_http_sources(tmp_path) -> None:
    client = object.__new__(GeminiWebImageClient)
    request_path = tmp_path / "cover.webp"
    page = object()

    with (
        patch.object(client, "_download_via_native_control", AsyncMock(side_effect=ValueError("native failed"))),
        patch.object(client, "_download_via_object_url", AsyncMock()) as object_mock,
        patch.object(client, "_download_via_request", AsyncMock(return_value=request_path)) as request_mock,
    ):
        result = asyncio.run(
            client._download_generated_image(
                page=page,
                image_meta={"src": "https://lh3.googleusercontent.com/generated=s1024"},
                output_path=tmp_path / "cover.png",
            )
        )

    assert result == request_path
    object_mock.assert_not_called()
    request_mock.assert_awaited_once_with(
        page,
        "https://lh3.googleusercontent.com/generated=s2048",
        tmp_path / "cover.png",
    )


def test_download_via_object_url_saves_suggested_file_with_real_suffix(tmp_path) -> None:
    client = object.__new__(GeminiWebImageClient)
    page = _FakePage(
        evaluate_results=[{"ok": True, "strategy": "synthetic-anchor"}],
        download=_FakeDownload("gemini.webp", _make_webp()),
    )

    result = asyncio.run(
        client._download_via_object_url(
            page,
            "blob:https://gemini.google.com/generated",
            tmp_path / "cover.png",
        )
    )

    assert result == tmp_path / "cover.webp"
    assert result.read_bytes().startswith(b"RIFF")


def test_download_via_request_preserves_original_bytes_and_suffix(tmp_path) -> None:
    client = object.__new__(GeminiWebImageClient)
    raw = _make_webp()
    page = _FakePage(
        response=_FakeAPIResponse(200, {"content-type": "image/webp"}, raw),
    )

    result = asyncio.run(
        client._download_via_request(
            page,
            "https://lh3.googleusercontent.com/generated=s2048",
            tmp_path / "cover.png",
        )
    )

    assert result == tmp_path / "cover.webp"
    assert result.read_bytes() == raw
    assert page.context.request.urls == ["https://lh3.googleusercontent.com/generated=s2048"]


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
