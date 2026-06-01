from __future__ import annotations

import asyncio
import io
import os
import sys
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is a runtime dependency.
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env")

from src.agent_os.feishu_tools import AgentOSFeishuTools
from src.agent_os.main_agent import MainAgentDependencies, create_main_agent
from src.agent_os.resource_tools import AgentOSResourceTools
from src.agent_os.runtime import MainAgentRuntime
from src.agent_os.schemas import AgentOSEvent, AgentToolResult
from src.agent_os.specialist_tools import build_route_tool_registry
from src.agent_os.store import AgentOSStore
from src.agent_os.task_manager import AgentOSTaskManager
from src.agent_os.tools import AgentTool, AgentToolContext, AgentToolRegistry
from src.config.settings import PathConfig
from src.orchestration.article_route import ArticlePostOrchestrator
from src.orchestration.delivery import DeliveryPackageSender
from src.orchestration.feishu_translation import parse_control_action_text
from src.orchestration.image_route import ImagePostOrchestrator
from src.orchestration.schemas import ResultEnvelope
from src.orchestration.video_route import VideoPostOrchestrator
from src.utils.feishu_interactive_workflow import acquire_interactive_session
from src.utils.feishu_notifier import get_feishu_notifier
from src.utils.logger import get_logger, setup_logging

FEISHU_INTERACTIVE_ENV_DEFAULTS = {
    "RESEARCH_MIN_POSTS_RESEARCHED": "3",
    "RESEARCH_VALIDATION_MAX_RETRIES": "3",
    "RESEARCH_MAX_NEW_POSTS_PER_ITERATION": "2",
    "RESEARCH_PER_ITERATION_REQUEST_LIMIT": "24",
    "RESEARCH_PER_ITERATION_TOOL_CALLS_LIMIT": "48",
    "RESEARCH_POST_IMAGE_READER_MAX_IMAGES": "2",
    "RESEARCH_POST_IMAGE_READER_REQUEST_LIMIT": "6",
    "RESEARCH_POST_IMAGE_READER_TOOL_CALLS_LIMIT": "8",
    "ARTICLE_RESEARCH_MIN_SOURCE_PAGES": "2",
    "ARTICLE_RESEARCH_MIN_UNIQUE_DOMAINS": "2",
    "ARTICLE_RESEARCH_MAX_SOURCE_PAGES": "3",
    "ARTICLE_RESEARCH_MAX_VIDEO_TRANSCRIPTS": "0",
    "ARTICLE_RESEARCH_MAX_ITERATIONS": "1",
    "ARTICLE_RESEARCH_MAX_TASKS_PER_ITERATION": "2",
    "ARTICLE_RESEARCH_MAX_CURATED_SOURCES_PER_TASK": "2",
    "ARTICLE_RESEARCH_MAX_CURATED_VIDEO_SOURCES_PER_TASK": "1",
    "ARTICLE_CONTENT_MAX_ITERATIONS": "2",
    "ARTICLE_IMAGE_MAX_IMAGES": "1",
    "VERTEX_AI_VISION_MAX_CONCURRENCY": "3",
    "VERTEX_AI_IMAGE_MAX_CONCURRENCY": "1",
    "IMAGE_GROUPING_REVIEW_MAX_RETRIES": "3",
}

logger = get_logger(__name__)


class AgentOSMainAgentSession:
    """Runs Pydantic AI one inserted user event at a time.

    Pydantic AI 1.x does not expose a live `enqueue` API, so the Agent OS keeps
    the queue at the application layer and preserves message history across
    sequential `agent.run(...)` calls.
    """

    def __init__(
        self,
        *,
        agent: Any,
        deps: MainAgentDependencies,
        notifier: Any | None = None,
        session: object | None = None,
    ) -> None:
        self.agent = agent
        self.deps = deps
        self.notifier = notifier
        self.session = session
        self._pending: deque[tuple[str, str]] = deque()
        self._message_history: list[Any] = []
        self._worker_task: asyncio.Task[None] | None = None
        self._current_run_task: asyncio.Task[Any] | None = None
        self._has_pending = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._closed = False

    @property
    def message_history(self) -> list[Any]:
        return list(self._message_history)

    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._closed = True
        self.cancel_current_task()
        if self._worker_task is not None:
            self._worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker_task

    def enqueue(self, text: str, *, priority: str = "asap") -> None:
        self._pending.append((text, priority))
        self._idle.clear()
        self._has_pending.set()

    def reset_session(self) -> None:
        self._pending.clear()
        self._message_history = []
        self.cancel_current_task()
        self._idle.set()

    def cancel_current_task(self) -> None:
        if self._current_run_task is not None and not self._current_run_task.done():
            self._current_run_task.cancel()

    async def wait_for_idle(self) -> None:
        while not self._idle.is_set():
            await self._idle.wait()

    async def _run_loop(self) -> None:
        while not self._closed:
            await self._has_pending.wait()
            self._has_pending.clear()
            while self._pending:
                text, _priority = self._pending.popleft()
                await self._run_once(text)
            self._idle.set()

    async def _run_once(self, text: str) -> None:
        self._current_run_task = asyncio.create_task(
            self.agent.run(
                text,
                deps=self.deps,
                message_history=self._message_history,
            )
        )
        try:
            result = await self._current_run_task
        except asyncio.CancelledError:
            logger.info("Agent OS 主 Agent 当前任务已取消")
            return
        except Exception as exc:
            logger.exception("Agent OS 主 Agent 处理事件失败")
            await self._emit_output(f"主 Agent 处理失败：{exc}")
            return
        finally:
            self._current_run_task = None

        all_messages = getattr(result, "all_messages", None)
        if callable(all_messages):
            self._message_history = list(all_messages())
        output = getattr(result, "output", "")
        if isinstance(output, str) and output.strip():
            await self._emit_output(output.strip())

    async def _emit_output(self, text: str) -> None:
        if self.notifier is None:
            return
        if self.session is not None and hasattr(self.notifier, "send_session_message"):
            await self.notifier.send_session_message(
                self.session,
                text,
                phase="idle",
                summary="主 Agent 回复",
            )
            return
        send_message = getattr(self.notifier, "send_message", None)
        if callable(send_message):
            await send_message(text, chat_id=self.deps.chat_id)


