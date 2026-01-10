"""
登录/注册 Agent
通过 Telegram 与用户交互完成任意网站的登录或注册

功能：
- 支持账号密码登录
- 支持短信验证码登录
- 支持扫码登录
- 支持自动注册新账号
- 通过 Telegram 与用户交互获取凭证

使用方式：
其他 Agent 可以将 LoginAgent 的方法作为 Tool 调用
"""
import asyncio
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Any

from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.usage import UsageLimits

from ..config.settings import (
    RetryConfig, 
    PathConfig, 
    TimeoutConfig,
    UserProfileConfig,
)
from ..utils.model_factory import get_model
from ..utils.telegram_notifier import get_telegram_notifier
from ..utils.tool_feedback import build_toolset_with_telegram_feedback
from ..utils.logger import get_logger

logger = get_logger(__name__)


class AuthType(str, Enum):
    """认证类型"""
    LOGIN_PASSWORD = "login_password"      # 账号密码登录
    LOGIN_SMS = "login_sms"                # 短信验证码登录
    LOGIN_QR = "login_qr"                  # 扫码登录
    REGISTER = "register"                   # 注册新账号
    MANUAL = "manual"                       # 需要手动处理


class AuthResult(BaseModel):
    """认证结果"""
    success: bool
    auth_type: str
    message: str
    url: str
    timestamp: str


class LoginAgent:
    """
    通用登录/注册助手
    
    通过 Telegram 与用户交互，使用 Playwright MCP 操作网页，
    完成任意网站的登录或注册。
    
    可被其他 Agent 作为工具调用。
    """
    
    def __init__(self, *, mcp_server: MCPServerStdio):
        """初始化 LoginAgent"""
        # IMPORTANT:
        # LoginAgent 必须复用调用方正在使用的同一个 MCPServerStdio 实例，
        # 才能保证登录发生在“同一个浏览器/同一个 tab 上下文”里。
        self.mcp_server = mcp_server
        self._install_mcp_guards()

        # 状态追踪（用于 Telegram 心跳反馈）
        self._auth_started_at: float | None = None
        self._last_action: str = "init"
        self._heartbeat_task: asyncio.Task | None = None

        # ==================== 1. 路径配置 ====================
        self.downloads_dir = PathConfig.DOWNLOADS_DIR
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        
        # ==================== 2. Telegram 通知器 ====================
        self.telegram = get_telegram_notifier()
        
        # ==================== 3. 用户信息 ====================
        self.user_profile = {
            "phone": UserProfileConfig.PHONE,
            "email": UserProfileConfig.EMAIL,
            "username": UserProfileConfig.USERNAME,
            "phone_alt": UserProfileConfig.PHONE_ALT,
            "email_alt": UserProfileConfig.EMAIL_ALT,
        }

        # ==================== 4. Agent ====================
        model = get_model()
        
        # 系统提示词，包含用户信息
        system_prompt = self._build_system_prompt()
        
        # 登录操作 Agent
        function_tools = [
            Tool(self._send_telegram_message, takes_ctx=False),
            Tool(self._send_telegram_image, takes_ctx=False),
            Tool(self._send_current_page_screenshot, takes_ctx=False),
            Tool(self._wait_for_user_reply, takes_ctx=False),
            Tool(self._ask_user, takes_ctx=False),
        ]
        self.auth_agent = Agent(
            model=model,
            output_type=AuthResult,
            toolsets=[
                build_toolset_with_telegram_feedback(
                    toolsets=[self.mcp_server],
                    tools=function_tools,
                )
            ],
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(system_prompt,),
        )
        
        logger.info("LoginAgent 初始化完成")

    def _install_mcp_guards(self) -> None:
        """
        给共享的 MCPServerStdio 加“硬约束”，避免 LLM 把浏览器玩炸：
        - 禁止新建 tab（browser_tabs action=new）
        - 复用调用方已有的 process_tool_call（如 ImageAgent 的 browser_close 拦截）
        """
        existing = getattr(self.mcp_server, "process_tool_call", None)

        async def wrapped(ctx, call_tool, name: str, args: dict[str, Any]):
            # 记录最近一次浏览器动作（用于 Telegram 状态反馈）
            try:
                if name == "browser_navigate" and isinstance(args, dict) and "url" in args:
                    self._last_action = f"playwright:{name} -> {str(args.get('url'))[:120]}"
                elif name == "browser_tabs" and isinstance(args, dict):
                    self._last_action = f"playwright:{name}({args.get('action')})"
                else:
                    self._last_action = f"playwright:{name}"
            except Exception:
                pass

            # 1) 禁止新建 tab（这是你看到“开一堆 tab”的最常见原因）
            if name == "browser_tabs" and isinstance(args, dict) and args.get("action") == "new":
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": "已拦截：禁止新建 tab，请在当前 tab 内完成操作。",
                        }
                    ]
                }

            # 2) 继续走已有拦截（若存在），否则直连真实工具
            if existing is not None:
                return await existing(ctx, call_tool, name, args)
            return await call_tool(name, args, None)

        # 覆盖为包装后的回调（保留既有逻辑）
        self.mcp_server.process_tool_call = wrapped

    async def _close_extra_tabs_keep_current(self) -> None:
        """用 browser_run_code 关闭除当前页外的所有 tab（不切换当前 tab）。"""
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
            # 关闭失败不应阻断登录流程
            logger.debug(f"清理多余 tab 失败（忽略）: {type(e).__name__}: {str(e)[:120]}")

    def _format_elapsed(self) -> str:
        """格式化已用时（mm:ss 或 hh:mm:ss）"""
        if self._auth_started_at is None:
            return "00:00"
        elapsed = int(asyncio.get_running_loop().time() - self._auth_started_at)
        mm, ss = divmod(max(0, elapsed), 60)
        hh, mm = divmod(mm, 60)
        if hh:
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
        return f"{mm:02d}:{ss:02d}"

    async def _start_heartbeat(self, *, phase: str, interval_seconds: float = 8.0) -> None:
        """
        启动 Telegram 状态心跳：持续编辑同一条“状态消息”，让用户知道正在处理还是在等回复。
        """
        # 避免重复启动
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
                    await self.telegram.upsert_status(status)
                    await asyncio.sleep(interval_seconds)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    # 心跳失败不应影响主流程
                    logger.debug(f"心跳发送失败（忽略）: {type(e).__name__}: {str(e)[:120]}")
                    await asyncio.sleep(interval_seconds)

        self._heartbeat_task = asyncio.create_task(_run())

    async def _stop_heartbeat(self, final_text: str | None = None) -> None:
        """停止心跳，并可选更新最终状态文本。"""
        if final_text:
            try:
                await self.telegram.upsert_status(final_text)
            except Exception:
                pass
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except Exception:
                pass
            self._heartbeat_task = None
    
    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        user_info = ""
        if any(self.user_profile.values()):
            user_info = """
## 用户常用账号信息（可用于自动填写表单）

"""
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
- `send_current_page_screenshot(caption)`: 截图当前页面并通过 Telegram 发送给用户（用于确认登录状态/展示二维码/排错）
- `wait_for_user_reply()`: 等待用户回复（会一直等待直到用户回复）
- `ask_user(question)`: 发送问题并等待回复（便捷方法）

