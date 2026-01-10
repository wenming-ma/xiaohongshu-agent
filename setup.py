"""
简化的安装脚本
自动化环境配置过程
"""
import subprocess
import sys
from pathlib import Path


def print_section(title: str) -> None:
    """打印分节标题"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def install_dependencies() -> bool:
    """安装 Python 依赖"""
    print_section("安装 Python 依赖")

    print("📦 安装依赖包...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            check=True
        )
        print("   ✅ 完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"   ❌ 失败: {e}")
        return False


def install_mcp_server() -> bool:
    """安装 Playwright MCP Server"""
    print_section("安装 Playwright MCP Server")

    print("🌐 检查 Playwright MCP Server...")
    try:
        subprocess.run(
            ["npx", "-y", "@playwright/mcp@latest", "--version"],
            check=True,
            capture_output=True
        )
        print("   ✅ Playwright MCP Server 可用")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"   ⚠️  警告: {e}")
        print("   提示: 首次运行时会自动下载")
        return True


def setup_env_file() -> bool:
    """设置环境变量文件"""
    print_section("配置环境变量")

    env_file = Path(".env")
    env_example = Path(".env.example")

    if env_file.exists():
        print("⚠️  .env 文件已存在")
        return True

    if env_example.exists():
        import shutil
        shutil.copy(env_example, env_file)
        print("✅ 已创建 .env 文件（从 .env.example 复制）")
    else:
        env_content = """# Pydantic-AI 小红书内容创作工具

# Anthropic API（必需）
ANTHROPIC_API_KEY=your-api-key-here

# 可选：自定义 API 端点
# ANTHROPIC_BASE_URL=https://api.anthropic.com
"""
        env_file.write_text(env_content, encoding='utf-8')
        print("✅ 已创建 .env 文件")

    print("\n⚠️  请编辑 .env 文件，填入你的 ANTHROPIC_API_KEY")
    return True


def create_directories() -> bool:
    """创建必要的目录"""
    print_section("创建项目目录")

    dirs = ["posts", "browser-sessions"]
    for dir_name in dirs:
        dir_path = Path(dir_name)
        dir_path.mkdir(exist_ok=True)
        print(f"✅ {dir_name}/")

    return True


def print_next_steps() -> None:
    """打印下一步指引"""
    print_section("✅ 安装完成！")

    print("""
下一步：

1️⃣  配置 API 密钥:
   编辑 .env 文件，填入：
   - ANTHROPIC_API_KEY (必需)

2️⃣  运行第一个工作流:
   python -m src.main --topic "西安公司避坑指南" --audience "求职者"

3️⃣  查看输出:
   生成的内容保存在 posts/ 目录

📚 快速开始:
   - 查看 src/main.py 了解工作流
   - 查看 src/agents/ 了解 Agent 实现
   - 查看 .claude/mcp.json 了解 MCP 配置

🎉 祝你使用愉快！
""")


def main():
    """主安装流程"""
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║  Xiaohongshu Pydantic-AI Agent - 安装脚本                 ║
    ║  自动化环境配置和依赖安装                                  ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    # 安装依赖
    if not install_dependencies():
        print("\n❌ 依赖安装失败")
        sys.exit(1)

    # 安装 MCP Server
    install_mcp_server()

    # 设置环境变量
    if not setup_env_file():
        print("\n❌ 环境变量配置失败")
        sys.exit(1)

    # 创建目录
    if not create_directories():
        print("\n❌ 目录创建失败")
        sys.exit(1)

    # 打印下一步指引
    print_next_steps()


if __name__ == "__main__":
    main()