@dataclass
class AgentOSToolRuntime:
    registry: AgentToolRegistry
    task_manager: AgentOSTaskManager


@dataclass
class FeishuAgentOSService:
    notifier: Any
    runtime: MainAgentRuntime
    tool_registry: AgentToolRegistry
    store: AgentOSStore
    main_agent: Any
    acquire_session: Any = acquire_interactive_session
    task_manager: AgentOSTaskManager | None = None
    agent_session: AgentOSMainAgentSession | None = None
    session: object | None = None

    async def serve_forever(self) -> None:
        start_polling = getattr(self.notifier, "start_polling", None)
        if callable(start_polling):
            await start_polling()
        await self._start_main_agent_session()
        logger.info("Feishu Agent OS 已启动，等待事件输入...")
        while True:
            try:
                await self.process_next_event_once()
            except Exception:
                logger.exception("处理 Feishu Agent OS 事件失败")

    async def process_next_event_once(self) -> AgentOSEvent | None:
        if self.agent_session is None:
            await self._start_main_agent_session()
        event = await self._wait_for_next_event()
        if event is None:
            return None
        self.store.append_event(event)
        self.runtime.ingest_event(event)
        return event

    async def _start_main_agent_session(self) -> None:
        if self.agent_session is not None:
            return
        session = await self._try_acquire_session()
        self.session = session
        deps = MainAgentDependencies(
            tool_registry=self.tool_registry,
            session=session,
            session_id=getattr(getattr(session, "handle", None), "session_id", None),
            chat_id=getattr(session, "chat_id", None) or getattr(self.notifier, "chat_id", None),
        )
        self.agent_session = AgentOSMainAgentSession(
            agent=self.main_agent,
            deps=deps,
            notifier=self.notifier,
            session=session,
        )
        self.agent_session.start()
        self.runtime.attach_run(self.agent_session)

    async def _try_acquire_session(self) -> object | None:
        if self.acquire_session is None:
            return None
        if not getattr(self.notifier, "client", None) or not getattr(self.notifier, "chat_id", None):
            return None
        session, blocked_reason = await self.acquire_session(
            notifier=self.notifier,
            workflow="feishu_agent_os",
            summary="主 Agent 会话",
            current_phase="idle",
        )
        if blocked_reason:
            logger.warning("无法获取 Feishu Agent OS 会话: %s", blocked_reason)
        return session

    async def _wait_for_next_event(self) -> AgentOSEvent | None:
        if self.session is not None and hasattr(self.notifier, "wait_for_session_event"):
            feishu_event = await self.notifier.wait_for_session_event(
                self.session,
                phase="idle",
                summary="主 Agent 等待用户输入",
            )
            return self._event_from_feishu_input(feishu_event)

        image_path, text = await self.notifier.wait_for_image_or_text()
        if image_path is not None:
            return AgentOSEvent.image(str(Path(image_path)), caption=text)
        return self._text_or_control_event(text)

    def _event_from_feishu_input(self, event: Any) -> AgentOSEvent | None:
        text = getattr(event, "text", "") or ""
        event_action = getattr(event, "action", None)
        control_action = (
            event_action
            if event_action in {"new_session", "interrupt", "follow_up"}
            else parse_control_action_text(text)
        )
        if control_action:
            return AgentOSEvent.control(control_action)
        image_path = getattr(event, "image_path", None)
        if image_path is not None:
            return AgentOSEvent.image(str(Path(image_path)), caption=text)
        return self._text_or_control_event(text)

    def _text_or_control_event(self, text: str) -> AgentOSEvent | None:
        if not text.strip():
            return None
        action = parse_control_action_text(text)
        if action:
            return AgentOSEvent.control(action)
        return AgentOSEvent.text(text)


