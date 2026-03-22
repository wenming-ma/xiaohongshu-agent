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
from typing import Optional, Any

from pydantic_ai import Agent, RunContext

from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import (
    ImageResult,
    GeneratedImage,
    XHSContent,
    ResearchResult,
    GroupSpec,
    ImageGroupingPlan,
    ImageGroupingReviewResult,
    ImageTypeSpec,
    ImageGenContext,
    ReferenceImageResult,
)
from ....utils.providers import get_text_model, get_google_model, get_openai_model, GeminiImageClient, GeminiWebImageClient
from ....utils.logger import get_logger
from ....config.settings import APIConfig, RetryConfig
from .validator import ImageQualityValidator
from .prompts import (
    image_system_prompt,
    image_user_prompt,
    image_grouping_system_prompt,
    image_grouping_review_system_prompt,
    REFERENCE_IMAGE_INSTRUCTION,
)
from .utils import (
    build_compact_items,
    calculate_grouping_params,
    groups_to_image_specs,
    run_grouping_with_review,
)

logger = get_logger(__name__)


def _is_retryable_error(e: Exception) -> bool:
    """判断是否为可降级到 Web 的可重试错误"""
    msg = str(e).lower()
    return any(kw in msg for kw in ("503", "unavailable", "overloaded", "timeout", "disconnected"))


class ImageAgent(BaseAgent):
    """Gemini 图片生成 Agent"""

    role = "图片设计师"
    goal = "生成吸引眼球的小红书配图"

    # ========================================================================
    # 初始化
    # ========================================================================

    def __init__(self):
        """初始化图片生成 Agent"""
        super().__init__()

    def init_tools(self) -> None:
        """初始化 Gemini 图片 API 客户端和质量验证器"""
        provider = APIConfig.GEMINI_IMAGE_PROVIDER
        if provider == "web":
            self.image_client = GeminiWebImageClient()
        elif provider == "api":
            self.image_client = GeminiImageClient()
        else:  # "auto"
            self.image_client = GeminiImageClient()
            self.web_image_client = GeminiWebImageClient()
        self.image_quality_validator = ImageQualityValidator(
            max_retries=RetryConfig.MAX_RETRIES,
            initial_delay=2.0
        )

    def init_agent(self) -> None:
        """初始化所有 Agent"""
        model = get_text_model()

        # 提示词生成 Agent
        self.prompt_generator = Agent(
            model=model,
            output_type=str,
            deps_type=ImageGenContext,
            instrument=True,
        )

        # 注册动态 system_prompt
        @self.prompt_generator.system_prompt
        async def dynamic_system_prompt(ctx: RunContext[ImageGenContext]) -> str:
            base_prompt = image_system_prompt()
            if ctx.deps.validation_feedback:
                return (
                    base_prompt +
                    "\n\n## 上次生成的图片问题（必须修复）\n"
                    f"{ctx.deps.validation_feedback}\n\n"
                    "请根据上述反馈调整提示词，确保生成的图片符合要求。"
                )
            return base_prompt

        # 语义分组 Agent（使用 OpenAI 兼容模型）
        self.grouping_agent = Agent(
            model=get_openai_model(),
            output_type=ImageGroupingPlan,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(image_grouping_system_prompt(),),
        )

        # 分组审核 Agent（使用 OpenAI 兼容模型）
        self.grouping_reviewer = Agent(
            model=get_openai_model(),
            output_type=ImageGroupingReviewResult,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(image_grouping_review_system_prompt(),),
        )

    # ========================================================================
    # 语义分组（可独立调用）
    # ========================================================================

    async def compute_groups(
        self,
        research: ResearchResult,
        topic: str,
    ) -> list[GroupSpec]:
        """
        独立的语义分组入口，供 tool.py 在 Content 之前调用。

        Args:
            research: 研究数据
            topic: 主题

        Returns:
            list[GroupSpec]: 分组结果
        """
        item_count = len(research.items)
        if item_count == 0:
            return []

        target_groups, target_group_size, max_group_size_cap = calculate_grouping_params(item_count)
        compact_items = build_compact_items(research.items or [])

        return await run_grouping_with_review(
            grouping_agent=self.grouping_agent,
            grouping_reviewer=self.grouping_reviewer,
            topic=topic,
            research=research,
            compact_items=compact_items,
            target_groups=target_groups,
            target_group_size=target_group_size,
            max_group_size_cap=max_group_size_cap,
        )

    # ========================================================================
    # 主入口：forward
    # ========================================================================

    async def forward(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        output_dir: Path,
        groups: list[GroupSpec] | None = None,
        reference_images: ReferenceImageResult | None = None,
    ) -> ImageResult:
        """
        生成配图（主入口）

        Args:
            content: 内容数据
            research: 研究数据
            topic: 主题
            output_dir: 输出目录
            groups: 预计算的语义分组（可选，为 None 时内部计算）
            reference_images: 参考图片收集结果（可选）

        Returns:
            ImageResult: 图片结果（包含多张图片）
        """
        # 1. 使用预计算分组，或内部计算
        if groups is None:
            groups = await self.compute_groups(research, topic)

        # 2. 构建图片生成规格
        item_count = len(research.items)
        image_specs = groups_to_image_specs(groups)
        logger.info("开始生成 %d 张配图 (%d 个内容项)", len(image_specs), item_count)

        # 3. 逐张生成图片
        generated_images: list[GeneratedImage] = []
        for spec in image_specs:
            # 查找当前 spec 对应的参考图片
            ref_paths: list[Path] | None = None
            if reference_images and not reference_images.skipped:
                image_type = spec["type"]
                if image_type.startswith("detail_"):
                    try:
                        group_idx = int(image_type.split("_")[1]) - 1
                        ref_paths = reference_images.get_images_for_group(group_idx) or None
                    except (ValueError, IndexError):
                        pass

            generated_image = await self.step(
                content=content,
                research=research,
                topic=topic,
                output_dir=output_dir,
                image_spec=spec,
                ref_image_paths=ref_paths,
            )
            generated_images.append(generated_image)
            logger.info("%s 生成完成", spec["type"])

        result = ImageResult(
            images=generated_images,
            total_count=len(generated_images),
            generated_at=datetime.now().isoformat()
        )

        # 验证结果
        validation = await self.validate(result)
        if not validation.passed:
            raise RuntimeError(validation.feedback)

        return result

    # ========================================================================
    # 工作流子步骤
    # ========================================================================

    async def step(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        output_dir: Path,
        image_spec: ImageTypeSpec,
        ref_image_paths: list[Path] | None = None,
    ) -> GeneratedImage:
        """
        工作流子步骤：生成单张图片

        Args:
            content: 内容数据
            research: 研究数据
            topic: 主题
            output_dir: 输出目录
            image_spec: 图片规格
            ref_image_paths: 参考图片路径列表（可选）

        Returns:
            GeneratedImage: 生成的图片
        """
        image_type = image_spec["type"]
        image_desc = image_spec.get("desc", "")

        logger.info("[%s] %s", image_type, image_desc)
        if ref_image_paths:
            logger.info("附加 %d 张参考图片", len(ref_image_paths))

        gen_ctx = ImageGenContext(topic=topic, image_type=image_type)

        logger.info("启动 Gemini API 图片生成...")
        image_path, final_prompt = await self.generate_via_api(
            output_dir=output_dir,
            image_type=image_type,
            topic=topic,
            gen_ctx=gen_ctx,
            content=content,
            research=research,
            image_spec=image_spec,
            ref_image_paths=ref_image_paths,
        )

        return GeneratedImage(
            image_path=str(image_path),
            prompt_used=final_prompt,
            image_type=image_type
        )

    # ========================================================================
    # 验证方法
    # ========================================================================

    async def validate(self, output: Any) -> ValidationResult:
        """
        验证图片生成结果

        Args:
            output: ImageResult 实例

        Returns:
            ValidationResult: 验证结果
        """
        if not isinstance(output, ImageResult):
            return ValidationResult.failure("输出类型错误，期望 ImageResult")

        if output.total_count == 0:
            logger.warning("图片生成结果为空")
            return ValidationResult.failure("图片生成结果为空")

        if not output.images:
            logger.warning("图片列表为空")
            return ValidationResult.failure("图片列表为空")

        logger.info("图片生成验证通过: %d 张图片", output.total_count)
        return ValidationResult.success(f"图片生成验证通过: {output.total_count} 张图片")

    # ========================================================================
    # 图片生成方法
    # ========================================================================

    async def generate_prompt(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        image_spec: ImageTypeSpec,
        gen_ctx: ImageGenContext,
        has_reference_images: bool = False,
    ) -> str:
        """生成 Gemini 图片提示词"""
        image_type = image_spec["type"]
        image_desc = image_spec["desc"]

        if image_type == "cover":
            body_excerpt = content.body
            title_for_prompt = content.title
        else:
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

            title_for_prompt = topic

        user_prompt = image_user_prompt(
            topic=topic,
            content_title=title_for_prompt,
            content_body=body_excerpt,
            image_type=image_type,
            image_desc=image_desc,
        )

        # 追加参考图片指令
        if has_reference_images:
            user_prompt += "\n\n" + REFERENCE_IMAGE_INSTRUCTION

        if gen_ctx.validation_feedback:
            logger.info("根据验证反馈重新生成提示词: %s", gen_ctx.validation_feedback[:100])

        result = await self.prompt_generator.run(user_prompt, deps=gen_ctx)
        return result.output

    async def generate_via_api(
        self,
        output_dir: Path,
        image_type: str,
        topic: str,
        gen_ctx: ImageGenContext,
        content: XHSContent,
        research: ResearchResult,
        image_spec: ImageTypeSpec,
        max_retries: int = RetryConfig.MAX_RETRIES,
        ref_image_paths: list[Path] | None = None,
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
            ref_image_paths: 参考图片路径列表（可选）

        Returns:
            (图片路径, 使用的提示词)
        """
        last_error: Optional[Exception] = None
        final_prompt = ""
        has_refs = bool(ref_image_paths)

        for attempt in range(max_retries):
            try:
                # 1. 生成提示词
                prompt = await self.generate_prompt(
                    content, research, topic, image_spec, gen_ctx,
                    has_reference_images=has_refs,
                )
                final_prompt = prompt

                # 2. 通过 API 生成图片（auto 模式下 API 失败时降级到 Web）
                output_path = output_dir / f"{image_type}.png"
                try:
                    # GeminiImageClient 支持 reference_images，GeminiWebImageClient 不支持
                    gen_kwargs: dict = dict(prompt=prompt, output_path=output_path, aspect_ratio="3:4")
                    if ref_image_paths and isinstance(self.image_client, GeminiImageClient):
                        gen_kwargs["reference_images"] = ref_image_paths
                    elif ref_image_paths:
                        logger.warning("Web 模式不支持参考图片，将忽略 %d 张参考图", len(ref_image_paths))
                    image_path = await self.image_client.generate_image(**gen_kwargs)
                except Exception as api_err:
                    if hasattr(self, 'web_image_client') and _is_retryable_error(api_err):
                        logger.warning("API 失败，降级到 Gemini Web: %s", api_err)
                        image_path = await self.web_image_client.generate_image(
                            prompt=prompt,
                            output_path=output_path,
                            aspect_ratio="3:4",
                        )
                    else:
                        raise

                # 3. 质量验证（可选，如果验证器可用）
                try:
                    validation_context = {
                        "topic": topic,
                        "image_type": image_type,
                        "content": content,
                        "research": research,
                        "image_type_info": image_spec,
                        "image_prompt": final_prompt,
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
