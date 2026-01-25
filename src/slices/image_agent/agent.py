"""
图片生成 Agent - ML 模型风格
使用 Gemini API 生成小红书配图

使用方式：
    agent = ImageAgent()
    result = await agent.forward(content, research, topic, output_dir)

通过 OpenAI 兼容 API 调用 Gemini 图片生成服务
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic_ai import Agent, RunContext

from ...models.schemas import (
    ImageResult,
    GeneratedImage,
    XHSContent,
    ResearchResult,
    ImageGroupingPlan,
    ImageGroupingReviewResult,
    ImageTypeSpec,
    ImageGenContext,
)
from ...utils.minimax_provider import get_minimax_model
from ...utils.logger import get_logger
from ...config.settings import RetryConfig
from .quality_validator import ImageQualityValidator
from .prompts import (
    image_system_prompt,
    image_user_prompt,
    image_grouping_system_prompt,
    image_grouping_review_system_prompt,
)
from .gemini_image_client import GeminiImageClient

# 从拆分的模块导入
from ._group_utils import (
    build_compact_items,
    calculate_grouping_params,
    groups_to_image_specs,
    run_grouping_with_review,
)

logger = get_logger(__name__)


class ImageAgent:
    """
    Gemini 图片生成 Agent（ML 模型风格）

    类似 PyTorch nn.Module 的设计：
    - __init__: 初始化所有组件
    - forward: 主执行入口

    使用方式：
        agent = ImageAgent()
        result = await agent.forward(content, research, topic, output_dir)
    """

    # ========================================================================
    # 初始化
    # ========================================================================

    def __init__(self):
        """初始化图片生成 Agent"""
        self._init_image_client()
        self._init_agents()

    def _init_image_client(self):
        """初始化 Gemini 图片 API 客户端"""
        self.image_client = GeminiImageClient()
        self.image_quality_validator = ImageQualityValidator(
            max_retries=RetryConfig.MAX_RETRIES,
            initial_delay=2.0
        )

    def _init_agents(self):
        """初始化所有 Agent"""
        model = get_minimax_model()

        # 提示词生成 Agent
        self.prompt_generator = Agent(
            model=model,
            output_type=str,
            deps_type=ImageGenContext,
            instrument=True,
        )

        # 注册动态 system_prompt
        @self.prompt_generator.system_prompt
        async def _dynamic_system_prompt(ctx: RunContext[ImageGenContext]) -> str:
            base_prompt = image_system_prompt()
            if ctx.deps.validation_feedback:
                return (
                    base_prompt +
                    "\n\n## 上次生成的图片问题（必须修复）\n"
                    f"{ctx.deps.validation_feedback}\n\n"
                    "请根据上述反馈调整提示词，确保生成的图片符合要求。"
                )
            return base_prompt

        # 语义分组 Agent
        self.grouping_agent = Agent(
            model=model,
            output_type=ImageGroupingPlan,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(image_grouping_system_prompt(),),
        )

        # 分组审核 Agent
        self.grouping_reviewer = Agent(
            model=get_minimax_model(),
            output_type=ImageGroupingReviewResult,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(image_grouping_review_system_prompt(),),
        )

    # ========================================================================
    # 主入口：forward
    # ========================================================================

    async def forward(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        output_dir: Path
    ) -> ImageResult:
        """
        生成配图（主入口）

        类似 PyTorch 的 forward 方法。

        流程：
        1. 计算分组参数
        2. 语义分组 + 审核循环
        3. 构建图片类型列表
        4. 逐张生成图片

        Args:
            content: 内容数据
            research: 研究数据
            topic: 主题
            output_dir: 输出目录

        Returns:
            ImageResult: 图片结果（包含多张图片）
        """
        item_count = len(research.items)

        # 1. 计算分组参数
        target_groups, target_group_size, max_group_size_cap = calculate_grouping_params(item_count)

        # 2. 构造 compact_items
        compact_items = build_compact_items(research.items or [])

        # 3. 语义分组 + 审核
        groups = await run_grouping_with_review(
            grouping_agent=self.grouping_agent,
            grouping_reviewer=self.grouping_reviewer,
            topic=topic,
            research=research,
            compact_items=compact_items,
            target_groups=target_groups,
            target_group_size=target_group_size,
            max_group_size_cap=max_group_size_cap,
        )

        # 4. 构建图片生成规格
        image_specs = groups_to_image_specs(groups)
        logger.info("开始生成 %d 张配图 (%d 个内容项)", len(image_specs), item_count)

        # 5. 生成图片
        generated_images = await self._generate_all_images(
            content=content,
            research=research,
            topic=topic,
            output_dir=output_dir,
            image_specs=image_specs,
        )

        return ImageResult(
            images=generated_images,
            total_count=len(generated_images),
            generated_at=datetime.now().isoformat()
        )

    # ========================================================================
    # 图片生成方法
    # ========================================================================

    async def _generate_all_images(
        self,
        *,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        output_dir: Path,
        image_specs: list[ImageTypeSpec],
    ) -> list[GeneratedImage]:
        """逐张生成图片"""
        generated_images: list[GeneratedImage] = []

        for spec in image_specs:
            image_type = spec["type"]
            image_desc = spec.get("desc", "")

            logger.info("[%s] %s", image_type, image_desc)

            gen_ctx = ImageGenContext(topic=topic, image_type=image_type)

            logger.info("启动 Gemini API 图片生成...")
            image_path, final_prompt = await self._generate_via_api(
                output_dir=output_dir,
                image_type=image_type,
                topic=topic,
                gen_ctx=gen_ctx,
                content=content,
                research=research,
                image_spec=spec,
            )

            generated_images.append(GeneratedImage(
                image_path=str(image_path),
                prompt_used=final_prompt,
                image_type=image_type
            ))

            logger.info("%s 生成完成", image_type)

        return generated_images

    async def _generate_prompt(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        image_spec: ImageTypeSpec,
        gen_ctx: ImageGenContext,
    ) -> str:
        """生成 Gemini 图片提示词"""
        image_type = image_spec["type"]
        image_desc = image_spec["desc"]

        if image_type == "cover":
            # cover 图：使用 content 的标题和正文
            body_excerpt = content.body
            title_for_prompt = content.title
        else:
            # detail 图：直接从 research + grouping 构建
            indices = image_spec.get("indices", [])
            items = [research.items[i] for i in indices if 0 <= i < len(research.items)]
            group_title = image_spec.get("group_title", "")

            if items:
                infos_text = "\n".join([
                    f"{i+1}. {item.title if hasattr(item, 'title') else item.get('title', '未知')}: {item.content if hasattr(item, 'content') else item.get('content', item.get('description', ''))}"
                    for i, item in enumerate(items)
                ])
                body_excerpt = f"本图主题板块：{group_title}\n本图需要展示以下 {len(items)} 个关键信息：\n{infos_text}"
            else:
                body_excerpt = f"本图主题板块：{group_title or topic}"

            # detail 图用 topic 代替 content.title，解耦 content 依赖
            title_for_prompt = topic

        user_prompt = image_user_prompt(
            topic=topic,
            content_title=title_for_prompt,
            content_body=body_excerpt,
            image_type=image_type,
            image_desc=image_desc,
        )

        if gen_ctx.validation_feedback:
            logger.info("根据验证反馈重新生成提示词: %s", gen_ctx.validation_feedback[:100])

        result = await self.prompt_generator.run(user_prompt, deps=gen_ctx)
        return result.output

    async def _generate_via_api(
        self,
        output_dir: Path,
        image_type: str,
        topic: str,
        gen_ctx: ImageGenContext,
        content: XHSContent,
        research: ResearchResult,
        image_spec: ImageTypeSpec,
        max_retries: int = RetryConfig.MAX_RETRIES,
    ) -> tuple[Path, str]:
        """
        通过 Gemini API 生成图片（带质量验证和重试）

        Args:
            output_dir: 输出目录
            image_type: 图片类型 (cover/detail_N)
            topic: 主题
            gen_ctx: 生成上下文
            content: 内容数据
            research: 研究数据
            image_spec: 图片规格
            max_retries: 最大重试次数

        Returns:
            (图片路径, 使用的提示词)
        """
        last_error: Optional[Exception] = None
        final_prompt = ""

        for attempt in range(max_retries):
            try:
                # 1. 生成提示词
                prompt = await self._generate_prompt(content, research, topic, image_spec, gen_ctx)
                final_prompt = prompt

                # 2. 通过 API 生成图片
                output_path = output_dir / f"{image_type}.png"
                image_path = await self.image_client.generate_image(
                    prompt=prompt,
                    output_path=output_path,
                )

                # 3. 质量验证（可选，如果验证器可用）
                try:
                    validation_context = {
                        "topic": topic,
                        "image_type": image_type,
                        "content": content,
                        "research": research,
                        "image_type_info": image_spec,
                    }
                    validation_result = await self.image_quality_validator.validate(
                        image_path=image_path,
                        context=validation_context,
                    )

                    if validation_result.passed:
                        logger.info("图片质量验证通过: score=%d", validation_result.style_score)
                        return image_path, final_prompt
                    else:
                        # 验证未通过，注入反馈并重试
                        feedback = f"质量问题: {', '.join(validation_result.issues)}"
                        gen_ctx.validation_feedback = feedback
                        logger.warning(
                            "图片质量验证未通过 (尝试 %d/%d): %s",
                            attempt + 1, max_retries, feedback
                        )
                        continue

                except Exception as e:
                    # 验证失败但图片已生成，记录警告但继续
                    logger.warning("图片质量验证失败，跳过验证: %s", e)
                    return image_path, final_prompt

            except Exception as e:
                last_error = e
                logger.warning(
                    "图片生成失败 (尝试 %d/%d): %s",
                    attempt + 1, max_retries, str(e)
                )

                # 检查是否是限流错误
                if "limited" in str(e).lower() or "429" in str(e):
                    raise  # 限流错误直接抛出

                if attempt < max_retries - 1:
                    import asyncio
                    delay = min(2 ** attempt * 2, 60)
                    logger.info("等待 %d 秒后重试...", delay)
                    await asyncio.sleep(delay)

        raise last_error or Exception("图片生成失败，已达最大重试次数")
