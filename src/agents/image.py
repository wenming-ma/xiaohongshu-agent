"""
图片生成 Agent
使用 Gemini 网页生成小红书配图
通过 Playwright MCP 操作 Gemini 网页

所有提示词统一在 prompts/image.yaml 管理

验证机制（通过类装饰器实现）：
- @GeminiConfigValidator: 每张图片生成后验证 Gemini 配置（Create images + Pro）
- @ImageQualityValidator: 验证图片质量（字迹清晰、风格匹配）
"""
import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic_ai import Agent, Tool, RunContext
from pydantic_ai.mcp import MCPServerStdio

from ..models.schemas import (
    ImageResult,
    GeneratedImage,
    XHSContent,
    ResearchResult,
    ImageGroupingPlan,
    ImageGroupingReviewResult,
    GeminiOperationResult,
    GroupSpec,
    CompactKeyInfo,
    ImageTypeSpec,
    ImageGenContext,
)
from ..utils.model_factory import get_model
from ..utils.openrouter_provider import get_openrouter_model
from ..utils.download_manager import DownloadManager
from ..utils.retry_handler import with_retry
from ..utils.logger import get_logger
from ..utils.tool_feedback import build_toolset_with_telegram_feedback
from ..validators import GeminiConfigValidator, ImageQualityValidator
from ..config.settings import RetryConfig, ImageConfig, PathConfig, TimeoutConfig, APIConfig
from prompts import get_system_prompt, get_user_prompt, get_prompt_field
from .login import LoginAgent

logger = get_logger(__name__)


