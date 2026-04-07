"""DiscussAgent - 穿搭搭配讨论 + 参考图片收集"""

import re
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import (
    OutfitItem,
    OutfitItemList,
    StyleSuggestion,
    VisualItemDetail,
    ItemReferenceImages,
    ReferenceImageResult,
)
from ....utils.providers import get_text_model
from ....utils.feishu_notifier import get_feishu_notifier
from ....utils.logger import get_logger
from ....config.settings import ReferenceImageConfig, RetryConfig
from .prompts import (
    item_parser_system_prompt,
    item_parser_user_prompt,
    style_suggestion_system_prompt,
    style_suggestion_user_prompt,
)

logger = get_logger(__name__)


class DiscussAgent(BaseAgent):
    """穿搭搭配讨论 Agent

    流程：
    1. 通过飞书与用户讨论确定穿搭搭配物品
    2. 用户确认/删除/补充物品列表
    3. 逐物品收集参考图片
    """

    role = "穿搭搭配讨论专员"
    goal = "与用户讨论确定穿搭搭配物品并收集参考图片"

    def init_tools(self) -> None:
        self.notifier = get_feishu_notifier()

    def init_agent(self) -> None:
        model = get_text_model()
        parser_retries = max(8, RetryConfig.AGENT_RETRIES)
        self.item_parser = Agent(
            model=model,
            output_type=OutfitItemList,
            system_prompt=(item_parser_system_prompt(),),
            retries=parser_retries,
            instrument=True,
        )
        self.style_suggester = Agent(
            model=model,
            output_type=StyleSuggestion,
            system_prompt=(style_suggestion_system_prompt(),),
            retries=parser_retries,
            instrument=True,
        )

    async def forward(
        self,
        output_dir: Path,
        topic_hint: str = "",
    ) -> tuple[list[OutfitItem], ReferenceImageResult, str]:
        """主入口：讨论物品 → 确认 → 收集参考图片 → 构建研究主题

        Returns:
            (物品列表, 参考图片结果, 研究主题)
        """
        # Phase 1: 与用户讨论搭配物品
        logger.info("开始与用户讨论穿搭搭配...")
        items = await self.discuss_items(topic_hint)

        if not items:
            logger.info("用户未提供搭配物品")
            return [], ReferenceImageResult(skipped=True), ""

        logger.info("用户确认 %d 个搭配单品", len(items))

        # Phase 1.5: 如果没有风格提示，询问用户风格方向
        if not topic_hint:
            topic_hint = await self.ask_style_direction(items)
            if topic_hint:
                logger.info("用户选择风格: %s", topic_hint)

        # Phase 2: 逐物品收集参考图片
        ref_dir = output_dir / "reference_images"
        ref_dir.mkdir(parents=True, exist_ok=True)

        collected = await self.collect_images(items, ref_dir)
        ref_result = ReferenceImageResult(items=collected)

        validation = await self.validate(ref_result)
        if not validation.passed:
            logger.warning("参考图片收集验证: %s", validation.feedback)

        total = sum(len(item.image_paths) for item in collected)
        logger.info("参考图片收集完成: %d 个物品, %d 张图片", len(collected), total)

        # 构建研究主题
        research_topic = self.build_research_topic(items, topic_hint)
        logger.info("构建研究主题: %s", research_topic)

        return items, ref_result, research_topic

    async def step(self, *args, **kwargs):
        """由 forward 内部各阶段方法替代，不直接使用"""
        raise NotImplementedError("DiscussAgent uses discuss/collect phases instead of step")

    # ========================================================================
    # Phase 1: 与用户讨论搭配物品
    # ========================================================================

    async def discuss_items(self, topic_hint: str = "") -> list[OutfitItem]:
        """通过飞书与用户讨论确定穿搭搭配物品，支持分多次发送单品。"""
        if self.notifier.client is None:
            logger.warning("飞书客户端未初始化，无法与用户讨论")
            return []

        # 发送初始提示
        if topic_hint:
            greeting = (
                f"**👗 穿搭搭配帖子 — {topic_hint}**\n\n"
                "请告诉我这次要分享的穿搭搭配包含哪些单品？\n\n"
                "例如：白色衬衫、高腰阔腿裤、小白鞋、帆布包\n\n"
                "可以一次性列出，也可以分多次发送。发完后回复“确认列表”。"
            )
        else:
            greeting = (
                "**👗 穿搭搭配帖子**\n\n"
                "请告诉我这次要分享的穿搭搭配包含哪些单品？\n\n"
                "例如：白色衬衫、高腰阔腿裤、小白鞋、帆布包\n\n"
                "可以一次性列出，也可以分多次发送。发完后回复“确认列表”。"
            )
        await self.notifier.send_message(greeting)

        items: list[OutfitItem] = []

        while True:
            image_path, text = await self.notifier.wait_for_image_or_text()

            if image_path is not None:
                await self.notifier.send_message("请先用文字告诉我搭配包含哪些单品，确认后再发送参考图片")
                continue

            text = text.strip()
            if not text:
                continue

            if text in ("取消", "算了", "全部跳过", "跳过"):
                return []

            # 确认当前列表（第一张卡片就是最终确认卡片，不再进入第二层确认流程）
            if text in ("确认列表", "确认"):
                if not items:
                    await self.notifier.send_message("还没有记录到单品，请先发送搭配单品")
                    continue
                return items

            # 单个删除按钮：删除_N
            delete_btn = re.match(r"删除_(\d+)", text)
            if delete_btn:
                idx = int(delete_btn.group(1))
                if 0 <= idx < len(items):
                    removed = items.pop(idx)
                    logger.info("用户删除单品: %s", removed.name)
                    if not items:
                        await self.notifier.send_message("搭配列表已清空，请重新发送单品")
                    else:
                        await self._send_items_card(items, topic_hint)
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
                    await self.notifier.send_message("搭配列表已清空，请重新发送单品")
                else:
                    await self._send_items_card(items, topic_hint)
                continue

            # 补充物品：匹配 "加xxx" / "添加xxx"
            add_match = re.match(r"(?:加|添加)\s*(.+)", text)
            if add_match:
                added = 0
                seen = {item.name for item in items}
                for name in re.split(r"[,，、]+", add_match.group(1)):
                    name = name.strip()
                    if name and name not in seen:
                        seen.add(name)
                        items.append(OutfitItem(name=name))
                        added += 1
                if added > 0:
                    await self._send_items_card(items, topic_hint)
                continue

            # 普通文本：解析并追加到列表
            parsed = await self._parse_items(text)
            if not parsed:
                await self.notifier.send_message(
                    "没有识别到具体的穿搭单品，请重新描述。\n"
                    "例如：白色衬衫、黑色阔腿裤、小白鞋"
                )
                continue

            seen = {item.name for item in items}
            added = 0
            for item in parsed:
                if item.name not in seen:
                    seen.add(item.name)
                    items.append(item)
                    added += 1

            if added == 0:
                await self.notifier.send_message("这些单品已经记录过了，可以继续补充，或回复“确认列表”进入下一步")
            else:
                await self._send_items_card(items, topic_hint)

    async def _parse_items(self, user_text: str) -> list[OutfitItem]:
        """LLM 解析用户文本为单品列表"""
        prompt = item_parser_user_prompt(user_text=user_text)
        result = await self.item_parser.run(prompt)
        return result.output.items

    async def _confirm_items(
        self,
        items: list[OutfitItem],
        topic_hint: str = "",
    ) -> list[OutfitItem]:
        """兼容保留：当前 discuss_items 已直接处理确认，这里仅返回 items。"""
        return list(items)

    def _build_items_card(
        self,
        items: list[OutfitItem],
        topic_hint: str = "",
    ) -> dict:
        """构建搭配单品列表卡片 JSON（每个物品带删除按钮）"""
        title = f"**📋 穿搭搭配：{topic_hint}**" if topic_hint else "**📋 穿搭搭配确认**"
        elements: list[dict] = [
            {"tag": "markdown", "content": f"{title}\n\n你的搭配包含以下单品："},
        ]

        for i, item in enumerate(items):
            desc = f" — {item.description}" if item.description else ""
            elements.append({
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": f"{i+1}. {item.name}{desc}"},
                        "type": "default",
                        "value": {"keyword": ""},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "❌"},
                        "type": "danger",
                        "value": {"keyword": f"删除_{i}", "toast": f"已删除「{item.name}」"},
                    },
                ],
            })

        elements.append({"tag": "markdown", "content": '回复"加 物品名"可补充'})

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

    async def _send_items_card(
        self,
        items: list[OutfitItem],
        topic_hint: str = "",
    ) -> str | None:
        """发送搭配单品列表卡片"""
        if self.notifier.client is None:
            return None
        card = self._build_items_card(items, topic_hint)
        return await self.notifier.send_card_message_raw(card)

    # ========================================================================
    # Phase 1.5: 询问风格方向
    # ========================================================================

    async def ask_style_direction(self, items: list[OutfitItem]) -> str:
        """根据单品动态推荐风格方向，让用户选择。返回风格关键词（空字符串表示不限）"""
        if self.notifier.client is None:
            return ""

        items_str = "、".join(item.name for item in items)

        # LLM 根据单品推荐风格选项
        logger.info("分析单品风格方向...")
        try:
            prompt = style_suggestion_user_prompt(items_text=items_str)
            result = await self.style_suggester.run(prompt)
            suggestion = result.output
        except Exception as e:
            logger.warning("风格推荐失败，跳过风格选择: %s", e)
            return ""

        if not suggestion.options:
            return ""

        # 构建飞书按钮，确保末尾有"不限风格"
        _NO_STYLE = "__no_style__"
        buttons = [(opt.label, opt.keyword or _NO_STYLE) for opt in suggestion.options]
        if not any(kw == _NO_STYLE for _, kw in buttons):
            buttons.append(("不限风格", _NO_STYLE))

        await self.notifier.send_card_message(
            text=f"**🎨 {items_str}**\n\n这套搭配主要想分享什么风格？",
            buttons=buttons,
        )

        while True:
            image_path, text = await self.notifier.wait_for_image_or_text()
            if image_path is not None:
                await self.notifier.send_message("请先选择风格方向，再发送图片")
                continue
            text = text.strip()
            if not text:
                continue
            # "不限风格" → 返回空字符串
            if text == _NO_STYLE:
                return ""
            return text

    # ========================================================================
    # Phase 2: 收集参考图片
    # ========================================================================

    async def collect_images(
        self,
        items: list[OutfitItem],
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
    # 构建研究主题
    # ========================================================================

    def build_research_topic(
        self,
        items: list[OutfitItem],
        hint: str = "",
    ) -> str:
        """从搭配物品构建小红书研究主题"""
        item_names = [item.name for item in items]
        # 搜索时限制物品数量避免过长
        search_names = item_names[:4]
        items_str = "、".join(search_names)

        if hint:
            return f"{hint}：{items_str} 穿法搭配"
        return f"{items_str} 穿搭穿法"

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
        item: OutfitItem,
        item_idx: int,
        total_items: int,
    ) -> str:
        lines = [
            f"**📸 [{item_idx + 1}/{total_items}] 请发送「{item.name}」的参考图片**",
            "可发送多张（不同角度/细节），发完点击按钮继续",
        ]
        if item.description:
            lines.append(f"描述: {item.description}")
        return "\n".join(lines)
