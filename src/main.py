"""
主程序入口
协调研究和内容创作的工作流
"""
import asyncio
import argparse
import sys
import io
from pathlib import Path
from datetime import datetime

# 🔑 必须在 logfire.configure() 之前加载 .env，否则 LOGFIRE_TOKEN 不会生效
from dotenv import load_dotenv
load_dotenv()

# 修复 Windows 控制台 UTF-8 编码问题
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Logfire 可观测性配置
import logfire

# Logfire 配置
# - 'if-token-present' 表示如果没有配置 LOGFIRE_TOKEN，则不发送数据（本地模式）
# - environment 区分开发/生产环境
# - service_name 标识服务名称，便于在 Dashboard 中筛选
logfire.configure(
    send_to_logfire='if-token-present',
    environment='development',
    service_name='xiaohongshu-agent',
)
logfire.instrument_pydantic_ai()

# 初始化日志配置（在 logfire 之后）
from .utils.logger import setup_logging, get_logger
setup_logging()
logger = get_logger(__name__)

from .agents.research import ResearchAgent
from .agents.content import ContentAgent
from .agents.image import ImageAgent
from .utils.file_ops import save_json


async def run_workflow(topic: str, audience: str, generate_image: bool = True) -> None:
    """
    运行完整的内容创作工作流

    Args:
        topic: 研究主题
        audience: 目标受众
        generate_image: 是否生成配图（默认开启）
    """
    logger.info("=" * 60)
    logger.info("小红书内容创作工作流（Pydantic-AI）")
    logger.info("=" * 60)
    logger.info(f"主题: {topic}")
    logger.info(f"受众: {audience}")

    # 创建输出目录
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # 清理主题名（移除特殊字符）
    safe_topic = "".join(c for c in topic if c.isalnum() or c in (' ', '-', '_'))[:20]
    project_dir = Path("posts") / f"{timestamp}-{safe_topic}"
    project_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"输出目录: {project_dir}")

    try:
        # ==================== Phase 1: 研究 ====================
        logger.info("=" * 60)
        logger.info("Phase 1: 小红书研究")
        logger.info("=" * 60)

        # 🔑 创建 Agent（MCP 工具已在构造时注册）
        research_agent = ResearchAgent()
        logger.info("ResearchAgent 已创建（包含 Playwright MCP 工具）")

        research = await research_agent.research(topic, audience, output_dir=project_dir)

        # 保存研究结果
        save_json(project_dir / "research.json", research.model_dump())

        logger.info("研究完成:")
        logger.info(f"  - 关键信息: {len(research.key_infos)} 个")
        logger.info(f"  - 案例: {len(research.cases)} 个")
        logger.info(f"  - 关键词: {len(research.keywords)} 个")
        logger.info(f"  - 可信度: {research.credibility}")
        logger.info(f"  - 数据点: {research.data_points} 个")

        # ==================== Phase 2: 内容创作 ====================
        logger.info("=" * 60)
        logger.info("Phase 2: 内容创作")
        logger.info("=" * 60)

        content_agent = ContentAgent()
        content = await content_agent.create_content(research, topic)

        # 保存内容
        save_json(project_dir / "content.json", content.model_dump())

        logger.info("内容创作完成:")
        logger.info(f"  - 标题: {content.title}")
        logger.info(f"  - 正文长度: {len(content.body)} 字")
        logger.info(f"  - 标签: {', '.join(content.hashtags)}")

        # ==================== Phase 3: 配图生成（可选） ====================
        image_result = None
        if generate_image:
            logger.info("=" * 60)
            logger.info("Phase 3: 配图生成")
            logger.info("=" * 60)

            try:
                image_agent = ImageAgent()
                logger.info("ImageAgent 已创建（包含 Playwright MCP 工具）")

                image_result = await image_agent.generate_image(
                    content=content,
                    research=research,
                    topic=topic,
                    output_dir=project_dir
                )

                # 保存图片结果
                save_json(project_dir / "image.json", image_result.model_dump())

                logger.info("配图生成完成:")
                logger.info(f"  - 生成数量: {image_result.total_count} 张")
                for img in image_result.images:
                    logger.info(f"  - {img.image_type}: {img.image_path}")
                logger.info(f"  - 生成时间: {image_result.generated_at}")

            except Exception as e:
                logger.warning(f"配图生成失败: {e}")
                logger.warning("继续完成其他步骤...")
        else:
            logger.info("跳过配图生成（--no-image）")

        # ==================== Phase 4: 发布到小红书（自动） ====================
        if image_result:
            logger.info("=" * 60)
            logger.info("Phase 4: 发布到小红书")
            logger.info("=" * 60)

            try:
                from .agents.publisher import PublisherAgent

                publisher_agent = PublisherAgent()
                logger.info("PublisherAgent 已创建（包含 Playwright MCP 工具）")

                # 提取图片路径
                image_paths = [Path(img.image_path) for img in image_result.images]

                publish_result = await publisher_agent.publish(
                    content=content,
                    images=image_paths,
                    output_dir=project_dir
                )

                # 保存发布结果
                save_json(project_dir / "publish.json", publish_result.model_dump())

                if publish_result.published:
                    logger.info("发布成功:")
                    logger.info(f"  - 发布时间: {publish_result.publish_time}")
                    if publish_result.post_url:
                        logger.info(f"  - 链接: {publish_result.post_url}")
                    if publish_result.retry_count > 0:
                        logger.info(f"  - 重试次数: {publish_result.retry_count}")
                else:
                    logger.error("发布失败:")
                    logger.error(f"  - 错误: {publish_result.error_message}")
                    logger.error("  - 元数据已保存到 publish.json，可手动重试")

            except Exception as e:
                logger.warning(f"发布失败: {e}")
                # 保存失败元数据
                from .models.schemas import PublishResult
                failed_result = PublishResult(
                    published=False,
                    publish_time=datetime.now().isoformat(),
                    error_message=str(e),
                    content_snapshot=content.model_dump(),
                    image_paths=[str(p) for p in image_paths]
                )
                save_json(project_dir / "publish.json", failed_result.model_dump())
                logger.info("元数据已保存，可稍后手动重试")

        # ==================== 完成 ====================
        # 注：审核已内置到各 Agent 的 Reflexion 循环中
        logger.info("=" * 60)
        logger.info("工作流完成！")
        logger.info("=" * 60)
        logger.info("输出文件:")
        logger.info(f"  - {project_dir / 'research.json'}")
        logger.info(f"  - {project_dir / 'content.json'}")
        if image_result:
            logger.info(f"  - {project_dir / 'image.json'}")
            for img in image_result.images:
                logger.info(f"  - {img.image_path}")
            # 发布结果（如果执行了发布）
            publish_json = project_dir / 'publish.json'
            if publish_json.exists():
                logger.info(f"  - {publish_json}")

        logger.info("预览内容:")
        logger.info("-" * 60)
        logger.info(f"标题: {content.title}")
        logger.info(f"正文: {content.body[:100]}...")
        logger.info(f"标签: {' '.join(['#' + tag for tag in content.hashtags])}")
        logger.info(f"互动: {content.call_to_action}")
        logger.info("-" * 60)

    except Exception as e:
        logger.error(f"错误: {e}")
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
