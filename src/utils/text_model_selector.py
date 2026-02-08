from ..config.settings import APIConfig
from .anthropic_provider import get_anthropic_model
from .google_provider import get_google_model
from .minimax_provider import get_minimax_model
from .openrouter_provider import get_openrouter_model
from .qwen_provider import get_qwen_model
from .sagehub_provider import get_sagehub_model


def get_text_model(model_name: str | None = None):
    """
    Return the configured default text model provider.

    Supported providers are controlled by APIConfig.MODEL_PROVIDER:
    - minimax
    - anthropic
    - openrouter
    - qwen
    - google
    - sagehub
    """
    provider = (APIConfig.MODEL_PROVIDER or "minimax").lower()

    if provider == "minimax":
        return get_minimax_model(model_name)
    if provider == "anthropic":
        return get_anthropic_model(model_name)
    if provider == "openrouter":
        return get_openrouter_model(model_name)
    if provider == "qwen":
        return get_qwen_model(model_name)
    if provider == "google":
        return get_google_model(model_name)
    if provider == "sagehub":
        return get_sagehub_model(model_name)

    raise ValueError(f"Unsupported MODEL_PROVIDER: {APIConfig.MODEL_PROVIDER}")
