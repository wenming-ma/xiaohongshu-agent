"""
分组处理工具模块

包含：
- build_compact_items: items → 精简格式
- calculate_grouping_params: 计算分组参数
- groups_to_image_specs: groups → 图片生成规格
- validate_groups: 防御性校验
- cap_groups_to_max_images: 限制最大图片数量
- review_groups: 调用分组审核 Agent
- run_grouping_with_review: 语义分组 + 审核循环
"""
import json
import math
from typing import TYPE_CHECKING, Optional

from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

from ...models.schemas import (
    GroupSpec,
    CompactKeyInfo,
    ImageTypeSpec,
    ImageGroupingPlan,
    ImageGroupingReviewResult,
    ResearchResult,
)
from ...config.settings import ImageConfig
from ...utils.logger import get_logger
from .prompts import image_grouping_user_prompt, image_grouping_review_user_prompt
from ._state import MessageHistoryManager

if TYPE_CHECKING:
    from pydantic_ai import Agent

logger = get_logger(__name__)


def build_compact_items(items: list) -> list[CompactKeyInfo]:
    """
    将 items 转换为精简格式

    Args:
        items: ResearchItem 列表或字典列表

    Returns:
        精简格式的 items 列表
    """
    max_text_len = ImageConfig.COMPACT_TEXT_MAX_LEN
    compact_items: list[CompactKeyInfo] = []
    for i, item in enumerate(items):
        # 支持 ResearchItem 对象或字典
        if hasattr(item, 'title'):
            title = item.title
            content = item.content
            item_type = item.item_type
        else:
            title = item.get("title") or item.get("name") or ""
            content = item.get("content") or item.get("description") or item.get("detail") or ""
            item_type = item.get("item_type") or item.get("type")

        text = f"{title}: {content}".strip(": ").strip()
        compact_items.append({
            "index": i,
            "type": item_type,
            "name": title,
            "text": text[:max_text_len],
        })
    return compact_items


def calculate_grouping_params(item_count: int) -> tuple[int, int, int]:
    """
    根据 item 数量计算分组参数

    Args:
        item_count: items 总数

    Returns:
        (target_groups, target_group_size, max_group_size_cap)
    """
    max_detail_images = ImageConfig.MAX_DETAIL_IMAGES
    target_groups = min(
        max_detail_images,
        max(ImageConfig.MIN_DETAIL_IMAGES, math.ceil(item_count / ImageConfig.ENTITIES_PER_DETAIL))
    )
    if target_groups > 0:
        target_group_size = math.ceil(item_count / target_groups)
    else:
        target_group_size = ImageConfig.ENTITIES_PER_DETAIL
    target_group_size = max(ImageConfig.ENTITIES_PER_DETAIL, target_group_size)
    max_group_size_cap = max(ImageConfig.MAX_GROUP_SIZE_CAP, ImageConfig.ENTITIES_PER_DETAIL)
    return target_groups, target_group_size, max_group_size_cap


