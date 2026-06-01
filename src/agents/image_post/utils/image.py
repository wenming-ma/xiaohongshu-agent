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
from .research import is_operational_research_item

if TYPE_CHECKING:
    from pydantic_ai import Agent

logger = get_logger(__name__)


def build_compact_items(items: list) -> list[CompactKeyInfo]:
    """将 items 转换为精简格式"""
    max_text_len = ImageConfig.COMPACT_TEXT_MAX_LEN
    compact_items: list[CompactKeyInfo] = []
    for i, item in enumerate(items):
        if is_operational_research_item(item):
            logger.warning("跳过不可成图的研究过程诊断信息: index=%d", i)
            continue

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


def calculate_grouping_params(
    item_count: int,
    *,
    requested_image_count: int | None = None,
    single_item_per_image: bool = False,
) -> tuple[int, int, int, bool]:
    """根据 item 数量计算分组参数"""
    max_detail_images = ImageConfig.MAX_DETAIL_IMAGES
    if single_item_per_image:
        target_groups = min(
            max_detail_images,
            item_count,
            max(1, requested_image_count) if requested_image_count is not None else item_count,
        )
        return target_groups, 1, 1, target_groups >= item_count

    if requested_image_count is not None:
        requested_detail_images = max(0, requested_image_count - 1)
        target_groups = min(max_detail_images, item_count, requested_detail_images)
        if target_groups <= 0:
            return 0, ImageConfig.ENTITIES_PER_DETAIL, ImageConfig.MAX_GROUP_SIZE_CAP, True
    else:
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
    return target_groups, target_group_size, max_group_size_cap, True


def groups_to_image_specs(groups: list[GroupSpec]) -> list[ImageTypeSpec]:
    """将分组列表转换为图片生成规格列表"""
    image_types: list[ImageTypeSpec] = [
        {"type": "cover", "desc": "封面图 - 纯视觉主图，突出主题；除非用户明确要求文字海报，否则不要生成标题文字"}
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
    require_all_items: bool = True,
    message_history: list[ModelMessage] | None = None,
) -> tuple[ImageGroupingReviewResult, list[ModelMessage]]:
    """验证并审核分组结果"""
    valid_indices = {
        item.get("index")
        for item in compact_items
        if isinstance(item.get("index"), int)
    }
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
            if isinstance(idx, int) and idx in valid_indices:
                all_indices.append(idx)
            else:
                issues.append(f"分组 {i+1} 包含无效 index: {idx}")

    actual = set(all_indices)
    missing = sorted(valid_indices - actual)
    duplicates = sorted(idx for idx in actual if all_indices.count(idx) > 1)
    if missing and require_all_items:
        issues.append(f"缺少 indices: {missing}")
    if duplicates:
        issues.append(f"重复 indices: {duplicates}")
    if require_all_items and len(all_indices) != len(valid_indices) and not missing and not duplicates:
        issues.append(f"索引总数 {len(all_indices)} != 期望 {len(valid_indices)}")

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
            item_usage_rule=_item_usage_rule(require_all_items=require_all_items, max_group_size=max_group_size),
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
    require_all_items: bool = True,
) -> list[GroupSpec]:
    """语义分组 + 审核循环"""
    max_detail_images = ImageConfig.MAX_DETAIL_IMAGES
    max_review_retries = ImageConfig.GROUPING_REVIEW_MAX_RETRIES

    history_mgr = MessageHistoryManager(max_rounds=3)
    groups: list[GroupSpec] = []

    if not compact_items:
        logger.warning("没有可成图的研究内容，跳过语义分组")
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
                item_usage_rule=_item_usage_rule(
                    require_all_items=require_all_items,
                    max_group_size=target_group_size,
                ),
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
                item_usage_rule=_item_usage_rule(
                    require_all_items=require_all_items,
                    max_group_size=target_group_size,
                ),
                feedback=feedback,
            )
            grouping_result = await grouping_agent.run(
                user_prompt,
                message_history=messages,
            )
            round_messages = list(grouping_result.new_messages())

        history_mgr.add_grouping_round(round_messages)
        plan: ImageGroupingPlan = grouping_result.output

        groups = [
            {"title": g.title, "indices": g.indices}
            for g in plan.groups
        ]

        review, review_round_messages = await review_groups(
            reviewer=grouping_reviewer,
            topic=topic,
            compact_items=compact_items,
            groups=groups,
            target_groups=target_groups,
            max_group_size=max_group_size_cap,
            max_groups=max_detail_images,
            require_all_items=require_all_items,
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


def _item_usage_rule(*, require_all_items: bool, max_group_size: int) -> str:
    if require_all_items:
        return "完整覆盖模式：每个 key_info 必须被分到且只分到 1 个组。"
    if max_group_size <= 1:
        return (
            "精选模式：只选择最适合成图的 target_groups 个 key_info；"
            "每组必须且只能包含 1 个 index；未被选中的素材可以不使用。"
        )
    return (
        "精选模式：只选择最适合成图的素材组成 target_groups 个组；"
        "每个被选中的 index 只能出现一次，未被选中的素材可以不使用。"
    )
