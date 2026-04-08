"""分组处理工具模块"""
import json
import math
from typing import TYPE_CHECKING

from pydantic_ai.messages import ModelMessage

from ..schemas import (
    GroupSpec,
    CompactKeyInfo,
    ImageTypeSpec,
    ImageGroupingPlan,
    ImageGroupingReviewResult,
    ResearchResult,
)
from ....config.settings import ImageConfig
from ....utils.logger import get_logger
from ..image.prompts import (
    image_grouping_revision_user_prompt,
    image_grouping_review_user_prompt,
    image_grouping_user_prompt,
)
from ..image.state import MessageHistoryManager

if TYPE_CHECKING:
    from pydantic_ai import Agent

logger = get_logger(__name__)


def build_compact_items(items: list) -> list[CompactKeyInfo]:
    """将 items 转换为精简格式"""
    max_text_len = ImageConfig.COMPACT_TEXT_MAX_LEN
    compact_items: list[CompactKeyInfo] = []
    for i, item in enumerate(items):
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


def _normalize_ref_items(ref_items: list[str] | None) -> list[str]:
    """去重并清理单个分组内的参考图物品名。"""
    normalized: list[str] = []
    seen: set[str] = set()
    for ref_item in ref_items or []:
        if not isinstance(ref_item, str):
            continue
        name = ref_item.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def normalize_group_ref_items(
    groups: list[GroupSpec],
    allowed_ref_items: list[str] | None = None,
) -> list[GroupSpec]:
    """
    归一化分组中的 ref_items，并在提供参考图清单时校验未知物品。

    - 允许同一个参考图物品出现在多个分组中
    - 仅去除单个分组内重复的 ref_items
    - 若出现未提供参考图的物品，直接抛错，避免后续生成继续执行
    """
    allowed_set = None
    if allowed_ref_items is not None:
        allowed_set = {
            ref_item.strip()
            for ref_item in allowed_ref_items
            if isinstance(ref_item, str) and ref_item.strip()
        }

    normalized_groups: list[GroupSpec] = []
    for group in groups:
        ref_items = _normalize_ref_items(group.get("ref_items", []))
        if allowed_set is not None:
            unknown_items = [ref_item for ref_item in ref_items if ref_item not in allowed_set]
            if unknown_items:
                allowed_text = "、".join(sorted(allowed_set)) if allowed_set else "（空）"
                raise ValueError(
                    "分组中出现未识别的参考图物品: "
                    f"{'、'.join(unknown_items)}。可用参考图物品: {allowed_text}"
                )

        normalized_group: GroupSpec = {
            "title": group["title"],
            "indices": list(group.get("indices", [])),
        }
        if "rationale" in group and group.get("rationale") is not None:
            normalized_group["rationale"] = group["rationale"]
        normalized_group["ref_items"] = ref_items
        normalized_groups.append(normalized_group)

    return normalized_groups


def calculate_grouping_params(item_count: int) -> tuple[int, int, int]:
    """根据 item 数量计算分组参数"""
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
    max_group_size_cap = max(
        ImageConfig.MAX_GROUP_SIZE_CAP,
        ImageConfig.ENTITIES_PER_DETAIL,
        target_group_size,  # 确保 cap >= 实际每组需要的数量，避免数学上不可能通过验证
    )
    return target_groups, target_group_size, max_group_size_cap


def groups_to_image_specs(groups: list[GroupSpec]) -> list[ImageTypeSpec]:
    """将分组列表转换为图片生成规格列表"""
    image_types: list[ImageTypeSpec] = [
        {"type": "cover", "desc": "封面图 - 大标题风格，突出主题"}
    ]
    for i, g in enumerate(groups, start=1):
        image_types.append({
            "type": f"detail_{i}",
            "desc": f"详情图{i} - 语义分组：{g['title']}",
            "group_title": g["title"],
            "indices": g["indices"],
            "ref_items": _normalize_ref_items(g.get("ref_items", [])),
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
    """验证并审核分组结果"""
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

    expected = set(range(n_items))
    actual = set(all_indices)
    missing = sorted(expected - actual)
    duplicates = sorted(idx for idx in actual if all_indices.count(idx) > 1)
    if missing:
        issues.append(f"缺少 indices: {missing}")
    if duplicates:
        issues.append(f"重复 indices: {duplicates}")
    if len(all_indices) != n_items and not missing and not duplicates:
        issues.append(f"索引总数 {len(all_indices)} != 期望 {n_items}")

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
    ref_item_names: list[str] | None = None,
) -> list[GroupSpec]:
    """语义分组 + 审核循环"""
    max_detail_images = ImageConfig.MAX_DETAIL_IMAGES
    max_review_retries = ImageConfig.GROUPING_REVIEW_MAX_RETRIES

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
                ref_item_names=", ".join(ref_item_names) if ref_item_names else "",
            )
            grouping_result = await grouping_agent.run(user_prompt, message_history=messages)
            round_messages = list(grouping_result.new_messages())
        else:
            issues_text = "\n".join(f"- {issue}" for issue in review.issues)
            feedback = f"分组审核未通过（{review.score:.0f}分）：{review.summary}\n\n问题：\n{issues_text}"
            user_prompt = image_grouping_revision_user_prompt(
                topic=topic,
                max_group_size=target_group_size,
                target_groups=target_groups,
                feedback=feedback,
            )
            grouping_result = await grouping_agent.run(
                user_prompt,
                message_history=messages,
            )
            round_messages = list(grouping_result.new_messages())

        history_mgr.add_grouping_round(round_messages)
        plan: ImageGroupingPlan = grouping_result.output

        groups = normalize_group_ref_items(
            [
                {"title": g.title, "indices": g.indices, "ref_items": g.ref_items}
                for g in plan.groups
            ],
            allowed_ref_items=ref_item_names,
        )

        review, review_round_messages = await review_groups(
            reviewer=grouping_reviewer,
            topic=topic,
            compact_items=compact_items,
            groups=groups,
            target_groups=target_groups,
            max_group_size=max_group_size_cap,
            max_groups=max_detail_images,
            message_history=history_mgr.get_review_history(),
        )

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
