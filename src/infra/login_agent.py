"""
登录/注册 Agent - ML 模型风格
通过 Telegram 与用户交互完成任意网站的登录或注册

使用方式：
    agent = LoginAgent(mcp_server=mcp_server)
    result = await agent.forward(url, action, hint)

功能：
- 支持账号密码登录
- 支持短信验证码登录
- 支持扫码登录
- 支持自动注册新账号
- 通过 Telegram 与用户交互获取凭证

其他 Agent 可以将 LoginAgent 的方法作为 Tool 调用
"""
import asyncio
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.usage import UsageLimits

from ..config.settings import (
    RetryConfig,
    PathConfig,
    UserProfileConfig,
)
from ..core.base_agent import BaseAgent, ValidationResult
from ..utils.anthropic_provider import get_anthropic_model
from ..utils.telegram_notifier import get_telegram_notifier
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# 数据模型
# ============================================================================

class AuthType(str, Enum):
    """认证类型"""
    LOGIN_PASSWORD = "login_password"
    LOGIN_SMS = "login_sms"
    LOGIN_QR = "login_qr"
    REGISTER = "register"
    MANUAL = "manual"


class AuthResult(BaseModel):
    """认证结果"""
    success: bool
    auth_type: str
    message: str
    url: str
    timestamp: str


# ============================================================================
# LoginAgent
# ============================================================================

