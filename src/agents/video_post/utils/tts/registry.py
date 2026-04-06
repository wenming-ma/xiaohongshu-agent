from __future__ import annotations

from .providers.base import TtsProvider


def normalize_provider_name(provider_name: str | None) -> str:
    normalized = (provider_name or "").strip().lower()
    aliases = {
        "": "fish",
        "fish": "fish",
        "fish_tts": "fish",
        "google": "google",
        "google_tts": "google",
        "qwen": "qwen",
        "qwen_tts": "qwen",
        "s2cpp": "s2cpp",
        "s2.cpp": "s2cpp",
        "s2": "s2cpp",
        "auto": "auto",
    }
    return aliases.get(normalized, normalized)


def create_tts_provider(provider_name: str) -> TtsProvider:
    normalized = normalize_provider_name(provider_name)
    if normalized == "fish":
        from .providers.fish import FishTtsProvider

        return FishTtsProvider()
    if normalized == "google":
        from .providers.google import GoogleTtsProvider

        return GoogleTtsProvider()
    if normalized == "qwen":
        from .providers.qwen import QwenTtsProvider

        return QwenTtsProvider()
    if normalized == "s2cpp":
        from .providers.s2cpp import S2CppTtsProvider

        return S2CppTtsProvider()
    raise ValueError(f"未知 VIDEO_DUB_TTS_PROVIDER: {provider_name}")
