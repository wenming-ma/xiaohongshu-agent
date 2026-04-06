"""CollectAgent - 推荐物品识别 + 用户确认 + 参考图片收集"""

import re
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import (
    ResearchResult,
    RecommendationAnalysis,
    VisualItemDetail,
    ItemReferenceImages,
    ReferenceImageResult,
)
from ....utils.providers import get_text_model
from ....utils.feishu_notifier import get_feishu_notifier
from ....utils.logger import get_logger
from ....config.settings import ReferenceImageConfig
from .prompts import recommendation_system_prompt, recommendation_user_prompt

logger = get_logger(__name__)


class CollectAgent(BaseAgent):
    """推荐物品识别与参考图片收集 Agent

    流程：
    1. LLM 从研究数据中识别正面推荐的视觉物品
    2. 通过飞书让用户确认/删除/补充推荐列表
    3. 逐物品收集参考图片
    """

    role = "推荐物品识别与参考图片收集专员"
    goal = "识别推荐物品，收集参考图片"

    def init_tools(self) -> None:
        self.notifier = get_feishu_notifier()

    def init_agent(self) -> None:
        model = get_text_model()
        self.analyzer = Agent(
            model=model,
            output_type=RecommendationAnalysis,
            system_prompt=(recommendation_system_prompt(),),
            retries=3,
            instrument=True,
        )

    async def forward(
        self,
        research: ResearchResult,
        topic: str,
        target_audience: str,
        output_dir: Path,
    ) -> ReferenceImageResult:
        """主入口：识别推荐物品 → 用户确认 → 收集参考图片"""
        if not research.items:
            return ReferenceImageResult(skipped=True)

        # Phase 1: LLM 识别推荐物品
        logger.info("分析研究数据，识别推荐物品...")
        recommendations = await self.identify_recommendations(
            research, topic, target_audience
        )

        if not recommendations:
            logger.info("未识别到需要视觉呈现的推荐物品")
            return ReferenceImageResult(skipped=True)

        logger.info("识别到 %d 个推荐物品", len(recommendations))

        # Phase 2: 用户确认与补充
        confirmed = await self.confirm_with_user(recommendations, topic)

        if not confirmed:
            logger.info("用户跳过推荐物品列表")
            return ReferenceImageResult(skipped=True)

        logger.info("用户确认 %d 个推荐物品", len(confirmed))

        # Phase 3: 逐物品收集参考图片
        ref_dir = output_dir / "reference_images"
        ref_dir.mkdir(parents=True, exist_ok=True)

        collected = await self.collect_images(confirmed, ref_dir)

        result = ReferenceImageResult(items=collected)

        validation = await self.validate(result)
        if not validation.passed:
            logger.warning("参考图片收集验证: %s", validation.feedback)

        total = sum(len(item.image_paths) for item in collected)
        logger.info("参考图片收集完成: %d 个物品, %d 张图片", len(collected), total)
        return result

    async def step(self, *args, **kwargs):
        """由 forward 内部各阶段方法替代，不直接使用"""
        raise NotImplementedError("CollectAgent uses identify/confirm/collect phases instead of step")

    # ========================================================================
    # Phase 1: 识别推荐物品
    # ========================================================================

    async def identify_recommendations(
        self,
        research: ResearchResult,
        topic: str,
        target_audience: str,
    ) -> list[VisualItemDetail]:
        """LLM 分析全部研究条目，提取正面推荐的视觉物品"""
        items_text = "\n".join([
            f"{i+1}. **{item.title}**: {item.content}"
            for i, item in enumerate(research.items)
        ])

        user_prompt = recommendation_user_prompt(
            topic=topic,
            target_audience=target_audience,
            items_text=items_text,
        )

        result = await self.analyzer.run(user_prompt)
        analysis = result.output

        if analysis.recommendations:
            logger.info(
                "识别到 %d 个推荐物品: %s",
                len(analysis.recommendations),
                ", ".join(item.name for item in analysis.recommendations),
            )
        else:
            logger.info("未识别到推荐物品。分析结论: %s", analysis.summary)

        return analysis.recommendations

    # ========================================================================
    # Phase 2: 用户确认与补充
    # ========================================================================

    async def confirm_with_user(
        self,
        recommendations: list[VisualItemDetail],
        topic: str,
    ) -> list[VisualItemDetail]:
        """通过飞书卡片让用户确认/删除/补充推荐物品列表"""
        if self.notifier.client is None:
            logger.warning("飞书客户端未初始化，跳过用户确认")
            return recommendations

        items = list(recommendations)

        # 发送初始列表
        await self._send_recommendation_card(items, topic)

        # 交互循环：等待用户确认、删除或补充
        while True:
            image_path, text = await self.notifier.wait_for_image_or_text()

            if image_path is not None:
                # 用户发了图片，忽略（还没到收集阶段）
                await self.notifier.send_message("当前是确认推荐列表阶段，请先确认列表后再发送图片")
                continue

            text = text.strip()

            # 确认列表
            if text in ("确认列表", "确认"):
                return items

            # 全部跳过
            if text in ("全部跳过", "跳过"):
                return []

            # 删除物品：匹配 "删除 N" 或 "删N"
            delete_match = re.match(r"删除?\s*(\d+)", text)
            if delete_match:
                idx = int(delete_match.group(1)) - 1
                if 0 <= idx < len(items):
                    removed = items.pop(idx)
                    await self.notifier.send_message(f"已删除「{removed.name}」")
                    if not items:
                        await self.notifier.send_message("推荐列表已清空")
                        return []
                    await self._send_recommendation_card(items, topic)
                else:
                    await self.notifier.send_message(f"编号 {idx+1} 不存在，请重试")
                continue

            # 补充物品：匹配 "加xxx" 或 "添加xxx"
            add_match = re.match(r"(?:加|添加)\s*(.+)", text)
            if add_match:
                name = add_match.group(1).strip()
                items.append(VisualItemDetail(
                    name=name,
                    description="用户补充",
                    visual_questions=[],
                ))
                await self.notifier.send_message(f"已添加「{name}」")
                await self._send_recommendation_card(items, topic)
                continue

            # 未识别的输入
            await self.notifier.send_message(
                "未识别操作。你可以：\n"
                '- 回复"删除 N"删除物品\n'
                '- 回复"加 物品名"补充物品\n'
                "- 点击按钮确认或跳过"
            )

    async def _send_recommendation_card(
        self,
        items: list[VisualItemDetail],
        topic: str,
    ) -> None:
        """发送推荐物品列表卡片"""
        lines = [
            f"**📋 帖子主题：{topic}**\n",
            "根据研究分析，以下物品值得推荐：\n",
        ]
        for i, item in enumerate(items):
            desc = f" — {item.description}" if item.description and item.description != "用户补充" else ""
            lines.append(f"{i+1}. **{item.name}**{desc}")

        lines.append("\n你可以：")
        lines.append('- 回复"删除 N"删除物品')
        lines.append('- 回复"加 物品名"补充物品')

        await self.notifier.send_card_message(
            text="\n".join(lines),
            buttons=[
                ("确认列表", "确认列表"),
                ("全部跳过", "全部跳过"),
            ],
        )

    # ========================================================================
    # Phase 3: 收集参考图片
    # ========================================================================

    async def collect_images(
        self,
        items: list[VisualItemDetail],
        ref_dir: Path,
    ) -> list[ItemReferenceImages]:
        """逐物品收集参考图片"""
        total_items = len(items)
        collected: list[ItemReferenceImages] = []
        global_stop = False

        for item_idx, item in enumerate(items):
            if global_stop:
                break

            item_dir = ref_dir / f"item_{item_idx}"
            item_dir.mkdir(parents=True, exist_ok=True)

            prompt = self._build_item_prompt(item, item_idx, total_items)
            images, stop_reason = await self.notifier.collect_images(
                prompt=prompt,
                save_dir=item_dir,
                done_keyword="完成",
                skip_keyword="跳过",
                next_keyword="下一个",
                max_images=ReferenceImageConfig.MAX_IMAGES_PER_ITEM,
            )

            if stop_reason == "skip":
                global_stop = True
            elif stop_reason == "done":
                global_stop = True
            elif stop_reason == "next" and len(images) == 0:
                confirm_msg = (
                    f'**⚠️ 还没有收到「{item.name}」的参考图片**\n'
                    f'点击"确定"跳过，或发送图片继续'
                )
                more_images, reason2 = await self.notifier.collect_images(
                    prompt=confirm_msg,
                    save_dir=item_dir,
                    done_keyword="完成",
                    skip_keyword="跳过",
                    next_keyword="确定",
                    max_images=ReferenceImageConfig.MAX_IMAGES_PER_ITEM,
                )
                images.extend(more_images)
                if reason2 in ("skip", "done"):
                    global_stop = True

            collected.append(ItemReferenceImages(
                item_name=item.name,
                image_paths=[str(p) for p in images],
            ))

            if images:
                logger.info("物品「%s」: 收集到 %d 张参考图片", item.name, len(images))
            else:
                logger.info("物品「%s」: 已跳过", item.name)

        return collected

    # ========================================================================
    # 验证
    # ========================================================================

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, ReferenceImageResult):
            return ValidationResult.failure("输出类型错误")
        return ValidationResult.success()

    # ========================================================================
    # 消息构建
    # ========================================================================

    def _build_item_prompt(
        self,
        item: VisualItemDetail,
        item_idx: int,
        total_items: int,
    ) -> str:
        lines = [
            f"**📸 [{item_idx + 1}/{total_items}] 请发送「{item.name}」的参考图片**",
            f"可发送多张（不同角度/细节），发完点击按钮继续",
        ]
        if item.description and item.description != "用户补充":
            lines.append(f"描述: {item.description}")
        for q in item.visual_questions:
            lines.append(f"   - {q}")
        return "\n".join(lines)
