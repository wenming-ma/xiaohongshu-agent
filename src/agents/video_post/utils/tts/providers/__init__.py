from __future__ import annotations

from importlib import import_module
from typing import Any

from .base import TtsProvider

__all__ = [
    "FishTtsProvider",
    "GoogleTtsProvider",
    "QwenTtsProvider",
    "S2CppTtsProvider",
    "TtsProvider",
]


def __getattr__(name: str) -> Any:
    if name == "FishTtsProvider":
        return import_module(".fish", __name__).FishTtsProvider
    if name == "GoogleTtsProvider":
        return import_module(".google", __name__).GoogleTtsProvider
    if name == "QwenTtsProvider":
        return import_module(".qwen", __name__).QwenTtsProvider
    if name == "S2CppTtsProvider":
        return import_module(".s2cpp", __name__).S2CppTtsProvider
    if name == "TtsProvider":
        return TtsProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
