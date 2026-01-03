"""测试 MCP Server 是否能正常启动"""
import asyncio
from pydantic_ai.mcp import MCPServerStdio

async def test_mcp():
    mcp = MCPServerStdio(
        command='npx',
        args=['-y', '@playwright/mcp'],
        env={
            'HEADLESS': 'false',
            'BROWSER_TYPE': 'chromium',
            'USER_DATA_DIR': './browser-sessions/xiaohongshu'
        },
        tool_prefix='playwright',
        cache_tools=True,
    )

    print("Starting MCP Server...")
    try:
        async with mcp as server:
            print("MCP Server started successfully")
            tools = await server.list_tools()
            print(f"Found {len(tools)} tools")
            for tool in tools[:3]:
                print(f"  - {tool.name}")
    except Exception as e:
        print(f"MCP Server failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_mcp())
