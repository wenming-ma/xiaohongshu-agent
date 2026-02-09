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
    PublishConfig,    # 发布配置
    ReviewConfig,     # 审核配置
)
```

## 环境变量

关键环境变量：
- `ANTHROPIC_API_KEY` - Claude API
- `MINIMAX_API_KEY` - MiniMax API
- `GEMINI_API_KEY` - Gemini API
- `TELEGRAM_BOT_TOKEN` - Telegram 通知
