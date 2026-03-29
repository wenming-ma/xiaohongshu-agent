from __future__ import annotations

from .providers.base import TtsProvider
from .providers.fish import FishTtsProvider
from .providers.google import GoogleTtsProvider
from .providers.s2cpp import S2CppTtsProvider


def normalize_provider_name(provider_name: str | None) -> str:
    normalized = (provider_name or "").strip().lower()
    aliases = {
        "": "fish",
        "fish": "fish",
        "fish_tts": "fish",
        "google": "google",
        "google_tts": "google",
        "s2cpp": "s2cpp",
        "s2.cpp": "s2cpp",
        "s2": "s2cpp",
        "auto": "auto",
    }
    return aliases.get(normalized, normalized)


def create_tts_provider(provider_name: str) -> TtsProvider:
    normalized = normalize_provider_name(provider_name)
    if normalized == "fish":
        return FishTtsProvider()
    if normalized == "google":
        return GoogleTtsProvider()
    if normalized == "s2cpp":
        return S2CppTtsProvider()
    raise ValueError(f"未知 VIDEO_DUB_TTS_PROVIDER: {provider_name}")
