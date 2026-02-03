from ....core.base_tool import BasePlatformTool
from ....core.tool_registry import ToolRegistry
from .schemas import XHSVideoPostInput, XHSVideoPostOutput


@ToolRegistry.register
class XHSVideoPostTool(BasePlatformTool[XHSVideoPostInput, XHSVideoPostOutput]):
    name = "xiaohongshu_video_post"
    description = "创建并发布小红书视频帖子。根据主题生成视频内容并发布到小红书平台。"
    platform = "xiaohongshu"
    content_type = "video_post"
    input_schema = XHSVideoPostInput
    output_schema = XHSVideoPostOutput

    async def execute(self, input_data: XHSVideoPostInput) -> XHSVideoPostOutput:
        # TODO: 实现视频帖子工作流
        raise NotImplementedError("视频帖子工具尚未实现")
