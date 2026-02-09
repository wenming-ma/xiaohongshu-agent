# Utils 目录

通用工具函数和 Provider。

## 文件说明

| 文件 | 职责 |
|------|------|
| `anthropic_provider.py` | Claude API 客户端封装 |
| `minimax_provider.py` | MiniMax API 客户端封装 |
| `gemini_provider.py` | Gemini 图片生成客户端 |
| `prompting.py` | 提示词模板渲染（`render_template`） |
| `logger.py` | 日志配置 |
| `file_ops.py` | 文件操作工具 |
| `image_compression.py` | 图片压缩（用于 API 上传） |
| `telegram_notifier.py` | Telegram 通知（登录交互） |
| `retry_handler.py` | 重试装饰器 |
| `navigate_tracker.py` | MCP 导航追踪 |

## Provider 使用

```python
from src.utils.anthropic_provider import get_anthropic_model
from src.utils.gemini_provider import GeminiImageClient

model = get_anthropic_model()
client = GeminiImageClient()
```
