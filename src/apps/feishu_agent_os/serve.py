from __future__ import annotations

import asyncio
import io
import os
import re
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
from src.agent_os.schemas import AgentOSEvent, AgentToolResult, TaskRunSpec
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
        self.deps.current_user_text = text
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
        query: str = "",
        limit: int = 8,
        **filters: Any,
    ) -> AgentToolResult:
        resolved_query = query.strip()
        if not resolved_query and filters:
            resolved_query = " ".join(str(value) for value in filters.values() if value)
        return _tool_success(
            ctx,
            "resource_tools",
            "prompt_search",
            resources.search_prompt_templates(resolved_query, limit=limit),
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
        options_spec: str = "",
        title: str = "",
        question: str = "",
        options: Any | None = None,
        phase: str = "clarify",
        value_prefix: str = "",
        summary: str | None = None,
        **_extra_params: Any,
    ) -> AgentToolResult:
        if ctx.session is None:
            return _tool_error(ctx, "feishu_tools", "缺少 Feishu 会话，无法渲染点选卡片")
        resolved_title = _resolve_choice_title(title=title, question=question)
        resolved_options = _resolve_options_spec(options_spec=options_spec, options=options)
        if not resolved_title:
            return _tool_error(ctx, "feishu_tools", "缺少问题标题，无法渲染点选卡片")
        if not resolved_options:
            return _tool_error(ctx, "feishu_tools", "缺少选项，无法渲染点选卡片")
        reply = await feishu.ask_single_choice(
            ctx.session,
            title=resolved_title,
            options_spec=resolved_options,
            phase=phase,
            value_prefix=value_prefix,
            summary=summary,
        )
        return _tool_success(ctx, "feishu_tools", "single_choice", {"reply": reply})

    async def ask_multi_select(
        ctx: AgentToolContext,
        *,
        options_spec: str = "",
        title: str = "",
        question: str = "",
        options: Any | None = None,
        phase: str = "clarify",
        input_name: str = "",
        input_placeholder: str = "",
        submit_label: str = "确认",
        summary: str | None = None,
        allow_custom_text: bool = False,
        custom_text_placeholder: str = "",
        **_extra_params: Any,
    ) -> AgentToolResult:
        if ctx.session is None:
            return _tool_error(ctx, "feishu_tools", "缺少 Feishu 会话，无法渲染多选卡片")
        resolved_title = _resolve_choice_title(title=title, question=question)
        resolved_options = _resolve_options_spec(options_spec=options_spec, options=options)
        if not resolved_title:
            return _tool_error(ctx, "feishu_tools", "缺少问题标题，无法渲染多选卡片")
        if not resolved_options:
            return _tool_error(ctx, "feishu_tools", "缺少选项，无法渲染多选卡片")
        resolved_input_name = input_name
        resolved_input_placeholder = input_placeholder
        if allow_custom_text:
            resolved_input_name = resolved_input_name or "custom_text"
            resolved_input_placeholder = (
                resolved_input_placeholder
                or custom_text_placeholder
                or "也可以补充其他要求"
            )
        reply = await feishu.ask_multi_select(
            ctx.session,
            title=resolved_title,
            options_spec=resolved_options,
            phase=phase,
            input_name=resolved_input_name,
            input_placeholder=resolved_input_placeholder,
            submit_label=submit_label,
            summary=summary,
        )
        return _tool_success(ctx, "feishu_tools", "multi_select", {"reply": reply})

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
            name="feishu_ask_single_choice",
            description="Ask the user to pick one option in Feishu using delimited options.",
            execute=ask_single_choice,
            category="feishu",
        )
    )
    registry.register(
        AgentTool(
            name="feishu_ask_multi_select",
            description=(
                "Ask the user to select one or more options in Feishu using "
                "delimited options formatted as label::value||label::value. "
                "Use this when missing constraints are easier to pick than type."
            ),
            execute=ask_multi_select,
            category="feishu",
        )
    )
    registry.register(
        AgentTool(
            name="feishu_send_progress",
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
        tool_name: str = "",
        params: dict[str, Any] | None = None,
        **extra_params: Any,
    ) -> AgentToolResult:
        resolved_tool_name = _resolve_background_tool_name(
            tool_name
            or str(extra_params.pop("task_type", "") or "")
            or str(extra_params.pop("route", "") or "")
            or str(extra_params.pop("content_type", "") or "")
        )
        resolved_params = dict(params or {})
        if extra_params:
            resolved_params.update(extra_params)
        current_user_text = _coerce_text(ctx.metadata.get("current_user_text"))
        if current_user_text:
            for key, value in _extract_runtime_aliases_from_text(current_user_text).items():
                resolved_params.setdefault(key, value)
        try:
            task_params = _normalize_background_task_params(
                resolved_tool_name,
                resolved_params,
            )
            task = task_manager.start_task(resolved_tool_name, ctx, params=task_params)
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

    async def cancel_background_agent_task(
        ctx: AgentToolContext,
        *,
        task_id: str,
    ) -> AgentToolResult:
        try:
            task = task_manager.cancel_task(task_id)
        except Exception as exc:
            return _tool_error(ctx, "agent_os_task_manager", str(exc))
        return _tool_success(
            ctx,
            "agent_os_task_manager",
            "cancel_background_agent_task",
            task.to_summary(),
        )

    registry.register(
        AgentTool(
            name="start_background_agent_task",
            description=(
                "Start a specialist Agent workflow in the background so the main "
                "Feishu chat can continue. Required params: tool_name or task_type, "
                "plus params.spec as a TaskRunSpec dict. At minimum params.spec "
                "must include objective; include route, topic, style_constraints, "
                "run_options.image.count, reference_images, and delivery.target='feishu' "
                "when the user provided them. Direct aliases such as objective, topic, "
                "style_constraints, image_count, research_max_items, skill, and prompt_template are accepted "
                "and normalized into params.spec."
            ),
            execute=start_background_agent_task,
            category="task",
        )
    )
    registry.register(
        AgentTool(
            name="cancel_background_agent_task",
            description="Cancel a running background Agent workflow by task_id.",
            execute=cancel_background_agent_task,
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


def _resolve_background_tool_name(value: str) -> str:
    normalized = value.strip()
    route_aliases = {
        "image": "execute_image_post",
        "image_post": "execute_image_post",
        "article": "execute_article_post",
        "article_post": "execute_article_post",
        "video": "execute_video_post",
        "video_post": "execute_video_post",
    }
    return route_aliases.get(normalized, normalized)


def _resolve_choice_title(*, title: str = "", question: str = "") -> str:
    return (title or question or "").strip()


def _resolve_options_spec(*, options_spec: str = "", options: Any | None = None) -> str:
    if options_spec.strip():
        return options_spec.strip()
    if options is None:
        return ""
    if isinstance(options, str):
        return options.strip()
    if isinstance(options, list | tuple | set):
        parts: list[str] = []
        for item in options:
            if isinstance(item, str):
                label = value = item.strip()
            elif isinstance(item, dict):
                label = _coerce_text(
                    item.get("label")
                    or item.get("text")
                    or item.get("name")
                    or item.get("title")
                    or item.get("value")
                )
                value = _coerce_text(
                    item.get("value")
                    or item.get("key")
                    or item.get("id")
                    or label
                )
            else:
                label = value = _coerce_text(item)
            if label and value:
                parts.append(f"{label}::{value}")
        return "||".join(parts)
    return ""


def _normalize_background_task_params(
    tool_name: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    if "spec" in params:
        spec_input = params["spec"]
    elif "task_spec" in params:
        spec_input = params["task_spec"]
    else:
        spec_input = _build_task_spec_from_direct_params(tool_name, params)

    if spec_input is None:
        raise ValueError(
            "start_background_agent_task requires params.spec TaskRunSpec or "
            "direct task details such as objective/topic/message."
        )

    spec_input = _lift_task_spec_aliases(spec_input, params)
    task_spec = TaskRunSpec.model_validate(spec_input)
    if task_spec.route is None:
        route = _route_from_background_tool_name(tool_name)
        if route:
            task_spec = TaskRunSpec.model_validate(
                {**task_spec.model_dump(mode="python"), "route": route}
            )

    normalized: dict[str, Any] = {"spec": task_spec.model_dump(mode="json")}
    for key in (
        "skill",
        "selected_skill",
        "prompt_template",
        "selected_prompt_template",
        "template",
    ):
        if key in params:
            normalized[key] = params[key]
    return normalized


def _build_task_spec_from_direct_params(
    tool_name: str,
    params: dict[str, Any],
) -> dict[str, Any] | None:
    objective = _first_present_text(
        params,
        "objective",
        "task",
        "request",
        "message",
        "user_request",
        "summary",
        "topic",
        "title",
    )
    if not objective:
        return None

    spec: dict[str, Any] = {
        "objective": objective,
        "route": _route_from_background_tool_name(tool_name),
        "delivery": {"target": "feishu"},
    }
    for field_name in ("topic", "audience"):
        value = _coerce_text(params.get(field_name))
        if value:
            spec[field_name] = value

    constraints = _coerce_text_list(params.get("constraints") or params.get("requirements"))
    if constraints:
        spec["constraints"] = constraints

    style_constraints = _coerce_text_list(
        params.get("style_constraints")
        or params.get("styles")
        or params.get("style")
        or params.get("visual_constraints")
    )
    if style_constraints:
        spec["style_constraints"] = style_constraints

    selected_skills = _coerce_text_list(params.get("selected_skills") or params.get("skill"))
    if selected_skills:
        spec["selected_skills"] = selected_skills

    selected_prompt_templates = _coerce_text_list(
        params.get("selected_prompt_templates")
        or params.get("prompt_template")
        or params.get("template")
    )
    if selected_prompt_templates:
        spec["selected_prompt_templates"] = selected_prompt_templates

    reference_images = params.get("reference_images")
    if reference_images:
        spec["reference_images"] = reference_images

    run_options = params.get("run_options")
    if isinstance(run_options, dict):
        spec["run_options"] = dict(run_options)
    else:
        spec["run_options"] = {}

    image_count = params.get("image_count") or params.get("count") or params.get("num_images")
    if image_count is not None:
        spec["run_options"].setdefault("image", {})["count"] = image_count

    image_model = params.get("image_model") or params.get("model")
    if image_model:
        spec["run_options"].setdefault("image", {})["model"] = image_model

    research_max_items = (
        params.get("research_max_items")
        or params.get("max_research_items")
        or params.get("research_count")
        or params.get("max_items")
        or params.get("min_posts_researched")
    )
    if research_max_items is not None:
        spec["run_options"].setdefault("research", {})["max_items"] = research_max_items

    return spec


def _lift_task_spec_aliases(spec_input: Any, outer_params: dict[str, Any]) -> Any:
    if not isinstance(spec_input, dict):
        return spec_input
    spec = dict(spec_input)
    for source in (spec_input, outer_params):
        _lift_runtime_aliases_into_spec(spec, source)
    return spec


def _lift_runtime_aliases_into_spec(spec: dict[str, Any], source: dict[str, Any]) -> None:
    run_options = spec.get("run_options")
    if isinstance(run_options, dict):
        normalized_run_options = dict(run_options)
    elif run_options is None:
        normalized_run_options = {}
    else:
        return

    image_count = _first_present_value(source, "image_count", "count", "num_images")
    if image_count is not None:
        normalized_run_options.setdefault("image", {}).setdefault("count", image_count)

    image_model = _first_present_value(source, "image_model", "model")
    if image_model:
        normalized_run_options.setdefault("image", {}).setdefault("model", image_model)

    image_generation_concurrency = _first_present_value(
        source,
        "image_generation_concurrency",
        "image_concurrency",
        "concurrency",
    )
    if image_generation_concurrency is not None:
        normalized_run_options.setdefault("image", {}).setdefault(
            "concurrency",
            image_generation_concurrency,
        )

    research_max_items = _first_present_value(
        source,
        "research_max_items",
        "max_research_items",
        "research_count",
        "max_items",
        "min_posts_researched",
    )
    if research_max_items is not None:
        normalized_run_options.setdefault("research", {}).setdefault("max_items", research_max_items)

    if normalized_run_options:
        spec["run_options"] = normalized_run_options


def _extract_runtime_aliases_from_text(text: str) -> dict[str, int]:
    aliases: dict[str, int] = {}
    patterns = {
        "image_count": [
            r"(?:图片数量|图片数|image_count|num_images|count)\s*[=:：]\s*(\d+)",
            r"(\d+)\s*张图",
        ],
        "research_max_items": [
            r"(?:research_max_items|max_research_items|research_count|max_items|min_posts_researched)\s*[=:：]\s*(\d+)",
        ],
        "image_generation_concurrency": [
            r"(?:image_generation_concurrency|image_concurrency|concurrency)\s*[=:：]\s*(\d+)",
        ],
    }
    for key, key_patterns in patterns.items():
        for pattern in key_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                aliases[key] = int(match.group(1))
                break
    return aliases


def _route_from_background_tool_name(tool_name: str) -> str | None:
    route_by_tool = {
        "execute_image_post": "image_post",
        "execute_article_post": "article_post",
        "execute_video_post": "video_post",
    }
    return route_by_tool.get(tool_name)


def _first_present_text(params: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _coerce_text(params.get(key))
        if value:
            return value
    return ""


def _first_present_value(params: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in params and params[key] is not None and params[key] != "":
            return params[key]
    return None


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _coerce_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        separators = ["\n", "；", ";", "|"]
        values = [value]
        for separator in separators:
            values = [
                part
                for item in values
                for part in item.split(separator)
            ]
        return [item.strip() for item in values if item.strip()]
    if isinstance(value, list | tuple | set):
        return [text for item in value if (text := _coerce_text(item))]
    return []


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
