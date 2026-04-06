import asyncio
from pathlib import Path

import httpx

from src.agents.video_post.utils.tts.providers import s2cpp as s2cpp_module


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeAsyncClient:
    def __init__(self, outcomes: list[object]):
        self._outcomes = outcomes

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *_args, **_kwargs):
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeProc:
    def __init__(self, poll_results: list[int | None]):
        self._poll_results = poll_results
        self.returncode = None
        self.kill_called = False

    def poll(self):
        if self._poll_results:
            result = self._poll_results.pop(0)
            self.returncode = result
            return result
        return self.returncode

    def kill(self):
        self.kill_called = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def test_ensure_s2cpp_server_retries_after_early_exit(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "s2.exe"
    exe.write_text("fake exe", encoding="utf-8")
    dll_dir = tmp_path / "dll"
    dll_dir.mkdir()
    model = tmp_path / "model.gguf"
    model.write_text("fake model", encoding="utf-8")
    tokenizer = tmp_path / "tokenizer.json"
    tokenizer.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(s2cpp_module, "_S2CPP_EXE", exe)
    monkeypatch.setattr(s2cpp_module, "_S2CPP_DLL_DIR", dll_dir)
    monkeypatch.setattr(s2cpp_module, "_S2CPP_MODEL", model)
    monkeypatch.setattr(s2cpp_module, "_S2CPP_TOKENIZER", tokenizer)
    monkeypatch.setattr(s2cpp_module, "_s2cpp_server_proc", None)

    outcomes: list[object] = [
        httpx.ConnectError("down"),
        httpx.ConnectError("down"),
        _FakeResponse(404),
    ]
    monkeypatch.setattr(
        s2cpp_module.httpx,
        "AsyncClient",
        lambda: _FakeAsyncClient(outcomes),
    )

    proc1 = _FakeProc([1])
    proc2 = _FakeProc([None])
    popen_calls = []

    def _fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return proc1 if len(popen_calls) == 1 else proc2

    monkeypatch.setattr(s2cpp_module.subprocess, "Popen", _fake_popen)

    async def _fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr(s2cpp_module.asyncio, "sleep", _fake_sleep)

    asyncio.run(s2cpp_module._ensure_s2cpp_server("http://127.0.0.1:3040", timeout_s=3.0))

    assert len(popen_calls) == 2
    assert s2cpp_module._s2cpp_server_proc is proc2
