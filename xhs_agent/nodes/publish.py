"""
Phase 4: 发布节点
使用 Playwright 自动发布到小红书
"""
from datetime import datetime
from pathlib import Path

from ..state import XHSState
from ..tools import write_json
from ..tools.browser import XiaohongshuPublisher


async def publish_node(state: XHSState) -> dict:
    """
    发布节点 - 使用 Playwright 发布到小红书

    Args:
        state: 当前工作流状态

    Returns:
        更新后的状态字段（publish_result）
    """
    content = state.get("content", {})
    images = state.get("images", [])
    project_dir = Path(state["project_dir"])

    if not content:
        error_msg = "No content to publish"
        return {
            "publish_result": {"status": "failed", "error": error_msg},
            "errors": [error_msg],
            "logs": [f"[{datetime.now().isoformat()}] ❌ {error_msg}"]
        }

    if not images:
        error_msg = "No images to publish"
        return {
            "publish_result": {"status": "failed", "error": error_msg},
            "errors": [error_msg],
            "logs": [f"[{datetime.now().isoformat()}] ❌ {error_msg}"]
        }

    try:
        # 提取内容信息
        title = content.get("title", "")
        body = content.get("body", "")
        hashtags = content.get("hashtags", [])

        # 合并标题和正文（小红书没有单独的标题字段）
        full_content = f"{title}\n\n{body}"

        print(f"\n📤 准备发布到小红书...")
        print(f"   标题: {title}")
        print(f"   正文长度: {len(body)} 字")
        print(f"   图片数量: {len(images)}")
        print(f"   话题标签: {hashtags}")

        # 使用浏览器自动化发布
        async with XiaohongshuPublisher(headless=False) as publisher:
            # 尝试加载已保存的session
            session_loaded = await publisher.load_session()

            if not session_loaded:
                # 如果没有session，需要先登录
                print("\n⚠️  未找到已保存的登录session")
                print("   请先运行登录流程：python -m langgraph.tools.browser")

                return {
                    "publish_result": {
                        "status": "failed",
                        "error": "No session found. Please login first.",
                        "note": "Run: python -m langgraph.tools.browser"
                    },
                    "current_phase": "completed",
                    "logs": [
                        f"[{datetime.now().isoformat()}] ❌ 未找到登录session",
                        "请先运行: python -m langgraph.tools.browser"
                    ]
                }

            # 发布笔记
            result = await publisher.publish_post(
                title=title,
                content=full_content,
                images=images,
                hashtags=hashtags
            )

            # 保存发布结果
            publish_result = {
                **result,
                "published_at": datetime.now().isoformat(),
                "images_uploaded": len(images)
            }
            write_json(project_dir / "publish-result.json", publish_result)

            # 记录日志
            if result["status"] == "success":
                log_message = f"[{datetime.now().isoformat()}] ✅ 发布成功: {result.get('post_url', 'N/A')}"
            else:
                log_message = f"[{datetime.now().isoformat()}] ❌ 发布失败: {result.get('error', 'Unknown error')}"

            return {
                "publish_result": publish_result,
                "current_phase": "completed",
                "logs": [log_message]
            }

    except Exception as e:
        error_msg = f"Publishing error: {str(e)}"
        publish_result = {
            "status": "failed",
            "error": error_msg,
            "published_at": datetime.now().isoformat()
        }
        write_json(project_dir / "publish-result.json", publish_result)

        return {
            "publish_result": publish_result,
            "current_phase": "completed",
            "errors": [error_msg],
            "logs": [f"[{datetime.now().isoformat()}] ❌ {error_msg}"]
        }
