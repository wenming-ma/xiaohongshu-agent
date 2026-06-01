# Feishu Agent OS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed Feishu route orchestrator with a long-running event-driven main Agent OS that turns user requirements into runtime parameters and calls atomic specialist Agents as tools.

**Architecture:** Add a new `src/agent_os/` package containing event/task schemas, a queue-backed main runtime, a tool registry, JSON state store, specialist tool wrappers, Feishu interaction tools, and a Pydantic AI main Agent. Existing image/article/video/login/delivery specialist capabilities are preserved and exposed through tool wrappers during migration.

**Tech Stack:** Python 3.11, Pydantic v2 models, Pydantic AI Agent/AgentRun enqueue APIs, existing `ResultEnvelope`, Feishu notifier/session utilities, pytest/anyio.

---

## File Structure

- Create `src/agent_os/__init__.py`: lazy exports for the new Agent OS package.
- Create `src/agent_os/schemas.py`: `AgentOSEvent`, `TaskRunSpec`, `TaskStepSpec`, `RunOptions`, `DeliverySpec`, `AgentToolResult`, and helper constructors.
- Create `src/agent_os/runtime.py`: `MainAgentRuntime`, `QueuedRuntimeEvent`, `MainAgentRunAdapter`, event priority handling, reset/interrupt/wait APIs.
- Create `src/agent_os/tools.py`: `AgentTool`, `AgentToolRegistry`, `AgentToolContext`, registration and execution contracts.
- Create `src/agent_os/store.py`: JSONL/JSON state persistence for events, task specs, envelopes, and artifact references.
- Create `src/agent_os/specialist_tools.py`: wrappers that expose current research/content/image/article/video/login/delivery capabilities as tool-callable functions.
- Create `src/agent_os/resource_tools.py`: Skill and prompt-template search/read tools.
- Create `src/agent_os/feishu_tools.py`: UI-agnostic interaction and delivery tools backed by existing Feishu translator/notifier.
- Create `src/agent_os/main_agent.py`: Pydantic AI main Agent setup, system prompt, tool registration, and run lifecycle.
- Create `src/apps/feishu_agent_os/__init__.py`: formal app package for the new entrypoint.
- Create `src/apps/feishu_agent_os/serve.py`: 24-hour Feishu activation loop using `MainAgentRuntime`.
- Modify `src/apps/feishu_orchestrator/serve.py`: delegate to `src.apps.feishu_agent_os.serve` or mark as compatibility entry.
- Modify `src/orchestration/feishu_workflow.py`: keep only compatibility tests or deprecate as old route workflow after Agent OS entry passes.
- Modify `src/agents/AGENTS.md`: document Agent OS as the formal Feishu entrypoint.
- Test `tests/test_agent_os_schemas.py`: schema defaults, parameter precedence, serialization.
- Test `tests/test_agent_os_runtime.py`: queue priority, reset, interrupt, attachment to fake AgentRun.
- Test `tests/test_agent_os_tools.py`: registry registration, duplicate protection, execution result format.
- Test `tests/test_agent_os_store.py`: JSONL persistence and resume reads.
- Test `tests/test_agent_os_specialist_tools.py`: route wrappers receive explicit params and return envelopes.
- Test `tests/test_agent_os_resource_tools.py`: skills/prompt tools expose resources without keyword matching.
- Test `tests/test_agent_os_feishu_tools.py`: UI-agnostic tool calls render through fake Feishu translator.
- Test `tests/test_agent_os_main_agent.py`: main Agent construction, tool availability, no direct notifier dependency.
- Test `tests/test_feishu_agent_os_serve.py`: app entrypoint starts the Agent OS service and wires notifier/runtime.
- Modify boundary tests in `tests/test_feishu_first_architecture_boundaries.py`: formal entrypoint is Agent OS, no direct route pipeline as top-level control.

---

### Task 1: Add Agent OS Schema Contracts

**Files:**
- Create: `src/agent_os/__init__.py`
- Create: `src/agent_os/schemas.py`
- Test: `tests/test_agent_os_schemas.py`

- [ ] **Step 1: Write failing schema tests**

Add `tests/test_agent_os_schemas.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

from src.agent_os.schemas import (
    AgentOSEvent,
    DeliverySpec,
    ImageRunOptionsSpec,
    ResearchRunOptionsSpec,
    RunOptions,
    TaskRunSpec,
    TaskStepSpec,
)
from src.orchestration.conversation import ContentRoute


def test_agent_os_event_defaults_to_asap_text_event() -> None:
    event = AgentOSEvent.text("帮我做 5 张图")

    assert event.source == "feishu"
    assert event.kind == "text"
    assert event.text == "帮我做 5 张图"
    assert event.priority == "asap"
    assert event.event_id
    assert event.created_at.tzinfo is not None


def test_task_run_spec_preserves_user_runtime_overrides() -> None:
    spec = TaskRunSpec(
        objective="做出国留学图文帖",
        route=ContentRoute.IMAGE_POST,
        topic="出国留学",
        style_constraints=["末日废土风格", "每张图片都必须有人物"],
        run_options=RunOptions(
            research=ResearchRunOptionsSpec(max_items=5, depth="fast"),
            image=ImageRunOptionsSpec(count=10, model="gemini-3-pro-image-preview", concurrency=2),
        ),
        steps=[
            TaskStepSpec(
                step_id="research",
                tool_name="run_research",
                params={"topic": "出国留学"},
            )
        ],
    )

    dumped = spec.model_dump(mode="json")

    assert dumped["run_options"]["research"]["max_items"] == 5
    assert dumped["run_options"]["image"]["count"] == 10
    assert dumped["run_options"]["image"]["model"] == "gemini-3-pro-image-preview"
    assert dumped["steps"][0]["tool_name"] == "run_research"


def test_task_run_spec_defaults_to_feishu_delivery() -> None:
    spec = TaskRunSpec(objective="自主探索")

    assert isinstance(spec.delivery, DeliverySpec)
    assert spec.delivery.target == "feishu"
    assert spec.delivery.include_artifacts is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_agent_os_schemas.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.agent_os'`.

- [ ] **Step 3: Implement schemas**

Create `src/agent_os/__init__.py`:

```python
from __future__ import annotations

from .schemas import (
    AgentOSEvent,
    AgentToolResult,
    DeliverySpec,
    GroupingRunOptionsSpec,
    ImageRunOptionsSpec,
    ResearchRunOptionsSpec,
    ReviewRunOptionsSpec,
    RunOptions,
    TaskRunSpec,
    TaskStepSpec,
)

__all__ = [
    "AgentOSEvent",
    "AgentToolResult",
    "DeliverySpec",
    "GroupingRunOptionsSpec",
    "ImageRunOptionsSpec",
    "ResearchRunOptionsSpec",
    "ReviewRunOptionsSpec",
    "RunOptions",
    "TaskRunSpec",
    "TaskStepSpec",
]
```

