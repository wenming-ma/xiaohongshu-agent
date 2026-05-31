from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
