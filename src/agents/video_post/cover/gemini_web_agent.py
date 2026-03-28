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
from ...shared.utils.image_sanitizer import sanitize_image
from ....utils.providers import get_text_model
from ...shared.utils.playwright_artifacts import install_playwright_artifact_guard
from ...shared.utils.watermark_remover import remove_gemini_watermark
from ....utils.logger import get_logger
from ..schemas import CoverImageResult
from .prompts import gemini_web_system_prompt, gemini_web_user_prompt

logger = get_logger(__name__)

_IMAGE_METADATA_JS = """() => {
  const isVisible = (img) => {
    const rect = img.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const candidates = [];
  for (const [index, img] of Array.from(document.images).entries()) {
    const src = img.currentSrc || img.src || '';
    if (!src || img.naturalWidth < 200 || img.naturalHeight < 200) continue;
    const rect = img.getBoundingClientRect();
    const score =
      (isVisible(img) ? 1_000_000 : 0) +
      ((img.alt || '').includes('AI generated') ? 500_000 : 0) +
      Math.round(rect.width * rect.height) +
      index;
    candidates.push({
      index,
      score,
      src,
      width: img.naturalWidth,
      height: img.naturalHeight,
      alt: img.alt || '',
    });
  }
  if (!candidates.length) {
    return JSON.stringify({ok: false, error: 'No generated image candidate found on page'});
  }
  candidates.sort((a, b) => a.score - b.score);
  const target = candidates[candidates.length - 1];
  return JSON.stringify({
    ok: true,
    src: target.src,
    width: target.width,
    height: target.height,
    alt: target.alt,
    candidateCount: candidates.length,
  });
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
    """Downloads the Gemini image to disk with URL-first fallbacks."""

    def __init__(self, mcp_server: MCPServerStdio):
        self._mcp = mcp_server
        self._output_path: Path | None = None
        self._saved_path: Path | None = None

    def bind(self, output_path: Path) -> None:
        self._output_path = output_path
        self._saved_path = None

    def get_tool(self) -> Tool:
        return Tool(self.save_image_to_disk, takes_ctx=False)

    @property
    def saved_path(self) -> Path | None:
        return self._saved_path

    async def save_image_to_disk(self) -> str:
        """从当前 Gemini 页面提取 AI 生成的图片并保存到磁盘。生成完成后必须调用此工具保存图片。"""
        if self._output_path is None:
            return json.dumps({"ok": False, "error": "未绑定输出路径"}, ensure_ascii=False)

        try:
            image_meta = await self._call_tool_json(
                name="browser_evaluate",
                args={"function": _IMAGE_METADATA_JS},
            )
        except Exception as e:
            return json.dumps(
                {"ok": False, "error": f"图片定位失败: {type(e).__name__}: {e}"},
                ensure_ascii=False,
            )

        if not image_meta.get("ok"):
            return json.dumps(image_meta, ensure_ascii=False)

        try:
            source_url = str(image_meta.get("src") or "").strip()
            if not source_url:
                raise ValueError("图片候选缺少 src")
            data_url, download_source = await self._resolve_image_data_url(source_url)
            data = self._decode_data_url(data_url)
        except Exception as e:
            return json.dumps(
                {"ok": False, "error": f"图片下载失败: {type(e).__name__}: {e}"},
                ensure_ascii=False,
            )

        if len(data) < 1024:
            return json.dumps({"ok": False, "error": f"图片数据过小: {len(data)} bytes"}, ensure_ascii=False)

        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._output_path.write_bytes(data)
        self._saved_path = self._output_path
        size_kb = len(data) // 1024
        logger.info(
            "[GeminiWebAgent] 图片已保存: %s (%d KB, source=%s)",
            self._output_path.name,
            size_kb,
            download_source,
        )
        return json.dumps({
            "ok": True,
            "path": str(self._output_path),
            "size_kb": size_kb,
            "width": image_meta.get("width"),
            "height": image_meta.get("height"),
            "download_source": download_source,
        }, ensure_ascii=False)

    async def _resolve_image_data_url(self, source_url: str) -> tuple[str, str]:
        if source_url.startswith("data:"):
            return source_url, "data-url"
        if source_url.startswith(("http://", "https://")):
            result = await self._call_tool_json(
                name="browser_run_code",
                args={"code": self._build_request_download_code(source_url)},
            )
            if result.get("ok") and isinstance(result.get("dataUrl"), str):
                return result["dataUrl"], str(result.get("downloadSource") or "request")
            logger.warning("[GeminiWebAgent] request 下载失败，回退 canvas: %s", result.get("error"))
        return await self._extract_data_url_via_canvas(source_url)

    async def _extract_data_url_via_canvas(self, source_url: str) -> tuple[str, str]:
        result = await self._call_tool_json(
            name="browser_evaluate",
            args={"function": self._build_canvas_extract_js(source_url)},
        )
        if not result.get("ok") or not isinstance(result.get("dataUrl"), str):
            raise ValueError(result.get("error") or "canvas 提取失败")
        return result["dataUrl"], "canvas"

    async def _call_tool_json(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        payload = await self._mcp.direct_call_tool(name=name, args=args)
        result = self._normalize_payload(payload)
        if not isinstance(result, dict):
            raise ValueError(
                f"无法解析 {name} 返回值 ({self._summarize_payload(result)})"
            )
        return result

    @staticmethod
    def _decode_data_url(data_url: str) -> bytes:
        if "," not in data_url:
            raise ValueError("返回值不是合法 data URL")
        b64 = data_url.split(",", 1)[1]
        return base64.b64decode(b64)

    @staticmethod
    def _build_request_download_code(source_url: str) -> str:
        source_json = json.dumps(source_url)
        return f"""async (page) => {{
  const sourceUrl = {source_json};
  const response = await page.context().request.get(sourceUrl);
  if (!response.ok()) {{
    return {{ ok: false, error: `HTTP ${{response.status()}}`, sourceUrl }};
  }}
  const contentType = response.headers()['content-type'] || 'image/png';
  const body = await response.body();
  return {{
    ok: true,
    dataUrl: `data:${{contentType}};base64,${{Buffer.from(body).toString('base64')}}`,
    downloadSource: 'request',
    sourceUrl,
  }};
}}"""

    @staticmethod
    def _build_canvas_extract_js(source_url: str) -> str:
        source_json = json.dumps(source_url)
        return f"""() => {{
  const sourceUrl = {source_json};
  const candidates = Array.from(document.images).filter(
    (img) => img.naturalWidth > 200 && img.naturalHeight > 200
  );
  const target =
    candidates.find((img) => (img.currentSrc || img.src || '') === sourceUrl) ||
    candidates[candidates.length - 1];
  if (!target) {{
    return JSON.stringify({{ ok: false, error: 'No canvas extraction target found' }});
  }}
  const canvas = document.createElement('canvas');
  canvas.width = target.naturalWidth;
  canvas.height = target.naturalHeight;
  const ctx = canvas.getContext('2d');
  if (!ctx) {{
    return JSON.stringify({{ ok: false, error: 'Canvas 2D context unavailable' }});
  }}
  ctx.drawImage(target, 0, 0);
  return JSON.stringify({{
    ok: true,
    dataUrl: canvas.toDataURL('image/png'),
    width: target.naturalWidth,
    height: target.naturalHeight,
  }});
}}"""

    @classmethod
    def _normalize_payload(cls, payload: Any) -> Any:
        if isinstance(payload, dict) and "ok" in payload:
            return payload

        texts = cls._extract_text_fragments(payload)
        for fragment in texts:
            parsed = cls._try_parse_json(fragment)
            if parsed is not None:
                return parsed

        combined = "\n".join(fragment.strip() for fragment in texts if fragment.strip())
        parsed_combined = cls._try_parse_json(combined)
        if parsed_combined is not None:
            return parsed_combined

        return combined or payload

    @classmethod
    def _extract_text_fragments(cls, payload: Any) -> list[str]:
        texts: list[str] = []
        if payload is None:
            return texts
        if isinstance(payload, str):
            texts.append(payload)
            return texts
        if isinstance(payload, dict):
            if isinstance(payload.get("text"), str):
                texts.append(payload["text"])
            for value in payload.values():
                texts.extend(cls._extract_text_fragments(value))
            return texts
        if isinstance(payload, (list, tuple)):
            for item in payload:
                texts.extend(cls._extract_text_fragments(item))
            return texts
        for attr in ("text", "content", "message", "markdown"):
            if hasattr(payload, attr):
                texts.extend(cls._extract_text_fragments(getattr(payload, attr)))
        return texts

    @staticmethod
    def _try_parse_json(candidate: str) -> Any | None:
        candidate = (candidate or "").strip()
        if not candidate:
            return None
        if candidate.startswith("```") and candidate.endswith("```"):
            lines = candidate.splitlines()
            if len(lines) >= 3:
                candidate = "\n".join(lines[1:-1]).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _summarize_payload(payload: Any, limit: int = 240) -> str:
        text = str(payload).strip().replace("\n", "\\n")
        if len(text) > limit:
            return text[: limit - 3] + "..."
        return text


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
        saved_path = self.save_tool.saved_path

        if result.success and saved_path and saved_path.exists() and saved_path.stat().st_size > 0:
            try:
                final_path = await self._post_process_saved_image(saved_path)
            except Exception as exc:
                result.success = False
                result.error_message = f"图片后处理失败: {type(exc).__name__}: {exc}"
            else:
                if not final_path.exists() or final_path.stat().st_size <= 0:
                    result.success = False
                    result.error_message = "图片后处理完成但输出文件不存在或为空"
                else:
                    result.cover_path = str(final_path)
                    logger.info("[GeminiWebAgent] 封面生成成功: %s", final_path.name)
        elif result.success:
            result.success = False
            result.error_message = "Agent 报告成功但保存文件不存在或为空"

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

    async def _post_process_saved_image(self, image_path: Path) -> Path:
        remove_gemini_watermark(image_path)
        logger.debug("[GeminiWebAgent] 去水印完成: %s", image_path.name)
        processed_path = await sanitize_image(image_path)
        logger.debug("[GeminiWebAgent] 去AI标记完成: %s", processed_path.name)
        return processed_path
