"""
登录/注册工具 - Agent Delegation 模式
通过飞书 Bot 与用户交互完成任意网站的登录或注册

使用方式：
    login_tool = create_login_tool(mcp_server)
    # 将 login_tool 加入父 Agent 的 tools 列表
"""
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.usage import UsageLimits

from ....config.settings import (
    RetryConfig,
    PathConfig,
    UserProfileConfig,
    FeishuConfig,
)
from ....utils.providers import get_text_model
from ....utils.feishu_notifier import get_feishu_notifier
from ....utils.logger import get_logger
from ..utils.playwright_artifacts import install_playwright_artifact_guard

logger = get_logger(__name__)


# ============================================================================
# 数据模型
# ============================================================================

class AuthResult(BaseModel):
    """认证结果"""
    success: bool
    auth_type: str
    message: str
    url: str
    timestamp: str


# ============================================================================
# 模块级纯函数
# ============================================================================

def _install_mcp_guard(mcp_server: MCPServerStdio) -> None:
    """安装 MCP 安全守卫：禁止新建 tab"""
    existing = getattr(mcp_server, "process_tool_call", None)

    async def wrapped(ctx, call_tool, name: str, args: dict[str, Any]):
        if name == "browser_tabs" and isinstance(args, dict) and args.get("action") == "new":
            return {
                "content": [{"type": "text", "text": "已拦截：禁止新建 tab，请在当前 tab 内完成操作。"}]
            }
        if existing is not None:
            return await existing(ctx, call_tool, name, args)
        return await call_tool(name, args, None)

    mcp_server.process_tool_call = wrapped


def _build_system_prompt(user_profile: dict) -> str:
    """构建系统提示词"""
    user_info = ""
    if any(user_profile.values()):
        user_info = "\n## 用户常用账号信息（可用于自动填写表单）\n\n"
        if user_profile["phone"]:
            user_info += f"- 手机号：{user_profile['phone']}\n"
        if user_profile["email"]:
            user_info += f"- 邮箱：{user_profile['email']}\n"
        if user_profile["username"]:
            user_info += f"- 用户名：{user_profile['username']}\n"
        if user_profile["phone_alt"]:
            user_info += f"- 备用手机号：{user_profile['phone_alt']}\n"
        if user_profile["email_alt"]:
            user_info += f"- 备用邮箱：{user_profile['email_alt']}\n"

    return f"""# 角色定义
你是一个通用的登录/注册助手，负责帮助用户完成各种网站的登录或注册。

## 核心能力

1. **网页操作**：使用 Playwright 工具操作浏览器
2. **用户交互**：通过飞书消息与用户沟通，获取必要的凭证

## 可用工具

### 消息交互工具
- `send_message_to_user(text)`: 发送消息给用户
- `send_current_page_screenshot(caption)`: 截图当前页面并发送给用户
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
5. 如果需要用户提供信息，通过消息询问
6. 使用获取到的信息完成登录/注册
7. 验证登录是否成功

## 交互规范

用自然、简洁的口语风格和用户沟通，不要用模板化的格式。
所有需要等待用户输入的场景都必须调用 `ask_for_user_reply(prompt=...)`。

- 需要密码：`ask_for_user_reply(prompt="请发一下密码")`
- 需要验证码：`ask_for_user_reply(prompt="验证码发到你手机了，发给我")`
- 扫码登录：先用 `send_current_page_screenshot` 发送二维码截图，再 `ask_for_user_reply(prompt="扫一下这个码，扫完回我")`，用户回复后检查页面状态即可，不要要求用户回复特定格式

{user_info}## 输出格式

完成后返回 AuthResult：
- success: 是否成功
- auth_type: 认证类型（login_password/login_sms/login_qr/register/manual）
- message: 结果描述
- url: 当前页面 URL
- timestamp: 完成时间
"""


def _build_user_prompt(url: str, action: str, hint: str) -> str:
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


# ============================================================================
# 工厂函数
# ============================================================================

