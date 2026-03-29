from __future__ import annotations

import os
import re
from pathlib import Path

import httpx

from .....utils.logger import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[5]


def get_env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    logger.warning("%s=%r 不是有效布尔值，回退默认值 %s", name, raw, default)
    return default


def get_env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r 不是有效整数，回退默认值 %s", name, raw, default)
        return default


def get_env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s=%r 不是有效数字，回退默认值 %s", name, raw, default)
        return default


def normalize_tts_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"<[^>]+>", "", text)
    return text


def extract_http_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        return str(body)
    except Exception:
        return response.text


def resolve_env_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path