def _resolve_env_path() -> Path:
    candidates = [
        PROJECT_ROOT / ".env",
        PROJECT_ROOT.parents[1] / ".env",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def apply_feishu_interactive_defaults() -> None:
    """Use practical defaults for always-on chat workflows unless .env overrides them."""
    for key, value in FEISHU_INTERACTIVE_ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)


def configure_windows_stdio() -> None:
    if sys.platform != "win32":
        return
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def build_default_tool_runtime(*, notifier: Any | None = None) -> AgentOSToolRuntime:
    delivery_sender = DeliveryPackageSender(notifier=notifier) if notifier is not None else None
    registry = build_route_tool_registry(
        image_runner=ImagePostOrchestrator(delivery_sender=delivery_sender),
        article_runner=ArticlePostOrchestrator(delivery_sender=delivery_sender),
        video_runner=VideoPostOrchestrator(delivery_sender=delivery_sender),
    )
    _register_resource_tools(registry)
    _register_feishu_tools(registry, notifier=notifier)
    task_manager = AgentOSTaskManager(tool_registry=registry, notifier=notifier)
    _register_task_tools(registry, task_manager=task_manager)
    return AgentOSToolRuntime(registry=registry, task_manager=task_manager)


def build_default_tool_registry(*, notifier: Any | None = None) -> AgentToolRegistry:
    return build_default_tool_runtime(notifier=notifier).registry


def _register_resource_tools(registry: AgentToolRegistry) -> None:
    resources = AgentOSResourceTools(
        skills_root=PathConfig.AGENT_SKILLS_DIR,
        prompt_root=Path(".agents") / "prompt",
    )

    async def list_skills(ctx: AgentToolContext) -> AgentToolResult:
        return _tool_success(ctx, "resource_tools", "skills", resources.list_skills())

    async def read_skill(ctx: AgentToolContext, *, name: str) -> AgentToolResult:
        return _tool_success(ctx, "resource_tools", f"skill:{name}", resources.read_skill(name))

    async def search_prompt_templates(
        ctx: AgentToolContext,
        *,
        query: str,
        limit: int = 8,
    ) -> AgentToolResult:
        return _tool_success(
            ctx,
            "resource_tools",
            "prompt_search",
            resources.search_prompt_templates(query, limit=limit),
        )

    async def read_prompt_template(ctx: AgentToolContext, *, path: str) -> AgentToolResult:
        return _tool_success(ctx, "resource_tools", "prompt_template", resources.read_prompt_template(path))

    registry.register(
        AgentTool(
            name="list_skills",
            description="List available Skill documents.",
            execute=list_skills,
            category="resource",
        )
    )
    registry.register(
        AgentTool(
            name="read_skill",
            description="Read a Skill document by name.",
            execute=read_skill,
            category="resource",
        )
    )
    registry.register(
        AgentTool(
            name="search_prompt_templates",
            description="Search versioned prompt templates by semantic query terms.",
            execute=search_prompt_templates,
            category="resource",
        )
    )
    registry.register(
        AgentTool(
            name="read_prompt_template",
            description="Read a versioned prompt template from the prompt library.",
            execute=read_prompt_template,
            category="resource",
        )
    )


def _register_feishu_tools(registry: AgentToolRegistry, *, notifier: Any | None) -> None:
    feishu = AgentOSFeishuTools(notifier=notifier)

    async def ask_single_choice(
        ctx: AgentToolContext,
        *,
        title: str,
        options_spec: str,
        phase: str = "clarify",
        value_prefix: str = "",
        summary: str | None = None,
    ) -> AgentToolResult:
        if ctx.session is None:
            return _tool_error(ctx, "feishu_tools", "缺少 Feishu 会话，无法渲染点选卡片")
        reply = await feishu.ask_single_choice(
            ctx.session,
            title=title,
            options_spec=options_spec,
            phase=phase,
            value_prefix=value_prefix,
            summary=summary,
        )
        return _tool_success(ctx, "feishu_tools", "single_choice", {"reply": reply})

    async def send_progress(
        ctx: AgentToolContext,
        *,
        message: str,
        phase: str = "running",
        summary: str | None = None,
    ) -> AgentToolResult:
        if ctx.session is None:
            return _tool_error(ctx, "feishu_tools", "缺少 Feishu 会话，无法发送会话进度")
        await feishu.send_progress(ctx.session, message, phase=phase, summary=summary)
        return _tool_success(ctx, "feishu_tools", "progress", {"sent": True})

    registry.register(
        AgentTool(
            name="ask_feishu_single_choice",
            description="Ask the user to pick one option in Feishu using delimited options.",
            execute=ask_single_choice,
            category="feishu",
        )
    )
    registry.register(
        AgentTool(
            name="send_feishu_progress",
            description="Send a short progress update to the current Feishu session.",
            execute=send_progress,
            category="feishu",
        )
    )


