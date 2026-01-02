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
from typing import List, Dict, Optional
from pydantic_ai import Agent, Tool
from pydantic_ai.mcp import MCPServerStdio
from ..models.schemas import ImageResult, GeneratedImage, XHSContent, ResearchResult
from ..utils.anthropic_provider import get_anthropic_model
from ..utils.download_manager import DownloadManager
from ..utils.retry_handler import with_retry
from ..config.settings import RetryConfig, ReviewConfig, ImageConfig, PathConfig, TimeoutConfig, APIConfig
from .image_review import ImageReviewAgent
from prompts import get_system_prompt, get_user_prompt, get_prompt_field


class ImageAgent:
    """Gemini 图片生成 Agent"""

    def __init__(
        self,
        max_iterations: int = None
    ):
        """
        初始化图片生成 Agent

        Args:
            max_iterations: 审核不通过时的最大重试次数，默认使用配置
        """
        self.max_iterations = max_iterations or ReviewConfig.MAX_ITERATIONS

        # 获取带 HTTP 重试的 Model（max_retries=5）
        model = get_anthropic_model()

        # Playwright 下载输出目录
        self.downloads_dir = PathConfig.DOWNLOADS_DIR
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

        # 记录操作开始时间（用于筛选新下载的文件）
        self._operation_start_time: Optional[float] = None

        # 创建 Playwright MCP Server 实例（用于操作 Gemini）
        self.mcp_server = MCPServerStdio(
            command='npx',
            args=[
                '-y', '@playwright/mcp',
                '--output-dir', str(self.downloads_dir)  # 指定下载目录
            ],
            env={
                'HEADLESS': 'false',  # 显示浏览器窗口（方便登录和调试）
                'BROWSER_TYPE': 'chromium',
                'USER_DATA_DIR': PathConfig.BROWSER_SESSION_GEMINI
            },
            tool_prefix='playwright',
            cache_tools=True,
            max_retries=RetryConfig.MCP_RETRIES,
        )

        # 提示词生成 Agent（生成 Gemini 图片描述）
        # 系统提示词从 prompts/image.yaml 的 system_prompt 读取
        self.prompt_generator = Agent(
            model=model,
            output_type=str,
            instrument=True,
            system_prompt=(get_system_prompt("image"),),
        )

        # 创建检查下载的工具
        def check_download_status() -> str:
            """
            检查下载目录是否有新的 PNG 图片文件。
            在点击下载按钮后调用此工具确认下载是否完成。
            返回: "DOWNLOADED: 文件名" 表示下载成功，"NOT_FOUND" 表示未找到新文件。
            """
            if self._operation_start_time is None:
                return "NOT_FOUND: 操作未开始"

            # 查找新下载的 PNG 文件
            for f in self.downloads_dir.glob("*.png"):
                if f.stat().st_mtime > self._operation_start_time:
                    # 检查文件是否完整（不是临时文件）
                    if not f.suffix.endswith(('.crdownload', '.tmp', '.part')):
                        return f"DOWNLOADED: {f.name} ({f.stat().st_size / 1024:.0f}KB)"

            return "NOT_FOUND: 下载目录中没有新文件"

        # Gemini 操作 Agent（使用 Playwright 工具 + 下载检查工具）
        # 系统提示词从 prompts/image.yaml 的 gemini_operator_prompt 读取
        self.gemini_operator = Agent(
            model=model,
            output_type=str,
            toolsets=[self.mcp_server],
            tools=[Tool(check_download_status, takes_ctx=False)],
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(get_prompt_field("image", "gemini_operator_prompt"),),
        )

        # Gemini URL
        self.gemini_url = APIConfig.GEMINI_URL

        # 图片审核 Agent（独立，也使用共享 Provider）
        self.reviewer = ImageReviewAgent()

        # 下载文件管理器（监控 Playwright 输出目录）
        self.download_manager = DownloadManager(download_dir=self.downloads_dir)

    def _get_image_types(self, research: ResearchResult) -> List[Dict]:
        """
        根据研究数据动态计算需要的图片类型

        Args:
            research: 研究结果（包含 entities 列表）

        Returns:
            图片类型列表，如 [cover, detail_1, detail_2, detail_3, ...]
        """
        # 1. 封面图（固定 1 张）
        types = [{"type": "cover", "desc": "封面图 - 大标题风格，突出主题"}]

        # 2. 计算详情图数量
        entity_count = len(research.entities)
        if entity_count == 0:
            # 没有实体时至少生成 1 张详情图
            detail_count = ImageConfig.MIN_DETAIL_IMAGES
        else:
            # 向上取整：(entity_count + per - 1) // per
            detail_count = max(
                ImageConfig.MIN_DETAIL_IMAGES,
                min(
                    ImageConfig.MAX_DETAIL_IMAGES,
                    (entity_count + ImageConfig.ENTITIES_PER_DETAIL - 1) // ImageConfig.ENTITIES_PER_DETAIL
                )
            )

        # 3. 生成详情图类型
        for i in range(1, detail_count + 1):
            start = (i - 1) * ImageConfig.ENTITIES_PER_DETAIL
            end = min(i * ImageConfig.ENTITIES_PER_DETAIL, entity_count)
            types.append({
                "type": f"detail_{i}",
                "desc": f"详情图{i} - 清单式，显示第 {start + 1}-{end} 个实体",
                "entity_start": start,  # 0-based index
                "entity_end": end
            })

        return types

    @with_retry(max_retries=RetryConfig.MAX_RETRIES, initial_delay=RetryConfig.INITIAL_DELAY)
    async def generate_image(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        output_dir: Path
    ) -> ImageResult:
        """
        生成配图（带审核循环 + 外层重试）

        Args:
            content: 内容数据
            research: 研究数据
            topic: 主题
            output_dir: 输出目录

        Returns:
            ImageResult: 图片结果（包含多张图片）
        """
        # 动态计算图片类型
        image_types = self._get_image_types(research)
        entity_count = len(research.entities)

        print(f"   🎨 开始生成 {len(image_types)} 张配图（{entity_count} 个实体，最多重试 {self.max_iterations} 次）...")

        # 存储已生成的图片 {image_type: GeneratedImage}
        generated_images: Dict[str, GeneratedImage] = {}

        # 待生成的图片类型
        pending_types = [t["type"] for t in image_types]

        for iteration in range(self.max_iterations):
            if not pending_types:
                break

            print(f"\n   🔄 第 {iteration + 1} 次生成（待生成: {pending_types}）")

            # 1. 生成待处理的图片
            for image_type in pending_types:
                image_type_info = next(t for t in image_types if t["type"] == image_type)
                image_desc = image_type_info["desc"]

                print(f"\n      [{image_type}] {image_desc}")

                # 生成 Gemini 提示词（传入实体分配信息）
                print(f"         📝 生成图片描述提示词...")
                prompt = await self._generate_prompt(content, research, topic, image_type_info)
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
            review = await self.reviewer.review(all_images, topic, len(image_types))

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
        research: ResearchResult,
        topic: str,
        image_type_info: Dict
    ) -> str:
        """
        生成 Gemini 图片提示词（带实体分配信息）

        Args:
            content: 内容数据
            research: 研究数据（包含 entities 列表）
            topic: 主题
            image_type_info: 图片类型信息（包含 type, desc, entity_start, entity_end）
        """
        image_type = image_type_info["type"]
        image_desc = image_type_info["desc"]

        if image_type == "cover":
            # 封面图：只需标题和主题
            body_excerpt = content.body[:150]
        else:
            # 详情图：提取对应的实体
            start = image_type_info.get("entity_start", 0)
            end = image_type_info.get("entity_end", len(research.entities))
            entities = research.entities[start:end]

            if entities:
                # 构建实体信息列表
                entities_info = "\n".join([
                    f"{i+1}. {e.get('name', '未知')}: {e.get('description', e.get('issue', ''))}"
                    for i, e in enumerate(entities)
                ])
                body_excerpt = f"本图需要展示以下 {len(entities)} 个实体：\n{entities_info}"
            else:
                # 无实体时使用正文
                body_excerpt = content.body[:300]

        # 从 YAML 读取用户提示词模板并填充变量
        user_prompt = get_user_prompt(
            "image",
            topic=topic,
            content_title=content.title,
            content_body=body_excerpt,
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
        self._operation_start_time = start_time  # 供 check_download_status 工具使用

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
        # 如果超时或找不到文件，让异常抛出，由 @with_retry 重试整个流程
        image_path = self.download_manager.wait_and_move(
            target_dir=output_dir,
            target_name=image_type,
            file_pattern="*.png",
            timeout=TimeoutConfig.GEMINI_WAIT,
            before_time=start_time
        )
        print(f"         ✅ 图片已保存: {image_path}")

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
