# Config 目录

配置管理。

## settings.py

所有配置项通过类属性定义，支持环境变量覆盖：

```python
from src.config.settings import (
    APIConfig,        # API 密钥和端点
    RetryConfig,      # 重试策略
    TimeoutConfig,    # 超时配置
    PathConfig,       # 路径配置
    ResearchConfig,   # 研究配置
    ImageConfig,      # 图片生成配置
    ReviewConfig,     # 审核配置
)
```

## 环境变量

关键环境变量：
- `ANTHROPIC_API_KEY` - Claude API
- `ANTHROPIC_BASE_URL` - Anthropic 兼容主端点（可选）
- `ANTHROPIC_FALLBACK_BASE_URL` - Anthropic 兼容回退端点（可选）
- `ANTHROPIC_FALLBACK_API_KEY` - 回退端点密钥（可选）
- `MINIMAX_API_KEY` - MiniMax API
- `GEMINI_API_KEY` - Gemini API
- `MODEL_PROVIDER` - 默认文本模型提供方
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` - 飞书应用配置
- `FEISHU_RUNTIME_ENV` / `FEISHU_CHAT_DEV_ID` / `FEISHU_CHAT_DEPLOY_ID` - 飞书开发/部署 chat id 分流配置
- `FEISHU_CHAT_ID` - 飞书 chat id 显式覆盖（优先于 DEV / DEPLOY 分流）
- `VERTEX_AI_PROJECT_ID` / `VERTEX_AI_LOCATION` - Vertex AI 图片生成与读图配置
- `PROMPT_TEMPLATE_ROOT` - 可选覆盖提示词片段库；默认固定为 `.agents/prompt`
- `TELEGRAM_BOT_TOKEN` - Telegram 通知
