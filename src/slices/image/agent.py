"""
图片生成 Agent - ML 模型风格
使用 Gemini 网页生成小红书配图

使用方式：
    agent = ImageAgent()
    result = await agent.forward(content, research, topic, output_dir)

通过 Playwright MCP 操作 Gemini 网页

验证机制（通过类装饰器实现）：
- @GeminiConfigValidator: 每张图片生成后验证 Gemini 配置（Create images + Pro）
- @ImageQualityValidator: 验证图片质量（字迹清晰、风格匹配）
"""
import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic_ai import Agent, Tool, RunContext
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

from ...models.schemas import (
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
from ...utils.minimax_provider import get_minimax_model
from ...utils.download_manager import DownloadManager
from ...utils.retry_handler import with_retry
from ...utils.logger import get_logger
from ...config.settings import RetryConfig, ImageConfig, PathConfig, TimeoutConfig, APIConfig
from ...infra.login_agent import LoginAgent
from .gemini_config_validator import GeminiConfigValidator
from .quality_validator import ImageQualityValidator
from .prompts import (
    image_system_prompt,
    image_user_prompt,
    image_grouping_system_prompt,
    image_grouping_user_prompt,
    image_grouping_review_system_prompt,
    image_grouping_review_user_prompt,
    gemini_operator_prompt,
    gemini_operation_template,
)

logger = get_logger(__name__)


class ImageAgent:
    """
    Gemini 图片生成 Agent（ML 模型风格）

    类似 PyTorch nn.Module 的设计：
    - __init__: 初始化所有组件
    - forward: 主执行入口

    使用方式：
        agent = ImageAgent()
        result = await agent.forward(content, research, topic, output_dir)
    """

    # ========================================================================
    # 初始化
    # ========================================================================

    def __init__(self):
        """初始化图片生成 Agent"""
        self._init_config()
        self._init_paths()
        self._init_state()
        self._init_download_manager()
        self._init_mcp_server()
        self._init_tools()
        self._init_agents()

    def _init_config(self):
        """初始化配置参数"""
        self.gemini_url = APIConfig.GEMINI_URL

    def _init_paths(self):
        """初始化路径配置"""
        self.downloads_dir = PathConfig.DOWNLOADS_DIR
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

    def _init_state(self):
        """初始化内部状态"""
        self._operation_start_time: Optional[float] = None

    def _init_download_manager(self):
        """初始化下载管理器"""
        self.download_manager = DownloadManager(download_dir=self.downloads_dir)

    def _init_mcp_server(self):
        """初始化 Playwright MCP Server"""
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
            timeout=TimeoutConfig.MCP_INIT_TIMEOUT,
            process_tool_call=ImageAgent._block_browser_close,
        )

    def _init_tools(self):
        """初始化工具集"""
        self.login_agent = LoginAgent(mcp_server=self.mcp_server)

    def _init_agents(self):
        """初始化所有 Agent"""
        model = get_minimax_model()

        # 提示词生成 Agent
        self.prompt_generator = Agent(
            model=model,
            output_type=str,
            deps_type=ImageGenContext,
            instrument=True,
        )

        # 注册动态 system_prompt
        @self.prompt_generator.system_prompt
        async def _dynamic_system_prompt(ctx: RunContext[ImageGenContext]) -> str:
            base_prompt = image_system_prompt()
            if ctx.deps.validation_feedback:
                return (
                    base_prompt +
                    "\n\n## 🚨 上次生成的图片问题（必须修复）\n"
                    f"{ctx.deps.validation_feedback}\n\n"
                    "请根据上述反馈调整提示词，确保生成的图片符合要求。"
                )
            return base_prompt

        # 语义分组 Agent
        self.grouping_agent = Agent(
            model=model,
            output_type=ImageGroupingPlan,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(image_grouping_system_prompt(),),
        )

        # 分组审核 Agent
        self.grouping_reviewer = Agent(
            model=get_minimax_model(),
            output_type=ImageGroupingReviewResult,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(image_grouping_review_system_prompt(),),
        )

        # Gemini 操作 Agent
        function_tools = [
            Tool(self._check_download_status, takes_ctx=False),
            self.login_agent.get_tool(),
        ]
        self.gemini_operator = Agent(
            model=model,
            output_type=GeminiOperationResult,
            toolsets=[self.mcp_server],
            tools=function_tools,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(gemini_operator_prompt(),),
        )

    @staticmethod
    async def _block_browser_close(
        ctx: RunContext[Any],
        call_tool,
        name: str,
        args: dict[str, Any]
    ):
        """拦截并阻止关闭浏览器的工具调用"""
        if name == 'browser_close':
            logger.debug("拦截 browser_close 调用：浏览器需要保持打开状态以供验证")
            return {"content": [{"type": "text", "text": "操作已跳过：浏览器需要保持打开状态以供后续验证。"}]}
        return await call_tool(name, args, None)

    # ========================================================================
    # 主入口：forward
    # ========================================================================

    async def forward(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        output_dir: Path
    ) -> ImageResult:
        """
        生成配图（主入口）

        类似 PyTorch 的 forward 方法。

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

    # ========================================================================
    # 工具方法
    # ========================================================================

    def _check_download_status(self) -> str:
        """检查下载目录是否有新的 PNG 图片文件"""
        if self._operation_start_time is None:
            return "NOT_FOUND: 操作未开始"

        for f in self.downloads_dir.glob("*.png"):
            if f.stat().st_mtime > self._operation_start_time:
                if not f.suffix.endswith(('.crdownload', '.tmp', '.part')):
                    return f"DOWNLOADED: {f.name} ({f.stat().st_size / 1024:.0f}KB)"

        return "NOT_FOUND: 下载目录中没有新文件"

    async def list_tools(self) -> None:
        """列出所有可用的 MCP 工具（用于验证）"""
        logger.info("正在检查 Gemini 操作工具...")
        try:
            async with self.mcp_server as server:
                tools = await server.list_tools()
                logger.info("发现 %d 个 Playwright MCP 工具", len(tools))
                for tool in tools[:5]:
                    tool_name = f"{self.mcp_server.tool_prefix}_{tool.name}" if self.mcp_server.tool_prefix else tool.name
                    logger.debug("  - %s", tool_name)
        except Exception as e:
            logger.warning("无法列出工具: %s", e)

    # ========================================================================
    # 分组相关方法
    # ========================================================================

    @staticmethod
    def _build_compact_items(key_infos: list[dict[str, Any]]) -> list[CompactKeyInfo]:
        """将 key_infos 转换为精简格式"""
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

    @staticmethod
    def _calculate_grouping_params(key_info_count: int) -> tuple[int, int, int]:
        """根据 key_info 数量计算分组参数"""
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

    @staticmethod
    def _dedupe_and_filter_indices(
        raw_groups: list,
        n_key_infos: int,
    ) -> tuple[list[GroupSpec], set[int]]:
        """去重并过滤越界 indices"""
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
        """补齐未被分配的 indices"""
        missing = [i for i in range(n_key_infos) if i not in seen]
        if missing:
            groups.append({"title": "其他补充", "indices": missing})
        return groups

    @staticmethod
    def _split_large_groups(
        groups: list[GroupSpec],
        max_group_size: int,
    ) -> list[GroupSpec]:
        """将超过 max_group_size 的组拆分"""
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
        """将过小的组合并到前一个组"""
        merged: list[GroupSpec] = []
        for g in groups:
            if not merged:
                merged.append(dict(g))
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
        """归一化分组计划"""
        if min_group_size is None:
            threshold = ImageConfig.MIN_GROUP_SIZE_THRESHOLD
            min_group_size = 3 if n_key_infos >= threshold else 1

        raw_groups = plan.groups or []

        cleaned, seen = self._dedupe_and_filter_indices(raw_groups, n_key_infos)
        cleaned = self._fill_missing_indices(cleaned, seen, n_key_infos)

        if not cleaned:
            return [{"title": "要点汇总", "indices": list(range(n_key_infos))}]

        split_groups = self._split_large_groups(cleaned, max_group_size)
        merged = self._merge_small_groups(split_groups, min_group_size, max_group_size)

        all_indices: list[int] = []
        for g in merged:
            all_indices.extend(g["indices"])
        if set(all_indices) != set(range(n_key_infos)) or len(all_indices) != n_key_infos:
            idxs = list(range(n_key_infos))
            chunks = [idxs[i : i + max_group_size] for i in range(0, len(idxs), max_group_size)]
            return [{"title": f"要点清单（{i}/{len(chunks)}）", "indices": chunk} for i, chunk in enumerate(chunks, start=1)]

        return merged

    @staticmethod
    def _validate_groups(groups: list[GroupSpec], n_key_infos: int, max_group_size: int) -> None:
        """运行时校验"""
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

    def _cap_groups_to_max_images(
        self,
        groups: list[GroupSpec],
        *,
        max_groups: int,
        max_group_size_cap: int,
    ) -> list[GroupSpec]:
        """确保 detail 组数量不超过 max_groups"""
        if len(groups) <= max_groups:
            return groups

        merged = [dict(title=g.get("title", "要点"), indices=list(g.get("indices", []))) for g in groups]

        def can_merge(a: dict, b: dict) -> bool:
            return len(a["indices"]) + len(b["indices"]) <= max_group_size_cap

        i = len(merged) - 2
        while len(merged) > max_groups and i >= 0:
            if i + 1 >= len(merged):
                i = len(merged) - 2
                continue
            a = merged[i]
            b = merged[i + 1]
            if can_merge(a, b):
                a["indices"].extend(b["indices"])
                a["indices"].sort()
                merged.pop(i + 1)
                i = min(i, len(merged) - 2)
            else:
                i -= 1

        if len(merged) <= max_groups:
            return merged

        all_indices: list[int] = []
        for g in groups:
            all_indices.extend(g.get("indices", []))
        all_indices = sorted(all_indices)
        if not all_indices:
            return groups[:max_groups]

        chunk_size = math.ceil(len(all_indices) / max_groups)
        chunk_size = min(max_group_size_cap, max(1, chunk_size))
        chunks = [all_indices[i : i + chunk_size] for i in range(0, len(all_indices), chunk_size)]
        while len(chunks) > max_groups:
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
        """调整组数量接近 target_groups"""
        if target_groups <= 0:
            return groups

        adjusted = [dict(title=g.get("title", "要点"), indices=list(g.get("indices", []))) for g in groups]

        if len(adjusted) > target_groups:
            adjusted = self._cap_groups_to_max_images(
                adjusted,
                max_groups=target_groups,
                max_group_size_cap=max_group_size_cap,
            )

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
                break
            mid = len(idxs) // 2
            left = idxs[:mid]
            right = idxs[mid:]
            if len(left) > max_group_size_cap or len(right) > max_group_size_cap:
                break
            title = g.get("title", "要点")
            adjusted[i] = {"title": f"{title}（续1）", "indices": left}
            adjusted.insert(i + 1, {"title": f"{title}（续2）", "indices": right})

        return adjusted

    async def _review_groups(
        self,
        *,
        topic: str,
        compact_items: list[CompactKeyInfo],
        groups: list[GroupSpec],
        target_groups: int,
        max_group_size: int,
        message_history: list[ModelMessage] | None = None,
    ) -> tuple[ImageGroupingReviewResult, list[ModelMessage]]:
        """调用分组审核 Agent"""
        user_prompt = image_grouping_review_user_prompt(
            topic=topic,
            key_infos_json=json.dumps(compact_items, ensure_ascii=False, indent=2),
            groups_json=json.dumps(groups, ensure_ascii=False, indent=2),
            target_groups=target_groups,
            max_group_size=max_group_size,
        )
        result = await self.grouping_reviewer.run(user_prompt, message_history=message_history or [])
        return result.output, list(result.new_messages())

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
        """语义分组 + 审核循环"""
        max_detail_images = ImageConfig.MAX_DETAIL_IMAGES
        max_review_retries = ImageConfig.GROUPING_REVIEW_MAX_RETRIES

        messages: list[ModelMessage] = []
        message_rounds: list[list[ModelMessage]] = []
        review_messages: list[ModelMessage] = []
        review_message_rounds: list[list[ModelMessage]] = []
        groups: list[GroupSpec] = []

        if len(research.key_infos or []) == 0:
            return []

        try:
            for attempt in range(max_review_retries):
                if attempt == 0:
                    user_prompt = image_grouping_user_prompt(
                        topic=topic,
                        key_infos_json=json.dumps(compact_items, ensure_ascii=False, indent=2),
                        max_group_size=target_group_size,
                        target_groups=target_groups,
                    )
                    logger.info("开始语义分组...")
                else:
                    review_feedback = (
                        f"分组审核未通过，请根据反馈重新分组。\n\n"
                        f"**审核评分**：{review.score:.1f}/100\n\n"
                        f"**问题摘要**：{review.summary}\n\n"
                        f"**具体问题**：\n"
                    )
                    for issue in review.issues:
                        review_feedback += f"- {issue}\n"

                    review_feedback += (
                        f"\n**要求**：\n"
                        f"- 确保覆盖所有 {len(compact_items)} 个关键信息\n"
                        f"- 分组语义一致、逻辑清晰\n"
                        f"- 目标分组数：{target_groups} 组\n"
                        f"- 每组建议大小：{target_group_size} 条\n"
                    )

                    feedback_message = ModelRequest(parts=[UserPromptPart(review_feedback)])
                    user_prompt = "请根据上述反馈重新分组，确保覆盖完整且分组语义一致。"
                    logger.info(f"根据反馈重新分组 (第{attempt+1}轮)...")

                if message_rounds:
                    kept_rounds = message_rounds[-3:]
                    messages = [msg for round_msgs in kept_rounds for msg in round_msgs]
                else:
                    messages = []

                if attempt == 0:
                    grouping_result = await self.grouping_agent.run(user_prompt, message_history=messages)
                    round_messages = list(grouping_result.new_messages())
                else:
                    grouping_result = await self.grouping_agent.run(
                        user_prompt,
                        message_history=messages + [feedback_message],
                    )
                    round_messages = [feedback_message] + list(grouping_result.new_messages())

                plan: ImageGroupingPlan = grouping_result.output
                message_rounds.append(round_messages)

                groups = self._normalize_grouping_plan(plan, len(compact_items), target_group_size)
                self._validate_groups(groups, len(compact_items), target_group_size)

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

                if review_message_rounds:
                    kept_review_rounds = review_message_rounds[-3:]
                    review_messages = [msg for round_msgs in kept_review_rounds for msg in round_msgs]
                else:
                    review_messages = []

                review, review_round_messages = await self._review_groups(
                    topic=topic,
                    compact_items=compact_items,
                    groups=groups,
                    target_groups=len(groups),
                    max_group_size=target_group_size,
                    message_history=review_messages,
                )
                review_message_rounds.append(review_round_messages)
                if review.passed:
                    logger.info("分组审核通过 (score=%.1f)", review.score)
                    return groups

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
            if groups:
                logger.warning("语义分组异常，使用最近一次分组结果继续生成 (groups=%d)", len(groups))
                return self._cap_groups_to_max_images(
                    groups,
                    max_groups=max_detail_images,
                    max_group_size_cap=max_group_size_cap,
                )
            if n_key_infos <= 0:
                return []
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

        logger.warning(
            "分组审核失败（已重试 %d 次），将使用最后一次分组继续生成 (最后评分: %.1f, 问题: %s)",
            max_review_retries, review.score, review.summary
        )
        return groups

    @staticmethod
    def _build_image_types(groups: list[GroupSpec]) -> list[ImageTypeSpec]:
        """将分组列表转换为图片类型列表"""
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

    # ========================================================================
    # 图片生成方法
    # ========================================================================

    async def _generate_all_images(
        self,
        *,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        output_dir: Path,
        image_types: list[ImageTypeSpec],
    ) -> list[GeneratedImage]:
        """在 MCP Server 上下文中逐张生成图片"""
        generated_images: list[GeneratedImage] = []

        async with self.mcp_server:
            for image_type_info in image_types:
                image_type = image_type_info["type"]
                image_desc = image_type_info.get("desc", "")

                logger.info("[%s] %s", image_type, image_desc)

                gen_ctx = ImageGenContext(topic=topic, image_type=image_type)

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

    async def _generate_prompt(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        image_type_info: ImageTypeSpec,
        gen_ctx: ImageGenContext,
    ) -> str:
        """生成 Gemini 图片提示词"""
        image_type = image_type_info["type"]
        image_desc = image_type_info["desc"]

        if image_type == "cover":
            # cover 图：使用 content 的标题和正文
            body_excerpt = content.body[:150]
            title_for_prompt = content.title
        else:
            # detail 图：不依赖 content，直接从 research + grouping 构建
            indices = image_type_info.get("indices", [])
            key_infos = [research.key_infos[i] for i in indices if 0 <= i < len(research.key_infos)]
            group_title = image_type_info.get("group_title", "")

            if key_infos:
                infos_text = "\n".join([
                    f"{i+1}. {info.get('name', '未知')}: {info.get('description', info.get('detail', ''))}"
                    for i, info in enumerate(key_infos)
                ])
                body_excerpt = f"本图主题板块：{group_title}\n本图需要展示以下 {len(key_infos)} 个关键信息：\n{infos_text}"
            else:
                body_excerpt = f"本图主题板块：{group_title or topic}"

            # detail 图用 topic 代替 content.title，解耦 content 依赖
            title_for_prompt = topic

        user_prompt = image_user_prompt(
            topic=topic,
            content_title=title_for_prompt,
            content_body=body_excerpt,
            image_type=image_type,
            image_desc=image_desc,
        )

        if gen_ctx.validation_feedback:
            logger.info("根据验证反馈重新生成提示词: %s", gen_ctx.validation_feedback[:100])

        result = await self.prompt_generator.run(user_prompt, deps=gen_ctx)
        return result.output

    @with_retry(max_retries=RetryConfig.MAX_RETRIES, initial_delay=RetryConfig.INITIAL_DELAY)
    @GeminiConfigValidator(max_retries=5, initial_delay=5.0)
    @ImageQualityValidator(max_retries=5, initial_delay=5.0)
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
        """通过 Gemini 网页生成图片（带重试和验证）"""
        start_time = time.time()
        self._operation_start_time = start_time

        prompt = await self._generate_prompt(content, research, topic, image_type_info, gen_ctx)
        logger.debug("提示词: %s...", prompt[:60])

        operation_prompt = gemini_operation_template(prompt=prompt)

        result = await self.gemini_operator.run(operation_prompt)
        op_result: GeminiOperationResult = result.output

        if op_result.success:
            logger.info("Gemini 操作成功: %s", op_result.status)
        else:
            logger.warning("Gemini 操作失败: %s", op_result.status)

        image_path = self.download_manager.wait_and_move(
            target_dir=output_dir,
            target_name=image_type,
            file_pattern="*.png",
            timeout=TimeoutConfig.GEMINI_WAIT,
            before_time=start_time
        )
        logger.info("图片已保存: %s", image_path)

        return image_path
