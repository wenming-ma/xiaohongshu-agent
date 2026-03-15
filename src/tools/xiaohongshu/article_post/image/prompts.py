"""Prompts for article image generation."""

from .....utils.prompting import render_template

IMAGE_SYSTEM_PROMPT = """你是一位中文内容配图策划师，负责为小红书长文生成简洁、高信息密度的配图提示词。

要求：
1. 图片风格适合小红书长文，不要出现英文长句。
2. 头图突出标题和情绪，章节图突出信息层次。
3. 避免复杂摄影描述，优先信息视觉化。
4. 输出只是一段用于生成图片的中文提示词。
"""

IMAGE_USER_PROMPT_TEMPLATE = """主题: {topic}
文章标题: {title}
图片类型: {label}
图片位置: {image_key}

上下文:
{context_text}
"""


def image_system_prompt(**variables: object) -> str:
    return render_template(IMAGE_SYSTEM_PROMPT, **variables)


def image_user_prompt(**variables: object) -> str:
    return render_template(IMAGE_USER_PROMPT_TEMPLATE, **variables)
