# Utils 目录

这里只放基础共享 infra，不放业务 helper。

## 允许放在这里的模块

| 文件 / 目录 | 职责 |
|------|------|
| `providers/` | 模型与图片生成 provider 封装；只负责基础调用，不做业务后处理 |
| `prompting.py` | 提示词模板渲染 |
| `logger.py` | 日志配置 |
| `file_ops.py` | 通用文件读写辅助 |
| `retry_handler.py` | 重试装饰器与重试策略 |
| `telegram_notifier.py` / `feishu_notifier.py` / `logfire_telegram_handler.py` | 通知与告警集成 |

## 不应该放在这里的代码

- 某个 pipeline 专用的 helper：放到 `src/agents/<pipeline>/utils/`
- 跨多个 pipeline 复用但仍属于业务语义的 helper：放到 `src/agents/shared/utils/`
- phase 目录下零散的 `utils.py`：统一收口到 pipeline 根下的 `utils/`

## Provider 使用

```python
from src.utils.providers import GeminiImageClient, get_text_model

model = get_text_model()
client = GeminiImageClient()
```
