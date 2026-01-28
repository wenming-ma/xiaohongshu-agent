"""
统一配置管理
所有可调参数集中在此文件
"""
import os
from pathlib import Path


# ==================== 重试配置 ====================
class RetryConfig:
    """
    重试相关配置
    
    遵循 pydantic-ai 官方最佳实践：
    - 只重试暂时性错误（Rate limits、Network timeouts、Temporary API outages）
    - 保守的重试次数（3-5 次）
    - 指数退避 + Retry-After header 支持
    """

    # 方法层重试（@with_retry 装饰器）
    MAX_RETRIES = 12           # 最大重试次数（网络不稳定时更耐心）
    INITIAL_DELAY = 2.0        # 初始延迟（秒），后续按 2^attempt 增长
    MAX_TOTAL_WAIT = 1800      # 总最大等待时间（30分钟），防止无限等待

    # HTTP 层重试（AsyncTenacityTransport）
    HTTP_MAX_RETRIES = 8       # HTTP 最大重试次数（加大容忍度）
    HTTP_MAX_WAIT = 90         # 单次最大等待（秒）
    HTTP_TOTAL_MAX_WAIT = 600  # 总最大等待（秒）

    # Agent 内部重试（工具验证/输出验证）
    AGENT_RETRIES = 5          # pydantic-ai Agent 重试（增加容错）
    MCP_RETRIES = 5            # MCP 工具重试


# ==================== 审核配置 ====================
class ReviewConfig:
    """审核相关配置"""

    # 迭代次数
    MAX_ITERATIONS = 10        # 审核不通过时的最大重试生成次数

    # 评分标准
    PASS_SCORE = 60            # 通过分数阈值
    CRITICAL_PENALTY = 25      # 严重问题扣分
    WARNING_PENALTY = 10       # 警告问题扣分
    INFO_PENALTY = 5           # 信息问题扣分


# ==================== 图片配置 ====================
class ImageConfig:
    """图片相关配置"""

    # 文件大小
    MIN_FILE_SIZE = 10 * 1024       # 最小文件大小（10KB）
    MAX_REVIEW_SIZE_MB = 5.0        # 审核时最大图片大小（MB）

    # 详情图动态数量配置
    ENTITIES_PER_DETAIL = 6         # 每张详情图显示的实体数量
    MIN_DETAIL_IMAGES = 1           # 最少详情图数量
    MAX_DETAIL_IMAGES = 12           # 最多详情图数量

    # 语义分组审核
    GROUPING_REVIEW_MAX_RETRIES = 15  # 分组审核失败后最大重试次数

    # 语义分组参数
    MAX_GROUP_SIZE_CAP = 16          # 可读性上限（每组最大条数）
    COMPACT_TEXT_MAX_LEN = 240       # compact key_info 文本最大长度
    MIN_GROUP_SIZE_THRESHOLD = 8     # key_infos >= 此值时，min_group_size=3

    # 压缩参数
    COMPRESS_QUALITY_START = 95    # 压缩起始质量
    COMPRESS_QUALITY_MIN = 20      # 压缩最低质量
    COMPRESS_QUALITY_STEP = 5      # 质量递减步长


# ==================== 超时配置 ====================
class TimeoutConfig:
    """超时相关配置"""

    DOWNLOAD_TIMEOUT = 60      # 下载超时（秒）
    POLL_INTERVAL = 2          # 轮询间隔（秒）
    GEMINI_WAIT = 60           # Gemini 生成等待（秒）
    MCP_INIT_TIMEOUT = 90      # MCP Server 初始化超时（秒）- Windows 上 npx 启动较慢


# ==================== 路径配置 ====================
class PathConfig:
    """路径相关配置"""

    # 输出目录
    DOWNLOADS_DIR = Path('./output/playwright-downloads')
    PROJECT_DIR = Path('posts')

    # 浏览器会话
    # NOTE: 所有 Agent 共用同一个 USER_DATA_DIR，以复用登录状态（cookies/localStorage）。
    BROWSER_SESSION_SHARED = './browser-sessions/shared'
    BROWSER_SESSION_XHS = BROWSER_SESSION_SHARED
    BROWSER_SESSION_GEMINI = BROWSER_SESSION_SHARED


