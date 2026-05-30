import os
from pathlib import Path


def _split_csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _resolve_minimax_anthropic_base_url() -> str:
    explicit = os.getenv("MINIMAX_ANTHROPIC_BASE_URL")
    if explicit:
        return explicit

    legacy = os.getenv("MINIMAX_BASE_URL")
    if legacy:
        lowered = legacy.lower()
        if "anthropic" in lowered or "claude" in lowered:
            return legacy

    return "https://api.minimax.io/anthropic"


def _resolve_minimax_openai_base_url() -> str:
    explicit = os.getenv("MINIMAX_OPENAI_BASE_URL")
    if explicit:
        return explicit

    legacy = os.getenv("MINIMAX_BASE_URL")
    if legacy:
        lowered = legacy.lower()
        if "anthropic" not in lowered and "claude" not in lowered:
            return legacy

    return "https://api.minimaxi.com/v1"


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
    PASS_SCORE = 80
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
    GEMINI_WAIT = 600
    GEMINI_WEB_TIMEOUT = 120
    MCP_INIT_TIMEOUT = 90


class PathConfig:
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    PROMPT_TEMPLATE_ROOT = Path(os.getenv("PROMPT_TEMPLATE_ROOT", _PROJECT_ROOT / ".prompt-template-repos"))
    DOWNLOADS_DIR = _PROJECT_ROOT / 'output' / 'playwright-downloads'
    FEISHU_SESSION_DIR = _PROJECT_ROOT / 'output' / 'feishu-sessions'
    IMAGE_PROJECT_DIR = _PROJECT_ROOT / 'posts' / 'image-posts'
    OUTFIT_PROJECT_DIR = _PROJECT_ROOT / 'posts' / 'outfit-posts'
    ARTICLE_PROJECT_DIR = _PROJECT_ROOT / 'posts' / 'article-posts'
    VIDEO_PROJECT_DIR = _PROJECT_ROOT / 'posts' / 'video-posts'
    BROWSER_SESSION_SHARED = str(_PROJECT_ROOT / 'browser-sessions' / 'shared')
    BROWSER_SESSION_XHS = BROWSER_SESSION_SHARED
    BROWSER_SESSION_GEMINI = str(_PROJECT_ROOT / 'browser-sessions' / 'gemini')


class APIConfig:
    ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
    ANTHROPIC_FALLBACK_BASE_URL = os.getenv("ANTHROPIC_FALLBACK_BASE_URL")
    ANTHROPIC_ENDPOINTS = [
        {"api_key_env": "ANTHROPIC_API_KEY"},
    ]
    MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")
    MINIMAX_ANTHROPIC_BASE_URL = _resolve_minimax_anthropic_base_url()
    MINIMAX_OPENAI_BASE_URL = _resolve_minimax_openai_base_url()
    GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")
    GOOGLE_VISION_MODEL = os.getenv("GOOGLE_VISION_MODEL", "gemini-2.5-pro")
    MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "minimax")
    GEMINI_URL = os.getenv("GEMINI_URL", "https://gemini.google.com/app")
    _GEMINI_ALL_KEYS = _split_csv_env("GEMINI_API_KEY")
    GEMINI_API_KEY = _GEMINI_ALL_KEYS[0] if _GEMINI_ALL_KEYS else os.getenv("GEMINI_API_KEY")
    GEMINI_FALLBACK_API_KEYS = _GEMINI_ALL_KEYS[1:] + _split_csv_env("GEMINI_FALLBACK_API_KEYS")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://sub2api.wenming-dev.org/v1")
    GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3-pro-image-preview")
    GEMINI_IMAGE_SIZE = os.getenv("GEMINI_IMAGE_SIZE", "2K")
    VERTEX_AI_PROJECT_ID = os.getenv("VERTEX_AI_PROJECT_ID")
    VERTEX_AI_LOCATION = os.getenv("VERTEX_AI_LOCATION", "global")
    VERTEX_AI_VISION_MODEL = os.getenv("VERTEX_AI_VISION_MODEL", "gemini-2.5-flash")
    VERTEX_AI_IMAGE_MODEL = os.getenv("VERTEX_AI_IMAGE_MODEL", "gemini-3-pro-image-preview")
    RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)
    # "api" = API only, "web" = web only, "auto" = API first then web fallback
    GEMINI_IMAGE_PROVIDER = os.getenv("GEMINI_IMAGE_PROVIDER", "auto")