Create `src/agent_os/schemas.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from src.orchestration.conversation import ContentRoute
from src.orchestration.schemas import ArtifactRef, ResultEnvelope


EventSource = Literal["feishu", "system"]
EventKind = Literal["text", "image", "button", "form", "control", "timer"]
EventPriority = Literal["asap", "when_idle"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentOSEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    source: EventSource = "feishu"
    kind: EventKind
    text: str = ""
    image_path: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: EventPriority = "asap"
    created_at: datetime = Field(default_factory=_utc_now)

    @classmethod
    def text(cls, text: str, *, priority: EventPriority = "asap") -> "AgentOSEvent":
        return cls(kind="text", text=text, priority=priority)

    @classmethod
    def image(cls, path: str, *, caption: str = "", priority: EventPriority = "asap") -> "AgentOSEvent":
        return cls(kind="image", text=caption, image_path=path, priority=priority)

    @classmethod
    def control(cls, action: str) -> "AgentOSEvent":
        return cls(kind="control", text=action, payload={"action": action}, priority="asap")


class ResearchRunOptionsSpec(BaseModel):
    max_items: int | None = None
    depth: Literal["fast", "standard", "deep"] | None = None


class GroupingRunOptionsSpec(BaseModel):
    target_group_count: int | None = None
    single_item_per_image: bool | None = None


class ImageRunOptionsSpec(BaseModel):
    count: int | None = None
    model: str | None = None
    aspect_ratio: str | None = None
    size: str | None = None
    reference_mode: str | None = None
    concurrency: int | None = None


class ReviewRunOptionsSpec(BaseModel):
    strictness: Literal["low", "standard", "high"] | None = None


class RunOptions(BaseModel):
    research: ResearchRunOptionsSpec = Field(default_factory=ResearchRunOptionsSpec)
    grouping: GroupingRunOptionsSpec = Field(default_factory=GroupingRunOptionsSpec)
    image: ImageRunOptionsSpec = Field(default_factory=ImageRunOptionsSpec)
    review: ReviewRunOptionsSpec = Field(default_factory=ReviewRunOptionsSpec)


class DeliverySpec(BaseModel):
    target: Literal["feishu"] = "feishu"
    include_artifacts: bool = True
    chat_id: str | None = None


class TaskStepSpec(BaseModel):
    step_id: str
    tool_name: str
    input_refs: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    parallel_group: str | None = None


class TaskRunSpec(BaseModel):
    task_id: str = Field(default_factory=lambda: uuid4().hex)
    objective: str
    route: ContentRoute | None = None
    topic: str | None = None
    audience: str | None = None
    constraints: list[str] = Field(default_factory=list)
    style_constraints: list[str] = Field(default_factory=list)
    reference_images: list[ArtifactRef] = Field(default_factory=list)
    selected_skills: list[str] = Field(default_factory=list)
    selected_prompt_templates: list[str] = Field(default_factory=list)
    run_options: RunOptions = Field(default_factory=RunOptions)
    steps: list[TaskStepSpec] = Field(default_factory=list)
    delivery: DeliverySpec = Field(default_factory=DeliverySpec)


class AgentToolResult(BaseModel):
    envelope: ResultEnvelope[Any]
    produced_refs: list[str] = Field(default_factory=list)
    next_suggestions: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run schema tests**

Run:

```powershell
uv run pytest tests/test_agent_os_schemas.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/agent_os/__init__.py src/agent_os/schemas.py tests/test_agent_os_schemas.py
git commit -m "feat: add Agent OS schema contracts"
```

---

### Task 2: Add Runtime Event Queue and Pydantic AI Run Adapter

**Files:**
- Create: `src/agent_os/runtime.py`
- Test: `tests/test_agent_os_runtime.py`

- [ ] **Step 1: Write failing runtime tests**

Add `tests/test_agent_os_runtime.py`:

```python
from __future__ import annotations

from pathlib import Path

from src.agent_os.runtime import MainAgentRuntime
from src.agent_os.schemas import AgentOSEvent


class FakeAgentRun:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str]] = []
        self.reset_calls = 0
        self.cancel_calls = 0
        self.idle_waits = 0

    def enqueue(self, text: str, *, priority: str = "asap") -> None:
        self.enqueued.append((text, priority))

    def reset_session(self) -> None:
        self.reset_calls += 1

    def cancel_current_task(self) -> None:
        self.cancel_calls += 1

    async def wait_for_idle(self) -> None:
        self.idle_waits += 1


def test_runtime_buffers_until_agent_run_attaches() -> None:
    runtime = MainAgentRuntime()
    run = FakeAgentRun()

    runtime.ingest_event(AgentOSEvent.text("先做 5 张图"))
    runtime.attach_run(run)

    assert run.enqueued == [("先做 5 张图", "asap")]
    assert runtime.pending_count == 0


def test_runtime_formats_image_event_as_user_message(tmp_path: Path) -> None:
    runtime = MainAgentRuntime()
    run = FakeAgentRun()
    runtime.attach_run(run)
    image_path = tmp_path / "ref.jpg"
    image_path.write_bytes(b"img")

    runtime.ingest_event(AgentOSEvent.image(str(image_path), caption="参考这件外套", priority="when_idle"))

    message, priority = run.enqueued[0]
    assert priority == "when_idle"
    assert "[用户发送图片]" in message
    assert str(image_path) in message
    assert "参考这件外套" in message


def test_runtime_new_session_resets_run_and_clears_pending() -> None:
    runtime = MainAgentRuntime()
    run = FakeAgentRun()

    runtime.ingest_event(AgentOSEvent.text("旧任务", priority="when_idle"))
    runtime.ingest_event(AgentOSEvent.control("new_session"))
    runtime.attach_run(run)

    assert runtime.pending_count == 0
    assert run.enqueued == []

    runtime.ingest_event(AgentOSEvent.text("新任务"))
    runtime.ingest_event(AgentOSEvent.control("new_session"))

    assert run.reset_calls == 1


