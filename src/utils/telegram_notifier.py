"""
Telegram 消息通知与交互

通过 Telegram Bot 与用户交互，支持：
- 发送文本消息
- 发送图片（如二维码）
- 阻塞等待用户回复（无超时限制）

用于 LoginAgent 与用户交互获取登录凭证。
"""
import asyncio
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, types
from aiogram.types import FSInputFile

from .logger import get_logger
from ..config.settings import TelegramConfig

logger = get_logger(__name__)


class TelegramNotifier:
    """
    Telegram 消息通知与交互
    
    特点：
    - 使用 asyncio.Queue 缓存用户回复
    - wait_for_reply() 永久阻塞等待，用户回复后立即唤醒
    - 支持多轮对话
    """
    
    _instance: Optional["TelegramNotifier"] = None
    _initialized: bool = False
    
    def __new__(cls) -> "TelegramNotifier":
        """单例模式，确保只有一个 Bot 实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化 Telegram Bot"""
        if TelegramNotifier._initialized:
            return
            
        self.bot_token = TelegramConfig.BOT_TOKEN
        self.chat_id = TelegramConfig.CHAT_ID
        
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN 未配置，Telegram 通知功能将不可用")
            self.bot = None
            self.dp = None
        else:
            self.bot = Bot(token=self.bot_token)
            self.dp = Dispatcher()
            
            # 用于接收用户回复的队列
            self._reply_queue: asyncio.Queue[str] = asyncio.Queue()
            
            # 注册消息处理器
            self._register_handlers()
            
            # 后台轮询任务
            self._polling_task: Optional[asyncio.Task] = None

            # 状态消息（用 edit 而不是刷屏）；按 key 维护多条状态，避免不同模块互相覆盖
            self._status_message_ids: dict[str, int] = {}
        
        TelegramNotifier._initialized = True
        logger.info("TelegramNotifier 初始化完成")
    
    def _register_handlers(self):
        """注册消息处理器"""
        
        @self.dp.message()
        async def on_message(message: types.Message):
            """收到用户消息时放入队列"""
            if message.text:
                logger.debug(f"收到 Telegram 消息: {message.text[:50]}...")
                await self._reply_queue.put(message.text)
            elif message.photo:
                # 如果用户发送图片，记录但不处理
                logger.debug("收到图片消息")
                await self._reply_queue.put("[IMAGE]")
    
    async def start_polling(self):
        """启动后台轮询接收消息"""
        if self.bot is None:
            logger.warning("Bot 未初始化，无法启动轮询")
            return
            
        if self._polling_task is not None:
            logger.debug("轮询已在运行")
            return
        
        async def _poll():
            try:
                logger.info("开始 Telegram 消息轮询...")
                await self.dp.start_polling(self.bot)
            except asyncio.CancelledError:
                logger.info("Telegram 轮询已停止")
            except Exception as e:
                logger.error(f"Telegram 轮询错误: {e}")
        
        self._polling_task = asyncio.create_task(_poll())
        # 等待一小段时间确保轮询启动
        await asyncio.sleep(0.5)
    
    async def stop_polling(self):
        """停止后台轮询"""
        if self._polling_task is not None:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None
            logger.info("Telegram 轮询已停止")
    
    async def send_message(self, text: str, chat_id: Optional[str] = None) -> Optional[int]:
        """
        发送文本消息
        
        Args:
            text: 消息内容
            chat_id: 目标聊天 ID（可选，默认使用配置的 CHAT_ID）
            
        Returns:
            消息 ID，发送失败返回 None
        """
        if self.bot is None:
            logger.warning("Bot 未初始化，无法发送消息")
            return None
        
        target_chat = chat_id or self.chat_id
        if not target_chat:
            logger.warning("未指定 chat_id，无法发送消息")
            return None
        
        try:
            message = await self.bot.send_message(
                chat_id=target_chat,
                text=text,
                parse_mode="Markdown"
            )
            logger.debug(f"消息已发送: {text[:50]}...")
            return message.message_id
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            # 尝试不使用 Markdown
            try:
                message = await self.bot.send_message(
                    chat_id=target_chat,
                    text=text
                )
                return message.message_id
            except Exception as e2:
                logger.error(f"重试发送失败: {e2}")
                return None

    async def upsert_status(self, text: str, chat_id: Optional[str] = None, *, key: str = "default") -> Optional[int]:
        """
        发送或更新“状态消息”（尽量复用同一条消息，避免刷屏）。

        Args:
            text: 状态内容
            chat_id: 目标聊天 ID（可选）
            key: 状态消息 key（用于区分不同模块的状态消息）

        Returns:
            状态消息 ID，失败返回 None
        """
        if self.bot is None:
            logger.warning("Bot 未初始化，无法发送状态")
            return None

        target_chat = chat_id or self.chat_id
        if not target_chat:
            logger.warning("未指定 chat_id，无法发送状态")
            return None

        status_message_id = self._status_message_ids.get(key)

        # 优先编辑已有状态消息
        if status_message_id is not None:
            try:
                await self.bot.edit_message_text(
                    chat_id=target_chat,
                    message_id=status_message_id,
                    text=text,
                )
                return status_message_id
            except Exception as e:
                # 编辑失败（比如消息太旧/已被删除），退化为重新发一条
                logger.debug(f"编辑状态消息失败，改为新发: {type(e).__name__}: {str(e)[:120]}")
                self._status_message_ids.pop(key, None)

        # 新发一条状态消息
        try:
            message = await self.bot.send_message(
                chat_id=target_chat,
                text=text,
            )
            self._status_message_ids[key] = message.message_id
            return message.message_id
        except Exception as e:
            logger.error(f"发送状态消息失败: {type(e).__name__}: {str(e)[:200]}")
            return None
    
    async def send_image(
        self, 
        image_path: Path, 
        caption: str = "",
        chat_id: Optional[str] = None
    ) -> Optional[int]:
        """
        发送图片（如二维码）
        
        Args:
            image_path: 图片路径
            caption: 图片说明
            chat_id: 目标聊天 ID（可选）
            
        Returns:
            消息 ID，发送失败返回 None
        """
        if self.bot is None:
            logger.warning("Bot 未初始化，无法发送图片")
            return None
        
        target_chat = chat_id or self.chat_id
        if not target_chat:
            logger.warning("未指定 chat_id，无法发送图片")
            return None
        
        if not image_path.exists():
            logger.error(f"图片不存在: {image_path}")
            return None
        
        try:
            photo = FSInputFile(str(image_path))
            message = await self.bot.send_photo(
                chat_id=target_chat,
                photo=photo,
                caption=caption
            )
            logger.debug(f"图片已发送: {image_path.name}")
            return message.message_id
        except Exception as e:
            logger.error(f"发送图片失败: {e}")
            return None
    
    async def wait_for_reply(self) -> str:
        """
        阻塞等待用户回复（无超时限制）
        
        用户不回复就一直等待，回复后立即返回。
        
        Returns:
            用户回复的消息内容
        """
        if self.bot is None:
            logger.warning("Bot 未初始化，无法等待回复")
            return ""
        
        # 确保轮询已启动
        if self._polling_task is None:
            await self.start_polling()
        
        logger.debug("等待用户回复...")
        reply = await self._reply_queue.get()
        logger.debug(f"收到用户回复: {reply[:50]}...")
        return reply
    
    async def ask(self, question: str, chat_id: Optional[str] = None) -> str:
        """
        发送问题并等待回复（便捷方法）
        
        Args:
            question: 问题内容
            chat_id: 目标聊天 ID（可选）
            
        Returns:
            用户回复
        """
        await self.send_message(question, chat_id)
        return await self.wait_for_reply()
    
    async def ask_with_image(
        self, 
        image_path: Path, 
        caption: str,
        chat_id: Optional[str] = None
    ) -> str:
        """
        发送图片问题并等待回复（便捷方法）
        
        Args:
            image_path: 图片路径
            caption: 图片说明/问题
            chat_id: 目标聊天 ID（可选）
            
        Returns:
            用户回复
        """
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
_notifier: Optional[TelegramNotifier] = None


def get_telegram_notifier() -> TelegramNotifier:
    """获取 TelegramNotifier 单例"""
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier
