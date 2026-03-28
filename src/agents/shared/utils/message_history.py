"""Shared helpers for safe message history truncation."""

from __future__ import annotations

from dataclasses import replace

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)


def truncate_history_by_rounds(
    history: list[ModelMessage],
    *,
    max_rounds: int,
    keep_first_round: bool,
) -> list[ModelMessage]:
    """Trim message history by complete user-prompt rounds.

    The result is additionally sanitized so any tool call / tool return pair
    crossing the truncation boundary is removed together.
    """
    if not history or max_rounds <= 0:
        return []

    rounds = _split_history_rounds(history)
    if len(rounds) <= max_rounds:
        return _sanitize_tool_message_pairs(history)

    if keep_first_round:
        if max_rounds == 1:
            selected_rounds = [rounds[0]]
        else:
            selected_rounds = [rounds[0]] + rounds[-(max_rounds - 1):]
    else:
        selected_rounds = rounds[-max_rounds:]

    selected_history = [msg for round_messages in selected_rounds for msg in round_messages]
    return _sanitize_tool_message_pairs(selected_history)


def _split_history_rounds(history: list[ModelMessage]) -> list[list[ModelMessage]]:
    run_boundaries = [
        idx
        for idx, msg in enumerate(history)
        if isinstance(msg, ModelRequest)
        and any(isinstance(part, UserPromptPart) for part in msg.parts)
    ]

    if not run_boundaries:
        return [history]

    rounds: list[list[ModelMessage]] = []
    prefix = history[: run_boundaries[0]]
    for i, start in enumerate(run_boundaries):
        end = run_boundaries[i + 1] if i + 1 < len(run_boundaries) else len(history)
        round_messages = history[start:end]
        if i == 0 and prefix:
            round_messages = prefix + round_messages
        rounds.append(round_messages)
    return rounds


def _sanitize_tool_message_pairs(messages: list[ModelMessage]) -> list[ModelMessage]:
    valid_tool_call_ids = _collect_matched_tool_call_ids(messages)
    if not valid_tool_call_ids:
        return [
            msg
            for msg in (_filter_message_parts(message, valid_tool_call_ids) for message in messages)
            if msg is not None
        ]

    return [
        msg
        for msg in (_filter_message_parts(message, valid_tool_call_ids) for message in messages)
        if msg is not None
    ]


def _collect_matched_tool_call_ids(messages: list[ModelMessage]) -> set[str]:
    tool_call_ids: set[str] = set()
    tool_return_ids: set[str] = set()

    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart) and part.tool_call_id:
                tool_call_ids.add(part.tool_call_id)
            elif isinstance(part, ToolReturnPart) and part.tool_call_id:
                tool_return_ids.add(part.tool_call_id)

    return tool_call_ids & tool_return_ids


def _filter_message_parts(message: ModelMessage, valid_tool_call_ids: set[str]) -> ModelMessage | None:
    filtered_parts = []
    for part in message.parts:
        if isinstance(part, ToolCallPart):
            if part.tool_call_id in valid_tool_call_ids:
                filtered_parts.append(part)
            continue
        if isinstance(part, ToolReturnPart):
            if part.tool_call_id in valid_tool_call_ids:
                filtered_parts.append(part)
            continue
        filtered_parts.append(part)

    if not filtered_parts:
        return None
    if len(filtered_parts) == len(message.parts):
        return message
    return replace(message, parts=filtered_parts)