### Playwright 网页操作工具
- 导航、点击、输入、截屏等

## 重要规则

1. **只使用一个 tab**：不要打开新 tab，始终在当前 tab 中操作
2. **先获取页面快照**：每次操作前先用 `playwright_snapshot` 获取页面状态
3. **不要关闭浏览器**：操作完成后保持浏览器打开

## 工作流程

1. 导航到目标 URL（在当前 tab）
2. 获取页面快照，分析登录方式
3. 识别登录/注册方式（账号密码、短信验证码、扫码等）
4. 如果需要用户提供信息（密码、验证码等），通过 Telegram 询问
5. 使用获取到的信息完成登录/注册
6. 验证登录是否成功

## 交互规范

### 请求密码
```
🔐 检测到需要登录 [网站名称]

请回复密码：
```

### 请求验证码
```
📱 已发送验证码到 [手机号/邮箱]

请回复收到的验证码：
```

### 扫码登录
1. 截取二维码图片
2. 发送图片给用户
3. 提示用户扫码
4. 等待用户回复 "done" 或 "完成"

### 注册新账号
1. 告知用户正在注册
2. 使用预设的用户信息填写表单
3. 如需验证码，询问用户
4. 完成注册

{user_info}
## 输出格式

完成后返回 AuthResult：
- success: 是否成功
- auth_type: 认证类型（login_password/login_sms/login_qr/register/manual）
- message: 结果描述
- url: 当前页面 URL
- timestamp: 完成时间
"""
    
    # ==================== Telegram 工具方法 ====================
    
    async def _send_telegram_message(self, text: str) -> str:
        """
        发送 Telegram 消息给用户
        
        Args:
            text: 消息内容
            
        Returns:
            发送结果
        """
        result = await self.telegram.send_message(text)
        if result:
            return f"消息已发送（ID: {result}）"
        return "消息发送失败"
    
    async def _send_telegram_image(self, image_path: str, caption: str = "") -> str:
        """
        发送图片（如二维码）给用户
        
        Args:
            image_path: 图片路径
            caption: 图片说明
            
        Returns:
            发送结果
        """
        path = Path(image_path)
        result = await self.telegram.send_image(path, caption)
        if result:
            return f"图片已发送（ID: {result}）"
        return "图片发送失败"

    async def _send_current_page_screenshot(self, caption: str = "") -> str:
        """
        截图当前页面并通过 Telegram 发送给用户（便捷工具）。

        说明：
        - 截图文件会保存到 Playwright MCP 的 output-dir（项目里默认是 output/playwright-downloads）
        - 该工具依赖 mcp_server 已经处于运行状态（通常在 request_auth 的 async with 中）

        Args:
            caption: 图片说明（可选）

        Returns:
            发送结果
        """
        filename = f"login-page-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        try:
            await self.mcp_server.direct_call_tool(
                name="browser_take_screenshot",
                args={"filename": filename, "type": "png"},
            )
        except Exception as e:
            return f"截图失败: {type(e).__name__}: {str(e)[:120]}"

        screenshot_path = PathConfig.DOWNLOADS_DIR / filename

        # 等待文件落盘（短暂轮询，避免偶发 race）
        for _ in range(20):
            if screenshot_path.exists() and screenshot_path.stat().st_size > 0:
                break
            import asyncio

            await asyncio.sleep(0.25)

        if not screenshot_path.exists():
            return f"截图文件不存在: {screenshot_path}"

        result = await self.telegram.send_image(screenshot_path, caption or "当前页面截图")
        if result:
            return f"截图已发送（ID: {result}）"
        return "截图发送失败"
    
    async def _wait_for_user_reply(self) -> str:
        """
        等待用户回复（会一直等待直到用户回复）
        
        Returns:
            用户回复的内容
        """
        self._last_action = "waiting:user_reply"
        await self.telegram.upsert_status(
            f"⌛ 等待你的回复中…\n已用时：{self._format_elapsed()}\n最近动作：{self._last_action}"
        )
        reply = await self.telegram.wait_for_reply()
        return reply
    
    async def _ask_user(self, question: str) -> str:
        """
        发送问题并等待用户回复（便捷方法）
        
        Args:
            question: 问题内容
            
        Returns:
            用户回复的内容
        """
        self._last_action = "ask:user"
        await self.telegram.upsert_status(
            f"📩 已向你提问，等待回复…\n已用时：{self._format_elapsed()}\n最近动作：{self._last_action}"
        )
        reply = await self.telegram.ask(question)
        return reply
    
    # ==================== 公开方法（可作为 Tool 暴露） ====================
    
    async def request_auth(
        self,
        url: str,
        action: str = "login",
        hint: str = "",
    ) -> AuthResult:
        """
        请求完成登录或注册
        
        这是暴露给其他 Agent 的主要方法。
        
        Args:
            url: 目标页面 URL
            action: 操作类型，"login" 或 "register"
            hint: 可选的提示信息（如"Google 账号"、"小红书"等）
            
        Returns:
            AuthResult: 认证结果
        """
        logger.info(f"收到认证请求: {action} @ {url}")
        self._auth_started_at = asyncio.get_running_loop().time()
        self._last_action = f"start:{action}"
        
        # 构建用户提示词
        user_prompt = f"""请帮助完成以下认证任务：

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
        
        # 启动 Telegram 轮询
        await self.telegram.start_polling()

        # 启动状态心跳（避免你在聊天里“只看到正在等待，不知道是否掉线”）
        await self._start_heartbeat(phase=f"{action} {hint}".strip())
        
        try:
            async with self.mcp_server:
                # 清理历史残留 tab（尤其是使用 persistent profile 时，浏览器会恢复上次会话的 tab）
                await self._close_extra_tabs_keep_current()
                # 关闭 pydantic-ai 默认 request_limit=50（避免登录流程因探索步骤多而中断）
                result = await self.auth_agent.run(user_prompt, usage_limits=UsageLimits(request_limit=None))
                await self._stop_heartbeat(final_text="✅ LoginAgent 已完成（模型返回结果）")
                return result.output
        except Exception as e:
            logger.error(f"认证失败: {e}")
            await self._stop_heartbeat(final_text=f"❌ LoginAgent 出错: {type(e).__name__}: {str(e)[:200]}")
            return AuthResult(
                success=False,
                auth_type="manual",
                message=f"认证过程出错: {str(e)}",
                url=url,
                timestamp=datetime.now().isoformat()
            )
    
    def get_tool(self) -> Tool:
        """
        获取可供其他 Agent 使用的 Tool
        
        Returns:
            Tool: request_auth 方法的 Tool 包装
        """
        return Tool(self.request_auth, takes_ctx=False)
