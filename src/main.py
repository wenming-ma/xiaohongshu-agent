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
from dotenv import load_dotenv

# 修复 Windows 控制台 UTF-8 编码问题
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Logfire 可观测性配置
import logfire

# 'if-token-present' 表示如果没有配置 LOGFIRE_TOKEN，则不发送数据（本地模式）
logfire.configure(send_to_logfire='if-token-present')
logfire.instrument_pydantic_ai()

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
    print("=" * 60)
    print("🚀 小红书内容创作工作流（Pydantic-AI）")
    print("=" * 60)
    print(f"\n主题: {topic}")
    print(f"受众: {audience}\n")

    # 创建输出目录
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # 清理主题名（移除特殊字符）
    safe_topic = "".join(c for c in topic if c.isalnum() or c in (' ', '-', '_'))[:20]
    project_dir = Path("posts") / f"{timestamp}-{safe_topic}"
    project_dir.mkdir(parents=True, exist_ok=True)

    print(f"📁 输出目录: {project_dir}\n")

    try:
        # ==================== Phase 1: 研究 ====================
        print("=" * 60)
        print("📚 Phase 1: 小红书研究")
        print("=" * 60)

        # 🔑 创建 Agent（MCP 工具已在构造时注册）
        research_agent = ResearchAgent()
        print("   ✅ ResearchAgent 已创建（包含 Playwright MCP 工具）")

        research = await research_agent.research(topic, audience)

        # 保存研究结果
        save_json(project_dir / "research.json", research.model_dump())

        print(f"\n✅ 研究完成:")
        print(f"   - 实体: {len(research.entities)} 个")
        print(f"   - 案例: {len(research.cases)} 个")
        print(f"   - 关键词: {len(research.keywords)} 个")
        print(f"   - 可信度: {research.credibility}")
        print(f"   - 数据点: {research.data_points} 个")

        # ==================== Phase 2: 内容创作 ====================
        print("\n" + "=" * 60)
        print("✍️  Phase 2: 内容创作")
        print("=" * 60)

        content_agent = ContentAgent()
        content = await content_agent.create_content(research, topic)

        # 保存内容
        save_json(project_dir / "content.json", content.model_dump())

        print(f"\n✅ 内容创作完成:")
        print(f"   - 标题: {content.title}")
        print(f"   - 正文长度: {len(content.body)} 字")
        print(f"   - 标签: {', '.join(content.hashtags)}")

        # ==================== Phase 3: 配图生成（可选） ====================
        image_result = None
        if generate_image:
            print("\n" + "=" * 60)
            print("🎨 Phase 3: 配图生成")
            print("=" * 60)

            try:
                image_agent = ImageAgent()
                print("   ✅ ImageAgent 已创建（包含 Playwright MCP 工具）")

                image_result = await image_agent.generate_image(
                    content=content,
                    research=research,
                    topic=topic,
                    output_dir=project_dir
                )

                # 保存图片结果
                save_json(project_dir / "image.json", image_result.model_dump())

                print(f"\n✅ 配图生成完成:")
                print(f"   - 生成数量: {image_result.total_count} 张")
                for img in image_result.images:
                    print(f"   - {img.image_type}: {img.image_path}")
                print(f"   - 生成时间: {image_result.generated_at}")

            except Exception as e:
                print(f"\n⚠️ 配图生成失败: {e}")
                print("   继续完成其他步骤...")
        else:
            print("\n⏭️ 跳过配图生成（--no-image）")

        # ==================== 完成 ====================
        # 注：审核已内置到各 Agent 的 Reflexion 循环中
        print("\n" + "=" * 60)
        print("🎉 工作流完成！")
        print("=" * 60)
        print(f"\n输出文件:")
        print(f"   - {project_dir / 'research.json'}")
        print(f"   - {project_dir / 'content.json'}")
        if image_result:
            print(f"   - {project_dir / 'image.json'}")
            for img in image_result.images:
                print(f"   - {img.image_path}")

        print(f"\n预览内容:")
        print(f"{'─' * 60}")
        print(f"标题: {content.title}")
        print(f"\n{content.body}")
        print(f"\n标签: {' '.join(['#' + tag for tag in content.hashtags])}")
        print(f"\n{content.call_to_action}")
        print(f"{'─' * 60}")

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    """CLI 入口"""
    # 加载环境变量
    load_dotenv()

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
        print("\n\n⚠️  用户中断")
        sys.exit(0)


if __name__ == "__main__":
    main()
