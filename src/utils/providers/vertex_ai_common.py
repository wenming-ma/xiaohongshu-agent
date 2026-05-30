"""Vertex AI provider shared helpers."""

from __future__ import annotations

import os
from typing import Optional

import google.auth
import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import types

from src.config.settings import APIConfig, TimeoutConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)

_RETRYABLE_KEYWORDS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "limit",
    "quota",
    "rate",
    "timeout",
    "unavailable",
    "overloaded",
    "connection",
    "disconnected",
    "deadline",
    "internal",
)


def resolve_vertex_project(project: Optional[str] = None) -> str:
    """Resolve a Vertex AI project from explicit input, env, or ADC."""
    if project:
        return project

    load_dotenv()
    env_project = (
        os.getenv("VERTEX_AI_PROJECT_ID")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCLOUD_PROJECT")
        or APIConfig.VERTEX_AI_PROJECT_ID
    )
    if env_project:
        return env_project

    try:
        _credentials, detected_project = google.auth.default()
    except Exception as exc:  # pragma: no cover - exercised via failure path at runtime
        raise ValueError(
            "未检测到 Vertex AI 项目 ID，请设置 VERTEX_AI_PROJECT_ID 或配置带 project 的 Application Default Credentials"
        ) from exc

    if detected_project:
        logger.info("Vertex AI project resolved from ADC: %s", detected_project)
        return detected_project

    raise ValueError(
        "未检测到 Vertex AI 项目 ID，请设置 VERTEX_AI_PROJECT_ID 或配置带 project 的 Application Default Credentials"
    )


def resolve_vertex_location(location: Optional[str] = None) -> str:
    """Resolve the Vertex AI location."""
    if location:
        return location
    load_dotenv()
    return os.getenv("VERTEX_AI_LOCATION") or APIConfig.VERTEX_AI_LOCATION


def build_vertex_client(
    *,
    project: Optional[str] = None,
    location: Optional[str] = None,
) -> tuple[genai.Client, str, str]:
    """Create a google-genai Vertex AI client backed by ADC."""
    resolved_project = resolve_vertex_project(project)
    resolved_location = resolve_vertex_location(location)
    timeout = TimeoutConfig.GEMINI_WAIT
    http_options = types.HttpOptions(timeout=timeout * 1000, api_version="v1")
    client = genai.Client(
        vertexai=True,
        project=resolved_project,
        location=resolved_location,
        http_options=http_options,
    )
    return client, resolved_project, resolved_location


def is_retryable_vertex_error(error: Exception) -> bool:
    """Best-effort retryability check for Vertex AI SDK/network failures."""
    if isinstance(
        error,
        (
            httpx.RemoteProtocolError,
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.ConnectTimeout,
            httpx.TimeoutException,
        ),
    ):
        return True
    return any(keyword in str(error).lower() for keyword in _RETRYABLE_KEYWORDS)
