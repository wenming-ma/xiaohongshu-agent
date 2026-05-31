from __future__ import annotations

from pathlib import Path

import pytest

from src.orchestration.delivery import DeliveryPackageSender, DeliverySendError
from src.orchestration.schemas import ArtifactRef, DeliveryPackage, DeliveryTextBlock, ResultEnvelope


class FakeNotifier:
    def __init__(self, *, fail_channel: str = "") -> None:
        self.messages: list[str] = []
        self.images: list[tuple[Path, str]] = []
        self.files: list[tuple[Path, str]] = []
        self.fail_channel = fail_channel

    async def send_message(self, text: str, chat_id: str | None = None) -> str | None:
        self.messages.append(text)
        if self.fail_channel == "text":
            return None
        return "msg-1"

    async def send_image(self, image_path: Path, caption: str = "", chat_id: str | None = None) -> str | None:
        self.images.append((image_path, caption))
        if self.fail_channel == "image":
            return None
        return "img-1"

    async def send_file(
        self,
        file_path: Path,
        caption: str = "",
        chat_id: str | None = None,
        *,
        duration: int | None = None,
    ) -> str | None:
        self.files.append((file_path, caption))
        if self.fail_channel == "file":
            return None
        return "file-1"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_delivery_sender_routes_text_images_and_files(tmp_path: Path) -> None:
    image_path = tmp_path / "cover.png"
    image_path.write_bytes(b"fake-image")
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake-video")

    package = DeliveryPackage(
        route="image_post",
        title="纯色背景穿搭",
        summary="产出已整理完成",
        text_blocks=[
            DeliveryTextBlock(label="title", text="标题：纯色背景穿搭"),
            DeliveryTextBlock(label="body", text="正文：每张图只展示一套穿搭。"),
        ],
        artifacts=[
            ArtifactRef(
                artifact_type="image",
                label="cover",
                path=str(image_path),
                mime_type="image/png",
            ),
            ArtifactRef(
                artifact_type="video",
                label="clip",
                path=str(video_path),
                mime_type="video/mp4",
            ),
        ],
    )
    envelope = ResultEnvelope[DeliveryPackage].success(
        agent_name="delivery_agent",
        payload=package,
        summary="交付完成",
        run_id="run-3",
        step_id="delivery",
    )

    notifier = FakeNotifier()
    sender = DeliveryPackageSender(notifier=notifier)

    receipts = await sender.send(envelope)

    assert notifier.messages
    assert "纯色背景穿搭" in notifier.messages[0]
    assert notifier.images == [(image_path, "cover")]
    assert notifier.files == [(video_path, "clip")]
    assert [receipt.channel for receipt in receipts] == ["text", "image", "file"]
    assert [receipt.message_id for receipt in receipts] == ["msg-1", "img-1", "file-1"]


@pytest.mark.anyio
async def test_delivery_sender_fails_when_feishu_returns_no_message_id(tmp_path: Path) -> None:
    image_path = tmp_path / "cover.png"
    image_path.write_bytes(b"fake-image")
    package = DeliveryPackage(
        route="image_post",
        title="纯色背景穿搭",
        summary="产出已整理完成",
        artifacts=[
            ArtifactRef(
                artifact_type="image",
                label="cover",
                path=str(image_path),
                mime_type="image/png",
            ),
        ],
    )
    envelope = ResultEnvelope[DeliveryPackage].success(
        agent_name="delivery_agent",
        payload=package,
        summary="交付完成",
        run_id="run-3",
        step_id="delivery",
    )

    sender = DeliveryPackageSender(notifier=FakeNotifier(fail_channel="image"))

    with pytest.raises(DeliverySendError, match="channel=image"):
        await sender.send(envelope)
