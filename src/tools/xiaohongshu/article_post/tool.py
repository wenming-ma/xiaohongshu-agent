from ....core.base_tool import BasePlatformTool
from .schemas import XHSArticlePostInput, XHSArticlePostOutput


class XHSArticlePostTool(BasePlatformTool[XHSArticlePostInput, XHSArticlePostOutput]):
    name = "xiaohongshu_article_post"
    description = "创建并发布小红书文章。根据主题生成长文内容并发布到小红书平台。"
    platform = "xiaohongshu"
    content_type = "article_post"
    input_schema = XHSArticlePostInput
    output_schema = XHSArticlePostOutput

    async def execute(self, input_data: XHSArticlePostInput) -> XHSArticlePostOutput:
        # TODO: 实现文章工具工作流
        raise NotImplementedError("文章工具尚未实现")
