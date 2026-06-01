from __future__ import annotations

import asyncio

import pytest

from src.agent_os.schemas import AgentToolResult
from src.agent_os.task_manager import AgentOSTaskManager
from src.agent_os.tools import AgentTool, AgentToolContext, AgentToolRegistry
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope


async def slow_success(ctx: AgentToolContext, **params):
    await asyncio.sleep(0.05)
    envelope = ResultEnvelope[DeliveryPackage].success(
        agent_name="fake_route",
        payload=DeliveryPackage(route="image_post", title=params["title"], summary="ok"),
        summary="ok",
        run_id=ctx.run_id,
        step_id=ctx.step_id or "fake_route",
    )
    return AgentToolResult(envelope=envelope, produced_refs=["delivery"])


@pytest.mark.anyio
async def test_task_manager_starts_specialist_tool_without_blocking() -> None:
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image route",
            execute=slow_success,
            category="specialist",
        )
    )
    manager = AgentOSTaskManager(tool_registry=registry)

    task = manager.start_task(
        "execute_image_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        params={"title": "面试穿搭"},
    )

    assert task.status == "running"
    assert manager.list_tasks()[0].task_id == task.task_id

    await manager.wait_for_all()

    finished = manager.get_task(task.task_id)
    assert finished.status == "succeeded"
    assert finished.result is not None
    assert finished.result.envelope.payload.title == "面试穿搭"


@pytest.mark.anyio
async def test_task_manager_can_run_multiple_background_tasks_concurrently() -> None:
    release = asyncio.Event()
    started: list[str] = []

    async def wait_for_release(ctx: AgentToolContext, **params):
        started.append(params["title"])
        await release.wait()
        return await slow_success(ctx, **params)

    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image route",
            execute=wait_for_release,
            category="specialist",
        )
    )
    manager = AgentOSTaskManager(tool_registry=registry)

    first = manager.start_task(
        "execute_image_post",
        AgentToolContext(run_id="run-1"),
        params={"title": "面试穿搭"},
    )
    second = manager.start_task(
        "execute_image_post",
        AgentToolContext(run_id="run-2"),
        params={"title": "登山穿搭"},
    )
    await asyncio.sleep(0)

    assert {task.status for task in manager.list_tasks()} == {"running"}
    assert started == ["面试穿搭", "登山穿搭"]

    release.set()
    await manager.wait_for_all()

    assert manager.get_task(first.task_id).status == "succeeded"
    assert manager.get_task(second.task_id).status == "succeeded"


class ProgressNotifier:
    def __init__(self) -> None:
        self.messages: list[dict[str, str | None]] = []

    async def send_message(self, text: str, *, chat_id: str | None = None):
        self.messages.append({"text": text, "chat_id": chat_id})
        return f"msg-{len(self.messages)}"


@pytest.mark.anyio
async def test_task_manager_notifies_feishu_when_background_task_fails() -> None:
    async def fail(_ctx: AgentToolContext, **_params):
        raise RuntimeError("image provider unavailable")

    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image route",
            execute=fail,
            category="specialist",
        )
    )
    notifier = ProgressNotifier()
    manager = AgentOSTaskManager(tool_registry=registry, notifier=notifier)

    task = manager.start_task(
        "execute_image_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        params={"title": "面试穿搭"},
    )
    await manager.wait_for_all()

    failed = manager.get_task(task.task_id)
    assert failed.status == "failed"
    assert "image provider unavailable" in (failed.error_message or "")
    assert notifier.messages[-1]["chat_id"] == "chat-1"
    assert "后台任务失败" in notifier.messages[-1]["text"]
    assert task.task_id in notifier.messages[-1]["text"]


@pytest.mark.anyio
async def test_task_manager_restarts_failed_task_with_original_parameters() -> None:
    calls = 0

    async def fail_then_succeed(ctx: AgentToolContext, **params):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary outage")
        return await slow_success(ctx, **params)

    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image route",
            execute=fail_then_succeed,
            category="specialist",
        )
    )
    manager = AgentOSTaskManager(tool_registry=registry)

    original = manager.start_task(
        "execute_image_post",
        AgentToolContext(run_id="run-1"),
        params={"title": "登山穿搭"},
    )
    await manager.wait_for_all()

    restarted = manager.restart_task(original.task_id)
    await manager.wait_for_all()

    assert restarted.task_id != original.task_id
    assert manager.get_task(original.task_id).status == "failed"
    assert manager.get_task(restarted.task_id).status == "succeeded"
    assert manager.get_task(restarted.task_id).result.envelope.payload.title == "登山穿搭"
