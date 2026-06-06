from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.utils.logger import get_logger

from .schemas import ArtifactRef, DeliveryPackage, ResultEnvelope

logger = get_logger(__name__)

PUBLIC_FEISHU_TEXT_BLOCK_LABELS = {
    "title",
    "body",
    "hashtags",
    "caption",
    "script",
}


@dataclass(frozen=True)
class DeliverySendReceipt:
    channel: str
    message_id: str
    label: str = ""


class DeliverySendError(RuntimeError):
    """Raised when a delivery package could not be fully sent to Feishu."""


class DeliveryPackageSender:
    def __init__(self, *, notifier: object):
        self.notifier = notifier

    async def send(
        self,
        envelope: ResultEnvelope[DeliveryPackage],
        *,
        chat_id: str | None = None,
    ) -> list[DeliverySendReceipt]:
        if envelope.payload is None:
            raise ValueError("delivery envelope payload is required")

        package = envelope.payload
        text = self._build_message(package)
        receipts: list[DeliverySendReceipt] = []
        message_id = await self.notifier.send_message(text, chat_id=chat_id)
        receipts.append(
            self._require_message_id(
                message_id,
                channel="text",
                label=package.title,
            )
        )

        for artifact in package.artifacts:
            receipts.append(await self._send_artifact(artifact, chat_id=chat_id))

        logger.info(
            "Feishu delivery sent: route=%s title=%s receipts=%s",
            package.route,
            package.title,
            [receipt.message_id for receipt in receipts],
        )
        return receipts

    def _build_message(self, package: DeliveryPackage) -> str:
        block_lines = [
            block.text
            for block in package.text_blocks
            if block.label in PUBLIC_FEISHU_TEXT_BLOCK_LABELS and block.text.strip()
        ]
        if block_lines:
            return "\n".join(block_lines)

        fallback_lines = [line for line in (package.title, package.summary) if line.strip()]
        return "\n".join(fallback_lines)

    async def _send_artifact(self, artifact: ArtifactRef, *, chat_id: str | None = None) -> DeliverySendReceipt:
        path = Path(artifact.path)
        if artifact.artifact_type == "image":
            message_id = await self.notifier.send_image(path, caption=artifact.label, chat_id=chat_id)
            return self._require_message_id(
                message_id,
                channel="image",
                label=artifact.label,
            )

        message_id = await self.notifier.send_file(path, caption=artifact.label, chat_id=chat_id)
        return self._require_message_id(
            message_id,
            channel="file",
            label=artifact.label,
        )

    def _require_message_id(
        self,
        message_id: object,
        *,
        channel: str,
        label: str = "",
    ) -> DeliverySendReceipt:
        if isinstance(message_id, str) and message_id.strip():
            return DeliverySendReceipt(channel=channel, message_id=message_id, label=label)
        raise DeliverySendError(f"Feishu delivery failed: channel={channel} label={label}")
