"""Image phase package."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import ImageAgent

__all__ = ["ImageAgent"]


def __getattr__(name: str):
    if name == "ImageAgent":
        from .agent import ImageAgent

        return ImageAgent
    raise AttributeError(name)
