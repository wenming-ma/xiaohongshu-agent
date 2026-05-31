from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from src.utils.feishu_sessions import (
    FeishuSessionManager,
    SessionRevokedError,
    wait_for_session_activation,
)


def test_session_manager_blocks_second_session_until_takeover(tmp_path):
    manager = FeishuSessionManager(state_dir=tmp_path, stale_after_seconds=900, owner_liveness_check=False)

    first = manager.acquire(
        chat_id="chat-1",
        workflow="image_post",
        owner_pid=1001,
        current_phase="research",
        summary="first run",
    )
    second = manager.acquire(
        chat_id="chat-1",
        workflow="article_post",
        owner_pid=1002,
        current_phase="content",
        summary="second run",
    )

    assert first.outcome == "acquired"
    assert second.outcome == "blocked"
    assert second.reason == "active_session"

    state = manager.get_state("chat-1")
    assert state is not None
    assert state.status == "takeover_pending"
    assert state.session_id == first.session.session_id
    assert state.challenger_session_id == second.session.session_id


def test_session_manager_takeover_promotes_challenger_and_revokes_old_session(tmp_path):
    manager = FeishuSessionManager(state_dir=tmp_path, stale_after_seconds=900, owner_liveness_check=False)

    first = manager.acquire(
        chat_id="chat-1",
        workflow="image_post",
        owner_pid=1001,
        current_phase="research",
        summary="first run",
    )
    second = manager.acquire(
        chat_id="chat-1",
        workflow="article_post",
        owner_pid=1002,
        current_phase="content",
        summary="second run",
    )

    manager.resolve_challenger(
        chat_id="chat-1",
        challenger_session_id=second.session.session_id,
        action="takeover",
    )

    state = manager.assert_active(second.session)
    assert state.workflow == "article_post"
    assert state.session_id == second.session.session_id
    assert state.status == "active"
    assert state.challenger_session_id is None

    with pytest.raises(SessionRevokedError):
        manager.assert_active(first.session)


def test_session_manager_continue_existing_clears_pending_challenger(tmp_path):
    manager = FeishuSessionManager(state_dir=tmp_path, stale_after_seconds=900, owner_liveness_check=False)

    first = manager.acquire(
        chat_id="chat-1",
        workflow="image_post",
        owner_pid=1001,
        current_phase="research",
        summary="first run",
    )
    second = manager.acquire(
        chat_id="chat-1",
        workflow="article_post",
        owner_pid=1002,
        current_phase="content",
        summary="second run",
    )

    manager.resolve_challenger(
        chat_id="chat-1",
        challenger_session_id=second.session.session_id,
        action="continue_existing",
    )

    state = manager.assert_active(first.session)
    assert state.status == "active"
    assert state.session_id == first.session.session_id
    assert state.challenger_session_id is None


def test_session_manager_reclaims_stale_active_session(tmp_path):
    manager = FeishuSessionManager(state_dir=tmp_path, stale_after_seconds=900, owner_liveness_check=False)

    manager.acquire(
        chat_id="chat-1",
        workflow="image_post",
        owner_pid=1001,
        current_phase="research",
        summary="first run",
    )

    state_path = manager._state_path("chat-1")
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["heartbeat_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=31)
    ).isoformat()
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    second = manager.acquire(
        chat_id="chat-1",
        workflow="article_post",
        owner_pid=1002,
        current_phase="content",
        summary="second run",
    )

    assert second.outcome == "acquired"
    assert second.reason == "expired_session"

    state = manager.assert_active(second.session)
    assert state.workflow == "article_post"
    assert state.session_id == second.session.session_id
    assert state.challenger_session_id is None


def test_session_manager_reclaims_abandoned_owner_pid(tmp_path, monkeypatch):
    manager = FeishuSessionManager(state_dir=tmp_path, stale_after_seconds=900)
    monkeypatch.setattr(manager, "_owner_process_alive", lambda pid: pid == os.getpid())

    first = manager.acquire(
        chat_id="chat-1",
        workflow="image_post",
        owner_pid=999999,
        current_phase="research",
        summary="orphaned run",
    )
    second = manager.acquire(
        chat_id="chat-1",
        workflow="feishu_orchestrator",
        owner_pid=os.getpid(),
        current_phase="startup",
        summary="new run",
    )

    assert first.outcome == "acquired"
    assert second.outcome == "acquired"
    assert second.reason == "expired_session"

    state = manager.assert_active(second.session)
    assert state.workflow == "feishu_orchestrator"
    assert state.session_id == second.session.session_id
    assert state.challenger_session_id is None


def test_session_manager_reclaims_stale_takeover_pending_session(tmp_path):
    manager = FeishuSessionManager(state_dir=tmp_path, stale_after_seconds=900, owner_liveness_check=False)

    first = manager.acquire(
        chat_id="chat-1",
        workflow="image_post",
        owner_pid=1001,
        current_phase="research",
        summary="first run",
    )
    manager.acquire(
        chat_id="chat-1",
        workflow="feishu_orchestrator",
        owner_pid=1002,
        current_phase="startup",
        summary="stale challenger",
    )

    state_path = manager._state_path("chat-1")
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["heartbeat_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=31)
    ).isoformat()
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    recovered = manager.acquire(
        chat_id="chat-1",
        workflow="feishu_orchestrator",
        owner_pid=1003,
        current_phase="startup",
        summary="new run",
    )

    assert first.outcome == "acquired"
    assert recovered.outcome == "acquired"
    assert recovered.reason == "expired_session"

    state = manager.assert_active(recovered.session)
    assert state.workflow == "feishu_orchestrator"
    assert state.session_id == recovered.session.session_id
    assert state.challenger_session_id is None


@pytest.mark.anyio
async def test_waiting_challenger_auto_promotes_when_active_owner_dies(tmp_path, monkeypatch):
    manager = FeishuSessionManager(state_dir=tmp_path, stale_after_seconds=900)
    alive_pids = {1001, 1002}
    monkeypatch.setattr(manager, "_owner_process_alive", lambda pid: pid in alive_pids)

    first = manager.acquire(
        chat_id="chat-1",
        workflow="image_post",
        owner_pid=1001,
        current_phase="research",
        summary="first run",
    )
    second = manager.acquire(
        chat_id="chat-1",
        workflow="feishu_orchestrator",
        owner_pid=1002,
        current_phase="startup",
        summary="new request",
    )

    assert first.outcome == "acquired"
    assert second.outcome == "blocked"
    assert second.reason == "active_session"

    alive_pids.remove(1001)
    wait_result = await wait_for_session_activation(
        manager,
        second.session,
        timeout_seconds=1,
        poll_interval_seconds=0.01,
    )

    assert wait_result.outcome == "acquired"
    state = manager.assert_active(second.session)
    assert state.session_id == second.session.session_id
    assert state.owner_pid == 1002
    assert state.status == "active"
    assert state.challenger_session_id is None
