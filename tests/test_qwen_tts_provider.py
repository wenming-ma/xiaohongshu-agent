import asyncio
import json
from pathlib import Path

from src.agents.video_post.utils.tts.providers import qwen as qwen_module
from src.agents.video_post.utils.tts.schemas import (
    TtsSynthesisContext,
    TtsSynthesisRequest,
)


def test_qwen_tts_provider_writes_batch_request_and_reads_results(
    monkeypatch,
    tmp_path: Path,
) -> None:
    python_path = tmp_path / "python.exe"
    python_path.write_text("", encoding="utf-8")
    runner_path = tmp_path / "qwen_runner.py"
    runner_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(qwen_module, "_QWEN_TTS_PYTHON", python_path)
    monkeypatch.setattr(qwen_module, "_QWEN_TTS_RUNNER", runner_path)
    monkeypatch.setenv("QWEN_TTS_SPEAKER", "Vivian")

    captured: dict[str, object] = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            request_path = Path(captured["request_path"])
            response_path = Path(captured["response_path"])
            captured["request_payload"] = json.loads(request_path.read_text(encoding="utf-8"))
            output_path = tmp_path / "seg_0000_raw.wav"
            output_path.write_bytes(b"RIFFfake")
            response_path.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "segment_index": 0,
                                "audio_path": str(output_path),
                                "raw_duration_seconds": 1.25,
                                "speaker": "Vivian",
                                "language": "Chinese",
                            }
                        ],
                        "failures": [
                            {"segment_index": 1, "error": "empty text"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return b"", b""

    async def _fake_create_subprocess_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        captured["request_path"] = cmd[cmd.index("--request") + 1]
        captured["response_path"] = cmd[cmd.index("--response") + 1]
        return _FakeProc()

    monkeypatch.setattr(
        qwen_module.asyncio,
        "create_subprocess_exec",
        _fake_create_subprocess_exec,
    )

    requests = [
        TtsSynthesisRequest(segment_index=3, text="[friendly] 你好呀", tone_tag="friendly"),
        TtsSynthesisRequest(segment_index=4, text=" "),
    ]
    result = asyncio.run(
        qwen_module.QwenTtsProvider().synthesize_many(
            requests=requests,
            context=TtsSynthesisContext(work_dir=tmp_path),
        )
    )

    request_payload = captured["request_payload"]
    assert captured["cmd"][0] == str(python_path)
    assert captured["cmd"][1] == str(runner_path)
    assert request_payload["model_id"] == qwen_module.DEFAULT_QWEN_MODEL_ID
    assert request_payload["items"] == [
        {
            "segment_index": 0,
            "text": "你好呀",
            "language": "Chinese",
            "speaker": "Vivian",
            "instruct": "用亲切友好的语气说",
            "output_path": str(tmp_path / "seg_0000_raw.wav"),
        }
    ]
    assert sorted(result.success_map) == [0]
    assert result.success_map[0].audio_path == tmp_path / "seg_0000_raw.wav"
    assert result.success_map[0].provider_metadata == {
        "speaker": "Vivian",
        "language": "Chinese",
    }
