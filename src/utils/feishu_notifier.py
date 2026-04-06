"""
飞书消息通知与交互

通过飞书 Bot WebSocket 长连接与用户交互，支持：
- 发送文本消息
- 发送图片（如二维码）
- 阻塞等待用户回复（无超时限制）
- 电话加急（通过 urgent_phone API 拨打电话通知用户）

用于 LoginAgent 与用户交互获取登录凭证。
"""
import asyncio
import json
import threading
import uuid
from pathlib import Path
from typing import Optional

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateFileRequest,
    CreateFileRequestBody,
    CreateMessageRequest,
    CreateMessageRequestBody,
    CreateImageRequest,
    CreateImageRequestBody,
    UpdateMessageRequest,
    UpdateMessageRequestBody,
    PatchMessageRequest,
    PatchMessageRequestBody,
    UrgentPhoneMessageRequest,
    UrgentReceivers,
)

from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
    CallBackToast,
)

from .logger import get_logger
from ..config.settings import FeishuConfig, PathConfig

logger = get_logger(__name__)


class FeishuNotifier:
    """
    飞书消息通知与交互

    特点：
    - WebSocket 长连接接收消息（无需公网 IP）
    - 使用 asyncio.Queue 缓存用户回复
    - wait_for_reply() 永久阻塞等待，用户回复后立即唤醒
    - 支持多轮对话
    """

    _instance: Optional["FeishuNotifier"] = None
    _initialized: bool = False

    def __new__(cls) -> "FeishuNotifier":
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化飞书 Bot"""
        if FeishuNotifier._initialized:
            return

        self.app_id = FeishuConfig.APP_ID
        self.app_secret = FeishuConfig.APP_SECRET
        self.dm_mode = FeishuConfig.DM_MODE
        if self.dm_mode:
            self.receive_id = FeishuConfig.MENTION_USER_ID
            self.receive_id_type = "open_id"
        else:
            self.receive_id = FeishuConfig.CHAT_ID
            self.receive_id_type = "chat_id"
        self.chat_id = self.receive_id

        if not self.app_id or not self.app_secret:
            logger.warning("FEISHU_APP_ID / FEISHU_APP_SECRET 未配置，飞书通知功能将不可用")
            self.client = None
        else:
            # API 客户端（用于发消息、发图片）
            self.client = (
                lark.Client.builder()
                .app_id(self.app_id)
                .app_secret(self.app_secret)
                .build()
            )

            # 用于接收用户回复的队列
            self._reply_queue: asyncio.Queue[str] = asyncio.Queue()

            # 用于接收图片/文本的结构化队列 (text, image_path)
            self._media_queue: asyncio.Queue[tuple[str, Path | None]] = asyncio.Queue()

            # 会话历史：记录本次会话中所有收发的消息
            # 每条记录: {"role": "bot"|"user", "type": "text"|"image"|"card"|"button", "content": str, "ts": float}
            self._session_history: list[dict] = []

            # WebSocket 后台线程
            self._polling_thread: Optional[threading.Thread] = None
            self._loop: Optional[asyncio.AbstractEventLoop] = None

            # 状态消息（用 update 而不是刷屏）
            self._status_message_ids: dict[str, str] = {}

        FeishuNotifier._initialized = True
        mode = "私聊模式" if self.dm_mode else "群聊模式"
        logger.info("FeishuNotifier 初始化完成 (%s)", mode)

    # ------------------------------------------------------------------
    # 会话历史
    # ------------------------------------------------------------------

    def _record(self, role: str, msg_type: str, content: str) -> None:
        """记录一条会话消息"""
        import time
        self._session_history.append({
            "role": role,
            "type": msg_type,
            "content": content,
            "ts": time.time(),
        })

    def get_session_history(self) -> list[dict]:
        """获取本次会话的完整聊天记录"""
        return list(self._session_history)

    def get_session_history_text(self) -> str:
        """获取本次会话的聊天记录（文本格式）"""
        lines = []
        for msg in self._session_history:
            role = "🤖" if msg["role"] == "bot" else "👤"
            lines.append(f"{role} [{msg['type']}] {msg['content'][:200]}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 消息轮询（WebSocket 长连接）
    # ------------------------------------------------------------------

    async def start_polling(self):
        """启动 WebSocket 长连接接收消息"""
        if self.client is None:
            logger.warning("飞书客户端未初始化，无法启动连接")
            return

        if self._polling_thread is not None:
            logger.debug("WebSocket 连接已在运行")
            return

        self._loop = asyncio.get_running_loop()

        def _on_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
            """收到用户消息时放入队列（在 WS 线程中执行）"""
            msg = data.event.message

            # 自动检测 chat_id
            if not self.chat_id and msg.chat_id:
                self.chat_id = msg.chat_id
                logger.info(f"自动检测到 chat_id: {self.chat_id}")

            if msg.message_type == "text":
                try:
                    content = json.loads(msg.content)
                    text = content.get("text", "")
                except (json.JSONDecodeError, TypeError):
                    text = str(msg.content)
                logger.debug(f"收到飞书消息: {text[:50]}...")
                self._record("user", "text", text)
                asyncio.run_coroutine_threadsafe(
                    self._reply_queue.put(text), self._loop
                )
                asyncio.run_coroutine_threadsafe(
                    self._media_queue.put((text, None)), self._loop
                )
            elif msg.message_type == "image":
                logger.debug("收到图片消息")
                self._record("user", "image", "[图片]")
                # 向 reply_queue 放入文本标记（向后兼容）
                asyncio.run_coroutine_threadsafe(
                    self._reply_queue.put("[IMAGE]"), self._loop
                )
                # 向 media_queue 放入结构化数据（下载图片）
                try:
                    image_key = json.loads(msg.content).get("image_key", "")
                    if image_key and msg.message_id:
                        asyncio.run_coroutine_threadsafe(
                            self._download_and_queue_image(msg.message_id, image_key),
                            self._loop,
                        )
                except Exception as e:
                    logger.warning(f"解析图片消息失败: {e}")

        def _on_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
            """收到卡片按钮/表单提交时放入队列（在 WS 线程中执行）"""
            try:
                action = data.event.action if (data.event and data.event.action) else None
                action_value = (action.value or {}) if action else {}
                keyword = action_value.get("keyword", "")

                # 表单提交：form_value 包含所有字段数据
                form_value = action.form_value if action else None
            except Exception as e:
                logger.error(f"解析卡片回调失败: {e}")
                form_value = None
                keyword = ""
                action = None
            if form_value:
                form_json = json.dumps(form_value, ensure_ascii=False)
                queue_text = f"__FORM__:{form_json}"
                logger.debug(f"收到表单提交: {form_json[:100]}")
                self._record("user", "form", form_json[:200])
                asyncio.run_coroutine_threadsafe(
                    self._reply_queue.put(queue_text), self._loop
                )
                asyncio.run_coroutine_threadsafe(
                    self._media_queue.put((queue_text, None)), self._loop
                )
                resp = P2CardActionTriggerResponse()
                resp.toast = CallBackToast()
                resp.toast.type = "success"
                resp.toast.content = "已提交"
                return resp

            # 普通按钮点击
            if keyword:
                logger.debug(f"收到卡片按钮点击: {keyword}")
                self._record("user", "button", keyword)
                asyncio.run_coroutine_threadsafe(
                    self._reply_queue.put(keyword), self._loop
                )
                asyncio.run_coroutine_threadsafe(
                    self._media_queue.put((keyword, None)), self._loop
                )
            resp = P2CardActionTriggerResponse()
            resp.toast = CallBackToast()
            resp.toast.type = "info"
            # 支持按钮自定义 toast 文本
            custom_toast = action_value.get("toast", "") if action_value else ""
            resp.toast.content = custom_toast or (f"已选择: {keyword}" if keyword else "操作已收到")
            return resp

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(_on_message)
            .register_p2_card_action_trigger(_on_card_action)
            .build()
        )

        ws_client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        def _run_ws():
            try:
                # lark SDK 的 ws/client.py 在模块导入时创建了全局 loop 变量，
                # start() 直接用 loop.run_until_complete()，
                # 必须替换该模块级变量，否则会用主线程的 loop 导致
                # "This event loop is already running"
                import lark_oapi.ws.client as _ws_mod
                from lark_oapi.ws.enum import MessageType
                from lark_oapi.ws.const import HEADER_TYPE

                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                _ws_mod.loop = new_loop

                # Monkey-patch: SDK 默认丢弃 CARD 帧，让它走 EVENT 同样的路径
                _orig_handle = ws_client._handle_data_frame

                async def _patched_handle(frame):
                    for h in frame.headers:
                        if h.key == HEADER_TYPE and h.value == MessageType.CARD.value:
                            h.value = MessageType.EVENT.value
                            break
                    return await _orig_handle(frame)

                ws_client._handle_data_frame = _patched_handle

                ws_client.start()
            except Exception as e:
                logger.error(f"飞书 WebSocket 连接异常: {e}")

        self._polling_thread = threading.Thread(
            target=_run_ws, daemon=True, name="feishu-ws"
        )
        self._polling_thread.start()

        # 等待连接建立
        await asyncio.sleep(1.5)
        logger.info("飞书 WebSocket 长连接已启动")

    async def stop_polling(self):
        """停止 WebSocket 连接"""
        self._polling_thread = None
        logger.info("飞书 WebSocket 连接已标记停止")

    # ------------------------------------------------------------------
    # 发送消息
    # ------------------------------------------------------------------

    async def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> Optional[str]:
        """
        发送文本消息

        Args:
            text: 消息内容
            chat_id: 目标聊天 ID（可选，默认使用配置的 CHAT_ID）
            parse_mode: 保留参数（兼容 Telegram 接口），飞书不使用

        Returns:
            消息 ID (str)，发送失败返回 None
        """
        if self.client is None:
            logger.warning("飞书客户端未初始化，无法发送消息")
            return None

        target_chat = chat_id or self.chat_id
        if not target_chat:
            logger.warning("未指定 chat_id，无法发送消息")
            return None

        try:
            request = (
                CreateMessageRequest.builder()
                .receive_id_type(self.receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(target_chat)
                    .msg_type("text")
                    .content(json.dumps({"text": text}))
                    .build()
                )
                .build()
            )

            response = await asyncio.to_thread(
                self.client.im.v1.message.create, request
            )

            if response.success():
                msg_id = response.data.message_id
                self._record("bot", "text", text)
                logger.debug(f"消息已发送: {text[:50]}...")
                return msg_id
            else:
                logger.error(
                    f"发送消息失败: code={response.code}, msg={response.msg}"
                )
                return None
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return None

    async def send_card_message(
        self,
        text: str,
        buttons: list[tuple[str, str]],
        chat_id: Optional[str] = None,
    ) -> Optional[str]:
        """发送交互式卡片消息（markdown 文本 + 按钮行）

        Args:
            text: 卡片正文（支持飞书 markdown）
            buttons: 按钮列表 [(显示文本, keyword), ...]
            chat_id: 目标聊天 ID（可选）

        Returns:
            消息 ID，失败返回 None
        """
        if self.client is None:
            return None

        target_chat = chat_id or self.chat_id
        if not target_chat:
            return None

        # 构建按钮 actions
        actions = []
        for label, keyword in buttons:
            btn_type = "danger" if keyword in ("跳过",) else (
                "primary" if keyword in ("完成",) else "default"
            )
            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": label},
                "type": btn_type,
                "value": {"keyword": keyword},
            })

        card = {
            "elements": [
                {"tag": "markdown", "content": text},
                {"tag": "action", "actions": actions},
            ],
        }

        try:
            request = (
                CreateMessageRequest.builder()
                .receive_id_type(self.receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(target_chat)
                    .msg_type("interactive")
                    .content(json.dumps(card))
                    .build()
                )
                .build()
            )

            response = await asyncio.to_thread(
                self.client.im.v1.message.create, request
            )

            if response.success():
                msg_id = response.data.message_id
                self._record("bot", "card", text)
                logger.debug(f"卡片消息已发送: {text[:50]}...")
                return msg_id
            else:
                logger.error(
                    f"发送卡片消息失败: code={response.code}, msg={response.msg}"
                )
                return None
        except Exception as e:
            logger.error(f"发送卡片消息失败: {e}")
            return None

    async def send_card_message_raw(
        self,
        card: dict,
        chat_id: Optional[str] = None,
    ) -> Optional[str]:
        """发送原始卡片 JSON（msg_type=interactive），返回 msg_id"""
        if self.client is None:
            return None
        target_chat = chat_id or self.chat_id
        if not target_chat:
            return None
        try:
            request = (
                CreateMessageRequest.builder()
                .receive_id_type(self.receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(target_chat)
                    .msg_type("interactive")
                    .content(json.dumps(card))
                    .build()
                )
                .build()
            )
            response = await asyncio.to_thread(
                self.client.im.v1.message.create, request
            )
            if response.success():
                msg_id = response.data.message_id
                self._record("bot", "card", json.dumps(card, ensure_ascii=False)[:100])
                return msg_id
            else:
                logger.error(f"发送卡片失败: code={response.code}, msg={response.msg}")
                return None
        except Exception as e:
            logger.error(f"发送卡片失败: {e}")
            return None

    async def update_card_message(
        self,
        message_id: str,
        card: dict,
    ) -> bool:
        """更新已发送的卡片消息内容（使用 patch API）"""
        if self.client is None:
            return False
        try:
            request = (
                PatchMessageRequest.builder()
                .message_id(message_id)
                .request_body(
                    PatchMessageRequestBody.builder()
                    .content(json.dumps(card))
                    .build()
                )
                .build()
            )
            response = await asyncio.to_thread(
                self.client.im.v1.message.patch, request
            )
            if response.success():
                return True
            else:
                logger.error(f"更新卡片失败: code={response.code}, msg={response.msg}")
                return False
        except Exception as e:
            logger.error(f"更新卡片失败: {e}")
            return False

    async def send_form_card(
        self,
        title: str,
        checkers: list[dict],
        input_name: str = "",
        input_placeholder: str = "",
        submit_label: str = "确认",
        chat_id: Optional[str] = None,
    ) -> Optional[str]:
        """发送带表单（checker + input + 提交按钮）的交互式卡片

        Args:
            title: 卡片顶部 markdown 文本
            checkers: [{"name": "item_0", "text": "物品名", "checked": True}, ...]
            input_name: 输入框字段名（空则不显示输入框）
            input_placeholder: 输入框占位符
            submit_label: 提交按钮文本
            chat_id: 目标聊天 ID

        Returns:
            消息 ID，失败返回 None
        """
        if self.client is None:
            return None

        target_chat = chat_id or self.chat_id
        if not target_chat:
            return None

        form_elements: list[dict] = [
            {"tag": "markdown", "content": title},
        ]

        for item in checkers:
            form_elements.append({
                "tag": "checker",
                "name": item["name"],
                "checked": item.get("checked", True),
                "text": {"tag": "plain_text", "content": item["text"]},
                "behaviors": [{"type": "callback", "value": {}}],
            })

        if input_name:
            form_elements.append({
                "tag": "input",
                "name": input_name,
                "placeholder": {"tag": "plain_text", "content": input_placeholder or "请输入"},
            })

        form_elements.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": submit_label},
            "type": "primary",
            "form_action_type": "submit",
            "behaviors": [{"type": "callback", "value": {"action": "form_submit"}}],
        })

        card = {
            "schema": "2.0",
            "body": {
                "elements": [{
                    "tag": "form",
                    "name": "recommend_form",
                    "elements": form_elements,
                }],
            },
        }

        try:
            request = (
                CreateMessageRequest.builder()
                .receive_id_type(self.receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(target_chat)
                    .msg_type("interactive")
                    .content(json.dumps(card))
                    .build()
                )
                .build()
            )

            response = await asyncio.to_thread(
                self.client.im.v1.message.create, request
            )

            if response.success():
                msg_id = response.data.message_id
                self._record("bot", "form", title[:100])
                logger.debug(f"表单卡片已发送: {title[:50]}...")
                return msg_id
            else:
                logger.error(
                    f"发送表单卡片失败: code={response.code}, msg={response.msg}"
                )
                return None
        except Exception as e:
            logger.error(f"发送表单卡片失败: {e}")
            return None

    async def upsert_status(
        self,
        text: str,
        chat_id: Optional[str] = None,
        *,
        key: str = "default",
    ) -> Optional[str]:
        """
        发送或更新"状态消息"（尽量复用同一条消息，避免刷屏）。

        Args:
            text: 状态内容
            chat_id: 目标聊天 ID（可选）
            key: 状态消息 key

        Returns:
            状态消息 ID，失败返回 None
        """
        if self.client is None:
            return None

        target_chat = chat_id or self.chat_id
        if not target_chat:
            return None

        status_message_id = self._status_message_ids.get(key)

        # 优先编辑已有状态消息
        if status_message_id is not None:
            try:
                request = (
                    UpdateMessageRequest.builder()
                    .message_id(status_message_id)
                    .request_body(
                        UpdateMessageRequestBody.builder()
                        .msg_type("text")
                        .content(json.dumps({"text": text}))
                        .build()
                    )
                    .build()
                )

                response = await asyncio.to_thread(
                    self.client.im.v1.message.update, request
                )

                if response.success():
                    return status_message_id
                else:
                    logger.debug(f"编辑状态消息失败: {response.msg}")
                    self._status_message_ids.pop(key, None)
            except Exception as e:
                logger.debug(
                    f"编辑状态消息失败: {type(e).__name__}: {str(e)[:120]}"
                )
                self._status_message_ids.pop(key, None)

        # 新发一条状态消息
        msg_id = await self.send_message(text, target_chat)
        if msg_id:
            self._status_message_ids[key] = msg_id
        return msg_id

    async def send_image(
        self,
        image_path: Path,
        caption: str = "",
        chat_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        发送图片（如二维码）

        Args:
            image_path: 图片路径
            caption: 图片说明
            chat_id: 目标聊天 ID（可选）

        Returns:
            消息 ID，发送失败返回 None
        """
        if self.client is None:
            logger.warning("飞书客户端未初始化，无法发送图片")
            return None

        target_chat = chat_id or self.chat_id
        if not target_chat:
            logger.warning("未指定 chat_id，无法发送图片")
            return None

        if not image_path.exists():
            logger.error(f"图片不存在: {image_path}")
            return None

        try:
            # 第一步：上传图片获取 image_key
            with open(image_path, "rb") as f:
                upload_request = (
                    CreateImageRequest.builder()
                    .request_body(
                        CreateImageRequestBody.builder()
                        .image_type("message")
                        .image(f)
                        .build()
                    )
                    .build()
                )

                upload_response = await asyncio.to_thread(
                    self.client.im.v1.image.create, upload_request
                )

            if not upload_response.success():
                logger.error(
                    f"上传图片失败: code={upload_response.code}, msg={upload_response.msg}"
                )
                return None

            image_key = upload_response.data.image_key

            # 第二步：发送图片消息
            request = (
                CreateMessageRequest.builder()
                .receive_id_type(self.receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(target_chat)
                    .msg_type("image")
                    .content(json.dumps({"image_key": image_key}))
                    .build()
                )
                .build()
            )

            response = await asyncio.to_thread(
                self.client.im.v1.message.create, request
            )

            if not response.success():
                logger.error(
                    f"发送图片消息失败: code={response.code}, msg={response.msg}"
                )
                return None

            msg_id = response.data.message_id
            self._record("bot", "image", f"[图片: {image_path.name}]")
            logger.debug(f"图片已发送: {image_path.name}")

            # 图片说明作为单独文本发送
            if caption:
                await self.send_message(caption, target_chat)

            return msg_id
        except Exception as e:
            logger.error(f"发送图片失败: {e}")
            return None

    async def send_file(
        self,
        file_path: Path,
        caption: str = "",
        chat_id: Optional[str] = None,
        *,
        duration: Optional[int] = None,
    ) -> Optional[str]:
        """
        发送文件（可用于视频文件）

        Args:
            file_path: 文件路径
            caption: 文件说明
            chat_id: 目标聊天 ID（可选）
            duration: 媒体时长（毫秒，可选）

        Returns:
            消息 ID，发送失败返回 None
        """
        if self.client is None:
            logger.warning("飞书客户端未初始化，无法发送文件")
            return None

        target_chat = chat_id or self.chat_id
        if not target_chat:
            logger.warning("未指定 chat_id，无法发送文件")
            return None

        if not file_path.exists():
            logger.error(f"文件不存在: {file_path}")
            return None

        try:
            with open(file_path, "rb") as f:
                body_builder = (
                    CreateFileRequestBody.builder()
                    .file_type("stream")
                    .file_name(file_path.name)
                    .file(f)
                )
                if duration is not None and duration > 0:
                    body_builder = body_builder.duration(duration)
                upload_request = (
                    CreateFileRequest.builder()
                    .request_body(body_builder.build())
                    .build()
                )

                upload_response = await asyncio.to_thread(
                    self.client.im.v1.file.create, upload_request
                )

            if not upload_response.success():
                logger.error(
                    f"上传文件失败: code={upload_response.code}, msg={upload_response.msg}"
                )
                return None

            file_key = upload_response.data.file_key
            request = (
                CreateMessageRequest.builder()
                .receive_id_type(self.receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(target_chat)
                    .msg_type("file")
                    .content(json.dumps({"file_key": file_key}))
                    .build()
                )
                .build()
            )

            response = await asyncio.to_thread(
                self.client.im.v1.message.create, request
            )

            if not response.success():
                logger.error(
                    f"发送文件消息失败: code={response.code}, msg={response.msg}"
                )
                return None

            msg_id = response.data.message_id
            logger.debug(f"文件已发送: {file_path.name}")

            if caption:
                await self.send_message(caption, target_chat)

            return msg_id
        except Exception as e:
            logger.error(f"发送文件失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 电话加急
    # ------------------------------------------------------------------

    async def call_phone(
        self,
        text: str,
        user_ids: list[str] | None = None,
        chat_id: str | None = None,
    ) -> bool:
        """
        发送消息并通过电话加急通知用户。

        先发送一条文本消息，再对该消息调用 urgent_phone API，
        飞书会拨打电话通知目标用户查看消息。

        注意：电话加急会消耗企业加急额度，请谨慎使用。

        Args:
            text: 加急消息内容
            user_ids: 目标用户 open_id 列表（默认使用 MENTION_USER_ID）
            chat_id: 目标聊天 ID（可选）

        Returns:
            是否成功触发电话加急
        """
        if self.client is None:
            logger.warning("飞书客户端未初始化，无法发起电话加急")
            return False

        # 1. 发送消息
        msg_id = await self.send_message(text, chat_id)
        if not msg_id:
            logger.error("电话加急失败：消息发送失败")
            return False

        # 2. 确定目标用户
        target_users = user_ids or [FeishuConfig.MENTION_USER_ID]
        if not target_users or not target_users[0]:
            logger.error("电话加急失败：未指定目标用户 (FEISHU_MENTION_USER_ID)")
            return False

        # 3. 调用 urgent_phone API
        try:
            request = (
                UrgentPhoneMessageRequest.builder()
                .message_id(msg_id)
                .user_id_type("open_id")
                .request_body(
                    UrgentReceivers.builder()
                    .user_id_list(target_users)
                    .build()
                )
                .build()
            )

            response = await asyncio.to_thread(
                self.client.im.v1.message.urgent_phone, request
            )

            if response.success():
                invalid = (
                    response.data.invalid_user_id_list
                    if response.data and response.data.invalid_user_id_list
                    else []
                )
                if invalid:
                    logger.warning(f"部分用户电话加急失败（不在会话中）: {invalid}")
                logger.info(f"电话加急已发起: msg_id={msg_id}, 目标用户={target_users}")
                return True
            else:
                logger.error(
                    f"电话加急失败: code={response.code}, msg={response.msg}"
                )
                return False
        except Exception as e:
            logger.error(f"电话加急异常: {e}")
            return False

    # ------------------------------------------------------------------
    # 等待回复
    # ------------------------------------------------------------------

    async def wait_for_reply(self) -> str:
        """
        阻塞等待用户回复（无超时限制）

        Returns:
            用户回复的消息内容
        """
        if self.client is None:
            logger.warning("飞书客户端未初始化，无法等待回复")
            return ""

        # 确保 WebSocket 已启动
        if self._polling_thread is None:
            await self.start_polling()

        logger.debug("等待用户回复...")
        reply = await self._reply_queue.get()
        logger.debug(f"收到用户回复: {reply[:50]}...")
        return reply

    # ------------------------------------------------------------------
    # 图片下载与多媒体等待
    # ------------------------------------------------------------------

    async def _download_and_queue_image(self, message_id: str, image_key: str) -> None:
        """Download image from Feishu and put path in media queue"""
        try:
            from lark_oapi.api.im.v1 import GetMessageResourceRequest

            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(image_key)
                .type("image")
                .build()
            )

            response = await asyncio.to_thread(
                self.client.im.v1.message_resource.get, request
            )

            if response.success():
                save_dir = PathConfig.DOWNLOADS_DIR
                save_dir.mkdir(parents=True, exist_ok=True)
                save_path = save_dir / f"feishu_img_{uuid.uuid4().hex[:8]}.jpg"

                # response.file is a file-like object
                save_path.write_bytes(response.file.read())
                logger.debug(f"飞书图片已下载: {save_path}")
                await self._media_queue.put(("", save_path))
            else:
                logger.warning(f"下载飞书图片失败: code={response.code}, msg={response.msg}")
                await self._media_queue.put(("[IMAGE_DOWNLOAD_FAILED]", None))
        except Exception as e:
            logger.warning(f"下载飞书图片异常: {e}")
            await self._media_queue.put(("[IMAGE_DOWNLOAD_FAILED]", None))

    async def wait_for_image_or_text(self) -> tuple[Path | None, str]:
        """等待用户回复，返回 (图片路径, 文本)。图片和文本互斥。"""
        if self.client is None:
            return None, ""

        if self._polling_thread is None:
            await self.start_polling()

        text, image_path = await self._media_queue.get()
        return image_path, text

    async def collect_images(
        self,
        prompt: str,
        save_dir: Path,
        done_keyword: str = "完成",
        skip_keyword: str = "跳过",
        next_keyword: str = "下一个",
        next_group_keyword: str = "",
        max_images: int = 5,
    ) -> tuple[list[Path], str]:
        """发送提示并循环收集多张图片，直到用户回复关键词。

        Returns:
            (图片路径列表, 停止原因: "done"/"skip"/"next"/"next_group"/"max_reached")
        """
        if self.client is None:
            return [], "skip"

        # 构建按钮列表并发送卡片消息
        buttons: list[tuple[str, str]] = []
        if next_keyword:
            buttons.append((next_keyword, next_keyword))
        if next_group_keyword:
            buttons.append((next_group_keyword, next_group_keyword))
        if skip_keyword:
            buttons.append((skip_keyword, skip_keyword))
        if done_keyword:
            buttons.append((done_keyword, done_keyword))

        if buttons:
            await self.send_card_message(prompt, buttons)
        else:
            await self.send_message(prompt)

        collected: list[Path] = []
        while len(collected) < max_images:
            image_path, text = await self.wait_for_image_or_text()

            if image_path is not None:
                # User sent an image - copy to save_dir
                dest = save_dir / f"ref_{len(collected) + 1:03d}{image_path.suffix or '.jpg'}"
                import shutil
                shutil.copy2(image_path, dest)
                collected.append(dest)
                logger.debug(f"收集参考图片 {len(collected)}: {dest}")
                continue

            # User sent text
            text_lower = text.strip().lower()
            if text_lower == done_keyword or text == done_keyword:
                return collected, "done"
            if text_lower == skip_keyword or text == skip_keyword:
                return collected, "skip"
            if text_lower == next_keyword or text == next_keyword:
                return collected, "next"
            if next_group_keyword and (text_lower == next_group_keyword or text == next_group_keyword):
                return collected, "next_group"

            # Unknown text, treat as continue signal
            logger.debug(f"收到未知文本回复: {text}, 继续等待图片")

        return collected, "max_reached"

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------

    async def ask(self, question: str, chat_id: Optional[str] = None) -> str:
        """发送问题并等待回复"""
        await self.send_message(question, chat_id)
        return await self.wait_for_reply()

    async def ask_with_image(
        self,
        image_path: Path,
        caption: str,
        chat_id: Optional[str] = None,
    ) -> str:
        """发送图片问题并等待回复"""
        await self.send_image(image_path, caption, chat_id)
        return await self.wait_for_reply()

    def clear_queue(self):
        """清空回复队列"""
        while not self._reply_queue.empty():
            try:
                self._reply_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.debug("回复队列已清空")


# 全局单例
_notifier: Optional[FeishuNotifier] = None


def get_feishu_notifier() -> FeishuNotifier:
    """获取 FeishuNotifier 单例"""
    global _notifier
    if _notifier is None:
        _notifier = FeishuNotifier()
    return _notifier
