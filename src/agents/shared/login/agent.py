"""
登录/注册工具 - Agent Delegation 模式
通过 Playwright 和 Android/ADB 自动完成可自动化的登录流程

使用方式：
    login_tool = create_login_tool(mcp_server)
    # 将 login_tool 加入父 Agent 的 tools 列表
"""
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.usage import UsageLimits

from ....config.settings import (
    RetryConfig,
    PathConfig,
    UserProfileConfig,
)
from ....utils.providers import get_text_model
from ....utils.logger import get_logger
from ..utils.playwright_artifacts import install_playwright_artifact_guard
from .android_qr import (
    AndroidQrLoginAutomator,
    AndroidQrLoginToolset,
    build_android_qr_tool_message,
)

logger = get_logger(__name__)

XHS_EXPLORE_LOGIN_URL = "https://www.rednote.com/explore"


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


def _normalize_login_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname and (
        parsed.hostname.endswith("xiaohongshu.com") or parsed.hostname.endswith("rednote.com")
    ):
        return XHS_EXPLORE_LOGIN_URL
    return url


def _classify_web_login_text(text: str) -> str:
    lowered = text.lower()
    if "ip at risk" in lowered or "安全限制" in text or "error_code=300012" in lowered:
        return "security_error"
    if any(token in text for token in ("Explore", "Notifications", "For you", "Me")) and not any(
        token in lowered for token in ("scan qr", "log in", "sign up")
    ):
        return "logged_in"
    if any(token in lowered for token in ("scan qr", "log in", "sign up", "login")) or any(
        token in text for token in ("登录", "扫码", "二维码")
    ):
        return "login_required"
    return "unknown"


def _extract_state_from_report(report: str) -> str:
    for line in report.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "state":
            return value.strip() or "unknown"
    return "unknown"


def _build_session_auth_result(state_report: str, url: str) -> AuthResult | None:
    state = _extract_state_from_report(state_report)
    timestamp = datetime.now().isoformat()

    if state == "logged_in":
        return AuthResult(
            success=True,
            auth_type="session",
            message="共享 Rednote 浏览器 session 已登录，无需扫码。",
            url=url,
            timestamp=timestamp,
        )

    if state == "security_error":
        return AuthResult(
            success=False,
            auth_type="session",
            message="Rednote 共享浏览器 session 检查命中安全限制，已停止自动登录。",
            url=url,
            timestamp=timestamp,
        )

    return None


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
2. **Android 自动扫码**：通过 ADB/uiautomator2 控制用户自己的小红书 App 完成扫码确认

## 可用工具

### 自动扫码工具
- `check_rednote_web_login_state()`: 打开 `https://www.rednote.com/explore` 并检查共享浏览器 session 是否已经登录
- `try_android_qr_login_from_current_page(caption)`: 截图当前网页二维码，并通过 Android/ADB 控制小红书 App 从相册识别二维码、等待登录确认按钮可点后提交

### Android 自动扫码工具
- `inspect_android_ui()`: 查看手机当前 App/页面/可见文本状态
- `push_qr_to_android_gallery(image_path)`: 把本地二维码截图推送到手机相册
- `open_xhs_scanner()`: 打开小红书 App 并进入扫码页
- `open_scanner_album()`: 打开扫码页的 Album/相册入口
- `select_latest_album_image()`: 选择相册中的最新二维码图片
- `submit_xhs_login_confirmation()`: 等待并点击手机端最终 Log in/登录确认按钮

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
5. 如果是小红书扫码登录，使用 Android 自动扫码工具完成
6. 如果需要密码、短信验证码或其他人工输入，不能请求用户手动输入，直接返回失败并说明缺少全自动凭证通道
7. 验证登录是否成功

## 交互规范

- 登录状态处理：先调用 `check_rednote_web_login_state()`。如果返回 `logged_in`，直接返回成功，不要扫码。
- 扫码登录：只有确认需要登录时，才调用 `try_android_qr_login_from_current_page(caption="扫码登录二维码")`。如果返回 `confirmation_submitted`，说明手机端已经点了确认，但这不是最终成功，必须继续用 Playwright 检查网页端状态；只有网页端已进入登录后页面，才算成功。
- 如果 Android 自动扫码返回 `login_failed`、`qr_expired`、`qr_not_identified` 或网页端仍未登录，先尝试刷新/重新生成二维码并再试一次；如果仍然失败，返回 `success=false`，不要请求用户手动处理。

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
   - 先调用 `check_rednote_web_login_state` 验证共享浏览器 session；如果已经登录，直接返回成功
   - 优先调用 `try_android_qr_login_from_current_page` 做 Android 自动扫码
   - 手机端返回 `confirmation_submitted` 后，继续检查网页端状态，网页端确认登录后才算成功
   - 如果 Android 自动扫码不可用、二维码过期、识别失败或网页端仍未登录，刷新/重新生成二维码再试一次；仍失败则返回失败
4. 如果需要账号密码：
   - 如果已有可用凭证则自动填写；没有凭证则返回失败
5. 如果需要验证码：
   - 当前不支持人工验证码输入，返回失败
6. 验证登录/注册是否成功
7. 返回结果

