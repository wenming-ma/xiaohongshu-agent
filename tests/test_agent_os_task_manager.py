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


@pytest.mark.anyio
async def test_task_manager_serializes_tools_in_same_resource_group() -> None:
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    started: list[str] = []

    async def wait_for_release(ctx: AgentToolContext, **params):
        started.append(params["title"])
        if params["title"] == "面试穿搭":
            first_started.set()
            await release_first.wait()
        return await slow_success(ctx, **params)

    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image route",
            execute=wait_for_release,
            category="specialist",
            resource_group="rednote_browser",
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
        params={"title": "约会穿搭"},
    )
    await first_started.wait()
    await asyncio.sleep(0.05)

    assert started == ["面试穿搭"]

    release_first.set()
    await manager.wait_for_all()

    assert started == ["面试穿搭", "约会穿搭"]
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
async def test_task_manager_treats_error_envelope_as_failed_task() -> None:
    async def return_error_envelope(ctx: AgentToolContext, **_params):
        return AgentToolResult(
            envelope=ResultEnvelope[DeliveryPackage].error(
                agent_name="fake_route",
                summary="登录预检失败",
                error_message="login required",
                run_id=ctx.run_id,
                step_id="research_access",
            )
        )

    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image route",
            execute=return_error_envelope,
            category="specialist",
        )
    )
    notifier = ProgressNotifier()
    manager = AgentOSTaskManager(tool_registry=registry, notifier=notifier)

    task = manager.start_task(
        "execute_image_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        params={"title": "约会穿搭"},
    )
    await manager.wait_for_all()

    failed = manager.get_task(task.task_id)
    assert failed.status == "failed"
    assert failed.error_message == "login required"
    assert notifier.messages[-1]["chat_id"] == "chat-1"
    assert "login required" in notifier.messages[-1]["text"]


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


@pytest.mark.anyio
async def test_task_manager_cancels_running_background_task() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def wait_forever(ctx: AgentToolContext, **params):
        started.set()
        await release.wait()
        return await slow_success(ctx, **params)

    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image route",
            execute=wait_forever,
            category="specialist",
        )
    )
    manager = AgentOSTaskManager(tool_registry=registry)

    task = manager.start_task(
        "execute_image_post",
        AgentToolContext(run_id="run-1"),
        params={"title": "面试穿搭"},
    )
    await started.wait()

    cancelled = manager.cancel_task(task.task_id)
    await manager.wait_for_all()

    assert cancelled.task_id == task.task_id
    assert manager.get_task(task.task_id).status == "cancelled"


@pytest.mark.anyio
async def test_task_manager_schedules_one_shot_specialist_task() -> None:
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

    schedule = manager.schedule_task(
        "execute_image_post",
        AgentToolContext(run_id="run-schedule-1"),
        params={"title": "每日热点穿搭"},
        delay_seconds=0.01,
    )
    await manager.wait_for_schedules()
    await manager.wait_for_all()

    assert schedule.status == "completed"
    assert schedule.run_count == 1
    assert len(schedule.task_ids) == 1
    assert manager.get_task(schedule.task_ids[0]).status == "succeeded"


@pytest.mark.anyio
async def test_task_manager_runs_recurring_specialist_task_until_max_runs() -> None:
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

    schedule = manager.schedule_task(
        "execute_image_post",
        AgentToolContext(run_id="run-loop"),
        params={"title": "循环热点扫描"},
        delay_seconds=0,
        interval_seconds=0.01,
        max_runs=3,
    )
    await manager.wait_for_schedules()
    await manager.wait_for_all()

    assert schedule.status == "completed"
    assert schedule.run_count == 3
    assert len(schedule.task_ids) == 3
    assert [manager.get_task(task_id).status for task_id in schedule.task_ids] == [
        "succeeded",
        "succeeded",
        "succeeded",
    ]


@pytest.mark.anyio
async def test_task_summary_exposes_human_readable_runtime_plan() -> None:
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
        AgentToolContext(run_id="run-brief"),
        params={
            "spec": {
                "objective": "做一篇默认配置图文",
                "route": "image_post",
                "topic": "雨天通勤包",
                "style_constraints": ["纯色背景", "平铺"],
                "run_options": {
                    "research": {"max_items": None},
                    "image": {"count": None},
                },
            }
        },
    )

    summary = task.to_summary()

    assert summary["human_summary"] == "image_post｜雨天通勤包｜图片：自动上限9｜研究：默认｜风格：纯色背景、平铺"
