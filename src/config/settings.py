"""
统一配置管理
所有可调参数集中在此文件
"""
from pathlib import Path


# ==================== 重试配置 ====================
class RetryConfig:
    """重试相关配置"""

    # 方法层重试（@with_retry 装饰器）
    MAX_RETRIES = 10           # 最大重试次数
    INITIAL_DELAY = 5.0        # 初始延迟（秒）

    # HTTP 层重试（AsyncTenacityTransport）
    HTTP_MAX_RETRIES = 10      # HTTP 最大重试次数
    HTTP_MAX_WAIT = 60         # 单次最大等待（秒）
    HTTP_TOTAL_MAX_WAIT = 300  # 总最大等待（秒）

    # Agent 内部重试
    AGENT_RETRIES = 5          # pydantic-ai Agent 重试
    MCP_RETRIES = 10           # MCP 工具重试


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

    # 图片数量
    DEFAULT_COUNT = 3          # 默认生成图片数量
    MIN_COUNT = 1              # 最小数量
    MAX_COUNT = 3              # 最大数量

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


# ==================== 路径配置 ====================
class PathConfig:
    """路径相关配置"""

    # 输出目录
    DOWNLOADS_DIR = Path('./output/playwright-downloads')
    PROJECT_DIR = Path('posts')

    # 浏览器会话
    BROWSER_SESSION_XHS = './browser-sessions/xiaohongshu'
    BROWSER_SESSION_GEMINI = './browser-sessions/gemini'


# ==================== API 配置 ====================
class APIConfig:
    """API 相关配置"""

    # Claude 模型
    DEFAULT_MODEL = "claude-sonnet-4-20250514"

    # Gemini URL
    GEMINI_URL = "https://gemini.google.com/app"

    # 可重试的 HTTP 状态码
    RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)