开始执行！
"""


# ============================================================================
# 工厂函数
# ============================================================================

def _build_login_tool(mcp_server: MCPServerStdio) -> Tool:
    """构建登录工具（Agent Delegation 模式）

    返回一个 pydantic-ai Tool，可直接加入父 Agent 的 tools 列表。

    Args:
        mcp_server: 父 Agent 已创建的 Playwright MCP Server 实例
    """
    install_playwright_artifact_guard(mcp_server)
    _install_mcp_guard(mcp_server)
    android_qr_automator = AndroidQrLoginAutomator()
    android_qr_toolset = AndroidQrLoginToolset(android_qr_automator)

    user_profile = {
        "phone": UserProfileConfig.PHONE,
        "email": UserProfileConfig.EMAIL,
        "username": UserProfileConfig.USERNAME,
        "phone_alt": UserProfileConfig.PHONE_ALT,
        "email_alt": UserProfileConfig.EMAIL_ALT,
    }
    PathConfig.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # ── 子工具（闭包，捕获 mcp_server）─────────────────────

    async def _capture_current_page_screenshot(prefix: str = "login-page") -> Path | str:
        filename = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
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

        return screenshot_path

    async def check_rednote_web_login_state() -> str:
        """Open Rednote Explore and classify whether the shared browser session is logged in."""
        try:
            await mcp_server.direct_call_tool(
                name="browser_navigate",
                args={"url": XHS_EXPLORE_LOGIN_URL},
            )
            await asyncio.sleep(2)
            result = await mcp_server.direct_call_tool(
                name="browser_evaluate",
                args={"function": "() => document.body?.innerText || ''"},
            )
        except Exception as e:
            return f"state=unknown\nerror={type(e).__name__}: {str(e)[:200]}"

        text = str(result)
        state = _classify_web_login_text(text)
        return (
            f"state={state}\n"
            f"url={XHS_EXPLORE_LOGIN_URL}\n"
            f"hint={text[:500]}"
        )

    async def try_android_qr_login_from_current_page(caption: str = "") -> str:
        """截图当前网页二维码，并尝试用已连接的 Android 手机自动扫码确认。"""
        screenshot_path = await _capture_current_page_screenshot("android-qr-login")
        if isinstance(screenshot_path, str):
            return screenshot_path

        result = await asyncio.to_thread(
            android_qr_automator.attempt_scan_from_album,
            screenshot_path,
        )
        return build_android_qr_tool_message(
            success=result.success,
            status=result.status,
            message=result.message if not caption else f"{caption}: {result.message}",
            screenshot_path=screenshot_path,
            remote_image_path=result.remote_image_path,
        )

    # ── 内部 Agent（创建一次，复用）──────────────────────────────────

    auth_agent = Agent(
        model=get_text_model(),
        output_type=AuthResult,
        toolsets=[mcp_server],
        tools=[
            Tool(check_rednote_web_login_state, takes_ctx=False),
            Tool(try_android_qr_login_from_current_page, takes_ctx=False),
            *android_qr_toolset.get_tools(),
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
        normalized_url = _normalize_login_url(url)
        logger.info(f"收到认证请求: {action} @ {url} -> {normalized_url}")

        try:
            await _close_extra_tabs()
            if normalized_url == XHS_EXPLORE_LOGIN_URL:
                state_report = await check_rednote_web_login_state()
                session_result = _build_session_auth_result(state_report, normalized_url)
                if session_result is not None:
                    logger.info(
                        "Rednote 共享 session 预检查结束: success=%s, auth_type=%s",
                        session_result.success,
                        session_result.auth_type,
                    )
                    return session_result

            prompt = _build_user_prompt(normalized_url, action, hint)
            result = await auth_agent.run(
                prompt,
                usage_limits=UsageLimits(request_limit=None),
            )
            return result.output
        except Exception as e:
            logger.error(f"认证失败: {e}")
            return AuthResult(
                success=False,
                auth_type="manual",
                message=f"认证过程出错: {str(e)}",
                url=normalized_url,
                timestamp=datetime.now().isoformat(),
            )

    logger.info("login_tool 创建完成")
    return Tool(login, takes_ctx=False)


class RednoteLoginAgent:
    """专门负责 Rednote / 小红书网页登录态和扫码登录的共享 Agent。"""

    def __init__(self, mcp_server: MCPServerStdio) -> None:
        self.mcp_server = mcp_server
        self._tool = _build_login_tool(mcp_server)

    def get_tool(self) -> Tool:
        """返回可挂载到其他 Agent 的登录工具。"""
        return self._tool

    async def login(
        self,
        url: str,
        action: str = "login",
        hint: str = "",
    ) -> AuthResult:
        """统一登录入口；其他 Agent 不直接处理登录细节。"""
        return await self._tool.function(url=url, action=action, hint=hint)

    async def ensure_rednote_research_access(self) -> AuthResult:
        """确保研究任务开始前 Rednote 网页登录态可用。"""
        return await self.login(
            url=XHS_EXPLORE_LOGIN_URL,
            action="login",
            hint="小红书研究前检查登录态；如需要登录，自动完成扫码登录",
        )


def create_login_tool(mcp_server: MCPServerStdio) -> Tool:
    """创建登录工具，兼容既有调用方。"""
    return RednoteLoginAgent(mcp_server).get_tool()
