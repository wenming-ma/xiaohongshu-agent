"""XHS Outfit Post Pipeline - 小红书穿搭搭配帖子流水线"""

from .pipeline import OutfitPostPipeline
from .schemas import OutfitPostInput, OutfitPostOutput

__all__ = ["OutfitPostPipeline", "OutfitPostInput", "OutfitPostOutput"]
