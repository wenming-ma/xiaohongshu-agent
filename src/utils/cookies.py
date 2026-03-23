import os

from ..config.settings import PathConfig
from .logger import get_logger

logger = get_logger(__name__)


def get_cookie_config() -> dict:
    cookie_file = PathConfig.COOKIES_FILE
    if os.path.isfile(cookie_file):
        logger.debug(f"Using cookie file: {cookie_file}")
        return {"cookiefile": cookie_file}
    logger.debug("No cookie file found, falling back to Chrome browser cookies")
    return {"cookiesfrombrowser": ("chrome",)}
