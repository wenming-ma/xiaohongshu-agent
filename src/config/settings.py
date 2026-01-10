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
    MAX_DETAIL_IMAGES = 8           # 最多详情图数量（1封面+8详情=9张，小红书上限）

    # 语义分组审核
    GROUPING_REVIEW_MAX_RETRIES = 3  # 分组审核失败后最大重试次数

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

    # OpenRouter 模型配置
    # 注意：研究阶段需要处理截屏，必须使用支持视觉的模型
    # 已验证可用的模型：
    #   - "anthropic/claude-3-haiku" （稳定，代码能力强，支持视觉）⭐推荐
    #   - "anthropic/claude-3.5-sonnet" （更强，但更贵）
    #   - "google/gemini-2.5-flash" （便宜，但代码生成偶有语法错误）
    #   - "google/gemini-2.0-flash-exp:free" （免费但不稳定）
    # 不支持视觉的模型（如 z-ai/glm-4.7）会报 404 错误
    OPENROUTER_MODEL = "minimax/minimax-m2.1"

    # MiniMax 模型配置（Anthropic 兼容格式 - 官方推荐）
    # 可用模型：
    #   - "MiniMax-M2.1" （最新旗舰模型，支持 Tool Use & Interleaved Thinking）
    #   - "MiniMax-Text-01" （支持100万token上下文）
    MINIMAX_MODEL = "MiniMax-M2.1"
    MINIMAX_BASE_URL = "https://api.minimax.io/anthropic"

    # 模型提供者选择："anthropic" 或 "openrouter" 或 "minimax"
    # minimax 使用 Anthropic 兼容 API，支持 Tool Use
    MODEL_PROVIDER = "minimax"

    # Gemini URL
    GEMINI_URL = "https://gemini.google.com/app"

    # 可重试的 HTTP 状态码
    RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)


# ==================== 发布配置 ====================
class PublishConfig:
    """发布相关配置"""

    # 重试配置
    MAX_RETRIES = 3            # 发布失败最大重试次数
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
    MIN_POSTS_RESEARCHED = 21      # 最少研究帖子数

    # 数据质量要求
    MIN_KEY_INFOS = 15            # 最少关键信息数量
    MIN_CASES = 10                 # 最少案例数量
    MIN_COMMENT_DATA_RATIO = 0.3  # 评论区数据最低占比（30%）

    # 验证配置
    VALIDATION_MAX_RETRIES = 15    # 验证失败最大重试次数
    VALIDATION_PASS_SCORE = 70    # 验证通过分数阈值


# ==================== Telegram 配置 ====================
class TelegramConfig:
    """Telegram Bot 配置"""
    
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # 你的 Telegram ID（可选，不限制）


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
