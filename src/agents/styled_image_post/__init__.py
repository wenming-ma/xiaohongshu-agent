"""XHS Styled Image Post Pipeline - 小红书图文帖子流水线（支持参考图片指定推荐物品样式）"""

from .pipeline import StyledImagePostPipeline
from .schemas import StyledImagePostInput, StyledImagePostOutput

__all__ = ["StyledImagePostPipeline", "StyledImagePostInput", "StyledImagePostOutput"]
