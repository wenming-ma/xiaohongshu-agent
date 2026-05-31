from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agent_events import AgentEventBridge, EnqueuePriority


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
                self.bridge.ingest_control_action(action, priority=priority)
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
        if text.startswith("__control__:"):
            return text.split(":", 1)[1].strip()
        return ""
