"""
图片生成工具
支持多种图片生成服务：OpenRouter (DALL-E 3), DALL-E 3, Gemini
"""
import os
import base64
from pathlib import Path
from typing import List, Literal
import aiohttp
from openai import AsyncOpenAI
from config import (
    OPENAI_API_KEY,
    GOOGLE_API_KEY,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_IMAGE_MODEL,
    OPENROUTER_SITE_URL,
    OPENROUTER_SITE_NAME
)


ImageProvider = Literal["openrouter", "dalle3", "gemini", "stable-diffusion"]


class ImageGenerator:
    """图片生成器基类"""

    def __init__(self, provider: ImageProvider = "dalle3"):
        """
        初始化图片生成器

        Args:
            provider: 图片生成服务提供商
        """
        self.provider = provider

    async def generate(
        self,
        prompt: str,
        output_path: str,
        size: str = "1024x1024",
        quality: str = "standard"
    ) -> str:
        """
        生成图片

        Args:
            prompt: 图片描述（越详细越好）
            output_path: 输出文件路径
            size: 图片尺寸
            quality: 图片质量

        Returns:
            生成的图片路径
        """
        raise NotImplementedError


class OpenRouterImageGenerator(ImageGenerator):
    """OpenRouter 图片生成器（支持多种模型）"""

    def __init__(self):
        super().__init__(provider="openrouter")
        if not OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY not set")

        # 使用 OpenAI SDK 但指向 OpenRouter 端点
        self.client = AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=OPENROUTER_API_KEY
        )
        self.model = OPENROUTER_IMAGE_MODEL
        self.site_url = OPENROUTER_SITE_URL
        self.site_name = OPENROUTER_SITE_NAME

    async def generate(
        self,
        prompt: str,
        output_path: str,
        size: str = "1024x1024",
        quality: str = "standard"
    ) -> str:
        """
        使用 OpenRouter 生成图片

        Args:
            prompt: 图片描述
            output_path: 输出路径
            size: 尺寸 (1024x1024, 1024x1792, 1792x1024)
            quality: 质量 (standard, hd)

        Returns:
            生成的图片路径
        """
        print(f"🎨 使用 OpenRouter ({self.model}) 生成图片...")
        print(f"   描述: {prompt[:100]}...")

        try:
            # 构建请求参数
            extra_headers = {}
            if self.site_url:
                extra_headers["HTTP-Referer"] = self.site_url
            if self.site_name:
                extra_headers["X-Title"] = self.site_name

            # 调用 OpenRouter API（使用 images.generate 接口）
            response = await self.client.images.generate(
                model=self.model,
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
                extra_headers=extra_headers if extra_headers else None
            )

            # 获取图片URL
            image_url = response.data[0].url

            # 下载图片
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        # 确保目录存在
                        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

                        # 保存图片
                        with open(output_path, 'wb') as f:
                            f.write(await resp.read())

                        print(f"   ✅ 图片已保存: {output_path}")
                        return output_path
                    else:
                        raise RuntimeError(f"Failed to download image: {resp.status}")

        except Exception as e:
            print(f"   ❌ 图片生成失败: {str(e)}")
            raise


class DALLE3Generator(ImageGenerator):
    """DALL-E 3 图片生成器"""

    def __init__(self):
        super().__init__(provider="dalle3")
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set")
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    async def generate(
        self,
        prompt: str,
        output_path: str,
        size: str = "1024x1024",
        quality: str = "standard"
    ) -> str:
        """
        使用 DALL-E 3 生成图片

        Args:
            prompt: 图片描述
            output_path: 输出路径
            size: 尺寸 (1024x1024, 1024x1792, 1792x1024)
            quality: 质量 (standard, hd)

        Returns:
            生成的图片路径
        """
        print(f"🎨 使用 DALL-E 3 生成图片...")
        print(f"   描述: {prompt[:100]}...")

        try:
            # 调用 DALL-E 3 API
            response = await self.client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                quality=quality,
                n=1
            )

            # 获取图片URL
            image_url = response.data[0].url

            # 下载图片
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        # 确保目录存在
                        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

                        # 保存图片
                        with open(output_path, 'wb') as f:
                            f.write(await resp.read())

                        print(f"   ✅ 图片已保存: {output_path}")
                        return output_path
                    else:
                        raise RuntimeError(f"Failed to download image: {resp.status}")

        except Exception as e:
            print(f"   ❌ 图片生成失败: {str(e)}")
            raise


