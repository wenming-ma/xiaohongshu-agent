import json
import os
from pathlib import Path


def _split_csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_endpoint(base_url_env: str, api_key_env: str) -> dict[str, str] | None:
    base_url = os.getenv(base_url_env)
    api_key = os.getenv(api_key_env)
    if not base_url and not api_key:
        return None

    endpoint = {"api_key_env": api_key_env}
    if base_url:
        endpoint["base_url"] = base_url
    return endpoint


def _load_anthropic_endpoints() -> list[dict[str, str]]:
    raw = os.getenv("ANTHROPIC_ENDPOINTS_JSON")
    if raw:
        endpoints = json.loads(raw)
        if not isinstance(endpoints, list) or not all(isinstance(item, dict) for item in endpoints):
            raise ValueError("ANTHROPIC_ENDPOINTS_JSON 必须是对象数组")
        return endpoints

    endpoints: list[dict[str, str]] = []

    primary = _build_endpoint("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY")
    if primary:
        endpoints.append(primary)
    else:
        endpoints.append({"api_key_env": "ANTHROPIC_API_KEY"})

    fallback = _build_endpoint("ANTHROPIC_FALLBACK_BASE_URL", "ANTHROPIC_FALLBACK_API_KEY")
    if fallback:
        endpoints.append(fallback)

    return endpoints


class RetryConfig:
    MAX_RETRIES = 12
    INITIAL_DELAY = 2.0
    MAX_TOTAL_WAIT = 1800
    HTTP_MAX_RETRIES = 8
    HTTP_MAX_WAIT = 90
    HTTP_TOTAL_MAX_WAIT = 600
    AGENT_RETRIES = 5
    MCP_RETRIES = 5


class ReviewConfig:
    MAX_ITERATIONS = 10
    PASS_SCORE = 60
    CRITICAL_PENALTY = 25
    WARNING_PENALTY = 10
    INFO_PENALTY = 5


class ImageConfig:
    MIN_FILE_SIZE = 10 * 1024
    MAX_REVIEW_SIZE_MB = 5.0
    ENTITIES_PER_DETAIL = 6
    MIN_DETAIL_IMAGES = 1
    MAX_DETAIL_IMAGES = 12
    GROUPING_REVIEW_MAX_RETRIES = 20
    MAX_GROUP_SIZE_CAP = 16
    COMPACT_TEXT_MAX_LEN = 240
    MIN_GROUP_SIZE_THRESHOLD = 8
    COMPRESS_QUALITY_START = 95
    COMPRESS_QUALITY_MIN = 20
    COMPRESS_QUALITY_STEP = 5


class TimeoutConfig:
    DOWNLOAD_TIMEOUT = 60
    POLL_INTERVAL = 2
    GEMINI_WAIT = 180
    MCP_INIT_TIMEOUT = 90


class PathConfig:
    DOWNLOADS_DIR = Path('./output/playwright-downloads')
    IMAGE_PROJECT_DIR = Path('posts/image-posts')
    VIDEO_PROJECT_DIR = Path('posts/video-posts')
    BROWSER_SESSION_SHARED = './browser-sessions/shared'
    BROWSER_SESSION_XHS = BROWSER_SESSION_SHARED
    BROWSER_SESSION_GEMINI = BROWSER_SESSION_SHARED


class APIConfig:
    ANTHROPIC_ENDPOINTS = _load_anthropic_endpoints()

    DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
    CLAUDE_IMAGE_MODEL = os.getenv("CLAUDE_IMAGE_MODEL", DEFAULT_MODEL)
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "minimax/minimax-m2.1")
    OPENROUTER_REVIEW_MODEL = os.getenv("OPENROUTER_REVIEW_MODEL", "qwen/qwen3-vl-30b-a3b-instruct")
    MISTRAL_REVIEW_MODEL = os.getenv("MISTRAL_REVIEW_MODEL", "pixtral-12b-latest")
    MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M2.5")
    MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/anthropic")
    QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-vl-plus")
    QWEN_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    SAGEHUB_MODEL = os.getenv("SAGEHUB_MODEL", "claude-sonnet-4-5-20250929")
    SAGEHUB_BASE_URL = os.getenv("SAGEHUB_BASE_URL", "https://api.sagehub.cc/v1")
    GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")
    MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "minimax")
    GEMINI_URL = os.getenv("GEMINI_URL", "https://gemini.google.com/app")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_FALLBACK_API_KEYS = _split_csv_env("GEMINI_FALLBACK_API_KEYS")
    GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3-pro-image-preview")
    GEMINI_IMAGE_SIZE = os.getenv("GEMINI_IMAGE_SIZE", "2K")
    REVIEW_MODEL = os.getenv("REVIEW_MODEL", "claude-sonnet-4-6")
    RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)


class PublishConfig:
    MAX_RETRIES = 5
    INITIAL_DELAY = 10.0
    UPLOAD_TIMEOUT = 120
    PUBLISH_TIMEOUT = 60
    XHS_PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish"


class ResearchConfig:
    MIN_POSTS_RESEARCHED = 17
    MIN_KEY_INFOS = 15
    MIN_CASES = 10
    MIN_COMMENT_DATA_RATIO = 0.4
    VALIDATION_MAX_RETRIES = 15
    VALIDATION_PASS_SCORE = 70


class TelegramConfig:
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    TOOL_FEEDBACK_ENABLED = os.getenv("TELEGRAM_TOOL_FEEDBACK_ENABLED", "0").lower() in ("1", "true", "yes", "on")


class FeishuConfig:
    APP_ID = os.getenv("FEISHU_APP_ID")
    APP_SECRET = os.getenv("FEISHU_APP_SECRET")
    CHAT_ID = os.getenv("FEISHU_CHAT_ID")
    MENTION_USER_ID = os.getenv("FEISHU_MENTION_USER_ID", "ou_4f24c411b1b8363b40a0ca18507db836")
    MENTION_USER_NAME = os.getenv("FEISHU_MENTION_USER_NAME", "马旖旎")


class UserProfileConfig:
    PHONE = os.getenv("USER_PHONE")
    EMAIL = os.getenv("USER_EMAIL")
    USERNAME = os.getenv("USER_USERNAME")
    PHONE_ALT = os.getenv("USER_PHONE_ALT")
    EMAIL_ALT = os.getenv("USER_EMAIL_ALT")


class SubtitleConfig:
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
    WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
    WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
    TARGET_LANGUAGE = "zh"
    FONT_NAME = "Microsoft YaHei"
    FONT_SIZE = 24
    ENABLE_TRANSLATION = True
