"""
LangGraph 系统配置
支持多模型、成本优化、环境变量管理
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# === 项目路径 ===
PROJECT_ROOT = Path(__file__).parent
POSTS_DIR = PROJECT_ROOT / "posts"
LEGACY_DIR = PROJECT_ROOT / "legacy"

# === API 配置 ===
# 自定义 Anthropic API 端点（统一管理所有模型）
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", ANTHROPIC_AUTH_TOKEN)

# OpenRouter 配置（用于图片生成）
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_IMAGE_MODEL = os.getenv("OPENROUTER_IMAGE_MODEL", "openai/dall-e-3")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "")
OPENROUTER_SITE_NAME = os.getenv("OPENROUTER_SITE_NAME", "Xiaohongshu Agent")

# 传统 API Keys（可选）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# === 模型配置 ===
MODELS = {
    "claude": {
        "name": "claude-sonnet-4-5-20250929",
        "provider": "anthropic",
        "cost_per_1m_tokens": 3.0,
        "best_for": "内容创作、高质量输出"
    },
    "gpt4": {
        "name": "gpt-4-turbo-2024-04-09",
        "provider": "openai",
        "cost_per_1m_tokens": 10.0,
        "best_for": "研究、数据处理"
    },
    "gpt4o": {
        "name": "gpt-4o",
        "provider": "openai",
        "cost_per_1m_tokens": 5.0,
        "best_for": "平衡性能和成本"
    },
    "gemini": {
        "name": "gemini-1.5-pro",
        "provider": "google",
        "cost_per_1m_tokens": 1.25,
        "best_for": "图片生成、低成本"
    }
}

# === 节点模型映射（统一使用自定义 Anthropic 端点）===
NODE_MODELS = {
    # Phase 1: 初始化 - 轻量级
    "init_project": None,  # 无需LLM

    # Phase 2A: 并行研究 - 使用Claude（通过自定义端点）
    "research_xhs": "claude",
    "research_web": "claude",

    # Phase 2B: 内容合成 - 使用Claude
    "synthesize": "claude",

    # Phase 3: 图片生成 - 使用Claude（或需要单独配置）
    "generate_images": "claude",

    # Phase 4: 发布 - 无需LLM
    "publish": None
}

# === 工作流配置 ===
WORKFLOW_CONFIG = {
    # 最大重试次数
    "max_retries": 3,

    # 超时设置（秒）
    "node_timeout": 300,
    "total_timeout": 1800,

    # 并行执行配置
    "parallel_research": True,

    # Checkpointing
    "enable_checkpointing": True,
    "checkpoint_dir": PROJECT_ROOT / ".checkpoints",

    # 日志
    "log_level": "INFO",
    "log_file": PROJECT_ROOT / "langgraph.log"
}

# === Xiaohongshu 平台配置 ===
XHS_CONFIG = {
    "publish_url": "https://creator.xiaohongshu.com/publish/publish",
    "login_url": "https://www.xiaohongshu.com/login",

    # 内容规范
    "title_max_length": 20,
    "title_min_length": 10,
    "body_max_length": 1000,
    "body_min_length": 100,
    "hashtags_count": (3, 5),  # (min, max)
    "images_count": (1, 9),    # (min, max)

    # 发布设置
    "headless": False,  # 浏览器是否无头模式
    "wait_after_publish": 5,  # 发布后等待秒数
}

# === Web 搜索配置 ===
WEB_SEARCH_CONFIG = {
    "platforms": {
        "xiaohongshu": {
            "search_url": "https://www.xiaohongshu.com/search_result",
            "enabled": True,
            "priority": 1
        },
        "zhihu": {
            "search_url": "https://www.zhihu.com/search",
            "enabled": True,
            "priority": 2
        },
        "weibo": {
            "search_url": "https://s.weibo.com/weibo",
            "enabled": True,
            "priority": 3
        },
        "baidu_tieba": {
            "search_url": "https://tieba.baidu.com/f/search/res",
            "enabled": True,
            "priority": 4
        }
    },

    # 搜索参数
    "max_results_per_platform": 10,
    "search_timeout": 30,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# === 成本估算函数 ===
def estimate_cost(node_name: str, input_tokens: int, output_tokens: int) -> float:
    """估算节点执行成本（美元）"""
    model_key = NODE_MODELS.get(node_name)
    if not model_key:
        return 0.0

    model_info = MODELS.get(model_key)
    if not model_info:
        return 0.0

    cost_per_1m = model_info["cost_per_1m_tokens"]
    total_tokens = input_tokens + output_tokens
    return (total_tokens / 1_000_000) * cost_per_1m


def get_model_for_node(node_name: str):
    """获取节点对应的模型实例（统一使用自定义 Anthropic 端点）"""
    from langchain_anthropic import ChatAnthropic
    from langchain_openai import ChatOpenAI
    from langchain_google_genai import ChatGoogleGenerativeAI

    model_key = NODE_MODELS.get(node_name)
    if not model_key:
        return None

    model_config = MODELS[model_key]
    provider = model_config["provider"]
    model_name = model_config["name"]

    if provider == "anthropic":
        # 使用自定义 API 端点
        return ChatAnthropic(
            model=model_name,
            api_key=ANTHROPIC_API_KEY,
            base_url=ANTHROPIC_BASE_URL,
            temperature=0.7,
            max_tokens=4096
        )
    elif provider == "openai":
        # 如果仍需使用 OpenAI（如 DALL-E 3），保留原配置
        return ChatOpenAI(
            model=model_name,
            api_key=OPENAI_API_KEY,
            temperature=0.7
        )
    elif provider == "google":
        # 如果仍需使用 Google，保留原配置
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=GOOGLE_API_KEY,
            temperature=0.7
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")


# === 环境检查 ===
def check_environment():
    """检查环境配置是否完整"""
    import sys

    # 设置 Windows 控制台编码
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass

    issues = []

    # 检查自定义 Anthropic 配置
    if not ANTHROPIC_BASE_URL:
        issues.append("Missing ANTHROPIC_BASE_URL")
    if not ANTHROPIC_AUTH_TOKEN and not ANTHROPIC_API_KEY:
        issues.append("Missing ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY")

    # OpenAI 和 Google 现在是可选的
    # if not OPENAI_API_KEY:
    #     issues.append("Missing OPENAI_API_KEY (optional)")
    # if not GOOGLE_API_KEY:
    #     issues.append("Missing GOOGLE_API_KEY (optional)")

    if issues:
        print("WARNING: Environment Issues:")
        for issue in issues:
            print(f"  - {issue}")
        print("\nPlease set missing configuration in .env file")
        return False

    print("OK: Environment check passed")
    print(f"Using Anthropic API endpoint: {ANTHROPIC_BASE_URL}")
    return True


if __name__ == "__main__":
    check_environment()
    print("\n📊 Model Configuration:")
    for node, model_key in NODE_MODELS.items():
        if model_key:
            model = MODELS[model_key]
            print(f"  {node:20s} → {model['name']:30s} (${model['cost_per_1m_tokens']}/1M tokens)")
