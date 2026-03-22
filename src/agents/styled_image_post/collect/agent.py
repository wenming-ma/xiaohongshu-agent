"""CollectAgent - LLM 视觉分析 + 飞书逐物品参考图片收集"""

from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import (
    GroupSpec,
    ResearchResult,
    GroupVisualAnalysis,
    VisualItemDetail,
    ItemReferenceImages,
    ReferenceImageGroup,
    ReferenceImageResult,
)
from ....utils.providers import get_text_model
from ....utils.feishu_notifier import get_feishu_notifier
from ....utils.logger import get_logger
from ....config.settings import ReferenceImageConfig
from .prompts import visual_analysis_system_prompt, visual_analysis_user_prompt

logger = get_logger(__name__)


class CollectAgent(BaseAgent):
    """参考图片收集 Agent

    通过 LLM 分析每个分组中的推荐内容，提取需要视觉呈现的物品，
    然后通过飞书逐物品向用户收集参考图片（每个物品支持多张图）。
    """

    role = "参考图片收集专员"
    goal = "分析分组推荐内容，逐物品向用户收集参考图片"

    def init_tools(self) -> None:
        self.notifier = get_feishu_notifier()

    def init_agent(self) -> None:
        model = get_text_model()
        self.analyzer = Agent(
            model=model,
            output_type=GroupVisualAnalysis,
            system_prompt=(visual_analysis_system_prompt(),),
            retries=3,
            instrument=True,
        )

    async def forward(
        self,
        groups: list[GroupSpec],
        research: ResearchResult,
        topic: str,
        output_dir: Path,
    ) -> ReferenceImageResult:
        """主入口：分析分组 → 逐物品收集参考图片"""
        if not ReferenceImageConfig.ENABLED:
            logger.info("参考图片收集已禁用 (REFERENCE_IMAGE_ENABLED=0)")
            return ReferenceImageResult(skipped=True)

        if not groups:
            return ReferenceImageResult(skipped=True)

        # 1. LLM 分析每个分组
        analyses: list[GroupVisualAnalysis] = []
        for i, group in enumerate(groups):
            analysis = await self.step(group, research, topic, group_index=i)
            analyses.append(analysis)

        # 2. 过滤有视觉物品的分组
        visual_groups = [a for a in analyses if a.has_visual_items and a.visual_items]
        if not visual_groups:
            logger.info("所有分组均无需视觉指定的推荐物品，跳过参考图片收集")
            return ReferenceImageResult(skipped=True)

        logger.info("检测到 %d 个分组包含推荐物品，开始收集参考图片", len(visual_groups))

        # 3. 发送汇总消息
        summary_msg = self._build_summary_message(topic, visual_groups)
        await self.notifier.send_message(summary_msg)

        # 4. 逐组、逐物品收集参考图片
        ref_dir = output_dir / "reference_images"
        ref_dir.mkdir(parents=True, exist_ok=True)

        collected_groups: list[ReferenceImageGroup] = []
        global_stop = False

        for analysis in visual_groups:
            if global_stop:
                break

            group_dir = ref_dir / f"group_{analysis.group_index}"
            group_dir.mkdir(parents=True, exist_ok=True)

            # 发送分组标题
            total_items = len(analysis.visual_items)
            await self.notifier.send_message(
                f"📸 分组{analysis.group_index + 1}: {analysis.group_title}\n"
                f"共 {total_items} 个物品需要参考图片"
            )

            item_refs: list[ItemReferenceImages] = []

            for item_idx, item in enumerate(analysis.visual_items):
                if global_stop:
                    break

                item_dir = group_dir / f"item_{item_idx}"
                item_dir.mkdir(parents=True, exist_ok=True)

                # 发送单物品提示
                prompt = self._build_item_prompt(item, item_idx, total_items)
                images, stop_reason = await self.notifier.collect_images(
                    prompt=prompt,
                    save_dir=item_dir,
                    done_keyword="完成",
                    skip_keyword="跳过",
                    next_keyword="下一个",
                    max_images=ReferenceImageConfig.MAX_IMAGES_PER_GROUP,
                )

                if stop_reason == "skip":
                    global_stop = True
                elif stop_reason == "done":
                    global_stop = True
                elif stop_reason == "next" and len(images) == 0:
                    # 用户说"下一个"但没发图，提醒确认
                    confirm_msg = (
                        f'⚠️ 还没有收到「{item.name}」的参考图片，确定跳过吗？\n'
                        f'回复"确定"跳过，或发送图片继续'
                    )
                    more_images, reason2 = await self.notifier.collect_images(
                        prompt=confirm_msg,
                        save_dir=item_dir,
                        done_keyword="完成",
                        skip_keyword="跳过",
                        next_keyword="确定",
                        max_images=ReferenceImageConfig.MAX_IMAGES_PER_GROUP,
                    )
                    images.extend(more_images)
                    if reason2 == "skip":
                        global_stop = True
                    elif reason2 == "done":
                        global_stop = True

                item_refs.append(ItemReferenceImages(
                    item_name=item.name,
                    image_paths=[str(p) for p in images],
                ))

                if images:
                    logger.info("物品「%s」: 收集到 %d 张参考图片", item.name, len(images))
                else:
                    logger.info("物品「%s」: 已跳过", item.name)

            collected_groups.append(ReferenceImageGroup(
                group_index=analysis.group_index,
                group_title=analysis.group_title,
                items=item_refs,
            ))

        result = ReferenceImageResult(groups=collected_groups)

        validation = await self.validate(result)
        if not validation.passed:
            logger.warning("参考图片收集验证: %s", validation.feedback)

        total = sum(len(item.image_paths) for g in collected_groups for item in g.items)
        logger.info("参考图片收集完成: %d 个分组, %d 张图片", len(collected_groups), total)
        return result

    async def step(
        self,
        group: GroupSpec,
        research: ResearchResult,
        topic: str,
        group_index: int = 0,
    ) -> GroupVisualAnalysis:
        """分析单个分组中的推荐物品"""
        indices = group.get("indices", [])
        items = [research.items[i] for i in indices if 0 <= i < len(research.items)]

        if not items:
            return GroupVisualAnalysis(
                group_index=group_index,
                group_title=group.get("title", ""),
                has_visual_items=False,
                summary="分组无内容项",
            )

        items_text = "\n".join([
            f"{j+1}. **{item.title}**: {item.content}"
            for j, item in enumerate(items)
        ])

        user_prompt = visual_analysis_user_prompt(
            topic=topic,
            group_title=group.get("title", ""),
            group_index=group_index,
            items_text=items_text,
        )

        result = await self.analyzer.run(user_prompt)
        analysis = result.output
        analysis.group_index = group_index
        analysis.group_title = group.get("title", "")

        if analysis.has_visual_items:
            logger.info(
                "分组 %d「%s」: 检测到 %d 个视觉物品",
                group_index, group.get("title", ""), len(analysis.visual_items),
            )
        else:
            logger.info("分组 %d「%s」: 无需视觉指定的物品", group_index, group.get("title", ""))

        return analysis

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, ReferenceImageResult):
            return ValidationResult.failure("输出类型错误")
        return ValidationResult.success()

    # ========================================================================
    # 消息构建
    # ========================================================================

    def _build_summary_message(
        self,
        topic: str,
        visual_groups: list[GroupVisualAnalysis],
    ) -> str:
        lines = [
            f"📸 需要参考图片\n",
            f"帖子主题：{topic}\n",
            f"以下 {len(visual_groups)} 个分组包含推荐物品，将逐个物品收集参考图片：\n",
        ]
        for analysis in visual_groups:
            item_names = ", ".join(item.name for item in analysis.visual_items)
            lines.append(f"🔹 分组{analysis.group_index + 1}: {analysis.group_title}")
            lines.append(f"   物品: {item_names}\n")

        lines.append("接下来逐个物品发送提示，每个物品可发多张图（不同角度/细节）。")
        return "\n".join(lines)

    def _build_item_prompt(
        self,
        item: VisualItemDetail,
        item_idx: int,
        total_items: int,
    ) -> str:
        lines = [
            f"📸 [{item_idx + 1}/{total_items}] 请发送「{item.name}」的参考图片",
            f"可发送多张（不同角度/细节），发完回复\"下一个\"",
        ]
        if item.description:
            lines.append(f"描述: {item.description}")
        for q in item.visual_questions:
            lines.append(f"   - {q}")
        lines.append("")
        lines.append('跳过所有剩余物品回复"跳过"，全部完成回复"完成"')
        return "\n".join(lines)
