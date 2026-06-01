from __future__ import annotations

from typing import Any

from src.orchestration.feishu_translation import (
    FeishuInteractionTranslator,
    parse_delimited_options,
)
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope
from src.utils.feishu_notifier import get_feishu_notifier


class AgentOSFeishuTools:
    def __init__(
        self,
        *,
        notifier: Any | None = None,
        translator: Any | None = None,
    ) -> None:
        self.notifier = notifier or get_feishu_notifier()
        self.translator = translator or FeishuInteractionTranslator(notifier=self.notifier)

    async def feishu_ask_single_choice(
        self,
        session: object,
        *,
        title: str,
        options_spec: str,
        phase: str,
        value_prefix: str = "",
        summary: str | None = None,
    ) -> str:
        await self.translator.ask_single_choice(
            session,
            title=title,
            options=parse_delimited_options(options_spec),
            phase=phase,
            value_prefix=value_prefix,
            summary=summary,
        )
        _, reply = await self.notifier.wait_for_session_image_or_text(
            session,
            phase=phase,
            summary=summary,
        )
        return reply

    async def feishu_ask_multi_select(
        self,
        session: object,
        *,
        title: str,
        options_spec: str,
        phase: str,
        input_name: str = "",
        input_placeholder: str = "",
        submit_label: str = "确认",
        summary: str | None = None,
    ) -> str:
        await self.translator.ask_multi_select(
            session,
            title=title,
            options=parse_delimited_options(options_spec),
            phase=phase,
            input_name=input_name,
            input_placeholder=input_placeholder,
            submit_label=submit_label,
            summary=summary,
        )
        _, reply = await self.notifier.wait_for_session_image_or_text(
            session,
            phase=phase,
            summary=summary,
        )
        return reply

    async def feishu_send_progress(
        self,
        session: object,
        message: str,
        *,
        phase: str,
        summary: str | None = None,
    ) -> None:
        await self.notifier.send_session_message(
            session,
            message,
            phase=phase,
            summary=summary,
        )

    async def feishu_send_delivery_summary(
        self,
        session: object,
        envelope: ResultEnvelope[DeliveryPackage],
    ) -> None:
        if envelope.payload is None:
            await self.notifier.send_session_message(
                session,
                f"执行失败：{envelope.error_message or envelope.summary}",
                phase="failed",
                summary=envelope.summary,
            )
            return
        await self.notifier.send_session_message(
            session,
            f"已完成 {envelope.payload.route} 交付，标题：{envelope.payload.title}",
            phase="completed",
            summary=envelope.payload.summary,
        )