def test_runtime_interrupt_cancels_current_task_and_enqueues_control_message() -> None:
    runtime = MainAgentRuntime()
    run = FakeAgentRun()
    runtime.attach_run(run)

    runtime.ingest_event(AgentOSEvent.control("interrupt"))

    assert run.cancel_calls == 1
    assert run.enqueued == [("[用户控制事件]\naction: interrupt", "asap")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_agent_os_runtime.py -q
```

Expected: FAIL with `ModuleNotFoundError` or missing `MainAgentRuntime`.

- [ ] **Step 3: Implement runtime**

Create `src/agent_os/runtime.py`:

```python
from __future__ import annotations

from collections import deque
from typing import Any, Protocol

from .schemas import AgentOSEvent, EventPriority


class SupportsMainAgentRun(Protocol):
    def enqueue(self, text: str, *, priority: str = "asap") -> None: ...


class MainAgentRuntime:
    def __init__(self) -> None:
        self._run: SupportsMainAgentRun | None = None
        self._pending: deque[AgentOSEvent] = deque()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def attach_run(self, run: SupportsMainAgentRun) -> None:
        self._run = run
        self.flush()

    def detach_run(self, run: SupportsMainAgentRun | None = None) -> None:
        if run is None or run is self._run:
            self._run = None

    def ingest_event(self, event: AgentOSEvent) -> None:
        action = self._control_action(event)
        if action == "new_session":
            self._pending.clear()
            self.reset_session()
            return
        if action == "interrupt":
            self.cancel_current_task()
            self._enqueue_text("[用户控制事件]\naction: interrupt", priority="asap")
            return
        if action == "follow_up":
            self._enqueue_text("[用户控制事件]\naction: follow_up", priority="when_idle")
            return

        if self._run is None:
            self._pending.append(event)
            return
        self._enqueue_event(event)

    def flush(self) -> None:
        while self._run is not None and self._pending:
            self._enqueue_event(self._pending.popleft())

    async def wait_for_idle(self) -> None:
        wait_for_idle = getattr(self._run, "wait_for_idle", None)
        if callable(wait_for_idle):
            await wait_for_idle()

    def reset_session(self) -> None:
        reset = getattr(self._run, "reset_session", None)
        if callable(reset):
            reset()

    def cancel_current_task(self) -> None:
        cancel = getattr(self._run, "cancel_current_task", None)
        if callable(cancel):
            cancel()

    def _enqueue_event(self, event: AgentOSEvent) -> None:
        if event.kind == "image" and event.image_path:
            self._enqueue_text(self._format_image_message(event), priority=event.priority)
            return
        self._enqueue_text(event.text, priority=event.priority)

    def _enqueue_text(self, text: str, *, priority: EventPriority) -> None:
        if self._run is None:
            self._pending.append(AgentOSEvent.text(text, priority=priority))
            return
        self._run.enqueue(text, priority=priority)

    def _format_image_message(self, event: AgentOSEvent) -> str:
        parts = ["[用户发送图片]", f"path: {event.image_path}"]
        if event.text.strip():
            parts.append(f"caption: {event.text.strip()}")
        return "\n".join(parts)

    def _control_action(self, event: AgentOSEvent) -> str:
        if event.kind != "control":
            return ""
        action = str(event.payload.get("action") or event.text).strip()
        return action if action in {"new_session", "interrupt", "follow_up"} else ""
```

- [ ] **Step 4: Export runtime**

Modify `src/agent_os/__init__.py`:

```python
from .runtime import MainAgentRuntime
```

Add `"MainAgentRuntime"` to `__all__`.

- [ ] **Step 5: Run runtime tests**

Run:

```powershell
uv run pytest tests/test_agent_os_runtime.py tests/test_agent_os_schemas.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_os/__init__.py src/agent_os/runtime.py tests/test_agent_os_runtime.py
git commit -m "feat: add Agent OS runtime queue"
```

---

### Task 3: Add Agent Tool Registry

**Files:**
- Create: `src/agent_os/tools.py`
- Test: `tests/test_agent_os_tools.py`

- [ ] **Step 1: Write failing tool registry tests**

Add `tests/test_agent_os_tools.py`:

```python
from __future__ import annotations

import pytest

from src.agent_os.schemas import AgentToolResult
from src.agent_os.tools import AgentTool, AgentToolContext, AgentToolRegistry
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope


async def fake_execute(ctx: AgentToolContext, **params):
    assert ctx.run_id == "run-1"
    envelope = ResultEnvelope[DeliveryPackage].success(
        agent_name="fake_tool",
        payload=DeliveryPackage(route="image_post", title=params["title"], summary="ok"),
        summary="ok",
        run_id=ctx.run_id,
        step_id="fake",
    )
    return AgentToolResult(envelope=envelope, produced_refs=["delivery"])


@pytest.mark.anyio
async def test_registry_executes_registered_tool() -> None:
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="fake_delivery",
            description="Fake delivery tool",
            execute=fake_execute,
        )
    )

    result = await registry.execute(
        "fake_delivery",
        AgentToolContext(run_id="run-1"),
        title="测试标题",
    )

    assert result.envelope.payload is not None
    assert result.envelope.payload.title == "测试标题"
    assert result.produced_refs == ["delivery"]


def test_registry_rejects_duplicate_tool_names() -> None:
    registry = AgentToolRegistry()
    tool = AgentTool(name="same", description="one", execute=fake_execute)

    registry.register(tool)

    with pytest.raises(ValueError, match="Duplicate Agent OS tool"):
        registry.register(tool)


