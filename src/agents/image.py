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
from typing import List, Dict, Optional, Any, Tuple
from pydantic_ai import Agent, Tool
from pydantic_ai.mcp import MCPServerStdio
from ..models.schemas import (
    ImageResult,
    GeneratedImage,
    XHSContent,
    ResearchResult,
    ImageGroupingPlan,
    ImageGroupingReviewResult,
)
from ..utils.model_factory import get_model
from ..utils.download_manager import DownloadManager
from ..utils.retry_handler import with_retry
from ..validators import GeminiConfigValidator, ImageQualityValidator
from ..config.settings import RetryConfig, ImageConfig, PathConfig, TimeoutConfig, APIConfig
from prompts import get_system_prompt, get_user_prompt, get_prompt_field


class ImageAgent:
    """Gemini 图片生成 Agent"""

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
        )

        # ==================== 6. Agents ====================
        # 获取带 HTTP 重试的 Model（根据配置选择 Anthropic 或 OpenRouter）
        model = get_model()

        # 提示词生成 Agent
        self.prompt_generator = Agent(
            model=model,
            output_type=str,
            instrument=True,
            system_prompt=(get_system_prompt("image"),),
        )

        # 语义分组 Agent（将 key_infos 分组后再分发到详情图）
        self.grouping_agent = Agent(
            model=model,
            output_type=ImageGroupingPlan,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(get_system_prompt("image_grouping"),),
        )

        # 分组审核 Agent（验证分组是否合理，失败则触发重新分组）
        self.grouping_reviewer = Agent(
            model=model,
            output_type=ImageGroupingReviewResult,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(get_system_prompt("image_grouping_review"),),
        )

        # Gemini 操作 Agent
        self.gemini_operator = Agent(
            model=model,
            output_type=str,
            toolsets=[self.mcp_server],
            tools=[Tool(self._check_download_status, takes_ctx=False)],
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


    async def _semantic_group_key_infos(
        self,
        *,
        topic: str,
        research: ResearchResult,
        max_group_size: int,
        target_groups: int,
        review_feedback: str | None = None,
    ) -> List[Dict[str, Any]]:
        """
        使用 LLM 对 key_infos 做语义分组，然后进行确定性归一化（去重/补漏/拆分/合并）。

        Returns:
            list of group dicts: {title: str, indices: list[int]}
        """
        key_infos = research.key_infos or []
        n = len(key_infos)
        if n == 0:
            return []

        # 构造精简输入，降低 token，提升稳定性
        compact_items: list[dict[str, Any]] = []
        for i, info in enumerate(key_infos):
            name = info.get("name") or info.get("title") or ""
            desc = info.get("description") or info.get("detail") or info.get("desc") or ""
            compact_items.append(
                {
                    "index": i,
                    "type": info.get("type"),
                    "name": name,
                    "text": (f"{name}: {desc}".strip(": ").strip())[:240],
                }
            )

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

    def _normalize_grouping_plan(
        self,
        plan: ImageGroupingPlan,
        n_key_infos: int,
        max_group_size: int,
        min_group_size: int | None = None,
    ) -> List[Dict[str, Any]]:
        """
        归一化分组计划：
        - indices 去重（保留首次出现）
        - 剔除越界 indices
        - 补齐缺失 indices 到“其他”
        - 大组拆分
        - 小组尽量合并（减少 Gemini 补全/幻觉风险）
        - 最终保证覆盖且不重复
        """
        if min_group_size is None:
            # key_infos 足够多时，尽量每组 >= 3；否则放宽
            min_group_size = 3 if n_key_infos >= 8 else 1

        raw_groups = plan.groups or []
        seen: set[int] = set()
        normalized: list[dict[str, Any]] = []

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
                normalized.append({"title": title, "indices": indices})

        # 补齐缺失
        missing = [i for i in range(n_key_infos) if i not in seen]
        if missing:
            normalized.append({"title": "其他补充", "indices": missing})

        if not normalized:
            # 彻底失败时：退化为单组
            return [{"title": "要点汇总", "indices": list(range(n_key_infos))}]

        # 大组拆分
        split_groups: list[dict[str, Any]] = []
        for g in normalized:
            idxs = g["indices"]
            if len(idxs) <= max_group_size:
                split_groups.append(g)
            else:
                chunks = [idxs[i : i + max_group_size] for i in range(0, len(idxs), max_group_size)]
                for ci, chunk in enumerate(chunks, start=1):
                    split_groups.append({"title": f"{g['title']}（续{ci}）", "indices": chunk})

        # 小组合并（尽量往前合并）
        merged: list[dict[str, Any]] = []
        for g in split_groups:
            if not merged:
                merged.append(g)
                continue
            if len(g["indices"]) < min_group_size:
                prev = merged[-1]
                if len(prev["indices"]) + len(g["indices"]) <= max_group_size:
                    prev["indices"].extend(g["indices"])
                    prev["indices"].sort()
                    # 标题保持 prev，不强行拼接避免变长
                    continue
            merged.append(g)

        # 最终覆盖校验
        all_indices: list[int] = []
        for g in merged:
            all_indices.extend(g["indices"])
        if set(all_indices) != set(range(n_key_infos)) or len(all_indices) != n_key_infos:
            # 兜底：按顺序切片（稳定且可控）
            fallback: list[dict[str, Any]] = []
            idxs = list(range(n_key_infos))
            chunks = [idxs[i : i + max_group_size] for i in range(0, len(idxs), max_group_size)]
            for i, chunk in enumerate(chunks, start=1):
                fallback.append({"title": f"要点清单（{i}/{len(chunks)}）", "indices": chunk})
            return fallback

        return merged

    def _validate_groups(self, groups: List[Dict[str, Any]], n_key_infos: int, max_group_size: int) -> None:
        """
        运行时校验：覆盖且不重复、每组大小不超过限制。
        失败应抛异常，由上层触发 fallback。
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
        compact_items: list[dict[str, Any]],
        groups: list[dict[str, Any]],
        target_groups: int,
        max_group_size: int,
    ) -> ImageGroupingReviewResult:
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
        groups: List[Dict[str, Any]],
        *,
        max_groups: int,
        max_group_size_cap: int,
    ) -> List[Dict[str, Any]]:
        """
        确保 detail 组数量不超过 max_groups。

        策略：从尾部开始合并相邻组，允许每组最多 max_group_size_cap 条（比 ENTITIES_PER_DETAIL 更宽松），
        以满足“图片数量上限”这一硬约束；若仍无法满足，则退化为均匀切块。
        """
        if len(groups) <= max_groups:
            return groups

        merged = [dict(title=g.get("title", "要点"), indices=list(g.get("indices", []))) for g in groups]

        def can_merge(a: dict, b: dict) -> bool:
            return len(a["indices"]) + len(b["indices"]) <= max_group_size_cap

        # 尽量从末尾往前合并，保留前面主题性更强的标题
        i = len(merged) - 2
        while len(merged) > max_groups and i >= 0:
            a = merged[i]
            b = merged[i + 1]
            if can_merge(a, b):
                a["indices"].extend(b["indices"])
                a["indices"].sort()
                merged.pop(i + 1)
                # 合并后，继续尝试从同一位置往前合并
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
        groups: List[Dict[str, Any]],
        *,
        target_groups: int,
        max_group_size_cap: int,
    ) -> List[Dict[str, Any]]:
        """
        让组数量尽量接近 target_groups：
        - 多了：合并相邻组（复用 _cap_groups_to_max_images 逻辑）
        - 少了：拆分最大的组（标题追加“续”）
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

    async def generate_image(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        output_dir: Path
    ) -> ImageResult:
        """
        生成配图（每张图片即时验证）

        使用 async with self.mcp_server 保持浏览器会话，
        每张图片生成后立即验证，验证失败自动重试单张图片。

        验证机制（通过类装饰器实现）：
        - @GeminiConfigValidator: 验证 Create images + Pro 模式
        - @ImageQualityValidator: 验证字迹清晰度和风格

        Args:
            content: 内容数据
            research: 研究数据
            topic: 主题
            output_dir: 输出目录

        Returns:
            ImageResult: 图片结果（包含多张图片）
        """
        key_info_count = len(research.key_infos)
        max_detail_images = ImageConfig.MAX_DETAIL_IMAGES
        max_review_retries = ImageConfig.GROUPING_REVIEW_MAX_RETRIES

        # 计算目标分组数（不超过最大详情图数量）
        target_groups = min(
            max_detail_images,
            max(ImageConfig.MIN_DETAIL_IMAGES, math.ceil(key_info_count / ImageConfig.ENTITIES_PER_DETAIL))
        )
        # 每组建议大小（确保所有 key_infos 能被覆盖）
        target_group_size = math.ceil(key_info_count / target_groups) if target_groups > 0 else ImageConfig.ENTITIES_PER_DETAIL
        target_group_size = max(ImageConfig.ENTITIES_PER_DETAIL, target_group_size)
        # 可读性上限：避免每张过多要点导致字太小
        max_group_size_cap = max(16, ImageConfig.ENTITIES_PER_DETAIL)

        # 构造 compact_items（用于分组和审核）
        compact_items: list[dict[str, Any]] = []
        for i, info in enumerate(research.key_infos or []):
            name = info.get("name") or info.get("title") or ""
            desc = info.get("description") or info.get("detail") or info.get("desc") or ""
            compact_items.append({
                "index": i,
                "type": info.get("type"),
                "name": name,
                "text": (f"{name}: {desc}".strip(": ").strip())[:240],
            })

        # 语义分组 + 审核（失败则带反馈重试）
        review_feedback: str | None = None
        groups: list[dict[str, Any]] = []
        for attempt in range(max_review_retries):
            # 1) 语义分组
            groups = await self._semantic_group_key_infos(
                topic=topic,
                research=research,
                max_group_size=target_group_size,
                target_groups=target_groups,
                review_feedback=review_feedback,
            )
            # 2) 确定性调整：确保组数接近目标且不超过最大图片数
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
            # 3) 审核分组（语义一致性/覆盖完整性）
            review = await self._review_groups(
                topic=topic,
                compact_items=compact_items,
                groups=groups,
                target_groups=len(groups),  # 审核时用实际组数
                max_group_size=target_group_size,
            )
            if review.passed:
                print(f"   ✅ 分组审核通过（score={review.score}）")
                break
            review_feedback = f"score={review.score}; issues={review.issues}; summary={review.summary}"
            print(f"   ⚠️ 分组审核未通过（attempt={attempt+1}/{max_review_retries}）: {review.summary}")
            if attempt == max_review_retries - 1:
                raise RuntimeError(f"分组审核失败（已重试 {max_review_retries} 次）: {review_feedback}")

        # 构建 image_types（cover + 语义分组后的 detail_N）
        image_types: list[dict[str, Any]] = [{"type": "cover", "desc": "封面图 - 大标题风格，突出主题"}]
        for i, g in enumerate(groups, start=1):
            image_types.append({
                "type": f"detail_{i}",
                "desc": f"详情图{i} - 语义分组：{g['title']}",
                "group_title": g["title"],
                "indices": g["indices"],
            })

        print(f"   🎨 开始生成 {len(image_types)} 张配图（{key_info_count} 个关键信息）...")

        # 存储已生成的图片
        generated_images: List[GeneratedImage] = []

        # 使用 MCP Server 上下文保持浏览器会话
        # 浏览器在所有图片生成完成后才关闭
        async with self.mcp_server:
            for image_type_info in image_types:
                image_type = image_type_info["type"]
                image_desc = image_type_info["desc"]

                print(f"\n      [{image_type}] {image_desc}")

                # 生成 Gemini 提示词（传入实体分配信息）
                print(f"         📝 生成图片描述提示词...")
                prompt = await self._generate_prompt(content, research, topic, image_type_info)
                print(f"         ✅ 提示词: {prompt[:60]}...")

                # 使用 Playwright 操作 Gemini 生成图片
                # 验证由 @GeminiConfigValidator 和 @ImageQualityValidator 装饰器处理
                print(f"         🌐 启动 Gemini 图片生成...")
                image_path = await self._generate_via_gemini(
                    prompt=prompt,
                    output_dir=output_dir,
                    image_type=image_type,
                    topic=topic  # 传递 topic 用于质量验证
                )

                generated_images.append(GeneratedImage(
                    image_path=str(image_path),
                    prompt_used=prompt,
                    image_type=image_type
                ))

                print(f"         ✅ {image_type} 生成并验证完成")

        # 所有图片生成完成，直接返回结果
        # 无需批量审核，每张图片已在生成时验证
        return ImageResult(
            images=generated_images,
            total_count=len(generated_images),
            generated_at=datetime.now().isoformat()
        )
        # <-- MCP Server 在这里退出，关闭浏览器

    async def _generate_prompt(
        self,
        content: XHSContent,
        research: ResearchResult,
        topic: str,
        image_type_info: Dict
    ) -> str:
        """
        生成 Gemini 图片提示词（带关键信息分配）

        Args:
            content: 内容数据
            research: 研究数据（包含 key_infos 列表）
            topic: 主题
            image_type_info: 图片类型信息（包含 type, desc, group_title, indices）
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

        result = await self.prompt_generator.run(user_prompt)
        return result.output

    @with_retry(max_retries=RetryConfig.MAX_RETRIES, initial_delay=RetryConfig.INITIAL_DELAY)
    @GeminiConfigValidator(max_retries=3, initial_delay=5.0)
    @ImageQualityValidator(max_retries=2, initial_delay=5.0)
    async def _generate_via_gemini(
        self,
        prompt: str,
        output_dir: Path,
        image_type: str = "cover",
        topic: str = ""
    ) -> Path:
        """
        通过 Gemini 网页生成图片（带重试和验证）

        三层重试机制（由装饰器处理）：
        1. @with_retry: 网络/API 错误重试
        2. @GeminiConfigValidator: 验证 Gemini 配置（Create images + Pro）
        3. @ImageQualityValidator: 验证图片质量（字迹清晰、风格匹配）

        失败时自动重试单张图片生成。

        Args:
            prompt: 图片描述提示词
            output_dir: 输出目录
            image_type: 图片类型
            topic: 主题（用于风格验证）

        Returns:
            Path: 图片保存路径
        """
        # 记录开始时间（用于筛选新下载的文件）
        start_time = time.time()
        self._operation_start_time = start_time  # 供 check_download_status 工具使用

        # 从 YAML 读取操作提示词模板并填充变量
        operation_prompt = get_prompt_field(
            "image",
            "gemini_operation_template",
            prompt=prompt
        )

        # 运行 Gemini 操作 Agent
        # 截屏验证由装饰器 @GeminiConfigValidator 处理
        result = await self.gemini_operator.run(operation_prompt)

        # 检查 Agent 输出状态
        if "SUCCESS" in result.output or "成功" in result.output:
            print(f"         ✅ Gemini 操作成功")
        else:
            print(f"         ⚠️ Gemini 操作状态: {result.output}")

        # 等待下载完成并移动文件到目标目录
        # 如果超时或找不到文件，让异常抛出，由验证装饰器处理重试
        image_path = self.download_manager.wait_and_move(
            target_dir=output_dir,
            target_name=image_type,
            file_pattern="*.png",
            timeout=TimeoutConfig.GEMINI_WAIT,
            before_time=start_time
        )
        print(f"         ✅ 图片已保存: {image_path}")

        return image_path

    async def list_tools(self) -> None:
        """列出所有可用的 MCP 工具（用于验证）"""
        print("\n   🔧 正在检查 Gemini 操作工具...")

        try:
            async with self.mcp_server as server:
                tools = await server.list_tools()
                print(f"\n   📋 发现 {len(tools)} 个 Playwright MCP 工具")
                for tool in tools[:5]:  # 只显示前5个
                    tool_name = f"{self.mcp_server.tool_prefix}_{tool.name}" if self.mcp_server.tool_prefix else tool.name
                    print(f"      ✅ {tool_name}")
        except Exception as e:
            print(f"   ⚠️ 无法列出工具: {e}")