class LoginAgent(BaseAgent):
    """
    通用登录/注册助手（ML 模型风格）

    类似 PyTorch nn.Module 的设计：
    - __init__: 初始化所有组件
    - forward: 主执行入口
    - step: 工作流子步骤
    - validate: 验证输出

    通过 Telegram 与用户交互，使用 Playwright MCP 操作网页，
    完成任意网站的登录或注册。

    使用方式：
        agent = LoginAgent(mcp_server=mcp_server)
        result = await agent.forward(url, action, hint)
    """

    # ========================================================================
    # 初始化
    # ========================================================================

    def __init__(self, *, mcp_server: MCPServerStdio):
        """初始化 LoginAgent"""
        self.mcp_server = mcp_server
        self.init_mcp_guards()
        self.init_state()
        self.init_paths()
        self.init_user_profile()
        super().__init__()

        logger.info("LoginAgent 初始化完成")

    def init_mcp_guards(self):
        """安装 MCP 安全守卫"""
        existing = getattr(self.mcp_server, "process_tool_call", None)

        async def wrapped(ctx, call_tool, name: str, args: dict[str, Any]):
            # 记录最近一次浏览器动作
            try:
                if name == "browser_navigate" and isinstance(args, dict) and "url" in args:
                    self._last_action = f"playwright:{name} -> {str(args.get('url'))[:120]}"
                elif name == "browser_tabs" and isinstance(args, dict):
                    self._last_action = f"playwright:{name}({args.get('action')})"
                else:
                    self._last_action = f"playwright:{name}"
            except Exception:
                pass

            # 禁止新建 tab
            if name == "browser_tabs" and isinstance(args, dict) and args.get("action") == "new":
                return {
                    "content": [{"type": "text", "text": "已拦截：禁止新建 tab，请在当前 tab 内完成操作。"}]
                }

            if existing is not None:
                return await existing(ctx, call_tool, name, args)
            return await call_tool(name, args, None)

        self.mcp_server.process_tool_call = wrapped

    def init_state(self):
        """初始化内部状态"""
        self._auth_started_at: float | None = None
        self._last_action: str = "init"
        self._heartbeat_task: asyncio.Task | None = None

    def init_paths(self):
        """初始化路径配置"""
        self.downloads_dir = PathConfig.DOWNLOADS_DIR
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

    def init_user_profile(self):
        """初始化用户信息"""
        self.user_profile = {
            "phone": UserProfileConfig.PHONE,
            "email": UserProfileConfig.EMAIL,
            "username": UserProfileConfig.USERNAME,
            "phone_alt": UserProfileConfig.PHONE_ALT,
            "email_alt": UserProfileConfig.EMAIL_ALT,
        }

    def init_tools(self) -> None:
        """初始化工具集（Telegram 通知器）"""
        self.telegram = get_telegram_notifier()

    def init_agent(self) -> None:
        """初始化认证 Agent"""
        model = get_anthropic_model()
        system_prompt = self.build_system_prompt()

        function_tools = [
            Tool(self.send_telegram_message, takes_ctx=False),
            Tool(self.send_telegram_image, takes_ctx=False),
            Tool(self.send_current_page_screenshot, takes_ctx=False),
            Tool(self.ask_for_user_reply, takes_ctx=False),
        ]

        self.auth_agent = Agent(
            model=model,
            output_type=AuthResult,
            toolsets=[self.mcp_server],
            tools=function_tools,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(system_prompt,),
        )

    # ========================================================================
    # 主入口：forward
    # ========================================================================

    async def forward(
        self,
        url: str,
        action: str = "login",
        hint: str = "",
    ) -> AuthResult:
        """
        请求完成登录或注册（主入口）

        类似 PyTorch 的 forward 方法。

        Args:
            url: 目标页面 URL
            action: 操作类型，"login" 或 "register"
            hint: 可选的提示信息

        Returns:
            AuthResult: 认证结果
        """
        logger.info(f"收到认证请求: {action} @ {url}")
        self._auth_started_at = asyncio.get_running_loop().time()
        self._last_action = f"start:{action}"

        user_prompt = self.build_user_prompt(url, action, hint)

        # 启动 Telegram 轮询
        await self.telegram.start_polling()

        try:
            result = await self.step(user_prompt, url)

            # 验证结果
            validation = await self.validate(result)
            if not validation.passed:
                logger.warning("认证结果验证未通过: %s", validation.feedback)

            return result
        except Exception as e:
            logger.error(f"认证失败: {e}")
            await self.telegram.send_message(f"❌ LoginAgent 出错: {type(e).__name__}: {str(e)[:200]}")
            return AuthResult(
                success=False,
                auth_type="manual",
                message=f"认证过程出错: {str(e)}",
                url=url,
                timestamp=datetime.now().isoformat()
            )

    # ========================================================================
    # 工作流子步骤
    # ========================================================================

    async def step(self, user_prompt: str, url: str) -> AuthResult:
        """
        工作流子步骤：执行认证流程

        Args:
            user_prompt: 用户提示词
            url: 目标 URL

        Returns:
            AuthResult: 认证结果
        """
        async with self.mcp_server:
            await self.close_extra_tabs_keep_current()
            result = await self.auth_agent.run(
                user_prompt,
                usage_limits=UsageLimits(request_limit=None)
            )
            await self.telegram.send_message("✅ LoginAgent 已完成（模型返回结果）")
            return result.output

    # ========================================================================
    # 验证方法
    # ========================================================================

    async def validate(self, output: Any) -> ValidationResult:
        """
        验证认证结果

        Args:
            output: AuthResult 实例

        Returns:
            ValidationResult: 验证结果
        """
        if not isinstance(output, AuthResult):
            return ValidationResult.failure("输出类型错误，期望 AuthResult")

        if output.success:
            logger.info("认证成功: %s", output.message)
            return ValidationResult.success(f"认证成功: {output.message}")
        else:
            logger.warning("认证失败: %s", output.message)
            return ValidationResult.failure(f"认证失败: {output.message}")

    # 暴露给其他 Agent 的工具方法
    async def request_auth(
        self,
        url: str,
        action: str = "login",
        hint: str = "",
    ) -> AuthResult:
        """forward 的别名，用于 Tool 暴露"""
        return await self.forward(url, action, hint)

    def get_tool(self) -> Tool:
        """获取可供其他 Agent 使用的 Tool"""
        return Tool(self.request_auth, takes_ctx=False)

    # ========================================================================
    # 辅助方法
    # ========================================================================

    async def close_extra_tabs_keep_current(self) -> None:
        """关闭除当前页外的所有 tab"""
        try:
            await self.mcp_server.direct_call_tool(
                name="browser_run_code",
                args={
                    "code": (
                        "async (page) => {"
                        "  const pages = page.context().pages();"
                        "  let closed = 0;"
                        "  for (const p of pages) {"
                        "    if (p !== page) {"
                        "      try { await p.close(); closed++; } catch (e) {}"
                        "    }"
                        "  }"
                        "  return { pages: pages.length, closed };"
                        "}"
                    )
                },
            )
        except Exception as e:
            logger.debug(f"清理多余 tab 失败（忽略）: {type(e).__name__}: {str(e)[:120]}")

    def _format_elapsed(self) -> str:
        """格式化已用时"""
        if self._auth_started_at is None:
            return "00:00"
        elapsed = int(asyncio.get_running_loop().time() - self._auth_started_at)
        mm, ss = divmod(max(0, elapsed), 60)
        hh, mm = divmod(mm, 60)
        if hh:
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
        return f"{mm:02d}:{ss:02d}"

    async def start_heartbeat(self, *, phase: str, interval_seconds: float = 8.0) -> None:
        """启动 Telegram 状态心跳"""
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return

        async def _run():
            while True:
                try:
                    status = (
                        f"⏳ LoginAgent 正在处理：{phase}\n"
                        f"已用时：{self._format_elapsed()}\n"
                        f"最近动作：{self._last_action}\n"
                        f"（若长时间不变，可能卡在页面加载/验证码/等待你回复）"
                    )
                    await self.telegram.send_message(status)
                    await asyncio.sleep(interval_seconds)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug(f"心跳发送失败（忽略）: {type(e).__name__}: {str(e)[:120]}")
                    await asyncio.sleep(interval_seconds)

        self._heartbeat_task = asyncio.create_task(_run())

    async def stop_heartbeat(self, final_text: str | None = None) -> None:
        """停止心跳"""
        if final_text:
            try:
                await self.telegram.send_message(final_text)
            except Exception:
                pass
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except Exception:
                pass
            self._heartbeat_task = None

    # ========================================================================
    # 提示词构建
    # ========================================================================

    def build_user_prompt(self, url: str, action: str, hint: str) -> str:
        """构建用户提示词"""
        return f"""请帮助完成以下认证任务：

## 任务信息
- 目标 URL: {url}
- 操作类型: {action}
- 提示信息: {hint or "无"}

## 操作步骤

1. 首先导航到目标 URL
2. 分析页面，确定登录/注册方式
3. 如果是扫码登录：
   - 截取二维码区域的截图
   - 发送给用户并等待扫码完成
4. 如果需要账号密码：
   - 询问用户密码（账号可能已预设或需要询问）
   - 填写表单并提交
5. 如果需要验证码：
   - 触发验证码发送
   - 询问用户验证码
   - 填写验证码并提交
6. 验证登录/注册是否成功
7. 返回结果

开始执行！
"""

    def build_system_prompt(self) -> str:
        """构建系统提示词"""
        user_info = ""
        if any(self.user_profile.values()):
            user_info = "\n## 用户常用账号信息（可用于自动填写表单）\n\n"
            if self.user_profile["phone"]:
                user_info += f"- 手机号：{self.user_profile['phone']}\n"
            if self.user_profile["email"]:
                user_info += f"- 邮箱：{self.user_profile['email']}\n"
            if self.user_profile["username"]:
                user_info += f"- 用户名：{self.user_profile['username']}\n"
            if self.user_profile["phone_alt"]:
                user_info += f"- 备用手机号：{self.user_profile['phone_alt']}\n"
            if self.user_profile["email_alt"]:
                user_info += f"- 备用邮箱：{self.user_profile['email_alt']}\n"

        return f"""# 角色定义
你是一个通用的登录/注册助手，负责帮助用户完成各种网站的登录或注册。

## 核心能力

1. **网页操作**：使用 Playwright 工具操作浏览器
2. **用户交互**：通过 Telegram 与用户沟通，获取必要的凭证

## 可用工具

### Telegram 交互工具
- `send_telegram_message(text)`: 发送消息给用户
- `send_telegram_image(image_path, caption)`: 发送图片（如二维码）给用户
- `send_current_page_screenshot(caption)`: 截图当前页面并通过 Telegram 发送给用户
- `ask_for_user_reply(prompt)`: 发送提示信息并等待用户回复。**必须传入 prompt 参数**

### Playwright 网页操作工具
- 导航、点击、输入、截屏等

## 重要规则

1. **只使用一个 tab**：不要打开新 tab，始终在当前 tab 中操作
2. **先获取页面快照**：每次操作前先用 `playwright_snapshot` 获取页面状态
3. **不要关闭浏览器**：操作完成后保持浏览器打开
4. **自动勾选协议**：登录时如果遇到需要勾选的用户协议，直接勾选即可

## 工作流程

1. 导航到目标 URL（在当前 tab）
2. 获取页面快照，分析登录方式
3. 识别登录/注册方式（账号密码、短信验证码、扫码等）
4. **检查并勾选协议**
5. 如果需要用户提供信息，通过 Telegram 询问
6. 使用获取到的信息完成登录/注册
7. 验证登录是否成功

## 交互规范

### 请求密码
```
ask_for_user_reply(prompt="🔐 检测到需要登录 [网站名称]\\n\\n已填写账号：[账号]\\n请回复密码：")
```

### 请求验证码
```
ask_for_user_reply(prompt="📱 已发送验证码到 [手机号/邮箱]\\n\\n请回复收到的验证码：")
```

### 扫码登录
1. 截取二维码图片并发送
2. 使用 `ask_for_user_reply` 提示用户扫码

{user_info}
## 输出格式

完成后返回 AuthResult：
- success: 是否成功
- auth_type: 认证类型（login_password/login_sms/login_qr/register/manual）
- message: 结果描述
- url: 当前页面 URL
- timestamp: 完成时间
"""

    # ========================================================================
    # Telegram 工具方法
    # ========================================================================

    async def send_telegram_message(self, text: str) -> str:
        """发送 Telegram 消息给用户"""
        result = await self.telegram.send_message(text)
        if result:
            return f"消息已发送（ID: {result}）"
        return "消息发送失败"

    async def send_telegram_image(self, image_path: str, caption: str = "") -> str:
        """发送图片给用户"""
        path = Path(image_path)
        result = await self.telegram.send_image(path, caption)
        if result:
            return f"图片已发送（ID: {result}）"
        return "图片发送失败"

    async def send_current_page_screenshot(self, caption: str = "") -> str:
        """截图当前页面并通过 Telegram 发送"""
        filename = f"login-page-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        try:
            await self.mcp_server.direct_call_tool(
                name="browser_take_screenshot",
                args={"filename": filename, "type": "png"},
            )
        except Exception as e:
            return f"截图失败: {type(e).__name__}: {str(e)[:120]}"

        screenshot_path = PathConfig.DOWNLOADS_DIR / filename

        for _ in range(20):
            if screenshot_path.exists() and screenshot_path.stat().st_size > 0:
                break
            await asyncio.sleep(0.25)

        if not screenshot_path.exists():
            return f"截图文件不存在: {screenshot_path}"

        result = await self.telegram.send_image(screenshot_path, caption or "当前页面截图")
        if result:
            return f"截图已发送（ID: {result}）"
        return "截图发送失败"

    async def ask_for_user_reply(self, prompt: str) -> str:
        """发送提示信息并等待用户回复"""
        self._last_action = "waiting:user_reply"
        await self.telegram.send_message(prompt)
        reply = await self.telegram.wait_for_reply()
        return reply
