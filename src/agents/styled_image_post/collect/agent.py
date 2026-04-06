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
        """通过飞书卡片（按钮+文字）让用户确认/删除/补充推荐物品列表"""
        if self.notifier.client is None:
            logger.warning("飞书客户端未初始化，跳过用户确认")
            return recommendations

        items = list(recommendations)

        # 发送推荐列表卡片
        card_msg_id = await self._send_recommendation_card(items, topic)

        # 交互循环
        while True:
            image_path, text = await self.notifier.wait_for_image_or_text()

            if image_path is not None:
                await self.notifier.send_message("当前是确认推荐列表阶段，请先确认列表后再发送图片")
                continue

            text = text.strip()

            # 按钮或文字确认
            if text in ("确认列表", "确认"):
                return items

            # 全部跳过
            if text in ("全部跳过", "跳过"):
                return []

            # 单个删除按钮：删除_N
            delete_btn = re.match(r"删除_(\d+)", text)
            if delete_btn:
                idx = int(delete_btn.group(1))
                if 0 <= idx < len(items):
                    removed = items.pop(idx)
                    logger.info("用户删除推荐物品: %s", removed.name)
                    if not items:
                        await self.notifier.send_message("推荐列表已清空")
                        return []
                    # 更新卡片（原地刷新）
                    card = self._build_recommendation_card(items, topic)
                    if card_msg_id:
                        await self.notifier.update_card_message(card_msg_id, card)
                    else:
                        card_msg_id = await self._send_recommendation_card(items, topic)
                continue

            # 文字批量删除：支持 "删除 1,2,3"
            delete_match = re.match(r"删除?\s*([\d,，、\s]+)", text)
            if delete_match:
                raw = delete_match.group(1)
                indices = sorted(
                    {int(n) - 1 for n in re.findall(r"\d+", raw)},
                    reverse=True,
                )
                for idx in indices:
                    if 0 <= idx < len(items):
                        items.pop(idx)
                if not items:
                    await self.notifier.send_message("推荐列表已清空")
                    return []
                card = self._build_recommendation_card(items, topic)
                if card_msg_id:
                    await self.notifier.update_card_message(card_msg_id, card)
                else:
                    card_msg_id = await self._send_recommendation_card(items, topic)
                continue

            # 补充物品：匹配 "加xxx" / "添加xxx"
            add_match = re.match(r"(?:加|添加)\s*(.+)", text)
            if add_match:
                for name in re.split(r"[,，、]+", add_match.group(1)):
                    name = name.strip()
                    if name:
                        items.append(VisualItemDetail(
                            name=name,
                            description="用户补充",
                            visual_questions=[],
                        ))
                # 更新卡片
                card = self._build_recommendation_card(items, topic)
                if card_msg_id:
                    await self.notifier.update_card_message(card_msg_id, card)
                else:
                    card_msg_id = await self._send_recommendation_card(items, topic)
                continue

    def _build_recommendation_card(
        self,
        items: list[VisualItemDetail],
        topic: str,
    ) -> dict:
        """构建推荐物品列表卡片 JSON（每个物品带删除按钮）"""
        elements: list[dict] = [
            {"tag": "markdown", "content": f"**📋 帖子主题：{topic}**\n\n根据研究分析，以下物品值得推荐："},
        ]

        # 每个物品一行：名称 + 删除按钮
        for i, item in enumerate(items):
            desc = f" — {item.description}" if item.description and item.description != "用户补充" else ""
            elements.append({
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": f"{item.name}{desc}"},
                        "type": "default",
                        "value": {"keyword": ""},  # 不触发操作，仅显示
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "❌"},
                        "type": "danger",
                        "value": {"keyword": f"删除_{i}"},
                    },
                ],
            })

        elements.append({"tag": "markdown", "content": '回复"加 物品名"可补充'})

        # 底部操作按钮
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "确认列表"},
                    "type": "primary",
                    "value": {"keyword": "确认列表"},
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "全部跳过"},
                    "type": "danger",
                    "value": {"keyword": "全部跳过"},
                },
            ],
        })

        return {"elements": elements}

    async def _send_recommendation_card(
        self,
        items: list[VisualItemDetail],
        topic: str,
    ) -> str | None:
        """发送推荐物品列表卡片，返回 msg_id 用于后续更新"""
        if self.notifier.client is None:
            return None
        card = self._build_recommendation_card(items, topic)
        return await self.notifier.send_card_message_raw(card)

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
