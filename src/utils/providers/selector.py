from ...config.settings import APIConfig
from .minimax import get_minimax_model
from .google_text import get_google_model
from .openai import get_openai_model


def get_text_model(model_name: str | None = None):
    """
    Return the configured default text model provider.

    Supported providers (APIConfig.MODEL_PROVIDER):
    - minimax (default)
    - google
    - openai
    """
    provider = (APIConfig.MODEL_PROVIDER or "minimax").lower()

    if provider == "minimax":
        return get_minimax_model(model_name)
    if provider == "google":
        return get_google_model(model_name)
    if provider == "openai":
        return get_openai_model(model_name)

    raise ValueError(f"Unsupported MODEL_PROVIDER: {APIConfig.MODEL_PROVIDER}")
