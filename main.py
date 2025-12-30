"""
Xiaohongshu LangGraph 主入口文件

使用方法：
    python main.py --topic "西安公司避坑指南" --audience "求职者"
"""
import asyncio
import argparse
from pathlib import Path

from xhs_agent.graph import create_xiaohongshu_workflow
from xhs_agent.state import create_initial_state, XHSState
from config import check_environment, POSTS_DIR


async def run_xiaohongshu_workflow(
    topic: str,
    target_audience: str = "年轻女性",
    num_images: int = 3
) -> XHSState:
    """
    运行完整的小红书内容创建工作流

    Args:
        topic: 主题
        target_audience: 目标受众
        num_images: 需要的图片数量

    Returns:
        最终状态
    """
    # 确保环境配置正确
    if not check_environment():
        raise RuntimeError("Environment check failed. Please set API keys in .env file")

    # 创建初始状态
    initial_state = create_initial_state(topic, target_audience, num_images)

    # 创建工作流
    app = create_xiaohongshu_workflow()

    # 打印工作流信息
    print(f"\n{'='*60}")
    print(f"🎯 主题: {topic}")
    print(f"👥 目标受众: {target_audience}")
    print(f"📸 图片数量: {num_images}")
    print(f"📁 项目目录: {initial_state['project_dir']}")
    print(f"{'='*60}\n")

    # 运行工作流（带流式输出）
    print("⏳ 启动工作流...\n")

    config = {"configurable": {"thread_id": initial_state["project_id"]}}

    final_state = None
    async for event in app.astream(initial_state, config):
        # 打印节点执行信息
        for node_name, node_state in event.items():
            if node_name != "__end__":
                print(f"✓ 节点完成: {node_name}")

                # 打印日志
                if "logs" in node_state:
                    for log in node_state["logs"]:
                        print(f"  📝 {log}")

                final_state = node_state

    print(f"\n{'='*60}")
    print("✅ 工作流完成！")
    print(f"{'='*60}\n")

    return final_state


async def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="LangGraph Xiaohongshu 内容创建工作流"
    )
    parser.add_argument(
        "--topic",
        type=str,
        required=True,
        help="主题（例如：西安公司避坑指南）"
    )
    parser.add_argument(
        "--audience",
        type=str,
        default="年轻女性",
        help="目标受众（默认：年轻女性）"
    )
    parser.add_argument(
        "--images",
        type=int,
        default=3,
        help="图片数量（默认：3）"
    )

    args = parser.parse_args()

    # 运行工作流
    final_state = await run_xiaohongshu_workflow(
        topic=args.topic,
        target_audience=args.audience,
        num_images=args.images
    )

    # 打印最终结果摘要
    if final_state:
        print("\n📊 最终结果摘要：")
        print(f"  • 当前阶段: {final_state.get('current_phase', 'unknown')}")

        if final_state.get("content"):
            content = final_state["content"]
            print(f"  • 标题: {content.get('title', 'N/A')}")
            print(f"  • 实体数量: {len(content.get('entities_used', []))}")
            print(f"  • 多平台验证: {content.get('multi_platform_verified_count', 0)}")

        if final_state.get("publish_result"):
            pub = final_state["publish_result"]
            print(f"  • 发布状态: {pub.get('status', 'unknown')}")
            print(f"  • 发布URL: {pub.get('post_url', 'N/A')}")

        print(f"\n📁 项目文件位置: {final_state.get('project_dir', 'N/A')}\n")


if __name__ == "__main__":
    asyncio.run(main())