# ==================== API 配置 ====================
class APIConfig:
    """API 相关配置"""

    # Claude 模型（Anthropic 直连）
    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    CLAUDE_IMAGE_MODEL = os.getenv("CLAUDE_IMAGE_MODEL", "claude-sonnet-4-20250514")

    # OpenRouter 模型配置（已废弃，保留用于参考）
    # 注意：研究阶段需要处理截屏，必须使用支持视觉的模型
    # 已验证可用的模型：
    #   - "anthropic/claude-3-haiku" （稳定，代码能力强，支持视觉）⭐推荐
    #   - "anthropic/claude-3.5-sonnet" （更强，但更贵）
    #   - "google/gemini-2.5-flash" （便宜，但代码生成偶有语法错误）
    #   - "google/gemini-2.0-flash-exp:free" （免费但不稳定）
    # 不支持视觉的模型（如 z-ai/glm-4.7）会报 404 错误
    OPENROUTER_MODEL = "minimax/minimax-m2.1"

    # 图片审核（视觉理解）使用的 OpenRouter 模型
    # 可用视觉模型：
    #   - "qwen/qwen3-vl-30b-a3b-instruct" （Qwen3 视觉模型，支持图片理解）
    #   - "qwen/qwen-2.5-vl-7b-instruct:free" （免费但可能不稳定）
    OPENROUTER_REVIEW_MODEL = os.getenv("OPENROUTER_REVIEW_MODEL", "qwen/qwen3-vl-30b-a3b-instruct")

    # Mistral AI 模型配置（OpenAI 兼容格式）
    # 支持视觉的模型：
    #   - "pixtral-12b-latest" （专门的视觉模型，推荐）
    #   - "devstral-small-latest" （代码+视觉）
    #   - "ministral-3b-latest" （轻量级）
    # 注意：devstral-2512 不支持视觉
    MISTRAL_REVIEW_MODEL = os.getenv("MISTRAL_REVIEW_MODEL", "pixtral-12b-latest")

    # MiniMax 模型配置（通过 Nexus 代理访问，Anthropic 兼容格式）
    # 可用模型：
    #   - "MiniMax-M2.1" （最新旗舰模型，支持 Tool Use & Interleaved Thinking）
    #   - "MiniMax-Text-01" （支持100万token上下文）
    MINIMAX_MODEL = "MiniMax-M2.1"
    MINIMAX_BASE_URL = "https://nexus.itssx.com/api/claude_code/cc_minimax21"

    # Qwen 模型配置（阿里云通义千问，OpenAI 兼容格式）
    # 可用视觉模型：
    #   - "qwen-vl-plus" （视觉理解模型，性价比高）
    #   - "qwen-vl-max" （最强视觉理解模型）
    # 模型列表：https://www.alibabacloud.com/help/zh/model-studio/models
    QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-vl-plus")
    # 新加坡/弗吉尼亚地域：https://dashscope-intl.aliyuncs.com/compatible-mode/v1
    # 北京地域：https://dashscope.aliyuncs.com/compatible-mode/v1
    QWEN_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

    # SageHub 模型配置（Claude 中转服务，OpenAI 兼容格式）
    # 可用视觉模型（全部支持视觉）：
    #   - "claude-opus-4-5-20251101" （最强模型，推荐）
    #   - "claude-sonnet-4-5-20250929" （性价比高）
    #   - "claude-haiku-4-5-20251001" （最快最便宜）
    SAGEHUB_MODEL = os.getenv("SAGEHUB_MODEL", "claude-sonnet-4-5-20250929")
    SAGEHUB_BASE_URL = "https://api.sagehub.cc/v1"

    # Google Gemini 模型配置（直连 Google AI）
    # 可用视觉模型：
    #   - "gemini-3-flash-preview" （最新 Gemini 3 视觉模型，推荐）
    #   - "gemini-2.5-flash" （稳定版本）
    #   - "gemini-2.5-pro" （更强大）
    # 需要设置 GOOGLE_API_KEY 环境变量
    GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-3-flash-preview")

    # 模型提供者选择："anthropic" 或 "openrouter" 或 "minimax"
    # minimax 使用 Anthropic 兼容 API，支持 Tool Use
    MODEL_PROVIDER = "minimax"

    # Gemini URL (网页版，已废弃，保留用于参考)
    GEMINI_URL = "https://gemini.google.com/app"

    # Gemini 图片生成 API 配置 (OpenAI 兼容格式)
    # 通过本地代理服务访问
    GEMINI_IMAGE_BASE_URL = os.getenv("GEMINI_IMAGE_BASE_URL", "http://127.0.0.1:8045/v1")
    GEMINI_IMAGE_API_KEY = os.getenv("GEMINI_IMAGE_API_KEY", "your-api-key")
    GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3-pro-image")
    # 支持的尺寸: 任意 WIDTHxHEIGHT 格式，自动计算宽高比
    # 小红书推荐使用 3:4 竖版，使用 1080x1440 (3:4) 作为默认
    GEMINI_IMAGE_SIZE = os.getenv("GEMINI_IMAGE_SIZE", "1080x1440")
    # 图片质量: "hd" (4K), "medium" (2K), "standard" (默认)
    GEMINI_IMAGE_QUALITY = os.getenv("GEMINI_IMAGE_QUALITY", "hd")

    # 可重试的 HTTP 状态码
    RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)


