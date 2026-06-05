from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agent_events import AgentEventBridge, EnqueuePriority

CONTROL_ACTIONS = {"new_session", "interrupt", "follow_up"}
CONTROL_ACTION_ALIASES = {
    "新开会话": "new_session",
    "开启新会话": "new_session",
    "重置会话": "new_session",
    "重新开始": "new_session",
    "/new": "new_session",
    "中断": "interrupt",
    "中断当前任务": "interrupt",
    "停止当前任务": "interrupt",
    "取消当前任务": "interrupt",
    "/interrupt": "interrupt",
    "稍后处理": "follow_up",
    "等当前任务结束": "follow_up",
    "完成后再处理": "follow_up",
    "/follow_up": "follow_up",
}


@dataclass(frozen=True)
class ChoiceOption:
    """A UI-agnostic option passed by an Agent tool call."""

    label: str
    value: str
    description: str = ""
    checked: bool = False


def parse_delimited_options(options: str) -> list[ChoiceOption]:
    """Parse simple tool-call option payloads: ``label::value||label::value``."""

    parsed: list[ChoiceOption] = []
    for item in options.split("||"):
        raw = item.strip()
        if not raw:
            continue
        if "::" in raw:
            label, value = raw.split("::", 1)
        else:
            label = value = raw
        label = label.strip()
        value = value.strip()
        if not label or not value:
            continue
        parsed.append(ChoiceOption(label=label, value=value))
    return parsed


def parse_control_action_text(text: str) -> str:
    """Normalize Feishu text rewrites of hidden control shortcuts."""

    normalized = (text or "").strip().lstrip("@").strip()
    if normalized in CONTROL_ACTION_ALIASES:
        return CONTROL_ACTION_ALIASES[normalized]
    for prefix in ("__control__:", "control:"):
        if not normalized.startswith(prefix):
            continue
        action = normalized.split(":", 1)[1].strip()
        return action if action in CONTROL_ACTIONS else ""
    return ""


class FeishuInteractionTranslator:
    """Renders Agent interaction primitives into Feishu UI calls."""

    def __init__(self, *, notifier: Any) -> None:
        self.notifier = notifier

    async def ask_single_choice(
        self,
        session: object,
        *,
        title: str,
        options: list[ChoiceOption],
        phase: str,
        value_prefix: str = "",
        summary: str | None = None,
    ) -> None:
        buttons = [(option.label, f"{value_prefix}{option.value}") for option in options]
        await self.notifier.send_session_card_message(
            session,
            title,
            buttons,
            phase=phase,
            summary=summary,
        )

    async def ask_multi_select(
        self,
        session: object,
        *,
        title: str,
        options: list[ChoiceOption],
        phase: str,
        input_name: str = "",
        input_placeholder: str = "",
        submit_label: str = "确认",
        summary: str | None = None,
    ) -> None:
        checkers = [
            {"name": option.value, "text": option.label, "checked": option.checked}
            for option in options
        ]
        await self.notifier.send_session_form_card(
            session,
            title,
            checkers,
            phase=phase,
            input_name=input_name,
            input_placeholder=input_placeholder,
            submit_label=submit_label,
            summary=summary,
        )


class FeishuInputTranslator:
    """Translates Feishu-side events into ordinary Agent session insertions."""

    def __init__(self, *, bridge: AgentEventBridge) -> None:
        self.bridge = bridge

    def ingest(self, event: Any, *, priority: EnqueuePriority = "asap") -> None:
        if getattr(event, "kind", "") == "control":
            action = getattr(event, "action", None) or self._control_action_from_text(getattr(event, "text", ""))
            if action == "new_session":
                self.bridge.ingest_control_action("new_session", priority=priority)
                return
            if action in {"interrupt", "follow_up"}:
                self.bridge.ingest_control_action(action, priority=self._control_priority(action, priority))
                return

        image_path = getattr(event, "image_path", None)
        if image_path is not None:
            self.bridge.ingest_user_image(
                image_path,
                caption=getattr(event, "text", "") or "",
                priority=priority,
            )
            return

        text = getattr(event, "text", "") or ""
        self.bridge.ingest_user_text(text, priority=priority)

    def _control_action_from_text(self, text: str) -> str:
        return parse_control_action_text(text)

    def _control_priority(self, action: str, explicit_priority: EnqueuePriority) -> EnqueuePriority:
        if action == "follow_up" and explicit_priority == "asap":
            return "when_idle"
        return explicit_priority
