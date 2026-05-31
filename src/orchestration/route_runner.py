from __future__ import annotations

from typing import Protocol

from .conversation import ConversationRequest
from .style_context import StyleContext


class RouteRunner(Protocol):
    async def run(
        self,
        request: ConversationRequest,
        *,
        run_id: str | None = None,
        chat_id: str | None = None,
        send_to_feishu: bool = False,
        style_context: StyleContext | None = None,
    ): ...
