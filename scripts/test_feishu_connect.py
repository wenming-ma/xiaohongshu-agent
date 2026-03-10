"""测试飞书长连接 — 运行后在飞书开放平台保存订阅方式即可。"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import os
import lark_oapi as lark
from lark_oapi.api.im.v1 import *

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")


def on_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    """收到消息的回调"""
    msg = data.event.message
    print(f"[收到消息] type={msg.message_type}, content={msg.content}")


event_handler = (
    lark.EventDispatcherHandler.builder("", "")
    .register_p2_im_message_receive_v1(on_message)
    .build()
)

cli = lark.ws.Client(
    APP_ID,
    APP_SECRET,
    event_handler=event_handler,
    log_level=lark.LogLevel.DEBUG,
)

print("正在连接飞书长连接...")
print("连接成功后，请回到飞书开放平台点击[保存]按钮。")
print("然后在飞书中找到你的机器人，发一条消息测试。")
print("按 Ctrl+C 退出。")
cli.start()
