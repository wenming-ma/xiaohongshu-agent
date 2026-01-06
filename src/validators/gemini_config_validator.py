"""
Gemini 配置验证器
检查 Gemini 页面是否正确选择了 Create images + Pro 模式

验证项目：
- Tools -> Create images 是否已选中
- Pro 模式是否已选中

使用方式：
    @GeminiConfigValidator(max_retries=3)
    async def _generate_via_gemini(self, prompt, output_dir, image_type):
        ...
"""
from datetime import datetime
from pathlib import Path
from typing import Any
from pydantic_ai import Agent, BinaryContent
from .external_base import ExternalValidator
from ..models.schemas import GeminiConfigReview
from ..utils.image_compression import compress_image_for_review
from prompts import get_system_prompt, get_user_prompt


class GeminiConfigValidator(ExternalValidator):
    """
    Gemini 配置验证器 - 可直接作为装饰器使用

    验证 Gemini 页面配置：
    1. Tools -> Create images 是否已选中
    2. Pro 模式是否已选中

    验证失败时自动重试整个被装饰的函数。
    """

    @property
    def validator_name(self) -> str:
        return "GeminiConfig"

    @property
    def agent(self) -> Agent:
        """延迟初始化 Agent（首次使用时创建）"""
        if self._agent is None:
            from ..utils.anthropic_provider import get_anthropic_model
            from ..config.settings import RetryConfig
            self._agent = Agent(
                model=get_anthropic_model(),
                output_type=GeminiConfigReview,
                instrument=True,
                retries=RetryConfig.AGENT_RETRIES,  # Agent 内部重试
                system_prompt=(get_system_prompt("gemini_config_review"),),
            )
        return self._agent

    async def get_validation_target(
        self,
        agent_instance: Any,
        result: Any,
        context: dict
    ) -> Path:
        """
        截屏 Gemini 页面作为验证目标

        Args:
            agent_instance: ImageAgent 实例（需要有 mcp_server 和 downloads_dir）
            result: 被装饰函数的返回值（不使用）
            context: 上下文信息

        Returns:
            截屏文件路径
        """
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"gemini-config-{timestamp}.png"

        # 通过 MCP Server 调用截屏工具
        await agent_instance.mcp_server.direct_call_tool(
            name="browser_take_screenshot",
            args={"filename": filename, "type": "png"}
        )

        screenshot_path = agent_instance.downloads_dir / filename
        print(f"         📸 [{self.validator_name}] 截屏: {screenshot_path.name}")

        # 保存截屏路径，验证通过后删除
        self._temp_screenshot = screenshot_path
        return screenshot_path

    async def validate(self, screenshot_path: Path, context: dict) -> GeminiConfigReview:
        """
        验证 Gemini 页面配置

        通过分析页面截屏，检查：
        1. Tools -> Create images 是否已选中
        2. Pro 模式是否已选中

        Args:
            screenshot_path: Gemini 页面截屏路径
            context: 上下文信息（未使用）

        Returns:
            GeminiConfigReview: 验证结果
        """
        # 检查截屏文件
        if not screenshot_path.exists():
            return GeminiConfigReview(
                passed=False,
                create_images_enabled=False,
                pro_mode_enabled=False,
                issues=["截屏文件不存在"],
                summary="无法验证：截屏文件不存在"
            )

        # 压缩截屏文件（Claude API 限制 5MB）
        image_data = await compress_image_for_review(screenshot_path, max_size_mb=5.0)

        # 获取用户提示词
        user_prompt = get_user_prompt("gemini_config_review")

        # 使用 Agent 分析截屏（使用压缩后的 JPEG）
        result = await self.agent.run(
            [
                user_prompt,
                BinaryContent(data=image_data, media_type='image/jpeg')
            ]
        )

        return result.output

    def _log_success(self, review: GeminiConfigReview) -> None:
        """记录验证成功（覆盖基类方法以显示更多信息）"""
        print(f"         ✅ [{self.validator_name}] 配置正确 (Create images: ✓, Pro: ✓)")