class GeminiImageGenerator(ImageGenerator):
    """Gemini 图片生成器（使用 Imagen）"""

    def __init__(self):
        super().__init__(provider="gemini")
        if not GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not set")
        self.api_key = GOOGLE_API_KEY

    async def generate(
        self,
        prompt: str,
        output_path: str,
        size: str = "1024x1024",
        quality: str = "standard"
    ) -> str:
        """
        使用 Gemini Imagen 生成图片

        注意：需要 Google Cloud 项目和 Imagen API 访问权限

        Args:
            prompt: 图片描述
            output_path: 输出路径
            size: 尺寸
            quality: 质量

        Returns:
            生成的图片路径
        """
        print(f"🎨 使用 Gemini Imagen 生成图片...")
        print(f"   ⚠️  Gemini 图片生成需要 Google Cloud 配置")

        # TODO: 实现 Gemini Imagen API 调用
        # 这需要 Google Cloud 项目和特定的 API 配置
        raise NotImplementedError(
            "Gemini image generation requires Google Cloud setup. "
            "Please use DALL-E 3 instead or configure Google Cloud."
        )


class ImageGenerationService:
    """图片生成服务 - 统一接口"""

    def __init__(self, provider: ImageProvider = "openrouter"):
        """
        初始化图片生成服务

        Args:
            provider: 优先使用的提供商
        """
        self.provider = provider
        self.generator = self._create_generator(provider)

    def _create_generator(self, provider: ImageProvider) -> ImageGenerator:
        """创建图片生成器实例"""
        if provider == "openrouter":
            return OpenRouterImageGenerator()
        elif provider == "dalle3":
            return DALLE3Generator()
        elif provider == "gemini":
            return GeminiImageGenerator()
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    async def generate_multiple(
        self,
        prompts: List[str],
        output_paths: List[str],
        size: str = "1024x1024"
    ) -> List[str]:
        """
        批量生成多张图片

        Args:
            prompts: 图片描述列表
            output_paths: 输出路径列表
            size: 图片尺寸

        Returns:
            生成的图片路径列表
        """
        if len(prompts) != len(output_paths):
            raise ValueError("Prompts and output_paths must have same length")

        results = []
        for idx, (prompt, output_path) in enumerate(zip(prompts, output_paths)):
            print(f"\n📸 生成图片 {idx + 1}/{len(prompts)}")
            try:
                result_path = await self.generator.generate(
                    prompt=prompt,
                    output_path=output_path,
                    size=size
                )
                results.append(result_path)
            except Exception as e:
                print(f"❌ 图片 {idx + 1} 生成失败: {str(e)}")
                # 创建占位符或抛出异常
                results.append(None)

        return results

    async def generate_xiaohongshu_images(
        self,
        image_descriptions: List[str],
        output_dir: Path | str,
        filenames: List[str] = None
    ) -> List[str]:
        """
        为小红书生成图片（优化提示词）

        Args:
            image_descriptions: 图片描述列表
            output_dir: 输出目录
            filenames: 文件名列表（默认: cover.png, image-1.png, image-2.png）

        Returns:
            生成的图片路径列表
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 默认文件名
        if filenames is None:
            filenames = ["cover.png", "image-1.png", "image-2.png"]

        # 优化提示词（添加小红书风格）
        enhanced_prompts = []
        for desc in image_descriptions:
            enhanced_prompt = (
                f"Create a trendy, eye-catching social media post image in Xiaohongshu (Little Red Book) style. "
                f"{desc} "
                f"The image should be visually appealing, colorful, and perfect for social media. "
                f"Include clean typography if there's text mentioned."
            )
            enhanced_prompts.append(enhanced_prompt)

        # 生成输出路径
        output_paths = [str(output_dir / filename) for filename in filenames]

        # 批量生成
        return await self.generate_multiple(
            prompts=enhanced_prompts,
            output_paths=output_paths,
            size="1024x1024"  # 小红书推荐尺寸
        )


async def test_image_generation():
    """测试图片生成"""
    service = ImageGenerationService(provider="openrouter")

    test_prompts = [
        "A vibrant social media post with the text '避坑指南' in bold Chinese characters, "
        "colorful gradient background (#FFE5F0 to #FFC0CB), modern minimalist design, "
        "with small icons of warning signs and checkmarks",

        "An infographic-style image showing a list of company names with ratings, "
        "clean layout, using soft pastel colors, professional yet friendly design",

        "A conclusion card with the text '记得点赞收藏哦~' in cute handwritten font, "
        "surrounded by small hearts and star emojis, warm pink background"
    ]

    output_dir = Path("test_images")
    filenames = ["test_cover.png", "test_1.png", "test_2.png"]

    results = await service.generate_xiaohongshu_images(
        image_descriptions=test_prompts,
        output_dir=output_dir,
        filenames=filenames
    )

    print(f"\n✅ 测试完成！生成了 {len([r for r in results if r])} 张图片")
    for path in results:
        if path:
            print(f"   📁 {path}")


if __name__ == "__main__":
    import asyncio
    print("=== 图片生成测试 ===\n")
    asyncio.run(test_image_generation())
