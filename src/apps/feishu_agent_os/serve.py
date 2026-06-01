from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.agent_os.main_agent import create_main_agent
from src.agent_os.runtime import MainAgentRuntime
from src.agent_os.store import AgentOSStore
from src.agent_os.tools import AgentToolRegistry
from src.utils.feishu_notifier import get_feishu_notifier
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FeishuAgentOSService:
    notifier: Any
    runtime: MainAgentRuntime
    tool_registry: AgentToolRegistry
    store: AgentOSStore
    main_agent: Any

    async def serve_forever(self) -> None:
        await self.notifier.start_polling()
        logger.info("Feishu Agent OS 已启动，等待事件输入...")
        while True:
            image_path, text = await self.notifier.wait_for_image_or_text()
            if image_path is not None:
                self.runtime.ingest_event_from_image(Path(image_path), caption=text)
            elif text.strip():
                self.runtime.ingest_text(text)


def create_service(*, notifier: Any | None = None) -> FeishuAgentOSService:
    resolved_notifier = notifier or get_feishu_notifier()
    return FeishuAgentOSService(
        notifier=resolved_notifier,
        runtime=MainAgentRuntime(),
        tool_registry=AgentToolRegistry(),
        store=AgentOSStore(Path("output") / "agent-os"),
        main_agent=create_main_agent(),
    )


async def async_main() -> None:
    service = create_service()
    await service.serve_forever()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
