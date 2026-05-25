import io
import logging
import sys

from src.utils.logger import setup_logging


def test_setup_logging_reconfigures_console_streams_to_utf8(monkeypatch):
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    stderr = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")

    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(sys, "platform", "win32")

    setup_logging(force=True)

    assert sys.stdout.encoding.lower().replace("-", "") == "utf8"
    assert sys.stdout.errors == "replace"
    assert sys.stderr.encoding.lower().replace("-", "") == "utf8"
    assert sys.stderr.errors == "replace"
    assert any(isinstance(handler, logging.StreamHandler) for handler in logging.getLogger().handlers)