def groups_to_image_specs(groups: list[GroupSpec]) -> list[ImageTypeSpec]:
    """
    将分组列表转换为图片生成规格列表

    Args:
        groups: 分组列表

    Returns:
        图片规格列表（封面 + 详情图）
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


def validate_groups(groups: list[GroupSpec], n_items: int, max_group_size: int) -> Optional[str]:
    """
    防御性校验分组结果

    Args:
        groups: 分组列表
        n_items: items 总数
        max_group_size: 每组最大大小

    Returns:
        None: 验证通过
        str: 验证失败的错误信息
    """
    all_indices: list[int] = []

    for g in groups:
        idxs = g.get("indices", [])
        if not isinstance(idxs, list):
            return "group.indices must be a list"
        if len(idxs) == 0:
            return "group.indices is empty"
        if len(idxs) > max_group_size:
            return f"group too large: {len(idxs)} > {max_group_size}"

        for idx in idxs:
            if not isinstance(idx, int):
                return "index must be int"
            if idx < 0 or idx >= n_items:
                return f"index out of range: {idx}"
            all_indices.append(idx)

    if len(all_indices) != n_items:
        return f"coverage mismatch: {len(all_indices)} != {n_items}"
    if set(all_indices) != set(range(n_items)):
        return "coverage mismatch: indices not complete or duplicated"

    return None


def cap_groups_to_max_images(
    groups: list[GroupSpec],
    *,
    max_groups: int,
    max_group_size_cap: int,
) -> list[GroupSpec]:
    """
    限制分组数量不超过 max_groups（通过合并相邻组）

    Args:
        groups: 分组列表
        max_groups: 最大分组数
        max_group_size_cap: 合并后单组最大大小

    Returns:
        合并后的分组列表
    """
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

    return merged


async def review_groups(
    *,
    reviewer: "Agent[None, ImageGroupingReviewResult]",
    topic: str,
    compact_items: list[CompactKeyInfo],
    groups: list[GroupSpec],
    target_groups: int,
    max_group_size: int,
    message_history: list[ModelMessage] | None = None,
) -> tuple[ImageGroupingReviewResult, list[ModelMessage]]:
    """
    调用分组审核 Agent

    Args:
        reviewer: 分组审核 Agent 实例
        topic: 主题
        compact_items: 精简格式的 items
        groups: 分组列表
        target_groups: 目标分组数
        max_group_size: 每组最大大小
        message_history: 消息历史

    Returns:
        (审核结果, 新消息列表)
    """
    user_prompt = image_grouping_review_user_prompt(
        topic=topic,
        key_infos_json=json.dumps(compact_items, ensure_ascii=False, indent=2),
        groups_json=json.dumps(groups, ensure_ascii=False, indent=2),
        target_groups=target_groups,
        max_group_size=max_group_size,
    )
    result = await reviewer.run(user_prompt, message_history=message_history or [])
    return result.output, list(result.new_messages())


async def run_grouping_with_review(
    *,
    grouping_agent: "Agent[None, ImageGroupingPlan]",
    grouping_reviewer: "Agent[None, ImageGroupingReviewResult]",
    topic: str,
    research: ResearchResult,
    compact_items: list[CompactKeyInfo],
    target_groups: int,
    target_group_size: int,
    max_group_size_cap: int,
) -> list[GroupSpec]:
    """
    语义分组 + 审核循环

    Args:
        grouping_agent: 分组 Agent 实例
        grouping_reviewer: 审核 Agent 实例
        topic: 主题
        research: 研究结果
        compact_items: 精简格式的 items
        target_groups: 目标分组数
        target_group_size: 每组目标大小
        max_group_size_cap: 每组最大大小上限

    Returns:
        分组列表
    """
    max_detail_images = ImageConfig.MAX_DETAIL_IMAGES
    max_review_retries = ImageConfig.GROUPING_REVIEW_MAX_RETRIES

    # 使用 MessageHistoryManager 管理消息历史
    history_mgr = MessageHistoryManager(max_rounds=3)
    groups: list[GroupSpec] = []

    if len(research.items or []) == 0:
        return []

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

        # 获取分组历史
        messages = history_mgr.get_grouping_history()

        # 执行分组
        if attempt == 0:
            grouping_result = await grouping_agent.run(user_prompt, message_history=messages)
            round_messages = list(grouping_result.new_messages())
        else:
            grouping_result = await grouping_agent.run(
                user_prompt,
                message_history=messages + [feedback_message],
            )
            round_messages = [feedback_message] + list(grouping_result.new_messages())

        # 保存本轮消息
        history_mgr.add_grouping_round(round_messages)
        plan: ImageGroupingPlan = grouping_result.output

        # 转换为 GroupSpec 格式
        groups = [
            {"title": g.title, "indices": g.indices}
            for g in plan.groups
        ]

        # 防御性校验（使用硬性上限而非建议值）
        validation_error = validate_groups(groups, len(compact_items), max_group_size_cap)
        if validation_error:
            # 验证失败：构造审核不通过的结果，让AI重新分组
            logger.warning(f"分组验证失败: {validation_error}")

            # 构造一个模拟的审核不通过结果
            from ...models.schemas import ImageGroupingReviewResult
            review = ImageGroupingReviewResult(
                passed=False,
                score=0.0,
                summary=f"分组验证失败: {validation_error}",
                issues=[
                    f"验证错误: {validation_error}",
                    f"每组最大允许 {max_group_size_cap} 个项目",
                    "请重新分组，确保每组大小符合要求"
                ]
            )

            logger.warning(
                "分组验证未通过 (attempt=%d/%d): %s",
                attempt + 1, max_review_retries, validation_error
            )
            continue  # 跳过本轮，进入下一轮重试

        # 限制最大图片数量
        groups = cap_groups_to_max_images(
            groups,
            max_groups=max_detail_images,
            max_group_size_cap=max_group_size_cap,
        )

        # 获取审核历史
        review_messages = history_mgr.get_review_history()

        # 审核分组
        review, review_round_messages = await review_groups(
            reviewer=grouping_reviewer,
            topic=topic,
            compact_items=compact_items,
            groups=groups,
            target_groups=len(groups),
            max_group_size=target_group_size,
            message_history=review_messages,
        )

        # 保存审核消息
        history_mgr.add_review_round(review_round_messages)

        if review.passed:
            logger.info("分组审核通过 (score=%.1f)", review.score)
            return groups

        logger.warning(
            "分组审核未通过 (attempt=%d/%d): %s",
            attempt + 1, max_review_retries, review.summary
        )

    logger.warning(
        "分组审核失败（已重试 %d 次），将使用最后一次分组继续生成 (最后评分: %.1f, 问题: %s)",
        max_review_retries, review.score, review.summary
    )
    return groups
