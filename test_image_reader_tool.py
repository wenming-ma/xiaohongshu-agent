"""
最小读图 Tool 测试脚本

用法：
  0) 使用 uv 安装依赖：uv sync
  1) 设置环境变量 ANTHROPIC_API_KEY
  2) 运行：uv run python test_image_reader_tool.py

脚本会生成一张包含文字的临时图片，然后调用 ImageReaderAgent.read_image()。
"""

import asyncio
import os
from pathlib import Path

from PIL import Image, ImageDraw

from src.agents.image_reader import ImageReaderAgent


def _make_test_image(path: Path) -> None:
    img = Image.new("RGB", (900, 520), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((40, 40), "测试图片 / Test Image", fill=(0, 0, 0))
    draw.text((40, 120), "要点：", fill=(0, 0, 0))
    draw.text((80, 170), "1) 这是第一条", fill=(0, 0, 0))
    draw.text((80, 220), "2) 第二条包含数字 12345", fill=(0, 0, 0))
    draw.text((40, 320), "URL: https://example.com", fill=(0, 0, 0))
    img.save(path)


async def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "缺少环境变量 ANTHROPIC_API_KEY。\n"
            "请在当前 shell 设置后再运行：\n"
            "  - PowerShell: $env:ANTHROPIC_API_KEY=\"...\" \n"
            "  - 或者在 .env 中配置（如果你的启动逻辑会加载 .env）\n"
        )

    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    img_path = out_dir / "image_reader_test.png"
    _make_test_image(img_path)

    agent = ImageReaderAgent()
    res = await agent.read_image(
        str(img_path),
        question="图片里有哪些要点？请只根据图片回答。",
    )
    print(res)


if __name__ == "__main__":
    asyncio.run(main())

