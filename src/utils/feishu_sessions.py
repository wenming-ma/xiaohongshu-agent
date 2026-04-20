from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from filelock import FileLock
from pydantic import BaseModel

from ..config.settings import PathConfig
from .logger import get_logger

logger = get_logger(__name__)


ACTIVE_SESSION_STATUSES = {"active", "takeover_pending"}
TERMINAL_SESSION_STATUSES = {"revoked", "cancelled", "completed"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_filename(chat_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in chat_id)


class SessionOwnershipError(RuntimeError):
    """Base error for lost session ownership."""


class SessionRevokedError(SessionOwnershipError):
    """Raised when a session has been replaced by another workflow run."""


class SessionExpiredError(SessionOwnershipError):
    """Raised when a session heartbeat has gone stale."""


class SessionInactiveError(SessionOwnershipError):
    """Raised when a session is no longer active."""


class FeishuChatSessionState(BaseModel):
    session_id: str
    chat_id: str
    workflow: str
    status: Literal["active", "takeover_pending", "revoked", "cancelled", "completed", "expired"]
    owner_pid: int
    started_at: str
    heartbeat_at: str
    current_phase: str
    summary: str
    challenger_session_id: str | None = None
    challenger_workflow: str | None = None
    challenger_owner_pid: int | None = None
    challenger_started_at: str | None = None
    challenger_current_phase: str | None = None
    challenger_summary: str | None = None
    conflict_message_id: str | None = None


@dataclass(frozen=True)
class FeishuSessionHandle:
    session_id: str
    chat_id: str
    workflow: str


@dataclass(frozen=True)
class SessionAcquireResult:
    outcome: Literal["acquired", "blocked"]
    reason: Literal["available", "active_session", "expired_session", "challenger_pending"]
    session: FeishuSessionHandle
    state: FeishuChatSessionState


@dataclass(frozen=True)
class SessionWaitResult:
    outcome: Literal["acquired", "continue_existing", "timeout"]
    state: FeishuChatSessionState | None


class FeishuSessionManager:
    def __init__(
        self,
        state_dir: str | Path | None = None,
        *,
        stale_after_seconds: int = 15 * 60,
    ) -> None:
        self.state_dir = Path(state_dir or PathConfig.FEISHU_SESSION_DIR)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.stale_after_seconds = stale_after_seconds

    def _state_path(self, chat_id: str) -> Path:
        return self.state_dir / f"{_safe_filename(chat_id)}.json"

    def _lock_path(self, chat_id: str) -> Path:
        return self.state_dir / f"{_safe_filename(chat_id)}.lock"

    def _read_state_unlocked(self, chat_id: str) -> FeishuChatSessionState | None:
        path = self._state_path(chat_id)
        if not path.exists():
            return None
        try:
            return FeishuChatSessionState.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("读取 Feishu 会话状态失败: %s", path, exc_info=True)
            return None

    def _write_state_unlocked(self, chat_id: str, state: FeishuChatSessionState) -> FeishuChatSessionState:
        path = self._state_path(chat_id)
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        return state

    def _clear_challenger(self, state: FeishuChatSessionState) -> FeishuChatSessionState:
        state.challenger_session_id = None
        state.challenger_workflow = None
        state.challenger_owner_pid = None
        state.challenger_started_at = None
        state.challenger_current_phase = None
        state.challenger_summary = None
        state.conflict_message_id = None
        return state

    def _promote_challenger(self, state: FeishuChatSessionState) -> FeishuChatSessionState:
        if not state.challenger_session_id or not state.challenger_workflow:
            raise SessionInactiveError("missing challenger session")
        now = _utcnow().isoformat()
        state.session_id = state.challenger_session_id
        state.workflow = state.challenger_workflow
        state.owner_pid = state.challenger_owner_pid or state.owner_pid
        state.started_at = state.challenger_started_at or now
        state.heartbeat_at = now
        state.current_phase = state.challenger_current_phase or "startup"
        state.summary = state.challenger_summary or state.summary
        state.status = "active"
        return self._clear_challenger(state)

    def _is_stale(self, state: FeishuChatSessionState) -> bool:
        try:
            heartbeat_at = datetime.fromisoformat(state.heartbeat_at)
        except ValueError:
            return True
        if heartbeat_at.tzinfo is None:
            heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
        return (_utcnow() - heartbeat_at).total_seconds() > self.stale_after_seconds

    def _build_active_state(
        self,
        *,
        handle: FeishuSessionHandle,
        owner_pid: int,
        current_phase: str,
        summary: str,
    ) -> FeishuChatSessionState:
        now = _utcnow().isoformat()
        return FeishuChatSessionState(
            session_id=handle.session_id,
            chat_id=handle.chat_id,
            workflow=handle.workflow,
            status="active",
            owner_pid=owner_pid,
            started_at=now,
            heartbeat_at=now,
            current_phase=current_phase,
            summary=summary,
        )

    def get_state(self, chat_id: str) -> FeishuChatSessionState | None:
        lock = FileLock(str(self._lock_path(chat_id)))
        with lock:
            state = self._read_state_unlocked(chat_id)
            if state is None:
                return None
            if state.status == "active" and self._is_stale(state):
                state.status = "expired"
                self._write_state_unlocked(chat_id, state)
            return state

    def get_routing_state(self, chat_id: str) -> FeishuChatSessionState | None:
        state = self.get_state(chat_id)
        if state is None:
            return None
        if state.status not in ACTIVE_SESSION_STATUSES:
            return None
        if self._is_stale(state):
            return None
        return state

    def acquire(
        self,
        *,
        chat_id: str,
        workflow: str,
        owner_pid: int | None = None,
        current_phase: str = "startup",
        summary: str = "",
    ) -> SessionAcquireResult:
        handle = FeishuSessionHandle(
            session_id=uuid.uuid4().hex,
            chat_id=chat_id,
            workflow=workflow,
        )
        owner_pid = owner_pid or os.getpid()
        lock = FileLock(str(self._lock_path(chat_id)))
        with lock:
            state = self._read_state_unlocked(chat_id)
            if state is None or state.status in TERMINAL_SESSION_STATUSES:
                state = self._build_active_state(
                    handle=handle,
                    owner_pid=owner_pid,
                    current_phase=current_phase,
                    summary=summary,
                )
                self._write_state_unlocked(chat_id, state)
                return SessionAcquireResult("acquired", "available", handle, state)

            stale = self._is_stale(state)
            if stale and state.status == "active":
                state.status = "expired"

            if state.status == "takeover_pending" and state.challenger_session_id and state.challenger_session_id != handle.session_id:
                self._write_state_unlocked(chat_id, state)
                return SessionAcquireResult("blocked", "challenger_pending", handle, state)

            state.status = "takeover_pending"
            state.challenger_session_id = handle.session_id
            state.challenger_workflow = handle.workflow
            state.challenger_owner_pid = owner_pid
            state.challenger_started_at = _utcnow().isoformat()
            state.challenger_current_phase = current_phase
            state.challenger_summary = summary
            self._write_state_unlocked(chat_id, state)
            reason: Literal["active_session", "expired_session"] = "expired_session" if stale or state.status == "expired" else "active_session"
            return SessionAcquireResult("blocked", reason, handle, state)

    def resolve_challenger(
        self,
        *,
        chat_id: str,
        challenger_session_id: str,
        action: Literal["continue_existing", "takeover"],
    ) -> FeishuChatSessionState:
        lock = FileLock(str(self._lock_path(chat_id)))
        with lock:
            state = self._read_state_unlocked(chat_id)
            if state is None:
                raise SessionInactiveError("session state not found")
            if state.challenger_session_id != challenger_session_id:
                return state
            if action == "continue_existing":
                state = self._clear_challenger(state)
                state.status = "expired" if self._is_stale(state) else "active"
            elif action == "takeover":
                state = self._promote_challenger(state)
            else:
                raise ValueError(f"unknown action: {action}")
            return self._write_state_unlocked(chat_id, state)

    def assert_active(self, handle: FeishuSessionHandle) -> FeishuChatSessionState:
        lock = FileLock(str(self._lock_path(handle.chat_id)))
        with lock:
            state = self._read_state_unlocked(handle.chat_id)
            if state is None:
                raise SessionInactiveError("session state not found")
            if state.session_id != handle.session_id:
                raise SessionRevokedError(f"session {handle.session_id} revoked by another run")
            if self._is_stale(state):
                state.status = "expired"
                self._write_state_unlocked(handle.chat_id, state)
                raise SessionExpiredError(f"session {handle.session_id} expired")
            if state.status not in ACTIVE_SESSION_STATUSES:
                raise SessionInactiveError(f"session {handle.session_id} is {state.status}")
            return state

    def heartbeat(
        self,
        handle: FeishuSessionHandle,
        *,
        current_phase: str | None = None,
        summary: str | None = None,
    ) -> FeishuChatSessionState:
        lock = FileLock(str(self._lock_path(handle.chat_id)))
        with lock:
            state = self._read_state_unlocked(handle.chat_id)
            if state is None:
                raise SessionInactiveError("session state not found")
            if state.session_id != handle.session_id:
                raise SessionRevokedError(f"session {handle.session_id} revoked by another run")
            if self._is_stale(state):
                state.status = "expired"
                self._write_state_unlocked(handle.chat_id, state)
                raise SessionExpiredError(f"session {handle.session_id} expired")
            if state.status not in ACTIVE_SESSION_STATUSES:
                raise SessionInactiveError(f"session {handle.session_id} is {state.status}")
            state.heartbeat_at = _utcnow().isoformat()
            if current_phase is not None:
                state.current_phase = current_phase
            if summary is not None:
                state.summary = summary
            return self._write_state_unlocked(handle.chat_id, state)

    def release(
        self,
        handle: FeishuSessionHandle,
        *,
        status: Literal["completed", "cancelled"] = "completed",
    ) -> FeishuChatSessionState | None:
        lock = FileLock(str(self._lock_path(handle.chat_id)))
        with lock:
            state = self._read_state_unlocked(handle.chat_id)
            if state is None:
                return None

            if state.session_id == handle.session_id:
                if state.challenger_session_id:
                    state = self._promote_challenger(state)
                else:
                    state.status = status
                    state.heartbeat_at = _utcnow().isoformat()
                    state.current_phase = status
                return self._write_state_unlocked(handle.chat_id, state)

            if state.challenger_session_id == handle.session_id:
                state = self._clear_challenger(state)
                state.status = "expired" if self._is_stale(state) else "active"
                return self._write_state_unlocked(handle.chat_id, state)

            return state


class FeishuWorkflowSession:
    def __init__(
        self,
        manager: FeishuSessionManager,
        handle: FeishuSessionHandle,
        *,
        current_phase: str,
        summary: str = "",
        heartbeat_interval_seconds: int = 30,
    ) -> None:
        self.manager = manager
        self.handle = handle
        self.chat_id = handle.chat_id
        self.workflow = handle.workflow
        self.current_phase = current_phase
        self.summary = summary
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._ownership_error: SessionOwnershipError | None = None

    async def start(self) -> "FeishuWorkflowSession":
        self.manager.heartbeat(
            self.handle,
            current_phase=self.current_phase,
            summary=self.summary,
        )
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        return self

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval_seconds)
                self.manager.heartbeat(
                    self.handle,
                    current_phase=self.current_phase,
                    summary=self.summary,
                )
            except asyncio.CancelledError:
                raise
            except SessionOwnershipError as exc:
                self._ownership_error = exc
                logger.info("Feishu workflow session lost ownership: %s", exc)
                return

    async def ensure_active(self) -> FeishuChatSessionState:
        if self._ownership_error is not None:
            raise self._ownership_error
        return self.manager.assert_active(self.handle)

    async def update_phase(self, phase: str, *, summary: str | None = None) -> FeishuChatSessionState:
        self.current_phase = phase
        if summary is not None:
            self.summary = summary
        return self.manager.heartbeat(
            self.handle,
            current_phase=self.current_phase,
            summary=self.summary,
        )

    async def finish(self, *, status: Literal["completed", "cancelled"] = "completed") -> FeishuChatSessionState | None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        return self.manager.release(self.handle, status=status)


_manager: Optional[FeishuSessionManager] = None


def get_feishu_session_manager() -> FeishuSessionManager:
    global _manager
    if _manager is None:
        _manager = FeishuSessionManager()
    return _manager


async def wait_for_session_activation(
    manager: FeishuSessionManager,
    handle: FeishuSessionHandle,
    *,
    timeout_seconds: int = 5 * 60,
    poll_interval_seconds: float = 1.0,
) -> SessionWaitResult:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        state = manager.get_state(handle.chat_id)
        if state is None:
            return SessionWaitResult("timeout", None)
        if state.session_id == handle.session_id and state.status == "active":
            return SessionWaitResult("acquired", state)
        if state.challenger_session_id == handle.session_id:
            await asyncio.sleep(poll_interval_seconds)
            continue
        return SessionWaitResult("continue_existing", state)
    return SessionWaitResult("timeout", manager.get_state(handle.chat_id))
