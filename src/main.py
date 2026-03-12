"""
主程序入口
使用 MasterAgent 处理用户请求
"""
import asyncio
import argparse
import sys
import io

from dotenv import load_dotenv
load_dotenv()

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import logfire

logfire.configure(
    send_to_logfire='if-token-present',
    environment='development',
    service_name='xiaohongshu-agent',
)
logfire.instrument_pydantic_ai()

from .utils.logger import setup_logging, get_logger
setup_logging()
logger = get_logger(__name__)

from .orchestrator.master_agent import MasterAgent


async def run_master(user_input: str) -> None:
    """使用 MasterAgent 处理用户请求"""
    logger.info("=" * 60)
    logger.info("启动 MasterAgent")
    logger.info("=" * 60)

    try:
        agent = MasterAgent()
        result = await agent.forward(user_input)

        logger.info("=" * 60)
        logger.info("执行完成")
        logger.info("=" * 60)
        logger.info(f"使用工具: {result.tool_used}")
        logger.info(f"摘要: {result.summary}")

        if result.result:
            if result.result.get("success"):
                logger.info("状态: 成功")
                if result.result.get("title"):
                    logger.info(f"标题: {result.result.get('title')}")
                if result.result.get("output_dir"):
                    logger.info(f"输出目录: {result.result.get('output_dir')}")
            else:
                logger.error(f"状态: 失败 - {result.result.get('error_message', '未知错误')}")

    except Exception as e:
        logger.error(f"执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


async def run_direct(topic: str, audience: str, generate_image: bool = True) -> None:
    """直接调用 XHSImagePostTool（兼容旧接口）"""
    from .tools.xiaohongshu.image_post import XHSImagePostTool
    from .tools.xiaohongshu.image_post.schemas import XHSImagePostInput

    logger.info("=" * 60)
    logger.info("直接调用 XHSImagePostTool")
    logger.info("=" * 60)

    try:
        tool = XHSImagePostTool()
        input_data = XHSImagePostInput(
            topic=topic,
            audience=audience,
            generate_image=generate_image,
            publish=True,
        )
        result = await tool.execute(input_data)

        logger.info("=" * 60)
        logger.info("执行完成")
        logger.info("=" * 60)

        if result.success:
            logger.info("状态: 成功")
            logger.info(f"标题: {result.title}")
            logger.info(f"标签: {' '.join(['#' + tag for tag in result.hashtags])}")
            logger.info(f"图片数量: {result.image_count}")
            logger.info(f"已发布: {result.published}")
            logger.info(f"输出目录: {result.output_dir}")
        else:
            logger.error(f"状态: 失败 - {result.error_message}")
            sys.exit(1)

    except Exception as e:
        logger.error(f"执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    """CLI 入口"""
    parser = argparse.ArgumentParser(
        description="多平台内容创作工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # MasterAgent 模式（自然语言）
  python -m src.main "帮我创建一篇关于西安美食的小红书帖子，目标受众是吃货"

  # 直接模式（指定参数）
  python -m src.main --topic "西安公司避坑指南" --audience "求职者"
        """
    )

    parser.add_argument(
        "input",
        nargs="?",
        help="自然语言请求（MasterAgent 模式）"
    )

    parser.add_argument(
        "--topic",
        help="研究主题（直接模式）"
    )

    parser.add_argument(
        "--audience",
        help="目标受众（直接模式）"
    )

    parser.add_argument(
        "--no-image",
        action="store_true",
        help="跳过配图生成步骤"
    )

    args = parser.parse_args()

    try:
        if args.input:
            asyncio.run(run_master(args.input))
        elif args.topic and args.audience:
            asyncio.run(run_direct(
                args.topic,
                args.audience,
                generate_image=not args.no_image
            ))
        else:
            parser.print_help()
            sys.exit(1)

    except KeyboardInterrupt:
        logger.warning("用户中断")
        sys.exit(0)


if __name__ == "__main__":
    main()
