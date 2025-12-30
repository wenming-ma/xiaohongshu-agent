"""
Phase 3: 图片生成节点
使用 OpenRouter (DALL-E 3) 生成高质量图片
"""
from datetime import datetime
from pathlib import Path

from ..state import XHSState
from ..tools.image_generation import ImageGenerationService


async def generate_images_node(state: XHSState) -> dict:
    """
    图片生成节点 - 使用 OpenRouter (DALL-E 3) 生成图片

    Args:
        state: 当前工作流状态

    Returns:
        更新后的状态字段（images, images_generated）
    """
    content = state.get("content", {})
    image_descriptions = content.get("image_descriptions", [])
    project_dir = Path(state["project_dir"])
    images_dir = project_dir / "images"

    if not image_descriptions:
        error_msg = "No image descriptions found in content"
        return {
            "images": [],
            "images_generated": False,
            "errors": [error_msg],
            "logs": [f"[{datetime.now().isoformat()}] ❌ {error_msg}"]
        }

    try:
        # 创建图片生成服务（使用 OpenRouter）
        service = ImageGenerationService(provider="openrouter")

        # 定义文件名
        filenames = ["cover.png", "image-1.png", "image-2.png"][:len(image_descriptions)]

        # 生成图片
        print(f"\n🎨 开始生成 {len(image_descriptions)} 张图片...")
        image_paths = await service.generate_xiaohongshu_images(
            image_descriptions=image_descriptions,
            output_dir=images_dir,
            filenames=filenames
        )

        # 过滤掉失败的图片
        successful_images = [path for path in image_paths if path is not None]

        if not successful_images:
            error_msg = "All images failed to generate"
            return {
                "images": [],
                "images_generated": False,
                "errors": [error_msg],
                "logs": [f"[{datetime.now().isoformat()}] ❌ {error_msg}"]
            }

        # 记录日志
        log_message = f"[{datetime.now().isoformat()}] Images generated: {len(successful_images)}/{len(image_descriptions)} successful"

        return {
            "images": successful_images,
            "images_generated": True,
            "current_phase": "publish",
            "logs": [log_message, f"✅ 成功生成 {len(successful_images)} 张图片"]
        }

    except Exception as e:
        error_msg = f"Image generation error: {str(e)}"
        return {
            "images": [],
            "images_generated": False,
            "errors": [error_msg],
            "logs": [f"[{datetime.now().isoformat()}] ❌ {error_msg}"]
        }
