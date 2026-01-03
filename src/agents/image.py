"""
图片生成 Agent
使用 Gemini 网页生成小红书配图
通过 Playwright MCP 操作 Gemini 网页

所有提示词统一在 prompts/image.yaml 管理

验证机制（通过类装饰器实现）：
- @GeminiConfigValidator: 每张图片生成后验证 Gemini 配置（Create images + Pro）
- @ImageQualityValidator: 验证图片质量（字迹清晰、风格匹配）
"""
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from pydantic_ai import Agent, Tool
from ..mcp import AutoScreenshotMCPServer
from ..models.schemas import ImageResult, GeneratedImage, XHSContent, ResearchResult
from ..utils.anthropic_provider import get_anthropic_model
from ..utils.download_manager import DownloadManager
from ..utils.retry_handler import with_retry
from ..validators import GeminiConfigValidator, ImageQualityValidator
from ..config.settings import RetryConfig, ImageConfig, PathConfig, TimeoutConfig, APIConfig
from prompts import get_system_prompt, get_user_prompt, get_prompt_field


class ImageAgent:
    """Gemini 图片生成 Agent"""

    def __init__(self):
        """初始化图片生成 Agent"""
        # ==================== 1. 配置参数 ====================
        self.gemini_url = APIConfig.GEMINI_URL

        # ==================== 2. 路径配置 ====================
        self.downloads_dir = PathConfig.DOWNLOADS_DIR
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

        # ==================== 3. 内部状态 ====================
        self._operation_start_time: Optional[float] = None
        self._last_gemini_screenshot: Optional[Path] = None

        # ==================== 4. 工具/管理器 ====================
        self.download_manager = DownloadManager(download_dir=self.downloads_dir)

        # ==================== 5. MCP Server ====================
        # Playwright MCP - 在所有图片生成完成后自动截屏（类似 C++ 析构函数）
        # 注：每张图片的验证截屏由 @GeminiConfigValidator 装饰器处理
        self.mcp_server = AutoScreenshotMCPServer(
            command='npx',
            args=['-y', '@playwright/mcp', '--output-dir', str(self.downloads_dir)],
            env={
                'HEADLESS': 'false',
                'BROWSER_TYPE': 'chromium',
                'USER_DATA_DIR': PathConfig.BROWSER_SESSION_GEMINI
            },
            tool_prefix='playwright',
            cache_tools=True,
            max_retries=RetryConfig.MCP_RETRIES,
            screenshot_dir=self.downloads_dir,
            screenshot_callback=self._on_auto_screenshot,
            auto_screenshot=ImageConfig.AUTO_SCREENSHOT_ENABLED,
        )

        # ==================== 6. Agents ====================
        model = get_anthropic_model()

        # 提示词生成 Agent
        self.prompt_generator = Agent(
            model=model,
            output_type=str,
            instrument=True,
            system_prompt=(get_system_prompt("image"),),
        )

        # Gemini 操作 Agent
        self.gemini_operator = Agent(
            model=model,
            output_type=str,
            toolsets=[self.mcp_server],
            tools=[Tool(self._check_download_status, takes_ctx=False)],
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(get_prompt_field("image", "gemini_operator_prompt"),),
        )

    # ==================== 工具方法 ====================

    def _check_download_status(self) -> str:
        """
        检查下载目录是否有新的 PNG 图片文件。
        在点击下载按钮后调用此工具确认下载是否完成。

        Returns:
            "DOWNLOADED: 文件名" 表示下载成功
            "NOT_FOUND" 表示未找到新文件
        """
        if self._operation_start_time is None:
            return "NOT_FOUND: 操作未开始"

        for f in self.downloads_dir.glob("*.png"):
            if f.stat().st_mtime > self._operation_start_time:
                if not f.suffix.endswith(('.crdownload', '.tmp', '.part')):
                    return f"DOWNLOADED: {f.name} ({f.stat().st_size / 1024:.0f}KB)"

        return "NOT_FOUND: 下载目录中没有新文件"

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

    async def generate_image(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        output_dir: Path
    ) -> ImageResult:
        """
        生成配图（每张图片即时验证）

        使用 async with self.mcp_server 保持浏览器会话，
        每张图片生成后立即验证，验证失败自动重试单张图片。

        验证机制（通过类装饰器实现）：
        - @GeminiConfigValidator: 验证 Create images + Pro 模式
        - @ImageQualityValidator: 验证字迹清晰度和风格

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

        print(f"   🎨 开始生成 {len(image_types)} 张配图（{entity_count} 个实体）...")

        # 存储已生成的图片
        generated_images: List[GeneratedImage] = []

        # 使用 MCP Server 上下文保持浏览器会话
        # 浏览器在所有图片生成完成后才关闭
        # AutoScreenshotMCPServer 会在退出时自动截屏
        async with self.mcp_server:
            for image_type_info in image_types:
                image_type = image_type_info["type"]
                image_desc = image_type_info["desc"]

                print(f"\n      [{image_type}] {image_desc}")

                # 生成 Gemini 提示词（传入实体分配信息）
                print(f"         📝 生成图片描述提示词...")
                prompt = await self._generate_prompt(content, research, topic, image_type_info)
                print(f"         ✅ 提示词: {prompt[:60]}...")

                # 使用 Playwright 操作 Gemini 生成图片
                # 验证由 @GeminiConfigValidator 和 @ImageQualityValidator 装饰器处理
                print(f"         🌐 启动 Gemini 图片生成...")
                image_path = await self._generate_via_gemini(
                    prompt=prompt,
                    output_dir=output_dir,
                    image_type=image_type,
                    topic=topic  # 传递 topic 用于质量验证
                )

                generated_images.append(GeneratedImage(
                    image_path=str(image_path),
                    prompt_used=prompt,
                    image_type=image_type
                ))

                print(f"         ✅ {image_type} 生成并验证完成")

        # 所有图片生成完成，直接返回结果
        # 无需批量审核，每张图片已在生成时验证
        return ImageResult(
            images=generated_images,
            total_count=len(generated_images),
            generated_at=datetime.now().isoformat()
        )
        # <-- MCP Server 在这里退出，触发自动截屏并关闭浏览器

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

    @with_retry(max_retries=RetryConfig.MAX_RETRIES, initial_delay=RetryConfig.INITIAL_DELAY)
    @GeminiConfigValidator(max_retries=3, initial_delay=5.0)
    @ImageQualityValidator(max_retries=2, initial_delay=5.0)
    async def _generate_via_gemini(
        self,
        prompt: str,
        output_dir: Path,
        image_type: str = "cover",
        topic: str = ""
    ) -> Path:
        """
        通过 Gemini 网页生成图片（带重试和验证）

        三层重试机制（由装饰器处理）：
        1. @with_retry: 网络/API 错误重试
        2. @GeminiConfigValidator: 验证 Gemini 配置（Create images + Pro）
        3. @ImageQualityValidator: 验证图片质量（字迹清晰、风格匹配）

        失败时自动重试单张图片生成。

        Args:
            prompt: 图片描述提示词
            output_dir: 输出目录
            image_type: 图片类型
            topic: 主题（用于风格验证）

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
        # 截屏验证由装饰器 @GeminiConfigValidator 处理
        result = await self.gemini_operator.run(operation_prompt)

        # 检查 Agent 输出状态
        if "SUCCESS" in result.output or "成功" in result.output:
            print(f"         ✅ Gemini 操作成功")
        else:
            print(f"         ⚠️ Gemini 操作状态: {result.output}")

        # 等待下载完成并移动文件到目标目录
        # 如果超时或找不到文件，让异常抛出，由验证装饰器处理重试
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

    async def _on_auto_screenshot(self, screenshot_path: Path) -> None:
        """
        最终截屏完成后的回调

        在所有图片生成完成、MCP Server 退出前触发最终截屏。
        类似 C++ 析构函数的自动清理机制。

        注：每张图片的验证截屏由 @GeminiConfigValidator 装饰器处理。

        Args:
            screenshot_path: 截屏文件路径
        """
        # 保存最后一次截屏路径
        self._last_gemini_screenshot = screenshot_path