def test_registry_lists_tools_without_exposing_callables() -> None:
    registry = AgentToolRegistry()
    registry.register(AgentTool(name="fake_delivery", description="Fake delivery tool", execute=fake_execute))

    assert registry.describe_tools() == [{"name": "fake_delivery", "description": "Fake delivery tool"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_agent_os_tools.py -q
```

Expected: FAIL with missing `src.agent_os.tools`.

- [ ] **Step 3: Implement tool registry**

Create `src/agent_os/tools.py`:

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from .schemas import AgentToolResult


class AgentToolContext(BaseModel):
    run_id: str
    task_id: str | None = None
    step_id: str | None = None
    chat_id: str | None = None
    workspace_dir: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


AgentToolExecute = Callable[..., Awaitable[AgentToolResult]]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    execute: AgentToolExecute
    category: str = "specialist"


@dataclass
class AgentToolRegistry:
    _tools: dict[str, AgentTool] = field(default_factory=dict)

    def register(self, tool: AgentTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate Agent OS tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown Agent OS tool: {name}") from exc

    def describe_tools(self) -> list[dict[str, str]]:
        return [
            {"name": tool.name, "description": tool.description}
            for tool in self._tools.values()
        ]

    async def execute(self, name: str, ctx: AgentToolContext, **params: Any) -> AgentToolResult:
        tool = self.get(name)
        return await tool.execute(ctx, **params)
```

- [ ] **Step 4: Export tool classes**

Modify `src/agent_os/__init__.py`:

```python
from .tools import AgentTool, AgentToolContext, AgentToolRegistry
```

Add names to `__all__`.

- [ ] **Step 5: Run tool tests**

Run:

```powershell
uv run pytest tests/test_agent_os_tools.py tests/test_agent_os_runtime.py tests/test_agent_os_schemas.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_os/__init__.py src/agent_os/tools.py tests/test_agent_os_tools.py
git commit -m "feat: add Agent OS tool registry"
```

---

### Task 4: Add JSON State Store

**Files:**
- Create: `src/agent_os/store.py`
- Test: `tests/test_agent_os_store.py`

- [ ] **Step 1: Write failing store tests**

Add `tests/test_agent_os_store.py`:

```python
from __future__ import annotations

from src.agent_os.schemas import AgentOSEvent, TaskRunSpec
from src.agent_os.store import AgentOSStore
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope


def test_store_appends_events_and_reads_them_back(tmp_path) -> None:
    store = AgentOSStore(tmp_path)
    event = AgentOSEvent.text("做 3 张图")

    store.append_event(event)

    events = store.read_events()
    assert len(events) == 1
    assert events[0].text == "做 3 张图"


def test_store_saves_task_spec_and_envelope(tmp_path) -> None:
    store = AgentOSStore(tmp_path)
    spec = TaskRunSpec(task_id="task-1", objective="做图文")
    envelope = ResultEnvelope[DeliveryPackage].success(
        agent_name="delivery_agent",
        payload=DeliveryPackage(route="image_post", title="标题", summary="done"),
        summary="done",
        run_id="run-1",
        step_id="delivery",
    )

    store.save_task_spec(spec)
    store.save_envelope("task-1", "delivery", envelope)

    assert store.read_task_spec("task-1").objective == "做图文"
    assert store.read_envelope("task-1", "delivery").payload["title"] == "标题"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_agent_os_store.py -q
```

Expected: FAIL with missing `AgentOSStore`.

- [ ] **Step 3: Implement JSON/JSONL store**

Create `src/agent_os/store.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import AgentOSEvent, TaskRunSpec
from src.orchestration.schemas import ResultEnvelope


class AgentOSStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    def append_event(self, event: AgentOSEvent) -> None:
        self._append_jsonl(self.events_path, event.model_dump(mode="json"))

    def read_events(self) -> list[AgentOSEvent]:
        if not self.events_path.exists():
            return []
        return [
            AgentOSEvent.model_validate_json(line)
            for line in self.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def save_task_spec(self, spec: TaskRunSpec) -> None:
        task_dir = self.root / "tasks" / spec.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "task.json").write_text(
            json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_task_spec(self, task_id: str) -> TaskRunSpec:
        path = self.root / "tasks" / task_id / "task.json"
        return TaskRunSpec.model_validate_json(path.read_text(encoding="utf-8"))

    def save_envelope(self, task_id: str, label: str, envelope: ResultEnvelope[Any]) -> None:
        steps_dir = self.root / "tasks" / task_id / "steps"
        steps_dir.mkdir(parents=True, exist_ok=True)
        path = steps_dir / f"{label}.json"
        path.write_text(
            json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_envelope(self, task_id: str, label: str) -> dict[str, Any]:
        path = self.root / "tasks" / task_id / "steps" / f"{label}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Export store**

Modify `src/agent_os/__init__.py`:

```python
from .store import AgentOSStore
```

Add `"AgentOSStore"` to `__all__`.

- [ ] **Step 5: Run store tests**

Run:

```powershell
uv run pytest tests/test_agent_os_store.py tests/test_agent_os_tools.py tests/test_agent_os_runtime.py tests/test_agent_os_schemas.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_os/__init__.py src/agent_os/store.py tests/test_agent_os_store.py
git commit -m "feat: add Agent OS state store"
```

---

### Task 5: Add Specialist Tool Wrappers With Explicit Params

**Files:**
- Create: `src/agent_os/specialist_tools.py`
- Test: `tests/test_agent_os_specialist_tools.py`

- [ ] **Step 1: Write failing specialist wrapper tests**

Add `tests/test_agent_os_specialist_tools.py`:

```python
from __future__ import annotations

import pytest

from src.agent_os.schemas import ImageRunOptionsSpec, RunOptions, TaskRunSpec
from src.agent_os.specialist_tools import build_route_tool_registry, conversation_request_from_task_spec
from src.agent_os.tools import AgentToolContext
from src.orchestration.conversation import ContentRoute, ConversationRequest
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope


class FakeRouteRunner:
    def __init__(self, route: str) -> None:
        self.route = route
        self.calls = []

    async def run(self, request, **kwargs):
        self.calls.append({"request": request, "kwargs": kwargs})
        return ResultEnvelope[DeliveryPackage].success(
            agent_name=f"{self.route}_runner",
            payload=DeliveryPackage(route=self.route, title=request.topic, summary="done"),
            summary="done",
            run_id=kwargs["run_id"],
            step_id="delivery",
        )


def test_conversation_request_from_task_spec_preserves_runtime_requirements() -> None:
    spec = TaskRunSpec(
        objective="做留学图文",
        route=ContentRoute.IMAGE_POST,
        topic="出国留学",
        audience="准留学生",
        style_constraints=["末日废土风格"],
        run_options=RunOptions(image=ImageRunOptionsSpec(count=10, concurrency=2)),
    )

    request = conversation_request_from_task_spec(spec)

    assert isinstance(request, ConversationRequest)
    assert request.topic == "出国留学"
    assert request.audience == "准留学生"
    assert request.style_constraints == ["末日废土风格"]
    assert request.image_count == 10


@pytest.mark.anyio
async def test_route_tool_registry_executes_image_route_with_spec_params() -> None:
    image_runner = FakeRouteRunner("image_post")
    registry = build_route_tool_registry(image_runner=image_runner)
    spec = TaskRunSpec(
        objective="做留学图文",
        route=ContentRoute.IMAGE_POST,
        topic="出国留学",
        audience="准留学生",
        style_constraints=["末日废土风格"],
        run_options=RunOptions(image=ImageRunOptionsSpec(count=10, concurrency=2)),
    )

    result = await registry.execute(
        "execute_image_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        spec=spec.model_dump(mode="json"),
    )

    assert result.envelope.payload is not None
    assert result.envelope.payload.route == "image_post"
    assert image_runner.calls[0]["request"].image_count == 10
    assert image_runner.calls[0]["kwargs"]["send_to_feishu"] is True
    assert image_runner.calls[0]["kwargs"]["chat_id"] == "chat-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_agent_os_specialist_tools.py -q
```

Expected: FAIL with missing `specialist_tools`.

- [ ] **Step 3: Implement route wrapper tools**

Create `src/agent_os/specialist_tools.py`:

```python
from __future__ import annotations

from typing import Any

from src.orchestration.conversation import ContentRoute, ConversationRequest
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope

from .schemas import AgentToolResult, TaskRunSpec
from .tools import AgentTool, AgentToolContext, AgentToolRegistry


def conversation_request_from_task_spec(spec: TaskRunSpec) -> ConversationRequest:
    image_count = spec.run_options.image.count
    reference_images = [ref.path for ref in spec.reference_images]
    return ConversationRequest(
        topic=spec.topic or spec.objective,
        audience=spec.audience or "泛人群",
        message=spec.objective,
        route_hint=spec.route,
        style_constraints=list(spec.style_constraints),
        image_count=image_count,
        reference_images=reference_images,
    )


def build_route_tool_registry(
    *,
    image_runner: Any | None = None,
    article_runner: Any | None = None,
    video_runner: Any | None = None,
) -> AgentToolRegistry:
    registry = AgentToolRegistry()
    if image_runner is not None:
        registry.register(
            AgentTool(
                name="execute_image_post",
                description="Execute an image-post specialist workflow from a TaskRunSpec.",
                execute=_build_route_execute(image_runner, ContentRoute.IMAGE_POST),
            )
        )
    if article_runner is not None:
        registry.register(
            AgentTool(
                name="execute_article_post",
                description="Execute an article-post specialist workflow from a TaskRunSpec.",
                execute=_build_route_execute(article_runner, ContentRoute.ARTICLE_POST),
            )
        )
    if video_runner is not None:
        registry.register(
            AgentTool(
                name="execute_video_post",
                description="Execute a video-post specialist workflow from a TaskRunSpec.",
                execute=_build_route_execute(video_runner, ContentRoute.VIDEO_POST),
            )
        )
    return registry


def _build_route_execute(runner: Any, route: ContentRoute):
    async def execute(ctx: AgentToolContext, *, spec: dict[str, Any]) -> AgentToolResult:
        task_spec = TaskRunSpec.model_validate(spec)
        request = conversation_request_from_task_spec(task_spec.model_copy(update={"route": route}))
        envelope: ResultEnvelope[DeliveryPackage] = await runner.run(
            request,
            run_id=ctx.run_id,
            chat_id=ctx.chat_id,
            send_to_feishu=True,
            run_options=task_spec.run_options,
        )
        return AgentToolResult(envelope=envelope, produced_refs=[route.value])

    return execute
```

- [ ] **Step 4: Export specialist helpers**

Modify `src/agent_os/__init__.py`:

```python
from .specialist_tools import build_route_tool_registry, conversation_request_from_task_spec
```

Add both names to `__all__`.

- [ ] **Step 5: Run specialist wrapper tests**

Run:

```powershell
uv run pytest tests/test_agent_os_specialist_tools.py tests/test_agent_os_tools.py tests/test_agent_os_schemas.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_os/__init__.py src/agent_os/specialist_tools.py tests/test_agent_os_specialist_tools.py
git commit -m "feat: wrap specialist routes as Agent OS tools"
```

---

### Task 6: Add Resource Tools for Skills and Prompt Templates

**Files:**
- Create: `src/agent_os/resource_tools.py`
- Test: `tests/test_agent_os_resource_tools.py`

- [ ] **Step 1: Write failing resource tool tests**

Add `tests/test_agent_os_resource_tools.py`:

```python
from __future__ import annotations

from src.agent_os.resource_tools import AgentOSResourceTools


def test_resource_tools_list_and_read_skills(tmp_path) -> None:
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\n---\n# Demo\nUse for demos.", encoding="utf-8")
    tools = AgentOSResourceTools(skills_root=tmp_path / "skills", prompt_root=tmp_path / "prompt")

    skills = tools.list_skills()
    body = tools.read_skill("demo")

    assert skills == [{"name": "demo", "path": str(skill_dir / "SKILL.md")}]
    assert "# Demo" in body


def test_resource_tools_search_prompt_templates_by_content_not_filename_trigger(tmp_path) -> None:
    prompt_root = tmp_path / "prompt"
    (prompt_root / "image").mkdir(parents=True)
    template = prompt_root / "image" / "editorial.md"
    template.write_text("## Use When\nUse for cinematic product photography.\n", encoding="utf-8")
    tools = AgentOSResourceTools(skills_root=tmp_path / "skills", prompt_root=prompt_root)

    results = tools.search_prompt_templates("cinematic product")

    assert results == [{"path": str(template), "score": 2}]
    assert "cinematic product photography" in tools.read_prompt_template(str(template))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_agent_os_resource_tools.py -q
```

Expected: FAIL with missing `AgentOSResourceTools`.

- [ ] **Step 3: Implement resource tools**

Create `src/agent_os/resource_tools.py`:

```python
from __future__ import annotations

from pathlib import Path


class AgentOSResourceTools:
    def __init__(self, *, skills_root: Path, prompt_root: Path) -> None:
        self.skills_root = Path(skills_root)
        self.prompt_root = Path(prompt_root)

    def list_skills(self) -> list[dict[str, str]]:
        if not self.skills_root.exists():
            return []
        skills = []
        for skill_file in sorted(self.skills_root.glob("*/SKILL.md")):
            skills.append({"name": skill_file.parent.name, "path": str(skill_file)})
        return skills

    def read_skill(self, name: str) -> str:
        path = self.skills_root / name / "SKILL.md"
        return path.read_text(encoding="utf-8")

    def search_prompt_templates(self, query: str, *, limit: int = 8) -> list[dict[str, int | str]]:
        terms = [term.lower() for term in query.split() if term.strip()]
        if not self.prompt_root.exists() or not terms:
            return []
        scored = []
        for path in sorted(self.prompt_root.rglob("*.md")):
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            score = sum(1 for term in terms if term in text)
            if score:
                scored.append({"path": str(path), "score": score})
        return sorted(scored, key=lambda item: (-int(item["score"]), str(item["path"])))[:limit]

    def read_prompt_template(self, path: str) -> str:
        candidate = Path(path)
        resolved = candidate.resolve()
        root = self.prompt_root.resolve()
        if root not in resolved.parents and resolved != root:
            raise ValueError(f"Prompt template path is outside prompt root: {path}")
        return resolved.read_text(encoding="utf-8")
```

- [ ] **Step 4: Export resource tools**

Modify `src/agent_os/__init__.py`:

```python
from .resource_tools import AgentOSResourceTools
```

Add `"AgentOSResourceTools"` to `__all__`.

- [ ] **Step 5: Run resource tests**

Run:

```powershell
uv run pytest tests/test_agent_os_resource_tools.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_os/__init__.py src/agent_os/resource_tools.py tests/test_agent_os_resource_tools.py
git commit -m "feat: add Agent OS resource tools"
```

---

### Task 7: Add Feishu Interaction Tools

**Files:**
- Create: `src/agent_os/feishu_tools.py`
- Test: `tests/test_agent_os_feishu_tools.py`

- [ ] **Step 1: Write failing Feishu tool tests**

Add `tests/test_agent_os_feishu_tools.py`:

```python
from __future__ import annotations

import pytest

from src.agent_os.feishu_tools import AgentOSFeishuTools
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope


class FakeTranslator:
    def __init__(self) -> None:
        self.single_choice_calls = []

    async def ask_single_choice(self, session, **kwargs):
        self.single_choice_calls.append({"session": session, **kwargs})


class FakeNotifier:
    def __init__(self) -> None:
        self.replies = ["__route__:image_post"]
        self.messages = []

    async def wait_for_session_image_or_text(self, session, **kwargs):
        return None, self.replies.pop(0)

    async def send_session_message(self, session, message, **kwargs):
        self.messages.append({"session": session, "message": message, **kwargs})


@pytest.mark.anyio
async def test_feishu_tools_ask_single_choice_uses_translator() -> None:
    translator = FakeTranslator()
    notifier = FakeNotifier()
    tools = AgentOSFeishuTools(notifier=notifier, translator=translator)

    reply = await tools.ask_single_choice(
        object(),
        title="选路线",
        options_spec="图文::image_post||文章::article_post",
        phase="clarify",
        value_prefix="__route__:",
    )

    assert reply == "__route__:image_post"
    assert translator.single_choice_calls[0]["title"] == "选路线"
    assert len(translator.single_choice_calls[0]["options"]) == 2


@pytest.mark.anyio
async def test_feishu_tools_send_delivery_summary() -> None:
    notifier = FakeNotifier()
    tools = AgentOSFeishuTools(notifier=notifier)
    envelope = ResultEnvelope[DeliveryPackage].success(
        agent_name="delivery",
        payload=DeliveryPackage(route="image_post", title="标题", summary="done"),
        summary="done",
        run_id="run-1",
        step_id="delivery",
    )

    await tools.send_delivery_summary(object(), envelope)

    assert "标题" in notifier.messages[0]["message"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_agent_os_feishu_tools.py -q
```

Expected: FAIL with missing `AgentOSFeishuTools`.

- [ ] **Step 3: Implement Feishu tools**

Create `src/agent_os/feishu_tools.py`:

```python
from __future__ import annotations

from typing import Any

from src.orchestration.feishu_translation import FeishuInteractionTranslator, parse_delimited_options
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope
from src.utils.feishu_notifier import get_feishu_notifier


class AgentOSFeishuTools:
    def __init__(self, *, notifier: Any | None = None, translator: Any | None = None) -> None:
        self.notifier = notifier or get_feishu_notifier()
        self.translator = translator or FeishuInteractionTranslator(notifier=self.notifier)

    async def ask_single_choice(
        self,
        session: object,
        *,
        title: str,
        options_spec: str,
        phase: str,
        value_prefix: str = "",
        summary: str | None = None,
    ) -> str:
        await self.translator.ask_single_choice(
            session,
            title=title,
            options=parse_delimited_options(options_spec),
            phase=phase,
            value_prefix=value_prefix,
            summary=summary,
        )
        _, reply = await self.notifier.wait_for_session_image_or_text(session, phase=phase, summary=summary)
        return reply

    async def send_progress(self, session: object, message: str, *, phase: str, summary: str | None = None) -> None:
        await self.notifier.send_session_message(session, message, phase=phase, summary=summary)

    async def send_delivery_summary(
        self,
        session: object,
        envelope: ResultEnvelope[DeliveryPackage],
    ) -> None:
        if envelope.payload is None:
            await self.notifier.send_session_message(
                session,
                f"执行失败：{envelope.error_message or envelope.summary}",
                phase="failed",
                summary=envelope.summary,
            )
            return
        await self.notifier.send_session_message(
            session,
            f"已完成 {envelope.payload.route} 交付，标题：{envelope.payload.title}",
            phase="completed",
            summary=envelope.payload.summary,
        )
```

- [ ] **Step 4: Export Feishu tools**

Modify `src/agent_os/__init__.py`:

```python
from .feishu_tools import AgentOSFeishuTools
```

Add `"AgentOSFeishuTools"` to `__all__`.

- [ ] **Step 5: Run Feishu tool tests**

Run:

```powershell
uv run pytest tests/test_agent_os_feishu_tools.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_os/__init__.py src/agent_os/feishu_tools.py tests/test_agent_os_feishu_tools.py
git commit -m "feat: add Agent OS Feishu tools"
```

---

### Task 8: Add Main Agent Construction and Tool Registration

**Files:**
- Create: `src/agent_os/main_agent.py`
- Test: `tests/test_agent_os_main_agent.py`

- [ ] **Step 1: Write failing main Agent tests**

Add `tests/test_agent_os_main_agent.py`:

```python
from __future__ import annotations

from src.agent_os.main_agent import MAIN_AGENT_SYSTEM_PROMPT, MainAgentDependencies, create_main_agent
from src.agent_os.tools import AgentToolRegistry


def test_main_agent_prompt_defines_planner_not_worker_role() -> None:
    assert "任务规划和组织者" in MAIN_AGENT_SYSTEM_PROMPT
    assert "不要亲自执行专项任务" in MAIN_AGENT_SYSTEM_PROMPT
    assert "TaskRunSpec" in MAIN_AGENT_SYSTEM_PROMPT
    assert "飞书" in MAIN_AGENT_SYSTEM_PROMPT


def test_main_agent_dependencies_hold_tool_registry() -> None:
    registry = AgentToolRegistry()
    deps = MainAgentDependencies(tool_registry=registry)

    assert deps.tool_registry is registry


def test_create_main_agent_returns_agent_with_expected_tools() -> None:
    agent = create_main_agent()
    tool_names = {tool.name for toolset in agent.toolsets() for tool in toolset.tools.values()}

    assert "describe_available_tools" in tool_names
    assert "execute_agent_tool" in tool_names
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_agent_os_main_agent.py -q
```

Expected: FAIL with missing `main_agent`.

- [ ] **Step 3: Implement main Agent factory**

Create `src/agent_os/main_agent.py`:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from src.utils.providers import get_text_model

from .schemas import AgentToolResult
from .tools import AgentToolContext, AgentToolRegistry


MAIN_AGENT_SYSTEM_PROMPT = """你是飞书内容系统的主 Agent，是一个长期运行的任务规划和组织者。

你的职责：
- 理解用户随时发来的自然语言、图片、按钮和表单反馈。
- 把用户要求转成明确的 TaskRunSpec 和工具调用参数。
- 选择 Skill、提示词模板和专项 Agent 工具。
- 通过工具询问用户、执行任务、读取产物、发送飞书交付。

边界：
- 不要亲自执行专项任务；研究、分组、图片生成、文章、视频、登录、交付都通过工具调用完成。
- 不要要求用户使用固定格式。缺信息时用飞书工具让用户点选或补充。
- 不要使用关键词触发规则选择 Skill 或提示词模板；根据语义和任务目标选择。
- 用户指定的数量、风格、模型、参考图、研究深度、并发、审核严格度必须变成工具参数。
- 最终内容只交付到飞书。
"""


class MainAgentDependencies(BaseModel):
    tool_registry: AgentToolRegistry = Field(default_factory=AgentToolRegistry)
    session_id: str | None = None
    chat_id: str | None = None

    model_config = {"arbitrary_types_allowed": True}


def create_main_agent() -> Agent[MainAgentDependencies, str]:
    agent = Agent(
        model=get_text_model(),
        deps_type=MainAgentDependencies,
        output_type=str,
        system_prompt=(MAIN_AGENT_SYSTEM_PROMPT,),
        instrument=True,
    )

    @agent.tool
    async def describe_available_tools(ctx: RunContext[MainAgentDependencies]) -> list[dict[str, str]]:
        return ctx.deps.tool_registry.describe_tools()

    @agent.tool
    async def execute_agent_tool(
        ctx: RunContext[MainAgentDependencies],
        tool_name: str,
        params: dict[str, Any],
        run_id: str,
        task_id: str | None = None,
        step_id: str | None = None,
    ) -> AgentToolResult:
        tool_ctx = AgentToolContext(
            run_id=run_id,
            task_id=task_id,
            step_id=step_id,
            chat_id=ctx.deps.chat_id,
        )
        return await ctx.deps.tool_registry.execute(tool_name, tool_ctx, **params)

    return agent
```

- [ ] **Step 4: Export main Agent helpers**

Modify `src/agent_os/__init__.py`:

```python
from .main_agent import MAIN_AGENT_SYSTEM_PROMPT, MainAgentDependencies, create_main_agent
```

Add names to `__all__`.

- [ ] **Step 5: Run main Agent tests**

Run:

```powershell
uv run pytest tests/test_agent_os_main_agent.py -q
```

Expected: PASS. If `agent.toolsets()` API differs in the installed Pydantic AI version, inspect `agent.toolsets()` and adjust the test to use the stable public accessor that lists registered tool definitions.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_os/__init__.py src/agent_os/main_agent.py tests/test_agent_os_main_agent.py
git commit -m "feat: add Agent OS main agent"
```

---

### Task 9: Add Agent OS Feishu App Entrypoint

**Files:**
- Create: `src/apps/feishu_agent_os/__init__.py`
- Create: `src/apps/feishu_agent_os/serve.py`
- Test: `tests/test_feishu_agent_os_serve.py`

- [ ] **Step 1: Write failing app entry tests**

Add `tests/test_feishu_agent_os_serve.py`:

```python
from __future__ import annotations

import importlib


def test_feishu_agent_os_serve_module_imports() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")

    assert hasattr(module, "create_service")
    assert hasattr(module, "main")


def test_create_service_wires_runtime_and_notifier() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    service = module.create_service(notifier=object())

    assert hasattr(service, "runtime")
    assert hasattr(service, "serve_forever")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_feishu_agent_os_serve.py -q
```

Expected: FAIL with missing `src.apps.feishu_agent_os`.

- [ ] **Step 3: Implement app entrypoint skeleton**

Create `src/apps/feishu_agent_os/__init__.py`:

```python
"""Feishu Agent OS app entrypoint."""
```

Create `src/apps/feishu_agent_os/serve.py`:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.agent_os.main_agent import MainAgentDependencies, create_main_agent
from src.agent_os.runtime import MainAgentRuntime
from src.agent_os.store import AgentOSStore
from src.agent_os.tools import AgentToolRegistry
from src.config.settings import PathConfig
from src.utils.feishu_notifier import FeishuInputEvent, get_feishu_notifier
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FeishuAgentOSService:
    notifier: Any
    runtime: MainAgentRuntime
    tool_registry: AgentToolRegistry
    store: AgentOSStore

    async def serve_forever(self) -> None:
        await self.notifier.start_polling()
        logger.info("Feishu Agent OS 已启动，等待事件输入…")
        while True:
            image_path, text = await self.notifier.wait_for_image_or_text()
            if image_path is not None:
                self.runtime.ingest_event_from_image(Path(image_path), caption=text)
            elif text.strip():
                self.runtime.ingest_text(text)


def create_service(*, notifier: Any | None = None) -> FeishuAgentOSService:
    resolved_notifier = notifier or get_feishu_notifier()
    runtime = MainAgentRuntime()
    registry = AgentToolRegistry()
    store = AgentOSStore(Path("output") / "agent-os")
    return FeishuAgentOSService(
        notifier=resolved_notifier,
        runtime=runtime,
        tool_registry=registry,
        store=store,
    )


async def async_main() -> None:
    service = create_service()
    await service.serve_forever()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
```

Then add convenience methods to `src/agent_os/runtime.py`:

```python
from pathlib import Path

def ingest_text(self, text: str, *, priority: EventPriority = "asap") -> None:
    self.ingest_event(AgentOSEvent.text(text, priority=priority))

def ingest_event_from_image(self, image_path: Path, *, caption: str = "", priority: EventPriority = "asap") -> None:
    self.ingest_event(AgentOSEvent.image(str(image_path), caption=caption, priority=priority))
```

- [ ] **Step 4: Run app entry tests**

Run:

```powershell
uv run pytest tests/test_feishu_agent_os_serve.py tests/test_agent_os_runtime.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/apps/feishu_agent_os src/agent_os/runtime.py tests/test_feishu_agent_os_serve.py
git commit -m "feat: add Feishu Agent OS app entrypoint"
```

---

### Task 10: Wire Main Agent Runtime to Pydantic AI Enqueue

**Files:**
- Modify: `src/agent_os/runtime.py`
- Modify: `src/apps/feishu_agent_os/serve.py`
- Test: `tests/test_agent_os_runtime.py`

- [ ] **Step 1: Add failing test for AgentRun attachment lifecycle**

Append to `tests/test_agent_os_runtime.py`:

```python
def test_runtime_attach_run_flushes_pending_in_order() -> None:
    runtime = MainAgentRuntime()
    run = FakeAgentRun()

    runtime.ingest_text("第一条")
    runtime.ingest_text("第二条", priority="when_idle")
    runtime.attach_run(run)

    assert run.enqueued == [("第一条", "asap"), ("第二条", "when_idle")]
```

- [ ] **Step 2: Run test**

Run:

```powershell
uv run pytest tests/test_agent_os_runtime.py::test_runtime_attach_run_flushes_pending_in_order -q
```

Expected: PASS if Task 9 convenience methods were implemented correctly; otherwise FAIL.

- [ ] **Step 3: Add Pydantic AgentRun adapter**

Modify `src/agent_os/runtime.py`:

```python
class PydanticAgentRunAdapter:
    def __init__(self, agent_run: Any) -> None:
        self.agent_run = agent_run
        self.cancelled = False

    def enqueue(self, text: str, *, priority: str = "asap") -> None:
        self.agent_run.enqueue(text, priority=priority)

    def reset_session(self) -> None:
        self.cancel_current_task()

    def cancel_current_task(self) -> None:
        self.cancelled = True
        cancel = getattr(self.agent_run, "cancel", None)
        if callable(cancel):
            cancel()
```

Export `PydanticAgentRunAdapter` in `src/agent_os/__init__.py`.

- [ ] **Step 4: Wire service to create main Agent dependencies**

Modify `src/apps/feishu_agent_os/serve.py` to hold the main Agent and dependencies:

```python
from src.agent_os.main_agent import MainAgentDependencies, create_main_agent

@dataclass
class FeishuAgentOSService:
    notifier: Any
    runtime: MainAgentRuntime
    tool_registry: AgentToolRegistry
    store: AgentOSStore
    main_agent: Any

def create_service(*, notifier: Any | None = None) -> FeishuAgentOSService:
    ...
    return FeishuAgentOSService(
        notifier=resolved_notifier,
        runtime=runtime,
        tool_registry=registry,
        store=store,
        main_agent=create_main_agent(),
    )
```

This step only wires construction. Starting the long-running `agent.iter(...)`
loop is Task 11, after tool registry construction is in place.

- [ ] **Step 5: Run targeted tests**

Run:

```powershell
uv run pytest tests/test_agent_os_runtime.py tests/test_feishu_agent_os_serve.py tests/test_agent_os_main_agent.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_os/__init__.py src/agent_os/runtime.py src/apps/feishu_agent_os/serve.py tests/test_agent_os_runtime.py
git commit -m "feat: wire Agent OS runtime to Pydantic AI runs"
```

---

### Task 11: Replace Formal Feishu Entrypoint With Agent OS Service

**Files:**
- Modify: `src/apps/feishu_orchestrator/serve.py`
- Modify: `tests/test_feishu_orchestrator_serve.py`
- Modify: `tests/test_feishu_first_architecture_boundaries.py`

- [ ] **Step 1: Add failing boundary test**

Append to `tests/test_feishu_first_architecture_boundaries.py`:

```python
def test_formal_feishu_entrypoint_delegates_to_agent_os() -> None:
    serve_path = REPO_ROOT / "src" / "apps" / "feishu_orchestrator" / "serve.py"
    text = serve_path.read_text(encoding="utf-8")

    assert "src.apps.feishu_agent_os.serve" in text
    assert "FeishuContentOrchestrator()" not in text
    assert "FeishuWorkflowService(" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
uv run pytest tests/test_feishu_first_architecture_boundaries.py::test_formal_feishu_entrypoint_delegates_to_agent_os -q
```

Expected: FAIL because old service still builds `FeishuContentOrchestrator`.

- [ ] **Step 3: Replace compatibility serve module**

Modify `src/apps/feishu_orchestrator/serve.py` to delegate:

```python
from __future__ import annotations

from src.apps.feishu_agent_os.serve import async_main, create_service, main

__all__ = ["async_main", "create_service", "main"]


if __name__ == "__main__":
    main()
```

If existing tests expect helper functions from `serve.py`, move those helpers to
`src/apps/feishu_agent_os/serve.py` before replacing and re-export them here.

- [ ] **Step 4: Update old serve tests**

Modify `tests/test_feishu_orchestrator_serve.py` so it asserts delegation rather
than old construction:

```python
def test_feishu_orchestrator_serve_delegates_to_agent_os() -> None:
    module = _load_module()

    assert module.create_service.__module__ == "src.apps.feishu_agent_os.serve"
```

- [ ] **Step 5: Run entrypoint tests**

Run:

```powershell
uv run pytest tests/test_feishu_orchestrator_serve.py tests/test_feishu_agent_os_serve.py tests/test_feishu_first_architecture_boundaries.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/apps/feishu_orchestrator/serve.py tests/test_feishu_orchestrator_serve.py tests/test_feishu_first_architecture_boundaries.py
git commit -m "feat: make Agent OS the formal Feishu entrypoint"
```

---

### Task 12: Update Documentation and Run Full Verification

**Files:**
- Modify: `src/agents/AGENTS.md`
- Modify: `README.md` if it documents the old Feishu orchestrator command
- Test: full suite

- [ ] **Step 1: Update agent organization docs**

Modify `src/agents/AGENTS.md` Feishu runtime section to say:

```markdown
## Feishu Agent OS Runtime

- The formal Feishu entrypoint is `src/apps/feishu_agent_os/`.
- The main Agent is a long-running task planner and organizer. It receives
  events, builds `TaskRunSpec`, and calls specialist Agent tools.
- `src/apps/feishu_orchestrator/` is a compatibility shim only.
- Specialist Agents remain atomic under `src/agents/<content_type>/<phase>/`.
- User requirements become runtime parameters passed to tools; config files only
  provide defaults.
```

- [ ] **Step 2: Search for stale formal-entry wording**

Run:

```powershell
rg -n "FeishuContentOrchestrator|FeishuWorkflowService|feishu_orchestrator|formal entry|正式入口" README.md docs src tests
```

Expected: Any remaining references either describe compatibility or tests that intentionally assert the old entry is not formal.

- [ ] **Step 3: Run all Agent OS targeted tests**

Run:

```powershell
uv run pytest tests/test_agent_os_*.py tests/test_feishu_agent_os_serve.py tests/test_feishu_orchestrator_serve.py tests/test_feishu_first_architecture_boundaries.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full test suite**

Run:

```powershell
uv run pytest -q
```

Expected: PASS with zero failures.

- [ ] **Step 5: Commit docs and final fixes**

```powershell
git add src/agents/AGENTS.md README.md tests src
git commit -m "docs: document Agent OS Feishu entrypoint"
```

- [ ] **Step 6: Push main**

```powershell
git status --short --branch
git push origin main
```

Expected: working tree clean and `main` pushed.

---

## Self-Review

### Spec Coverage

- Long-running Agent OS runtime: Tasks 2, 8, 10.
- Event bus / Feishu activation: Tasks 2, 7, 9, 11.
- User requirements as runtime parameters: Tasks 1, 5, 8.
- Specialist Agents as tools: Tasks 3, 5.
- Skill and prompt tools: Task 6.
- State store and envelopes: Tasks 1, 4, 5.
- Formal Feishu entrypoint replacement: Tasks 9, 11, 12.
- Test strategy: Every task starts with failing tests and includes targeted + full verification.

### Placeholder Scan

The plan has no unresolved marker text or unspecified "add tests" steps. Each code task includes file paths, test names, commands, expected results, and implementation snippets.

### Scope Check

The full Agent OS design is large. This plan implements the working kernel and formal Feishu entry replacement while preserving current specialist internals behind wrappers for one migration phase. Deleting old route orchestrators is intentionally left for the next plan after equivalent atomic tools have replaced every wrapper.
