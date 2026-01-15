"""
分组处理工具模块

包含：
- indices 验证工具
- 分组后处理管道
"""
import math
from typing import Any

from ...models.schemas import GroupSpec
from ...config.settings import ImageConfig
from ...utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Indices 验证工具
# ============================================================================

def validate_index(idx: Any, n_key_infos: int) -> bool:
    """验证单个 index 是否有效"""
    return isinstance(idx, int) and 0 <= idx < n_key_infos


def clean_indices(indices: list, n_key_infos: int) -> list[int]:
    """清理并验证 indices 列表"""
    return [idx for idx in indices if validate_index(idx, n_key_infos)]


# ============================================================================
# 分组处理工具
# ============================================================================

def dedupe_and_filter_indices(
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
            if not validate_index(idx, n_key_infos):
                continue
            if idx in seen:
                continue
            seen.add(idx)
            indices.append(idx)

        if indices:
            indices.sort()
            cleaned.append({"title": title, "indices": indices})

    return cleaned, seen


def fill_missing_indices(
    groups: list[GroupSpec],
    seen: set[int],
    n_key_infos: int,
) -> list[GroupSpec]:
    """补齐未被分配的 indices"""
    missing = [i for i in range(n_key_infos) if i not in seen]
    if missing:
        groups.append({"title": "其他补充", "indices": missing})
    return groups


def split_large_groups(
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


def merge_small_groups(
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


def validate_groups(groups: list[GroupSpec], n_key_infos: int, max_group_size: int) -> None:
    """运行时校验分组"""
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


def cap_groups_to_max_images(
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

    # 降级：均匀分块
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


def adjust_groups_to_target_count(
    groups: list[GroupSpec],
    *,
    target_groups: int,
    max_group_size_cap: int,
) -> list[GroupSpec]:
    """调整组数量接近 target_groups"""
    if target_groups <= 0:
        return groups

    adjusted = [dict(title=g.get("title", "要点"), indices=list(g.get("indices", []))) for g in groups]

    # 如果组数过多，先压缩
    if len(adjusted) > target_groups:
        adjusted = cap_groups_to_max_images(
            adjusted,
            max_groups=target_groups,
            max_group_size_cap=max_group_size_cap,
        )

    # 如果组数过少，拆分最大的组
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


# ============================================================================
# 分组后处理管道
# ============================================================================

def normalize_grouping_plan(
    plan,
    n_key_infos: int,
    max_group_size: int,
    min_group_size: int | None = None,
) -> list[GroupSpec]:
    """归一化分组计划"""
    if min_group_size is None:
        threshold = ImageConfig.MIN_GROUP_SIZE_THRESHOLD
        min_group_size = 3 if n_key_infos >= threshold else 1

    raw_groups = plan.groups or []

    cleaned, seen = dedupe_and_filter_indices(raw_groups, n_key_infos)
    cleaned = fill_missing_indices(cleaned, seen, n_key_infos)

    if not cleaned:
        return [{"title": "要点汇总", "indices": list(range(n_key_infos))}]

    split_groups = split_large_groups(cleaned, max_group_size)
    merged = merge_small_groups(split_groups, min_group_size, max_group_size)

    # 最终校验
    all_indices: list[int] = []
    for g in merged:
        all_indices.extend(g["indices"])
    if set(all_indices) != set(range(n_key_infos)) or len(all_indices) != n_key_infos:
        # 降级：均匀分块
        idxs = list(range(n_key_infos))
        chunks = [idxs[i : i + max_group_size] for i in range(0, len(idxs), max_group_size)]
        return [{"title": f"要点清单（{i}/{len(chunks)}）", "indices": chunk} for i, chunk in enumerate(chunks, start=1)]

    return merged


def post_process_groups(
    groups: list[GroupSpec],
    *,
    n_key_infos: int,
    target_groups: int,
    target_group_size: int,
    max_group_size_cap: int,
    max_detail_images: int,
) -> list[GroupSpec]:
    """统一的分组后处理管道"""
    # 1. 验证
    validate_groups(groups, n_key_infos, target_group_size)

    # 2. 调整到目标数量
    groups = adjust_groups_to_target_count(
        groups,
        target_groups=target_groups,
        max_group_size_cap=max_group_size_cap,
    )

    # 3. 限制最大数量
    groups = cap_groups_to_max_images(
        groups,
        max_groups=max_detail_images,
        max_group_size_cap=max_group_size_cap,
    )

    return groups
