from src.agents.shared.video_extract.extract.agent import ExtractAgent
from src.agents.shared.video_extract.schemas import VideoUrlExtractResult
from src.agents.shared.video_extract.tool import XHSVideoExtractTool
from src.config.settings import PathConfig


def test_video_extract_accepts_rednote_page_urls():
    payload = {
        "content": [
            {
                "text": "Result: https://www.rednote.com/explore/abc123?xsec_token=demo"
            }
        ]
    }

    urls = [
        url
        for url in ExtractAgent._extract_urls_from_payload(payload)
        if ExtractAgent._is_supported_note_page_url(url)
    ]

    assert urls == ["https://www.rednote.com/explore/abc123?xsec_token=demo"]
    assert ExtractAgent._extract_note_id(urls[0]) == "abc123"


def test_rednote_page_read_video_does_not_fallback_to_unsupported_page_download(
    monkeypatch,
    tmp_path,
):
    class _FailingExtractAgent:
        async def forward(self, page_url: str = ""):
            return VideoUrlExtractResult(
                current_page_url=page_url,
                note_id="abc123",
                error_message="当前页未发现真实 mp4 请求，可能视频尚未开始加载",
            )

    async def fail_if_called(_page_url, _dest):
        raise AssertionError("rednote page URLs should not be passed to yt-dlp fallback")

    monkeypatch.setattr(PathConfig, "DOWNLOADS_DIR", tmp_path)
    monkeypatch.setattr(XHSVideoExtractTool, "_download_from_page", staticmethod(fail_if_called))

    tool = XHSVideoExtractTool.__new__(XHSVideoExtractTool)
    tool._extract_agent = _FailingExtractAgent()

    result = __import__("asyncio").run(
        tool.read_video(page_url="https://www.rednote.com/explore/abc123?xsec_token=demo")
    )

    assert "未发现可下载视频直链" in result
    assert "yt-dlp fallback" not in result
