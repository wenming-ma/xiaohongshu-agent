"""从 Phase 4（图片生成）恢复执行 pipeline，跳过已完成的研究/分组/内容步骤。

用法：
    uv run python workshop/resume_from_image.py posts/image-posts/20260321-230812-装修避雷40条全是我花了20万买的教训
    uv run python workshop/resume_from_image.py <output_dir> --no-publish
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.agents.image_post.schemas import ResearchResult, XHSContent
from src.utils.logger import get_logger
from src.utils.file_ops import save_json

logger = get_logger(__name__)


async def resume(output_dir: Path, publish: bool = True) -> None:
    from src.agents.image_post.image import ImageAgent
    from src.agents.image_post.publish import PublisherAgent

    # --- 加载已有数据 ---
    research_path = output_dir / "research.json"
    groups_path = output_dir / "groups.json"
    content_path = output_dir / "content.json"

    for p in (research_path, groups_path, content_path):
        if not p.exists():
            logger.error("缺少必要文件: %s", p)
            raise SystemExit(1)

    research = ResearchResult.model_validate_json(research_path.read_text(encoding="utf-8"))
    groups = json.loads(groups_path.read_text(encoding="utf-8"))
    content = XHSContent.model_validate_json(content_path.read_text(encoding="utf-8"))

    # 从 content.json 或目录名提取 topic
    topic = output_dir.name.split("-", 3)[-1] if "-" in output_dir.name else content.title

    logger.info("=" * 60)
    logger.info("恢复执行: 从 Phase 4（图片生成）开始")
    logger.info("=" * 60)
    logger.info("主题: %s", topic)
    logger.info("输出目录: %s", output_dir)
    logger.info("分组数: %d", len(groups))

    # --- Phase 4: 图片生成 ---
    logger.info("-" * 40)
    logger.info("Phase 4: 图片生成")
    logger.info("-" * 40)

    image_agent = ImageAgent()
    image_result = await image_agent.forward(
        content=content,
        research=research,
        topic=topic,
        output_dir=output_dir,
        groups=groups,
    )
    save_json(output_dir / "image.json", image_result.model_dump())

    image_paths = [img.image_path for img in image_result.images]
    logger.info("图片生成完成: %d 张", len(image_paths))

    # --- Phase 5: 发布 ---
    if publish:
        logger.info("-" * 40)
        logger.info("Phase 5: 发布到小红书")
        logger.info("-" * 40)

        publisher_agent = PublisherAgent()
        publish_result = await publisher_agent.forward(
            content=content,
            images=[Path(p) for p in image_paths],
            output_dir=output_dir,
        )
        save_json(output_dir / "publish.json", publish_result.model_dump())
        logger.info("发布完成: %s", publish_result.published)
    else:
        logger.info("跳过发布")

    logger.info("=" * 60)
    logger.info("恢复执行完成")
    logger.info("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="从图片生成步骤恢复 pipeline")
    parser.add_argument("output_dir", type=Path, help="已有输出目录路径")
    parser.add_argument("--no-publish", action="store_true", help="跳过发布步骤")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    asyncio.run(resume(output_dir, publish=not args.no_publish))


if __name__ == "__main__":
    main()
