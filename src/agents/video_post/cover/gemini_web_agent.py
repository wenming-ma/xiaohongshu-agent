"""LLM-driven Gemini Web image generation agent.

Replaces the hard-coded GeminiWebImageClient with a pydantic-ai Agent
that uses Playwright MCP tools to autonomously navigate Gemini's UI.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, Tool
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.usage import UsageLimits

from ....core.base_agent import BaseAgent, ValidationResult
from ....config.settings import APIConfig, PathConfig, RetryConfig, TimeoutConfig
from ....utils.providers import get_text_model
from ....utils.playwright_artifacts import install_playwright_artifact_guard
from ....utils.logger import get_logger
from ..schemas import CoverImageResult
from .prompts import gemini_web_system_prompt, gemini_web_user_prompt

logger = get_logger(__name__)

_CANVAS_EXTRACT_JS = """async (page) => {
  const imgs = document.querySelectorAll('img');
  let target = null;
  for (const img of imgs) {
    if (img.naturalWidth > 200 && img.alt && img.alt.includes('AI generated')) {
      target = img;
      break;
    }
  }
  if (!target) return JSON.stringify({ok: false, error: 'No AI-generated image found on page'});
  const canvas = document.createElement('canvas');
  canvas.width = target.naturalWidth;
  canvas.height = target.naturalHeight;
  canvas.getContext('2d').drawImage(target, 0, 0);
  const dataUrl = canvas.toDataURL('image/png');
  return JSON.stringify({ok: true, dataUrl, width: target.naturalWidth, height: target.naturalHeight});
}"""


_gemini_account_index = 0


def _pick_gemini_session_dir() -> str:
    global _gemini_account_index
    base = Path(PathConfig.BROWSER_SESSION_GEMINI)
    base.mkdir(parents=True, exist_ok=True)
    accounts = sorted(d for d in base.iterdir() if d.is_dir() and d.name.startswith("account"))
    if not accounts:
        return str(base)
    chosen = accounts[_gemini_account_index % len(accounts)]
    _gemini_account_index += 1
    logger.info("[GeminiWebAgent] 使用账号会话: %s", chosen.name)
    return str(chosen)


def _create_gemini_mcp_server(output_dir: Path) -> MCPServerStdio:
    output_dir.mkdir(parents=True, exist_ok=True)
    session_dir = _pick_gemini_session_dir()
    server = MCPServerStdio(
        command="npx",
        args=[
            "-y", "@playwright/mcp@latest",
            "--browser", "chrome",
            "--user-data-dir", session_dir,
            "--output-dir", str(output_dir),
        ],
        env={
            "HEADLESS": "false",
            "BROWSER_TYPE": "chrome",
            "USER_DATA_DIR": session_dir,
        },
        cwd=str(output_dir),
        tool_prefix="playwright",
        max_retries=RetryConfig.MCP_RETRIES,
        timeout=TimeoutConfig.MCP_INIT_TIMEOUT,
    )
    install_playwright_artifact_guard(server)
    return server


class SaveImageTool:
    """Extracts the AI-generated image from Gemini page via canvas and saves to disk."""

    def __init__(self, mcp_server: MCPServerStdio):
        self._mcp = mcp_server
        self._output_path: Path | None = None

    def bind(self, output_path: Path) -> None:
        self._output_path = output_path

    def get_tool(self) -> Tool:
        return Tool(self.save_image_to_disk, takes_ctx=False)

    async def save_image_to_disk(self) -> str:
        """从当前 Gemini 页面提取 AI 生成的图片并保存到磁盘。生成完成后必须调用此工具保存图片。"""
        if self._output_path is None:
            return json.dumps({"ok": False, "error": "未绑定输出路径"}, ensure_ascii=False)

        try:
            payload = await self._mcp.direct_call_tool(
                name="browser_run_code",
                args={"code": _CANVAS_EXTRACT_JS},
            )
            text = self._extract_text(payload)
            result = json.loads(text)
        except Exception as e:
            return json.dumps({"ok": False, "error": f"canvas 提取失败: {e}"}, ensure_ascii=False)

        if not result.get("ok"):
            return json.dumps(result, ensure_ascii=False)

        data_url: str = result["dataUrl"]
        b64 = data_url.split(",", 1)[1]
        data = base64.b64decode(b64)

        if len(data) < 1024:
            return json.dumps({"ok": False, "error": f"图片数据过小: {len(data)} bytes"}, ensure_ascii=False)

        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._output_path.write_bytes(data)
        size_kb = len(data) // 1024
        logger.info("[GeminiWebAgent] 图片已保存: %s (%d KB)", self._output_path.name, size_kb)
        return json.dumps({
            "ok": True,
            "path": str(self._output_path),
            "size_kb": size_kb,
            "width": result.get("width"),
            "height": result.get("height"),
        }, ensure_ascii=False)

    @staticmethod
    def _extract_text(payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            if "text" in payload:
                return str(payload["text"])
            for v in payload.values():
                if isinstance(v, str):
                    return v
        if isinstance(payload, (list, tuple)):
            for item in payload:
                if isinstance(item, str):
                    return item
                if isinstance(item, dict) and "text" in item:
                    return str(item["text"])
        return str(payload)


class GeminiWebAgent(BaseAgent):

    role = "Gemini Web 图片生成操作员"
    goal = "通过浏览器在 Gemini 网页上生成图片"

    def __init__(self, output_dir: Path | None = None):
        self._output_dir = output_dir or PathConfig.DOWNLOADS_DIR
        super().__init__()

    def init_tools(self) -> None:
        self.mcp_server = _create_gemini_mcp_server(Path(self._output_dir))
        self.save_tool = SaveImageTool(self.mcp_server)

    def init_agent(self) -> None:
        self.agent = Agent(
            model=get_text_model(),
            output_type=CoverImageResult,
            toolsets=[self.mcp_server],
            tools=[self.save_tool.get_tool()],
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(gemini_web_system_prompt(gemini_url=APIConfig.GEMINI_URL),),
        )

    async def forward(
        self,
        prompt: str,
        output_path: Path,
        reference_images: list[Path] | None = None,
    ) -> CoverImageResult:
        logger.info("[GeminiWebAgent] 开始生成图片: %s", output_path.name)

        # Rebuild MCP if output dir changed
        target_dir = output_path.parent
        if str(target_dir) != str(self._output_dir):
            self._output_dir = target_dir
            self.init_tools()
            self.init_agent()

        self.save_tool.bind(output_path)

        ref_text = "无"
        if reference_images:
            valid = [p for p in reference_images if p.exists()]
            if valid:
                ref_text = "\n".join(f"- {p.absolute()}" for p in valid)
                logger.info("[GeminiWebAgent] 附加 %d 张参考图片", len(valid))

        user_prompt = gemini_web_user_prompt(
            prompt=prompt,
            reference_images=ref_text,
            output_path=str(output_path.absolute()),
        )

        result = await self.step(user_prompt)

        if result.success and output_path.exists() and output_path.stat().st_size > 0:
            logger.info("[GeminiWebAgent] 封面生成成功: %s", output_path.name)
        elif result.success:
            result.success = False
            result.error_message = "Agent 报告成功但文件不存在或为空"

        return result

    async def step(self, user_prompt: str) -> CoverImageResult:
        async with self.mcp_server:
            result = await self.agent.run(
                user_prompt,
                usage_limits=UsageLimits(request_limit=None),
            )
            return result.output

    async def validate(self, output: Any) -> ValidationResult:
        if isinstance(output, CoverImageResult) and output.success:
            return ValidationResult.success("图片生成成功")
        msg = output.error_message if isinstance(output, CoverImageResult) else "输出类型错误"
        return ValidationResult.failure(msg)
