"""
测试 LoginAgent 登录知乎
"""
import asyncio
import sys
import io

# 修复 Windows 控制台 UTF-8 编码问题
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

from pathlib import Path
from pydantic_ai.mcp import MCPServerStdio

from src.agents.login import LoginAgent
from src.config.settings import PathConfig, RetryConfig, TimeoutConfig
from src.utils.logger import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)


async def test_login_zhihu():
    """测试登录知乎"""
    
    # 创建下载目录
    downloads_dir = PathConfig.DOWNLOADS_DIR
    downloads_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建 Playwright MCP Server
    mcp_server = MCPServerStdio(
        command='npx',
        args=['-y', '@playwright/mcp@latest', '--output-dir', str(downloads_dir)],
        env={
            'HEADLESS': 'false',
            'BROWSER_TYPE': 'chromium',
            'USER_DATA_DIR': PathConfig.BROWSER_SESSION_SHARED
        },
        tool_prefix='playwright',
        cache_tools=True,
        max_retries=RetryConfig.MCP_RETRIES,
        timeout=TimeoutConfig.MCP_INIT_TIMEOUT,
    )
    
    # 创建 LoginAgent（复用同一个 mcp_server）
    login_agent = LoginAgent(mcp_server=mcp_server)
    
    logger.info("=" * 50)
    logger.info("开始测试 LoginAgent 登录知乎")
    logger.info("=" * 50)
    logger.info("请注意查看 Telegram，Agent 会通过 Telegram 向你请求登录凭证")
    logger.info("=" * 50)
    
    # 启动 MCP Server 并执行登录
    async with mcp_server:
        result = await login_agent.request_auth(
            url="https://www.zhihu.com/signin",
            action="login",
            hint="知乎账号登录"
        )
    
    logger.info("=" * 50)
    logger.info("登录结果:")
    logger.info(f"  成功: {result.success}")
    logger.info(f"  类型: {result.auth_type}")
    logger.info(f"  消息: {result.message}")
    logger.info(f"  URL: {result.url}")
    logger.info("=" * 50)
    
    return result


if __name__ == "__main__":
    result = asyncio.run(test_login_zhihu())
    print(f"\n{'✅ 登录成功!' if result.success else '❌ 登录失败: ' + result.message}")