def create_login_tool(mcp_server: MCPServerStdio) -> Tool:
    """创建登录工具（Agent Delegation 模式）

    返回一个 pydantic-ai Tool，可直接加入父 Agent 的 tools 列表。

    Args:
        mcp_server: 父 Agent 已创建的 Playwright MCP Server 实例
    """
    notifier = get_feishu_notifier()
    install_playwright_artifact_guard(mcp_server)
    _install_mcp_guard(mcp_server)

    user_profile = {
        "phone": UserProfileConfig.PHONE,
        "email": UserProfileConfig.EMAIL,
        "username": UserProfileConfig.USERNAME,
        "phone_alt": UserProfileConfig.PHONE_ALT,
        "email_alt": UserProfileConfig.EMAIL_ALT,
    }
    PathConfig.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # ── 子工具（闭包，捕获 notifier + mcp_server）─────────────────────

    async def send_message_to_user(text: str) -> str:
        """发送消息给用户"""
        result = await notifier.send_message(text)
        if result:
            return f"消息已发送（ID: {result}）"
        return "消息发送失败"

    async def send_current_page_screenshot(caption: str = "") -> str:
        """截图当前页面并发送给用户"""
        filename = f"login-page-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        try:
            await mcp_server.direct_call_tool(
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

        result = await notifier.send_image(screenshot_path, caption or "当前页面截图")
        if result:
            return f"截图已发送（ID: {result}）"
        return "截图发送失败"

    async def ask_for_user_reply(prompt: str) -> str:
        """发送提示信息并等待用户回复（自动 @指定用户）"""
        mention = f'<at user_id="{FeishuConfig.MENTION_USER_ID}">{FeishuConfig.MENTION_USER_NAME}</at> '
        await notifier.send_message(mention + prompt)
        return await notifier.wait_for_reply()

    # ── 内部 Agent（创建一次，复用）──────────────────────────────────

    auth_agent = Agent(
        model=get_text_model(),
        output_type=AuthResult,
        toolsets=[mcp_server],
        tools=[
            Tool(send_message_to_user, takes_ctx=False),
            Tool(send_current_page_screenshot, takes_ctx=False),
            Tool(ask_for_user_reply, takes_ctx=False),
        ],
        instrument=True,
        retries=RetryConfig.AGENT_RETRIES,
        system_prompt=(_build_system_prompt(user_profile),),
    )

    # ── 辅助函数 ─────────────────────────────────────────────────

    async def _close_extra_tabs() -> None:
        """关闭除当前页外的所有 tab"""
        try:
            await mcp_server.direct_call_tool(
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

    # ── 对外工具函数 ──────────────────────────────────────────────

    async def login(
        url: str,
        action: str = "login",
        hint: str = "",
    ) -> AuthResult:
        """完成网站登录或注册。当检测到页面需要登录（出现登录按钮、登录表单、未登录提示等）时，
        必须立即调用此工具完成登录，而不是等待用户手动操作。

        Args:
            url: 需要登录的页面 URL
            action: 操作类型，"login"（登录）或 "register"（注册）
            hint: 可选的提示信息，例如"需要手机验证码登录"
        """
        logger.info(f"收到认证请求: {action} @ {url}")
        await notifier.start_polling()

        try:
            await _close_extra_tabs()
            prompt = _build_user_prompt(url, action, hint)
            result = await auth_agent.run(
                prompt,
                usage_limits=UsageLimits(request_limit=None),
            )
            await notifier.send_message("✅ 登录完成")
            return result.output
        except Exception as e:
            logger.error(f"认证失败: {e}")
            await notifier.send_message(f"❌ LoginAgent 出错: {type(e).__name__}: {str(e)[:200]}")
            return AuthResult(
                success=False,
                auth_type="manual",
                message=f"认证过程出错: {str(e)}",
                url=url,
                timestamp=datetime.now().isoformat(),
            )

    logger.info("login_tool 创建完成")
    return Tool(login, takes_ctx=False)
