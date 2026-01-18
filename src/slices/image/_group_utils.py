"""
分组处理工具模块

包含：
- build_compact_items: items → 精简格式
- calculate_grouping_params: 计算分组参数
- groups_to_image_specs: groups → 图片生成规格
- review_groups: 验证 + 审核分组
- run_grouping_with_review: 语义分组 + 审核循环
"""
import json
import math
from typing import TYPE_CHECKING

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


async def review_groups(
    *,
    reviewer: "Agent[None, ImageGroupingReviewResult]",
    topic: str,
    compact_items: list[CompactKeyInfo],
    groups: list[GroupSpec],
    target_groups: int,
    max_group_size: int,
    max_groups: int,
    message_history: list[ModelMessage] | None = None,
) -> tuple[ImageGroupingReviewResult, list[ModelMessage]]:
    """
    验证并审核分组结果

    先做结构验证，通过后再调用 LLM 审核。

    Args:
        reviewer: 分组审核 Agent 实例
        topic: 主题
        compact_items: 精简格式的 items
        groups: 分组列表
        target_groups: 目标分组数
        max_group_size: 每组最大大小
        max_groups: 最大分组数量
        message_history: 消息历史

    Returns:
        (审核结果, 新消息列表)
    """
    # 1. 结构验证
    n_items = len(compact_items)
    issues = []

    if len(groups) > max_groups:
        issues.append(f"分组数量 {len(groups)} 超过限制 {max_groups}，请合并语义相近的分组")

    all_indices: list[int] = []
    for i, g in enumerate(groups):
        idxs = g.get("indices", [])
        if not isinstance(idxs, list) or len(idxs) == 0:
            issues.append(f"分组 {i+1} 的 indices 无效")
            continue
        if len(idxs) > max_group_size:
            issues.append(f"分组 {i+1} 有 {len(idxs)} 项，超过限制 {max_group_size}")
        for idx in idxs:
            if isinstance(idx, int) and 0 <= idx < n_items:
                all_indices.append(idx)

    if len(all_indices) != n_items or set(all_indices) != set(range(n_items)):
        issues.append(f"分组未完整覆盖所有 {n_items} 个关键信息，请确保每个信息只出现一次")

    # 2. 验证失败直接返回，通过则调用 LLM 审核
    if issues:
        review_result = ImageGroupingReviewResult(passed=False, score=0.0, summary="分组验证失败", issues=issues)
        new_messages: list[ModelMessage] = []
    else:
        user_prompt = image_grouping_review_user_prompt(
            topic=topic,
            key_infos_json=json.dumps(compact_items, ensure_ascii=False, indent=2),
            groups_json=json.dumps(groups, ensure_ascii=False, indent=2),
            target_groups=target_groups,
            max_group_size=max_group_size,
        )
        result = await reviewer.run(user_prompt, message_history=message_history or [])
        review_result, new_messages = result.output, list(result.new_messages())

    return review_result, new_messages


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
        logger.info("语义分组 (第%d轮)...", attempt + 1)
        messages = history_mgr.get_grouping_history()

        if attempt == 0:
            user_prompt = image_grouping_user_prompt(
                topic=topic,
                key_infos_json=json.dumps(compact_items, ensure_ascii=False, indent=2),
                max_group_size=target_group_size,
                target_groups=target_groups,
            )
            grouping_result = await grouping_agent.run(user_prompt, message_history=messages)
            round_messages = list(grouping_result.new_messages())
        else:
            issues_text = "\n".join(f"- {issue}" for issue in review.issues)
            feedback = f"分组审核未通过（{review.score:.0f}分）：{review.summary}\n\n问题：\n{issues_text}"
            feedback_message = ModelRequest(parts=[UserPromptPart(feedback)])
            grouping_result = await grouping_agent.run(
                "请根据上述反馈重新分组。",
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

        # 验证 + 审核（验证失败时不调用 LLM）
        review, review_round_messages = await review_groups(
            reviewer=grouping_reviewer,
            topic=topic,
            compact_items=compact_items,
            groups=groups,
            target_groups=len(groups),
            max_group_size=max_group_size_cap,
            max_groups=max_detail_images,
            message_history=history_mgr.get_review_history(),
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