# ==================== 发布配置 ====================
class PublishConfig:
    """发布相关配置"""

    # 重试配置
    MAX_RETRIES = 5            # 发布失败最大重试次数
    INITIAL_DELAY = 10.0       # 初始延迟（秒）

    # 超时配置
    UPLOAD_TIMEOUT = 120       # 图片上传超时（秒）
    PUBLISH_TIMEOUT = 60       # 发布操作超时（秒）

    # 小红书发布页面
    XHS_PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish"


# ==================== 研究配置 ====================
class ResearchConfig:
    """研究相关配置"""

    # 帖子数量要求
    MIN_POSTS_RESEARCHED = 17      # 最少研究帖子数

    # 数据质量要求
    MIN_KEY_INFOS = 15            # 最少关键信息数量
    MIN_CASES = 10                 # 最少案例数量
    MIN_COMMENT_DATA_RATIO = 0.4  # 评论区数据最低占比（30%）

    # 验证配置
    VALIDATION_MAX_RETRIES = 15    # 验证失败最大重试次数
    VALIDATION_PASS_SCORE = 70    # 验证通过分数阈值


# ==================== Telegram 配置 ====================
class TelegramConfig:
    """Telegram Bot 配置"""
    
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # 你的 Telegram ID（可选，不限制）
    TOOL_FEEDBACK_ENABLED = os.getenv("TELEGRAM_TOOL_FEEDBACK_ENABLED", "0").lower() in ("1", "true", "yes", "on")


# ==================== 用户信息配置 ====================
class UserProfileConfig:
    """
    用户常用账号信息 - 用于自动登录/注册
    
    这些信息会包含在 LoginAgent 的系统提示词中，
    便于自动填写注册/登录表单。
    """
    
    # 基本信息
    PHONE = os.getenv("USER_PHONE")           # 手机号
    EMAIL = os.getenv("USER_EMAIL")           # 邮箱
    USERNAME = os.getenv("USER_USERNAME")     # 常用用户名
    
    # 备用信息
    PHONE_ALT = os.getenv("USER_PHONE_ALT")   # 备用手机号
    EMAIL_ALT = os.getenv("USER_EMAIL_ALT")   # 备用邮箱
