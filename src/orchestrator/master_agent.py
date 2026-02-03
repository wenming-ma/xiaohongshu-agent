"""MasterAgent - 顶层AI Agent，根据用户意图选择和调用工具"""

from typing import Any
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ..core.base_agent import BaseAgent, ValidationResult
from ..core.tool_registry import ToolRegistry
from ..utils.anthropic_provider import get_anthropic_model
from ..utils.logger import get_logger

logger = get_logger(__name__)


class MasterAgentOutput(BaseModel):
    """MasterAgent 输出"""

    tool_used: str = Field(default="", description="使用的工具名称")
    result: dict = Field(default_factory=dict, description="工具执行结果")
    summary: str = Field(default="", description="执行摘要")


class MasterAgent(BaseAgent):
    """顶层 AI Agent

    根据用户自然语言输入选择合适的工具并执行。
    """

    def init_tools(self) -> None:
        """加载所有已注册的平台工具"""
        from ..tools.xiaohongshu.image_post import XHSImagePostTool  # noqa: 触发注册

        self.platform_tools = ToolRegistry.get_pydantic_tools()
        logger.info(f"MasterAgent 已加载 {len(self.platform_tools)} 个工具")

    def init_agent(self) -> None:
        """初始化 pydantic_ai Agent"""
        model = get_anthropic_model()

        self.agent = Agent(
            model=model,
            output_type=MasterAgentOutput,
            tools=self.platform_tools,
            instrument=True,
            system_prompt=(self._build_system_prompt(),),
        )

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        tool_descriptions = ToolRegistry.get_tool_descriptions()

        return f"""# 社交媒体内容创作助手

你是一个 AI 助手，帮助用户在多个社交媒体平台上创建和发布内容。

## 可用工具

{tool_descriptions}

## 你的职责

1. **理解用户意图**：分析用户想要创建什么内容，以及在哪个平台发布
2. **选择合适的工具**：根据以下因素选择最合适的工具：
   - 目标平台（小红书、B站、Twitter 等）
   - 内容类型（图文帖子、视频、文章等）
   - 用户的具体需求
3. **提取参数**：从用户输入中提取主题、受众等参数
4. **执行工具**：调用选定的工具并传入参数
5. **报告结果**：总结执行结果并提供相关链接/路径

## 指南

- 如果用户没有指定平台，请询问确认
- 如果主题不够明确，请要求更多细节
- 如果未指定目标受众，请询问确认
- 对于中文平台（小红书、B站），内容将以中文生成
- 对于国际平台，内容将以相应语言生成

## 交互示例

用户: "帮我创建一篇关于上海咖啡店的小红书帖子，目标受众是年轻白领"
操作: 使用 xiaohongshu_image_post 工具，topic="上海咖啡店"，audience="年轻白领"

用户: "我想在B站发一个Python编程教程视频"
操作: 使用 bilibili_video 工具，topic="Python编程教程"，video_type="tutorial"
"""

    async def forward(self, user_input: str) -> MasterAgentOutput:
        """处理用户输入并执行相应工具

        Args:
            user_input: 用户自然语言请求

        Returns:
            MasterAgentOutput: 执行结果
        """
        logger.info(f"MasterAgent 处理请求: {user_input[:100]}...")

        result = await self.agent.run(user_input)
        return result.output

    async def step(self, *args: Any, **kwargs: Any) -> Any:
        """MasterAgent 不使用 step 方法"""
        pass

    async def validate(self, output: Any) -> ValidationResult:
        """验证输出"""
        if not isinstance(output, MasterAgentOutput):
            return ValidationResult.failure("输出类型错误")

        if output.tool_used and output.result:
            return ValidationResult.success(f"成功执行 {output.tool_used}")

        return ValidationResult.failure("工具执行失败")