class PublishConfig:
    MAX_RETRIES = 5
    INITIAL_DELAY = 10.0
    UPLOAD_TIMEOUT = 120
    PUBLISH_TIMEOUT = 60
    XHS_PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish"


class ResearchConfig:
    MIN_POSTS_RESEARCHED = 21
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
    DM_MODE = os.getenv("FEISHU_DM_MODE", "0").lower() in ("1", "true", "yes", "on")


class UserProfileConfig:
    PHONE = os.getenv("USER_PHONE")
    EMAIL = os.getenv("USER_EMAIL")
    USERNAME = os.getenv("USER_USERNAME")
    PHONE_ALT = os.getenv("USER_PHONE_ALT")
    EMAIL_ALT = os.getenv("USER_EMAIL_ALT")


class SanitizerConfig:
    ENABLED = os.getenv("IMAGE_SANITIZER_ENABLED", "1") == "1"
    # Stage 2: 相机噪声
    SHOT_NOISE_GAIN = float(os.getenv("IMAGE_SANITIZER_SHOT_GAIN", "20"))
    READ_NOISE_SIGMA = float(os.getenv("IMAGE_SANITIZER_READ_SIGMA", "1.5"))
    NOISE_BLEND = float(os.getenv("IMAGE_SANITIZER_NOISE_BLEND", "0.25"))
    # Stage 2b: Bayer 去马赛克
    BAYER_BLEND = float(os.getenv("IMAGE_SANITIZER_BAYER_BLEND", "0.3"))
    # Stage 2c: 镜头光学效果
    VIGNETTE_STRENGTH = float(os.getenv("IMAGE_SANITIZER_VIGNETTE", "0.1"))
    CA_SHIFT = float(os.getenv("IMAGE_SANITIZER_CA_SHIFT", "1.0"))
    # Stage 3: 微几何变换
    ROTATION_MAX_DEG = float(os.getenv("IMAGE_SANITIZER_ROTATION", "0"))
    SCALE_RANGE = float(os.getenv("IMAGE_SANITIZER_SCALE", "0.02"))
    # Stage 3b: FFT 频域扰动
    FFT_NOISE_STD = float(os.getenv("IMAGE_SANITIZER_FFT_NOISE", "0.02"))
    # Stage 3c: LAB 色彩抖动
    COLOR_JITTER_L = float(os.getenv("IMAGE_SANITIZER_JITTER_L", "3.0"))
    COLOR_JITTER_AB = float(os.getenv("IMAGE_SANITIZER_JITTER_AB", "2.0"))
    # Stage 4: JPEG 重编码
    JPEG_QUALITY = int(os.getenv("IMAGE_SANITIZER_JPEG_QUALITY", "85"))


class ReferenceImageConfig:
    MAX_IMAGES_PER_ITEM = int(os.getenv("REFERENCE_IMAGE_MAX_PER_ITEM", "3"))
    MAX_TOTAL_IMAGES_PER_GROUP = int(os.getenv("REFERENCE_IMAGE_MAX_TOTAL_PER_GROUP", "6"))


class ASRConfig:
    PROVIDER = os.getenv("ASR_PROVIDER", "faster_whisper")


class SubtitleConfig:
    TARGET_LANGUAGE = "zh"
    FONT_NAME = "Microsoft YaHei"
    FONT_SIZE = 24
    ENABLE_TRANSLATION = True


class BrowserConfig:
    PLAYWRIGHT_RESEARCH_HEADLESS = _bool_env("PLAYWRIGHT_RESEARCH_HEADLESS", True)
    VIDEO_RESEARCH_HEADLESS = _bool_env(
        "VIDEO_RESEARCH_HEADLESS",
        PLAYWRIGHT_RESEARCH_HEADLESS,
    )
