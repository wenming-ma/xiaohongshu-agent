import os
from pathlib import Path


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
    GROUPING_REVIEW_MAX_RETRIES = 15
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
    PROJECT_DIR = Path('posts')
    BROWSER_SESSION_SHARED = './browser-sessions/shared'
    BROWSER_SESSION_XHS = BROWSER_SESSION_SHARED
    BROWSER_SESSION_GEMINI = BROWSER_SESSION_SHARED


class APIConfig:
    # 端点轮换：永久错误时自动切换
    ANTHROPIC_ENDPOINTS = [
        {
            "base_url": "https://api.123577.xyz/api",
            "api_key": "cr_e0004507949e2d9b4de61875aa885ee0533a43591645ba938bbb3a69789db43e",
        },
        {
            "base_url": "http://127.0.0.1:8045",
            "api_key": "your-api-key",
        },
    ]

    DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
    CLAUDE_IMAGE_MODEL = os.getenv("CLAUDE_IMAGE_MODEL", "claude-sonnet-4-5-20250929")
    OPENROUTER_MODEL = "minimax/minimax-m2.1"
    OPENROUTER_REVIEW_MODEL = os.getenv("OPENROUTER_REVIEW_MODEL", "qwen/qwen3-vl-30b-a3b-instruct")
    MISTRAL_REVIEW_MODEL = os.getenv("MISTRAL_REVIEW_MODEL", "pixtral-12b-latest")
    MINIMAX_MODEL = "MiniMax-M2.1"
    MINIMAX_BASE_URL = "https://nexus.itssx.com/api/claude_code/cc_minimax21"
    QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-vl-plus")
    QWEN_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    SAGEHUB_MODEL = os.getenv("SAGEHUB_MODEL", "claude-sonnet-4-5-20250929")
    SAGEHUB_BASE_URL = "https://api.sagehub.cc/v1"
    GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-3-flash-preview")
    MODEL_PROVIDER = "minimax"
    GEMINI_URL = "https://gemini.google.com/app"
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "your-api-key")
    GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3-pro-image-preview")
    GEMINI_IMAGE_SIZE = os.getenv("GEMINI_IMAGE_SIZE", "2K")
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


class UserProfileConfig:
    PHONE = os.getenv("USER_PHONE")
    EMAIL = os.getenv("USER_EMAIL")
    USERNAME = os.getenv("USER_USERNAME")
    PHONE_ALT = os.getenv("USER_PHONE_ALT")
    EMAIL_ALT = os.getenv("USER_EMAIL_ALT")