def _register_task_tools(
    registry: AgentToolRegistry,
    *,
    task_manager: AgentOSTaskManager,
) -> None:
    async def start_background_agent_task(
        ctx: AgentToolContext,
        *,
        tool_name: str,
        params: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        try:
            task = task_manager.start_task(tool_name, ctx, params=params or {})
        except Exception as exc:
            return _tool_error(ctx, "agent_os_task_manager", str(exc))
        return _tool_success(
            ctx,
            "agent_os_task_manager",
            "start_background_agent_task",
            task.to_summary(),
        )

    async def list_background_agent_tasks(ctx: AgentToolContext) -> AgentToolResult:
        return _tool_success(
            ctx,
            "agent_os_task_manager",
            "list_background_agent_tasks",
            [task.to_summary() for task in task_manager.list_tasks()],
        )

    async def restart_background_agent_task(
        ctx: AgentToolContext,
        *,
        task_id: str,
    ) -> AgentToolResult:
        try:
            task = task_manager.restart_task(task_id)
        except Exception as exc:
            return _tool_error(ctx, "agent_os_task_manager", str(exc))
        return _tool_success(
            ctx,
            "agent_os_task_manager",
            "restart_background_agent_task",
            task.to_summary(),
        )

    registry.register(
        AgentTool(
            name="start_background_agent_task",
            description=(
                "Start a specialist Agent workflow in the background so the main "
                "Feishu chat can continue."
            ),
            execute=start_background_agent_task,
            category="task",
        )
    )
    registry.register(
        AgentTool(
            name="list_background_agent_tasks",
            description="List background Agent workflow status for the current runtime.",
            execute=list_background_agent_tasks,
            category="task",
        )
    )
    registry.register(
        AgentTool(
            name="restart_background_agent_task",
            description="Restart a previous background Agent workflow with its original parameters.",
            execute=restart_background_agent_task,
            category="task",
        )
    )


def _tool_success(
    ctx: AgentToolContext,
    agent_name: str,
    step_id: str,
    payload: Any,
) -> AgentToolResult:
    envelope = ResultEnvelope[Any].success(
        agent_name=agent_name,
        payload=payload,
        summary=f"{step_id} completed",
        run_id=ctx.run_id,
        step_id=ctx.step_id or step_id,
    )
    return AgentToolResult(envelope=envelope)


def _tool_error(
    ctx: AgentToolContext,
    agent_name: str,
    error_message: str,
) -> AgentToolResult:
    envelope = ResultEnvelope[Any].error(
        agent_name=agent_name,
        summary=error_message,
        error_message=error_message,
        run_id=ctx.run_id,
        step_id=ctx.step_id or agent_name,
    )
    return AgentToolResult(envelope=envelope)


def create_service(
    *,
    notifier: Any | None = None,
    runtime: MainAgentRuntime | None = None,
    tool_registry: AgentToolRegistry | None = None,
    task_manager: AgentOSTaskManager | None = None,
    store: AgentOSStore | None = None,
    main_agent: Any | None = None,
    acquire_session: Any = acquire_interactive_session,
) -> FeishuAgentOSService:
    resolved_notifier = notifier or get_feishu_notifier()
    if tool_registry is None:
        tool_runtime = build_default_tool_runtime(notifier=resolved_notifier)
        resolved_registry = tool_runtime.registry
        resolved_task_manager = task_manager or tool_runtime.task_manager
    else:
        resolved_registry = tool_registry
        resolved_task_manager = task_manager
    return FeishuAgentOSService(
        notifier=resolved_notifier,
        runtime=runtime or MainAgentRuntime(),
        tool_registry=resolved_registry,
        store=store or AgentOSStore(Path("output") / "agent-os"),
        main_agent=main_agent or create_main_agent(),
        acquire_session=acquire_session,
        task_manager=resolved_task_manager,
    )


async def async_main() -> int:
    from dotenv import load_dotenv

    load_dotenv(_resolve_env_path())
    apply_feishu_interactive_defaults()

    import logfire

    logfire.configure(
        send_to_logfire="if-token-present",
        environment="development",
        service_name="xiaohongshu-agent-feishu-agent-os",
    )
    logfire.instrument_pydantic_ai()

    setup_logging()
    service = create_service()
    await service.serve_forever()
    return 0


main_async = async_main


def main() -> None:
    configure_windows_stdio()
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
