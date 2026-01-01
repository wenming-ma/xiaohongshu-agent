"""
图片生成 Agent
使用 Gemini 网页生成小红书配图
通过 Playwright MCP 操作 Gemini 网页

所有提示词统一在 prompts/image.yaml 管理
"""
import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from ..models.schemas import ImageResult, GeneratedImage, XHSContent, ResearchResult
from ..utils.anthropic_provider import get_anthropic_model
from ..utils.download_manager import DownloadManager
from .image_review import ImageReviewAgent
from prompts import get_system_prompt, get_user_prompt, get_prompt_field


class ImageAgent:
    """Gemini 图片生成 Agent"""

    # 图片类型配置
    IMAGE_TYPES = [
        {"type": "cover", "desc": "封面图 - 大标题风格，突出主题"},
        {"type": "detail_1", "desc": "详情图1 - 清单式，列出前半部分要点"},
        {"type": "detail_2", "desc": "详情图2 - 清单式，列出后半部分要点"},
    ]

    def __init__(
        self,
        image_count: int = 3,
        max_iterations: int = 3
    ):
        """
        初始化图片生成 Agent

        Args:
            image_count: 生成图片数量（1-3张，默认3张）
            max_iterations: 审核不通过时的最大重试次数（默认3次）
        """
        self.image_count = min(max(image_count, 1), 3)  # 限制 1-3 张
        self.max_iterations = max_iterations

        # 获取带 HTTP 重试的 Model（max_retries=5）
        model = get_anthropic_model()

        # 创建 Playwright MCP Server 实例（用于操作 Gemini）
        self.mcp_server = MCPServerStdio(
            command='npx',
            args=['-y', '@playwright/mcp'],
            env={
                'HEADLESS': 'false',  # 显示浏览器窗口（方便登录和调试）
                'BROWSER_TYPE': 'chromium',
                'USER_DATA_DIR': './browser-sessions/gemini'  # 保存 Gemini 登录态
            },
            tool_prefix='playwright',
            cache_tools=True,
            max_retries=5,
        )

        # 提示词生成 Agent（生成 Gemini 图片描述）
        # 系统提示词从 prompts/image.yaml 的 system_prompt 读取
        self.prompt_generator = Agent(
            model=model,
            output_type=str,
            instrument=True,
            system_prompt=(get_system_prompt("image"),),
        )

        # Gemini 操作 Agent（使用 Playwright 工具）
        # 系统提示词从 prompts/image.yaml 的 gemini_operator_prompt 读取
        self.gemini_operator = Agent(
            model=model,
            output_type=str,
            toolsets=[self.mcp_server],
            instrument=True,
            retries=3,
            system_prompt=(get_prompt_field("image", "gemini_operator_prompt"),),
        )

        # Gemini URL
        self.gemini_url = "https://gemini.google.com/app"

        # 图片审核 Agent（独立，也使用共享 Provider）
        self.reviewer = ImageReviewAgent()

        # 下载文件管理器（处理浏览器下载的文件）
        self.download_manager = DownloadManager()

    async def generate_image(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        output_dir: Path
    ) -> ImageResult:
        """
        生成配图（带审核循环，只重新生成失败的图片）

        Args:
            content: 内容数据
            research: 研究数据
            topic: 主题
            output_dir: 输出目录

        Returns:
            ImageResult: 图片结果（包含多张图片）
        """
        print(f"   🎨 开始生成 {self.image_count} 张配图（最多重试 {self.max_iterations} 次）...")

        # 存储已生成的图片 {image_type: GeneratedImage}
        generated_images: Dict[str, GeneratedImage] = {}

        # 待生成的图片类型
        pending_types = [t["type"] for t in self.IMAGE_TYPES[:self.image_count]]

        for iteration in range(self.max_iterations):
            if not pending_types:
                break

            print(f"\n   🔄 第 {iteration + 1} 次生成（待生成: {pending_types}）")

            # 1. 生成待处理的图片
            for image_type in pending_types:
                image_type_info = next(t for t in self.IMAGE_TYPES if t["type"] == image_type)
                image_desc = image_type_info["desc"]

                print(f"\n      [{image_type}] {image_desc}")

                # 生成 Gemini 提示词
                print(f"         📝 生成图片描述提示词...")
                prompt = await self._generate_prompt(content, topic, image_type, image_desc)
                print(f"         ✅ 提示词: {prompt[:60]}...")

                # 使用 Playwright 操作 Gemini 生成图片
                print(f"         🌐 启动 Gemini 图片生成...")
                image_path = await self._generate_via_gemini(prompt, output_dir, image_type)

                generated_images[image_type] = GeneratedImage(
                    image_path=str(image_path),
                    prompt_used=prompt,
                    image_type=image_type
                )

                print(f"         ✅ {image_type} 生成完成")

            # 2. 审核所有图片
            all_images = list(generated_images.values())
            review = await self.reviewer.review(all_images, topic, self.image_count)

            # 3. 检查是否通过
            if review.passed:
                print(f"\n   ✅ 图片审核通过（评分: {review.score:.1f}）")
                return ImageResult(
                    images=all_images,
                    total_count=len(all_images),
                    generated_at=datetime.now().isoformat()
                )

            # 4. 未通过，找出有问题的图片类型
            print(f"\n   ⚠️ 审核未通过（评分: {review.score:.1f}）")
            for issue in review.issues:
                print(f"      - [{issue.severity}] {issue.image_type}: {issue.description}")

            # 5. 获取需要重新生成的图片类型
            pending_types = self.reviewer.get_failed_image_types(review)

            if not pending_types:
                # 没有明确失败的图片，但审核未通过（可能是 warning 级别问题）
                # 不再重试，接受当前结果
                print(f"\n   ℹ️ 无 critical 问题，接受当前结果")
                break

            print(f"\n   🔄 将重新生成: {pending_types}")

        # 达到最大次数或无需重试，返回最终结果
        all_images = list(generated_images.values())
        return ImageResult(
            images=all_images,
            total_count=len(all_images),
            generated_at=datetime.now().isoformat()
        )

    async def _generate_prompt(
        self,
        content: XHSContent,
        topic: str,
        image_type: str = "cover",
        image_desc: str = ""
    ) -> str:
        """
        生成 Gemini 图片提示词

        Args:
            content: 内容数据
            topic: 主题
            image_type: 图片类型 (cover/detail_1/detail_2)
            image_desc: 图片描述
        """
        # 根据图片类型调整正文摘要
        body_text = content.body
        if image_type == "cover":
            # 封面图只需要标题和主题
            body_excerpt = body_text[:150]
        elif image_type == "detail_1":
            # 详情图1取前半部分
            mid = len(body_text) // 2
            body_excerpt = body_text[:mid]
        else:
            # 详情图2取后半部分
            mid = len(body_text) // 2
            body_excerpt = body_text[mid:]

        # 从 YAML 读取用户提示词模板并填充变量
        user_prompt = get_user_prompt(
            "image",
            topic=topic,
            content_title=content.title,
            content_body=body_excerpt[:300],
            image_type=image_type,
            image_desc=image_desc
        )

        result = await self.prompt_generator.run(user_prompt)
        return result.output

    async def _generate_via_gemini(
        self,
        prompt: str,
        output_dir: Path,
        image_type: str = "cover"
    ) -> Path:
        """
        通过 Gemini 网页生成图片

        Args:
            prompt: 图片描述提示词
            output_dir: 输出目录
            image_type: 图片类型

        Returns:
            Path: 图片保存路径
        """
        # 记录开始时间（用于筛选新下载的文件）
        start_time = time.time()

        # 从 YAML 读取操作提示词模板并填充变量
        operation_prompt = get_prompt_field(
            "image",
            "gemini_operation_template",
            prompt=prompt
        )

        # 运行 Gemini 操作 Agent
        result = await self.gemini_operator.run(operation_prompt)

        # 检查 Agent 执行状态
        if "SUCCESS" in result.output or "成功" in result.output:
            print(f"         ✅ Gemini 操作成功")
        else:
            print(f"         ⚠️ Gemini 操作状态: {result.output}")

        # 等待下载完成并移动文件到目标目录
        try:
            image_path = self.download_manager.wait_and_move(
                target_dir=output_dir,
                target_name=image_type,
                file_pattern="*.png",
                timeout=60,
                before_time=start_time
            )
            print(f"         ✅ 图片已保存: {image_path}")
        except (TimeoutError, FileNotFoundError) as e:
            print(f"         ⚠️ 文件处理失败: {e}")
            # 返回期望路径（审核时会检测到缺失）
            image_path = output_dir / f"{image_type}.png"

        return image_path

    async def list_tools(self) -> None:
        """列出所有可用的 MCP 工具（用于验证）"""
        print("\n   🔧 正在检查 Gemini 操作工具...")

        try:
            async with self.mcp_server as server:
                tools = await server.list_tools()
                print(f"\n   📋 发现 {len(tools)} 个 Playwright MCP 工具")
                for tool in tools[:5]:  # 只显示前5个
                    tool_name = f"{self.mcp_server.tool_prefix}_{tool.name}" if self.mcp_server.tool_prefix else tool.name
                    print(f"      ✅ {tool_name}")
        except Exception as e:
            print(f"   ⚠️ 无法列出工具: {e}")