class ImageAgent:
    """Gemini 图片生成 Agent"""

    @staticmethod
    async def _block_browser_close(
        ctx: RunContext[Any],
        call_tool,
        name: str,
        args: dict[str, Any]
    ):
        """
        拦截并阻止关闭浏览器的工具调用。

        浏览器需要保持打开状态，以便 @GeminiConfigValidator 装饰器
        在图片生成后截屏验证 Gemini 配置。

        Args:
            ctx: 运行上下文
            call_tool: 原始工具调用函数
            name: 工具名称
            args: 工具参数

        Returns:
            工具调用结果，或阻止消息
        """
        if name == 'browser_close':
            logger.debug("拦截 browser_close 调用：浏览器需要保持打开状态以供验证")
            return {"content": [{"type": "text", "text": "操作已跳过：浏览器需要保持打开状态以供后续验证。"}]}
        return await call_tool(name, args, None)

    def __init__(self):
        """初始化图片生成 Agent"""
        # ==================== 1. 配置参数 ====================
        self.gemini_url = APIConfig.GEMINI_URL

        # ==================== 2. 路径配置 ====================
        self.downloads_dir = PathConfig.DOWNLOADS_DIR
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

        # ==================== 3. 内部状态 ====================
        self._operation_start_time: Optional[float] = None

        # ==================== 4. 工具/管理器 ====================
        self.download_manager = DownloadManager(download_dir=self.downloads_dir)

        # ==================== 5. MCP Server ====================
        # Playwright MCP - 控制浏览器生成图片
        # 注：验证截屏由 @GeminiConfigValidator 装饰器处理
        # 注：process_tool_call 回调用于拦截 browser_close，确保截屏验证前浏览器保持打开
        self.mcp_server = MCPServerStdio(
            command='npx',
            args=['-y', '@playwright/mcp@latest', '--output-dir', str(self.downloads_dir)],
            env={
                'HEADLESS': 'false',
                'BROWSER_TYPE': 'chromium',
                'USER_DATA_DIR': PathConfig.BROWSER_SESSION_GEMINI
            },
            tool_prefix='playwright',
            cache_tools=True,
            max_retries=RetryConfig.MCP_RETRIES,
            timeout=TimeoutConfig.MCP_INIT_TIMEOUT,  # 初始化超时（npx + Playwright 启动）
            process_tool_call=ImageAgent._block_browser_close,  # 拦截 browser_close 调用
        )

        # LoginAgent - 用于处理登录/注册（复用同一个 Playwright MCP/浏览器会话）
        self.login_agent = LoginAgent(mcp_server=self.mcp_server)

        # ==================== 6. Agents ====================
        # 获取带 HTTP 重试的 Model（根据配置选择 Anthropic 或 OpenRouter）
        model = get_model()

        # 提示词生成 Agent（使用依赖注入传递验证反馈）
        self.prompt_generator = Agent(
            model=model,
            output_type=str,
            deps_type=ImageGenContext,  # 依赖注入：验证反馈通过 deps 传递
            instrument=True,
        )

        # 为 prompt_generator 注册动态 system_prompt
        # 当 gen_ctx.validation_feedback 不为空时，会将反馈追加到系统提示词
        @self.prompt_generator.system_prompt
        async def _dynamic_system_prompt(ctx: RunContext[ImageGenContext]) -> str:
            base_prompt = get_system_prompt("image")
            if ctx.deps.validation_feedback:
                return (
                    base_prompt +
                    "\n\n## 🚨 上次生成的图片问题（必须修复）\n"
                    f"{ctx.deps.validation_feedback}\n\n"
                    "请根据上述反馈调整提示词，确保生成的图片符合要求。"
                )
            return base_prompt

        # 语义分组 Agent（将 key_infos 分组后再分发到详情图）
        self.grouping_agent = Agent(
            model=model,
            output_type=ImageGroupingPlan,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(get_system_prompt("image_grouping"),),
        )

        # 分组审核 Agent（使用 OpenRouter 模型，验证分组是否合理，失败则触发重新分组）
        self.grouping_reviewer = Agent(
            model=get_openrouter_model("google/gemma-3-27b-it:free"),
            output_type=ImageGroupingReviewResult,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(get_system_prompt("image_grouping_review"),),
        )

        # Gemini 操作 Agent（结构化输出）
        function_tools = [
            Tool(self._check_download_status, takes_ctx=False),
            self.login_agent.get_tool(),  # 登录/注册工具
        ]
        self.gemini_operator = Agent(
            model=model,
            output_type=GeminiOperationResult,
            toolsets=[
                build_toolset_with_telegram_feedback(
                    toolsets=[self.mcp_server],
                    tools=function_tools,
                )
            ],
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(get_prompt_field("image", "gemini_operator_prompt"),),
        )

    # ==================== 工具方法 ====================

    def _check_download_status(self) -> str:
        """
        检查下载目录是否有新的 PNG 图片文件。
        在点击下载按钮后调用此工具确认下载是否完成。

        Returns:
            "DOWNLOADED: 文件名" 表示下载成功
            "NOT_FOUND" 表示未找到新文件
        """
        if self._operation_start_time is None:
            return "NOT_FOUND: 操作未开始"

        for f in self.downloads_dir.glob("*.png"):
            if f.stat().st_mtime > self._operation_start_time:
                if not f.suffix.endswith(('.crdownload', '.tmp', '.part')):
                    return f"DOWNLOADED: {f.name} ({f.stat().st_size / 1024:.0f}KB)"

        return "NOT_FOUND: 下载目录中没有新文件"

    @staticmethod
    def _build_compact_items(key_infos: list[dict[str, Any]]) -> list[CompactKeyInfo]:
        """
        将 key_infos 转换为精简格式，用于 LLM 输入（降低 token）。

        Args:
            key_infos: 原始 key_info 列表

        Returns:
            精简的 CompactKeyInfo 列表
        """
        max_text_len = ImageConfig.COMPACT_TEXT_MAX_LEN
        compact_items: list[CompactKeyInfo] = []
        for i, info in enumerate(key_infos):
            name = info.get("name") or info.get("title") or ""
            desc = info.get("description") or info.get("detail") or info.get("desc") or ""
            text = f"{name}: {desc}".strip(": ").strip()
            compact_items.append({
                "index": i,
                "type": info.get("type"),
                "name": name,
                "text": text[:max_text_len],
            })
        return compact_items

    async def _semantic_group_key_infos(
        self,
        *,
        topic: str,
        research: ResearchResult,
        max_group_size: int,
        target_groups: int,
        review_feedback: str | None = None,
    ) -> list[GroupSpec]:
        """
        使用 LLM 对 key_infos 做语义分组，然后进行确定性归一化（去重/补漏/拆分/合并）。

        Args:
            topic: 主题
            research: 研究数据
            max_group_size: 单组最大条数
            target_groups: 目标分组数
            review_feedback: 上一轮审核反馈（可选）

        Returns:
            归一化后的分组列表
        """
        key_infos = research.key_infos or []
        n = len(key_infos)
        if n == 0:
            return []

        compact_items = self._build_compact_items(key_infos)

        user_prompt = get_user_prompt(
            "image_grouping",
            topic=topic,
            key_infos_json=json.dumps(compact_items, ensure_ascii=False, indent=2),
            max_group_size=max_group_size,
            target_groups=target_groups,
        )
        if review_feedback:
            user_prompt += (
                "\n\n=== 上轮分组审核反馈（请修复）===\n"
                f"{review_feedback}\n"
                "请根据反馈重新分组，确保覆盖完整且分组语义一致。"
            )

        grouping_result = await self.grouping_agent.run(user_prompt)
        plan: ImageGroupingPlan = grouping_result.output
        groups = self._normalize_grouping_plan(plan, n, max_group_size)
        self._validate_groups(groups, n, max_group_size)
        return groups

    # ==================== 分组归一化辅助方法 ====================

    @staticmethod
    def _dedupe_and_filter_indices(
        raw_groups: list,
        n_key_infos: int,
    ) -> tuple[list[GroupSpec], set[int]]:
        """
        去重并过滤越界 indices。

        Args:
            raw_groups: LLM 输出的原始分组
            n_key_infos: key_infos 总数

        Returns:
            (清理后的分组列表, 已使用的索引集合)
        """
        seen: set[int] = set()
        cleaned: list[GroupSpec] = []
        for g in raw_groups:
            title = (g.title or "").strip() or "其他"
            indices: list[int] = []
            for idx in (g.indices or []):
                if not isinstance(idx, int):
                    continue
                if idx < 0 or idx >= n_key_infos:
                    continue
                if idx in seen:
                    continue
                seen.add(idx)
                indices.append(idx)
            if indices:
                indices.sort()
                cleaned.append({"title": title, "indices": indices})
        return cleaned, seen

    @staticmethod
    def _fill_missing_indices(
        groups: list[GroupSpec],
        seen: set[int],
        n_key_infos: int,
    ) -> list[GroupSpec]:
        """
        补齐未被分配的 indices 到"其他补充"组。

        Args:
            groups: 当前分组列表
            seen: 已使用的索引集合
            n_key_infos: key_infos 总数

        Returns:
            更新后的分组列表
        """
        missing = [i for i in range(n_key_infos) if i not in seen]
        if missing:
            groups.append({"title": "其他补充", "indices": missing})
        return groups

    @staticmethod
    def _split_large_groups(
        groups: list[GroupSpec],
        max_group_size: int,
    ) -> list[GroupSpec]:
        """
        将超过 max_group_size 的组拆分为多个子组。

        Args:
            groups: 分组列表
            max_group_size: 单组最大条数

        Returns:
            拆分后的分组列表
        """
        split_groups: list[GroupSpec] = []
        for g in groups:
            idxs = g["indices"]
            if len(idxs) <= max_group_size:
                split_groups.append(g)
            else:
                chunks = [idxs[i : i + max_group_size] for i in range(0, len(idxs), max_group_size)]
                for ci, chunk in enumerate(chunks, start=1):
                    split_groups.append({"title": f"{g['title']}（续{ci}）", "indices": chunk})
        return split_groups

    @staticmethod
    def _merge_small_groups(
        groups: list[GroupSpec],
        min_group_size: int,
        max_group_size: int,
    ) -> list[GroupSpec]:
        """
        将过小的组合并到前一个组。

        Args:
            groups: 分组列表
            min_group_size: 最小组大小（低于此值尝试合并）
            max_group_size: 单组最大条数

        Returns:
            合并后的分组列表
        """
        merged: list[GroupSpec] = []
        for g in groups:
            if not merged:
                merged.append(dict(g))  # shallow copy
                continue
            if len(g["indices"]) < min_group_size:
                prev = merged[-1]
                if len(prev["indices"]) + len(g["indices"]) <= max_group_size:
                    new_indices = sorted(prev["indices"] + g["indices"])
                    merged[-1] = {"title": prev["title"], "indices": new_indices}
                    continue
            merged.append(dict(g))
        return merged

    def _normalize_grouping_plan(
        self,
        plan: ImageGroupingPlan,
        n_key_infos: int,
        max_group_size: int,
        min_group_size: int | None = None,
    ) -> list[GroupSpec]:
        """
        归一化分组计划：去重 → 补漏 → 拆分大组 → 合并小组 → 覆盖校验。

        Args:
            plan: LLM 输出的分组计划
            n_key_infos: key_infos 总数
            max_group_size: 单组最大条数
            min_group_size: 最小组大小（None 时自动计算）

        Returns:
            归一化后的分组列表
        """
        if min_group_size is None:
            threshold = ImageConfig.MIN_GROUP_SIZE_THRESHOLD
            min_group_size = 3 if n_key_infos >= threshold else 1

        raw_groups = plan.groups or []

        # 1) 去重并过滤越界
        cleaned, seen = self._dedupe_and_filter_indices(raw_groups, n_key_infos)

        # 2) 补齐缺失
        cleaned = self._fill_missing_indices(cleaned, seen, n_key_infos)

        if not cleaned:
            return [{"title": "要点汇总", "indices": list(range(n_key_infos))}]

        # 3) 拆分大组
        split_groups = self._split_large_groups(cleaned, max_group_size)

        # 4) 合并小组
        merged = self._merge_small_groups(split_groups, min_group_size, max_group_size)

        # 5) 覆盖校验
        all_indices: list[int] = []
        for g in merged:
            all_indices.extend(g["indices"])
        if set(all_indices) != set(range(n_key_infos)) or len(all_indices) != n_key_infos:
            # 兜底：按顺序切片
            idxs = list(range(n_key_infos))
            chunks = [idxs[i : i + max_group_size] for i in range(0, len(idxs), max_group_size)]
            return [{"title": f"要点清单（{i}/{len(chunks)}）", "indices": chunk} for i, chunk in enumerate(chunks, start=1)]

        return merged

    @staticmethod
    def _validate_groups(groups: list[GroupSpec], n_key_infos: int, max_group_size: int) -> None:
        """
        运行时校验：覆盖且不重复、每组大小不超过限制。

        Args:
            groups: 分组列表
            n_key_infos: key_infos 总数
            max_group_size: 单组最大条数

        Raises:
            ValueError: 校验失败时抛出
        """
        all_indices: list[int] = []
        for g in groups:
            idxs = g.get("indices", [])
            if not isinstance(idxs, list):
                raise ValueError("group.indices must be a list")
            if len(idxs) == 0:
                raise ValueError("group.indices is empty")
            if len(idxs) > max_group_size:
                raise ValueError("group too large after normalization")
            for idx in idxs:
                if not isinstance(idx, int):
                    raise ValueError("index must be int")
                if idx < 0 or idx >= n_key_infos:
                    raise ValueError("index out of range")
                all_indices.append(idx)
        if len(all_indices) != n_key_infos:
            raise ValueError("coverage mismatch (count)")
        if set(all_indices) != set(range(n_key_infos)):
            raise ValueError("coverage mismatch (set)")

    async def _review_groups(
        self,
        *,
        topic: str,
        compact_items: list[CompactKeyInfo],
        groups: list[GroupSpec],
        target_groups: int,
        max_group_size: int,
    ) -> ImageGroupingReviewResult:
        """
        调用分组审核 Agent 验证分组质量。

        Args:
            topic: 主题
            compact_items: 精简的 key_info 列表
            groups: 分组列表
            target_groups: 目标分组数
            max_group_size: 单组最大条数

        Returns:
            审核结果
        """
        user_prompt = get_user_prompt(
            "image_grouping_review",
            topic=topic,
            key_infos_json=json.dumps(compact_items, ensure_ascii=False, indent=2),
            groups_json=json.dumps(groups, ensure_ascii=False, indent=2),
            target_groups=target_groups,
            max_group_size=max_group_size,
        )
        result = await self.grouping_reviewer.run(user_prompt)
        return result.output

    def _cap_groups_to_max_images(
        self,
        groups: list[GroupSpec],
        *,
        max_groups: int,
        max_group_size_cap: int,
    ) -> list[GroupSpec]:
        """
        确保 detail 组数量不超过 max_groups。

        策略：从尾部开始合并相邻组，允许每组最多 max_group_size_cap 条；
        若仍无法满足，则退化为均匀切块。

        Args:
            groups: 分组列表
            max_groups: 最大组数
            max_group_size_cap: 每组最大条数上限

        Returns:
            调整后的分组列表
        """
        if len(groups) <= max_groups:
            return groups

        merged = [dict(title=g.get("title", "要点"), indices=list(g.get("indices", []))) for g in groups]

        def can_merge(a: dict, b: dict) -> bool:
            return len(a["indices"]) + len(b["indices"]) <= max_group_size_cap

        # 尽量从末尾往前合并，保留前面主题性更强的标题
        i = len(merged) - 2
        while len(merged) > max_groups and i >= 0:
            # merged 在循环中会 pop，必须确保 i+1 仍然有效
            if i + 1 >= len(merged):
                i = len(merged) - 2
                continue
            a = merged[i]
            b = merged[i + 1]
            if can_merge(a, b):
                a["indices"].extend(b["indices"])
                a["indices"].sort()
                merged.pop(i + 1)
                # 合并后列表变短，i 可能变成最后一个索引，需回退到合法区间
                i = min(i, len(merged) - 2)
                # 合并后，继续尝试从当前位置往前合并
            else:
                i -= 1

        if len(merged) <= max_groups:
            return merged

        # 兜底：均匀切块（保证数量上限）
        all_indices: list[int] = []
        for g in groups:
            all_indices.extend(g.get("indices", []))
        all_indices = sorted(all_indices)
        if not all_indices:
            return groups[:max_groups]

        chunk_size = math.ceil(len(all_indices) / max_groups)
        chunk_size = min(max_group_size_cap, max(1, chunk_size))
        chunks = [all_indices[i : i + chunk_size] for i in range(0, len(all_indices), chunk_size)]
        # 如果仍超过 max_groups（因为 cap 导致 chunk_size 变小），再压一次
        while len(chunks) > max_groups:
            # 合并最后两个 chunk
            last = chunks.pop()
            chunks[-1].extend(last)
        capped: list[dict[str, Any]] = []
        for idx, chunk in enumerate(chunks[:max_groups], start=1):
            capped.append({"title": f"要点清单（{idx}/{min(len(chunks), max_groups)}）", "indices": chunk})
        return capped

    def _adjust_groups_to_target_count(
        self,
        groups: list[GroupSpec],
        *,
        target_groups: int,
        max_group_size_cap: int,
    ) -> list[GroupSpec]:
        """
        调整组数量接近 target_groups。

        - 太多：合并相邻组
        - 太少：拆分最大的组

        Args:
            groups: 分组列表
            target_groups: 目标组数
            max_group_size_cap: 每组最大条数上限

        Returns:
            调整后的分组列表
        """
        if target_groups <= 0:
            return groups

        adjusted = [dict(title=g.get("title", "要点"), indices=list(g.get("indices", []))) for g in groups]

        # 1) 太多：先合并到不超过 target_groups
        if len(adjusted) > target_groups:
            adjusted = self._cap_groups_to_max_images(
                adjusted,
                max_groups=target_groups,
                max_group_size_cap=max_group_size_cap,
            )

        # 2) 太少：拆分最大的组直到达到 target_groups（尽量不超过 cap）
        def pick_largest_idx() -> int:
            largest_i = 0
            largest_len = -1
            for i, g in enumerate(adjusted):
                l = len(g["indices"])
                if l > largest_len:
                    largest_len = l
                    largest_i = i
            return largest_i

        while len(adjusted) < target_groups:
            i = pick_largest_idx()
            g = adjusted[i]
            idxs = g["indices"]
            if len(idxs) <= 1:
                break  # 没法再拆
            mid = len(idxs) // 2
            left = idxs[:mid]
            right = idxs[mid:]
            # 防止拆出来的某一边超过 cap（理论上不会，因为拆分只会变小）
            if len(left) > max_group_size_cap or len(right) > max_group_size_cap:
                break
            title = g.get("title", "要点")
            adjusted[i] = {"title": f"{title}（续1）", "indices": left}
            adjusted.insert(i + 1, {"title": f"{title}（续2）", "indices": right})

        return adjusted

    # ==================== 图片生成主流程辅助方法 ====================

    @staticmethod
    def _calculate_grouping_params(key_info_count: int) -> tuple[int, int, int]:
        """
        根据 key_info 数量计算分组参数。

        Args:
            key_info_count: key_infos 总数

        Returns:
            (target_groups, target_group_size, max_group_size_cap)
        """
        max_detail_images = ImageConfig.MAX_DETAIL_IMAGES
        target_groups = min(
            max_detail_images,
            max(ImageConfig.MIN_DETAIL_IMAGES, math.ceil(key_info_count / ImageConfig.ENTITIES_PER_DETAIL))
        )
        if target_groups > 0:
            target_group_size = math.ceil(key_info_count / target_groups)
        else:
            target_group_size = ImageConfig.ENTITIES_PER_DETAIL
        target_group_size = max(ImageConfig.ENTITIES_PER_DETAIL, target_group_size)
        max_group_size_cap = max(ImageConfig.MAX_GROUP_SIZE_CAP, ImageConfig.ENTITIES_PER_DETAIL)
        return target_groups, target_group_size, max_group_size_cap

    async def _run_grouping_with_review(
        self,
        *,
        topic: str,
        research: ResearchResult,
        compact_items: list[CompactKeyInfo],
        target_groups: int,
        target_group_size: int,
        max_group_size_cap: int,
    ) -> list[GroupSpec]:
        """
        语义分组 + 审核循环：失败则带反馈重试。

        Args:
            topic: 主题
            research: 研究数据
            compact_items: 精简的 key_info 列表
            target_groups: 目标分组数
            target_group_size: 每组建议大小
            max_group_size_cap: 可读性上限

        Returns:
            审核通过的分组列表

        Raises:
            RuntimeError: 超过最大重试次数仍未通过审核
        """
        max_detail_images = ImageConfig.MAX_DETAIL_IMAGES
        max_review_retries = ImageConfig.GROUPING_REVIEW_MAX_RETRIES

        review_feedback: str | None = None
        groups: list[GroupSpec] = []

        # 没有 key_infos 时不需要分组（避免后续调整逻辑对空列表做索引）
        if len(research.key_infos or []) == 0:
            return []

        # 语义分组是“锦上添花”，不要让它成为配图的硬失败点：
        # - 若 LLM/Provider 层异常：降级为确定性切块分组（不依赖 LLM）
        # - 若审核一直不过：使用最后一次分组继续生成（并打印 warning）
        try:
            for attempt in range(max_review_retries):
                # 1) 语义分组
                groups = await self._semantic_group_key_infos(
                    topic=topic,
                    research=research,
                    max_group_size=target_group_size,
                    target_groups=target_groups,
                    review_feedback=review_feedback,
                )
                # 2) 确定性调整
                groups = self._adjust_groups_to_target_count(
                    groups,
                    target_groups=target_groups,
                    max_group_size_cap=max_group_size_cap,
                )
                groups = self._cap_groups_to_max_images(
                    groups,
                    max_groups=max_detail_images,
                    max_group_size_cap=max_group_size_cap,
                )
                # 3) 审核分组
                review = await self._review_groups(
                    topic=topic,
                    compact_items=compact_items,
                    groups=groups,
                    target_groups=len(groups),
                    max_group_size=target_group_size,
                )
                if review.passed:
                    logger.info("分组审核通过 (score=%.1f)", review.score)
                    return groups
                review_feedback = f"score={review.score}; issues={review.issues}; summary={review.summary}"
                logger.warning(
                    "分组审核未通过 (attempt=%d/%d): %s",
                    attempt + 1, max_review_retries, review.summary
                )
        except Exception:
            n_key_infos = len(research.key_infos or [])
            logger.exception(
                "语义分组阶段异常，降级为确定性分组 (key_infos=%d, target_groups=%d, target_group_size=%d)",
                n_key_infos, target_groups, target_group_size
            )
            if n_key_infos <= 0:
                return []
            # 兜底：按顺序切片，不依赖 LLM
            idxs = list(range(n_key_infos))
            chunk_size = max(1, min(target_group_size, max_group_size_cap))
            chunks = [idxs[i : i + chunk_size] for i in range(0, len(idxs), chunk_size)]
            fallback_groups: list[GroupSpec] = [
                {"title": f"要点清单（{i}/{len(chunks)}）", "indices": chunk}
                for i, chunk in enumerate(chunks, start=1)
                if chunk
            ]
            return self._cap_groups_to_max_images(
                fallback_groups,
                max_groups=max_detail_images,
                max_group_size_cap=max_group_size_cap,
            )

        # 走到这里表示“审核一直没过”，但我们仍然可以用最后一次分组继续生成
        logger.warning("分组审核失败（已重试 %d 次），将使用最后一次分组继续生成: %s", max_review_retries, review_feedback)
        return groups

    @staticmethod
    def _build_image_types(groups: list[GroupSpec]) -> list[ImageTypeSpec]:
        """
        将分组列表转换为图片类型列表（cover + detail_N）。

        Args:
            groups: 语义分组列表

        Returns:
            图片类型规格列表
        """
        image_types: list[ImageTypeSpec] = [
            {"type": "cover", "desc": "封面图 - 大标题风格，突出主题"}
        ]
        for i, g in enumerate(groups, start=1):
            image_types.append({
                "type": f"detail_{i}",
                "desc": f"详情图{i} - 语义分组：{g['title']}",
                "group_title": g["title"],
                "indices": g["indices"],
            })
        return image_types

    async def _generate_all_images(
        self,
        *,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        output_dir: Path,
        image_types: list[ImageTypeSpec],
    ) -> list[GeneratedImage]:
        """
        在 MCP Server 上下文中逐张生成图片。

        为每张图片创建独立的 ImageGenContext，用于依赖注入。
        验证失败时，反馈会写入 gen_ctx.validation_feedback，
        下次重试时 _generate_prompt 会读取该反馈并调整提示词。

        Args:
            content: 内容数据
            research: 研究数据
            topic: 主题
            output_dir: 输出目录
            image_types: 图片类型列表

        Returns:
            生成的图片列表
        """
        generated_images: list[GeneratedImage] = []

        async with self.mcp_server:
            for image_type_info in image_types:
                image_type = image_type_info["type"]
                image_desc = image_type_info.get("desc", "")

                logger.info("[%s] %s", image_type, image_desc)

                # 为每张图片创建独立的上下文（每张图片的反馈独立）
                gen_ctx = ImageGenContext(topic=topic, image_type=image_type)

                # 使用 Playwright 操作 Gemini 生成图片
                # 提示词生成现在在 _generate_via_gemini 内部完成
                # 验证失败时会更新 gen_ctx.validation_feedback 并重试
                logger.info("启动 Gemini 图片生成...")
                image_path = await self._generate_via_gemini(
                    output_dir=output_dir,
                    image_type=image_type,
                    topic=topic,
                    gen_ctx=gen_ctx,
                    content=content,
                    research=research,
                    image_type_info=image_type_info,
                )

                # 获取最终使用的提示词（用于记录）
                # 由于提示词在 _generate_via_gemini 内部生成，这里重新生成一次用于记录
                # TODO: 考虑将最终提示词作为返回值的一部分
                final_prompt = await self._generate_prompt(
                    content, research, topic, image_type_info, gen_ctx
                )

                generated_images.append(GeneratedImage(
                    image_path=str(image_path),
                    prompt_used=final_prompt,
                    image_type=image_type
                ))

                logger.info("%s 生成并验证完成", image_type)

        return generated_images

    # ==================== 图片生成主入口 ====================

    async def generate_image(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        output_dir: Path
    ) -> ImageResult:
        """
        生成配图（每张图片即时验证）。

        流程：
        1. 计算分组参数
        2. 语义分组 + 审核循环
        3. 构建图片类型列表
        4. 逐张生成图片

        Args:
            content: 内容数据
            research: 研究数据
            topic: 主题
            output_dir: 输出目录

        Returns:
            ImageResult: 图片结果（包含多张图片）
        """
        key_info_count = len(research.key_infos)

        # 1. 计算分组参数
        target_groups, target_group_size, max_group_size_cap = self._calculate_grouping_params(key_info_count)

        # 2. 构造 compact_items
        compact_items = self._build_compact_items(research.key_infos or [])

        # 3. 语义分组 + 审核
        groups = await self._run_grouping_with_review(
            topic=topic,
            research=research,
            compact_items=compact_items,
            target_groups=target_groups,
            target_group_size=target_group_size,
            max_group_size_cap=max_group_size_cap,
        )

        # 4. 构建图片类型列表
        image_types = self._build_image_types(groups)
        logger.info("开始生成 %d 张配图 (%d 个关键信息)", len(image_types), key_info_count)

        # 5. 生成图片
        generated_images = await self._generate_all_images(
            content=content,
            research=research,
            topic=topic,
            output_dir=output_dir,
            image_types=image_types,
        )

        return ImageResult(
            images=generated_images,
            total_count=len(generated_images),
            generated_at=datetime.now().isoformat()
        )

    async def _generate_prompt(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        image_type_info: ImageTypeSpec,
        gen_ctx: ImageGenContext,
    ) -> str:
        """
        生成 Gemini 图片提示词。

        通过依赖注入传递 gen_ctx，其中的 validation_feedback 字段
        会被动态 system_prompt 读取，用于指导重试时的提示词调整。

        Args:
            content: 内容数据
            research: 研究数据
            topic: 主题
            image_type_info: 图片类型信息
            gen_ctx: 图片生成上下文（用于依赖注入）

        Returns:
            Gemini 图片生成提示词
        """
        image_type = image_type_info["type"]
        image_desc = image_type_info["desc"]

        if image_type == "cover":
            # 封面图：只需标题和主题
            body_excerpt = content.body[:150]
        else:
            # 详情图：使用语义分组的 indices 获取对应关键信息
            indices = image_type_info.get("indices", [])
            key_infos = [research.key_infos[i] for i in indices if 0 <= i < len(research.key_infos)]

            if key_infos:
                # 构建关键信息列表
                infos_text = "\n".join([
                    f"{i+1}. {info.get('name', '未知')}: {info.get('description', info.get('detail', ''))}"
                    for i, info in enumerate(key_infos)
                ])
                group_title = image_type_info.get("group_title", "")
                body_excerpt = f"本图主题板块：{group_title}\n本图需要展示以下 {len(key_infos)} 个关键信息：\n{infos_text}"
            else:
                # 无关键信息时使用正文
                body_excerpt = content.body[:300]

        # 从 YAML 读取用户提示词模板并填充变量
        user_prompt = get_user_prompt(
            "image",
            topic=topic,
            content_title=content.title,
            content_body=body_excerpt,
            image_type=image_type,
            image_desc=image_desc
        )

        # 如果有验证反馈，记录日志
        if gen_ctx.validation_feedback:
            logger.info("根据验证反馈重新生成提示词: %s", gen_ctx.validation_feedback[:100])

        # 运行 Agent 时传入 deps（依赖注入）
        # 动态 system_prompt 会自动读取 gen_ctx.validation_feedback
        result = await self.prompt_generator.run(user_prompt, deps=gen_ctx)
        return result.output

    @with_retry(max_retries=RetryConfig.MAX_RETRIES, initial_delay=RetryConfig.INITIAL_DELAY)
    @GeminiConfigValidator(max_retries=3, initial_delay=5.0)
    @ImageQualityValidator(max_retries=2, initial_delay=5.0)
    async def _generate_via_gemini(
        self,
        output_dir: Path,
        image_type: str,
        topic: str,
        gen_ctx: ImageGenContext,
        content: XHSContent,
        research: ResearchResult,
        image_type_info: ImageTypeSpec,
    ) -> Path:
        """
        通过 Gemini 网页生成图片（带重试和验证）

        三层重试机制（由装饰器处理）：
        1. @with_retry: 网络/API 错误重试
        2. @GeminiConfigValidator: 验证 Gemini 配置（Create images + Pro）
        3. @ImageQualityValidator: 验证图片质量（字迹清晰、风格匹配）

        验证失败时，ExternalValidator 会更新 gen_ctx.validation_feedback，
        下次重试时 _generate_prompt 会读取该反馈并调整提示词。

        Args:
            output_dir: 输出目录
            image_type: 图片类型
            topic: 主题（用于风格验证）
            gen_ctx: 图片生成上下文（用于依赖注入，验证反馈会写入此对象）
            content: 内容数据
            research: 研究数据
            image_type_info: 图片类型信息

        Returns:
            Path: 图片保存路径
        """
        # 记录开始时间（用于筛选新下载的文件）
        start_time = time.time()
        self._operation_start_time = start_time  # 供 check_download_status 工具使用

        # 每次重试都重新生成提示词（gen_ctx.validation_feedback 会被更新）
        prompt = await self._generate_prompt(content, research, topic, image_type_info, gen_ctx)
        logger.debug("提示词: %s...", prompt[:60])

        # 从 YAML 读取操作提示词模板并填充变量
        operation_prompt = get_prompt_field(
            "image",
            "gemini_operation_template",
            prompt=prompt
        )

        # 运行 Gemini 操作 Agent（结构化输出）
        # 截屏验证由装饰器 @GeminiConfigValidator 处理
        result = await self.gemini_operator.run(operation_prompt)
        op_result: GeminiOperationResult = result.output

        # 使用结构化输出判断状态
        if op_result.success:
            logger.info("Gemini 操作成功: %s", op_result.status)
        else:
            logger.warning("Gemini 操作失败: %s", op_result.status)

        # 等待下载完成并移动文件到目标目录
        # 如果超时或找不到文件，让异常抛出，由验证装饰器处理重试
        image_path = self.download_manager.wait_and_move(
            target_dir=output_dir,
            target_name=image_type,
            file_pattern="*.png",
            timeout=TimeoutConfig.GEMINI_WAIT,
            before_time=start_time
        )
        logger.info("图片已保存: %s", image_path)

        return image_path

    async def list_tools(self) -> None:
        """列出所有可用的 MCP 工具（用于验证）"""
        logger.info("正在检查 Gemini 操作工具...")

        try:
            async with self.mcp_server as server:
                tools = await server.list_tools()
                logger.info("发现 %d 个 Playwright MCP 工具", len(tools))
                for tool in tools[:5]:  # 只显示前5个
                    tool_name = f"{self.mcp_server.tool_prefix}_{tool.name}" if self.mcp_server.tool_prefix else tool.name
                    logger.debug("  - %s", tool_name)
        except Exception as e:
            logger.warning("无法列出工具: %s", e)
