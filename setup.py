"""
安装和设置脚本
自动化环境配置过程
"""
import subprocess
import sys
from pathlib import Path


def print_section(title):
    """打印分节标题"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def run_command(cmd, description):
    """运行命令并显示进度"""
    print(f"🔧 {description}...")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=True,
            capture_output=True,
            text=True
        )
        print(f"   ✅ 完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"   ❌ 失败: {e.stderr}")
        return False


def check_python_version():
    """检查 Python 版本"""
    print_section("检查 Python 版本")
    version = sys.version_info
    print(f"Python 版本: {version.major}.{version.minor}.{version.micro}")

    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print("❌ 需要 Python 3.10 或更高版本")
        return False

    print("✅ Python 版本符合要求")
    return True


def install_dependencies():
    """安装 Python 依赖"""
    print_section("安装 Python 依赖")

    if not run_command(
        f"{sys.executable} -m pip install -r requirements.txt",
        "安装依赖包"
    ):
        return False

    if not run_command(
        "playwright install chromium",
        "安装 Playwright 浏览器"
    ):
        return False

    return True


def setup_env_file():
    """设置环境变量文件"""
    print_section("配置环境变量")

    env_file = Path(".env")
    env_example = Path(".env.example")

    if env_file.exists():
        print("⚠️  .env 文件已存在")
        response = input("是否覆盖? (y/N): ")
        if response.lower() != 'y':
            print("跳过 .env 配置")
            return True

    if env_example.exists():
        # 复制示例文件
        import shutil
        shutil.copy(env_example, env_file)
        print("✅ 已创建 .env 文件")
    else:
        # 创建基础 .env 文件
        env_content = """# API Keys for LangGraph Xiaohongshu Agent

# Anthropic API (for Claude models)
ANTHROPIC_API_KEY=

# OpenAI API (for GPT-4 and DALL-E 3)
OPENAI_API_KEY=

# Google Generative AI (for Gemini models)
GOOGLE_API_KEY=
"""
        env_file.write_text(env_content)
        print("✅ 已创建 .env 文件")

    print("\n⚠️  请编辑 .env 文件，填入你的 API 密钥")
    print("   必需: ANTHROPIC_API_KEY, OPENAI_API_KEY")
    print("   可选: GOOGLE_API_KEY")

    return True


def verify_environment():
    """验证环境配置"""
    print_section("验证环境配置")

    # 检查环境变量
    result = subprocess.run(
        f"{sys.executable} config.py",
        shell=True,
        capture_output=True,
        text=True
    )

    print(result.stdout)

    if "Environment check passed" in result.stdout:
        print("\n✅ 环境配置验证成功！")
        return True
    else:
        print("\n❌ 环境配置验证失败")
        print("请检查 .env 文件中的 API 密钥是否正确")
        return False


def create_directories():
    """创建必要的目录"""
    print_section("创建项目目录")

    dirs = ["posts", ".checkpoints"]
    for dir_name in dirs:
        dir_path = Path(dir_name)
        dir_path.mkdir(exist_ok=True)
        print(f"✅ {dir_name}/")

    return True


def print_next_steps():
    """打印下一步指引"""
    print_section("✅ 安装完成！")

    print("""
下一步：

1️⃣  配置 API 密钥（如果还没有）:
   编辑 .env 文件，填入：
   - ANTHROPIC_API_KEY (必需)
   - OPENAI_API_KEY (必需)
   - GOOGLE_API_KEY (可选)

2️⃣  小红书登录（一次性）:
   python -m langgraph.tools.browser

3️⃣  运行第一个工作流:
   python main.py --topic "西安公司避坑指南" --audience "求职者"

4️⃣  查看快速开始指南:
   查看 QUICKSTART.md 了解更多用法

📚 文档:
   - README.md - 完整说明文档
   - QUICKSTART.md - 5分钟快速上手
   - config.py - 模型配置说明

🎉 祝你使用愉快！
""")


def main():
    """主安装流程"""
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║  Xiaohongshu LangGraph Agent - 安装脚本                    ║
    ║  自动化环境配置和依赖安装                                  ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    # 检查 Python 版本
    if not check_python_version():
        sys.exit(1)

    # 安装依赖
    if not install_dependencies():
        print("\n❌ 依赖安装失败")
        sys.exit(1)

    # 设置环境变量
    if not setup_env_file():
        print("\n❌ 环境变量配置失败")
        sys.exit(1)

    # 创建目录
    if not create_directories():
        print("\n❌ 目录创建失败")
        sys.exit(1)

    # 验证环境
    verify_environment()

    # 打印下一步指引
    print_next_steps()


if __name__ == "__main__":
    main()
