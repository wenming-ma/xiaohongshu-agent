"""
主程序入口
协调研究和内容创作的工作流
"""
import asyncio
import argparse
import sys
import io

# 🔑 必须在 logfire.configure() 之前加载 .env，否则 LOGFIRE_TOKEN 不会生效
from dotenv import load_dotenv
load_dotenv()

# 修复 Windows 控制台 UTF-8 编码问题
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Logfire 可观测性配置
import logfire

# 创建 Telegram SpanProcessor（在 configure 之前）
from .utils.logfire_telegram_handler import TelegramSpanProcessor
telegram_processor = TelegramSpanProcessor(
    min_interval_sec=1.0,           # 最小发送间隔 1 秒
    include_http_requests=False,    # 不包含 HTTP 请求日志
    include_tool_args=True,         # 包含工具参数
    max_arg_length=200,             # 参数最大长度 200 字符
)

# Logfire 配置
# - 'if-token-present' 表示如果没有配置 LOGFIRE_TOKEN，则不发送数据（本地模式）
# - environment 区分开发/生产环境
# - service_name 标识服务名称，便于在 Dashboard 中筛选
# - additional_span_processors 添加自定义的 SpanProcessor
logfire.configure(
    send_to_logfire='if-token-present',
    environment='development',
    service_name='xiaohongshu-agent',
    additional_span_processors=[telegram_processor],
)
logfire.instrument_pydantic_ai()

# 初始化日志配置（在 logfire 之后）
from .utils.logger import setup_logging, get_logger
setup_logging()
logger = get_logger(__name__)

from .workflows import FullWorkflow
from .workflows.types import WorkflowContext


async def run_workflow(topic: str, audience: str, generate_image: bool = True) -> None:
    """
    运行完整的内容创作工作流

    Args:
        topic: 研究主题
        audience: 目标受众
        generate_image: 是否生成配图（默认开启）
    """
    ctx = WorkflowContext.create(
        topic=topic,
        audience=audience,
        generate_image=generate_image,
    )
    try:
        ctx = await FullWorkflow().run(ctx)

        logger.info("=" * 60)
        logger.info("工作流完成！")
        logger.info("=" * 60)
        logger.info("输出文件:")
        logger.info("  - %s", ctx.output_dir / "research.json")
        logger.info("  - %s", ctx.output_dir / "content.json")
        if ctx.image_result:
            logger.info("  - %s", ctx.output_dir / "image.json")
            for img in ctx.image_result.images:
                logger.info("  - %s", img.image_path)
        publish_json = ctx.output_dir / "publish.json"
        if publish_json.exists():
            logger.info("  - %s", publish_json)

        if ctx.content:
            logger.info("预览内容:")
            logger.info("-" * 60)
            logger.info("标题: %s", ctx.content.title)
            logger.info("正文: %s...", ctx.content.body[:100])
            logger.info("标签: %s", " ".join(["#" + tag for tag in ctx.content.hashtags]))
            logger.info("互动: %s", ctx.content.call_to_action)
            logger.info("-" * 60)
    except Exception as e:
        logger.error("错误: %s", e)
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    """CLI 入口"""
    # 注：load_dotenv() 已在模块顶部调用（Logfire 需要先加载 token）

    # 解析命令行参数
    parser = argparse.ArgumentParser(
        description="小红书内容创作工具（Pydantic-AI）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m src.main --topic "西安公司避坑指南" --audience "求职者"
  python -m src.main --topic "成都美食探店" --audience "吃货"
        """
    )

    parser.add_argument(
        "--topic",
        required=True,
        help="研究主题（如：西安公司避坑指南）"
    )

    parser.add_argument(
        "--audience",
        required=True,
        help="目标受众（如：求职者）"
    )

    parser.add_argument(
        "--no-image",
        action="store_true",
        help="跳过配图生成步骤"
    )

    args = parser.parse_args()

    # 运行工作流
    try:
        asyncio.run(run_workflow(
            args.topic,
            args.audience,
            generate_image=not args.no_image
        ))
    except KeyboardInterrupt:
        logger.warning("用户中断")
        sys.exit(0)


if __name__ == "__main__":
    main()
