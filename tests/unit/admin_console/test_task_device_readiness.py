# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.admin_console.routers import tasks
from apps.admin_console.schemas.task_schema import RunRequest
from artemis.core.diagnostics.schema import (
    ProbeCategory,
    ProbeResult,
    ProbeStatus,
)


@pytest.mark.parametrize("lock_state", [True, None, False])
@pytest.mark.asyncio
async def test_connected_target_is_queued_regardless_of_lock_state(monkeypatch, tmp_path, lock_state):
    queue_state = importlib.import_module(tasks.task_queue_service.__module__).state
    monkeypatch.setattr(tasks, "state", queue_state)
    monkeypatch.setattr(queue_state, "queue_items", [])
    monkeypatch.setattr(queue_state, "active_runs", {})
    monkeypatch.setattr(queue_state, "current_process", None)
    monkeypatch.setattr(queue_state, "_wake_event", asyncio.Event())
    monkeypatch.setattr(tasks.task_queue_service, "ensure_worker_running", lambda: None)
    monkeypatch.setattr(
        "artemis.runtime.device_lock.get_temp_dir", lambda _subfolder=None: tmp_path
    )
    monkeypatch.setattr(
        tasks.device_pool,
        "try_list_devices_async",
        AsyncMock(return_value=[SimpleNamespace(serial="target", state="device")]),
    )
    device_probe = ProbeResult(
        id="android_adb",
        category=ProbeCategory.DEVICE,
        title="Device / Emulator Connected",
        status=ProbeStatus.PASS if lock_state is False else ProbeStatus.WARN,
        is_blocker=lock_state is False,
        summary="Connected" if lock_state is False else "Device Locked" if lock_state else "Lock State Unknown",
        description="Task execution verifies the lock screen.",
        metadata={"active_device": {"serial": "target", "is_locked": lock_state}},
    )
    monkeypatch.setattr(
        tasks.readiness_engine,
        "run_device_submission_probe",
        AsyncMock(return_value=device_probe),
    )

    result = await tasks.run_task(RunRequest(goal="Open Settings", device_serial="target"))

    assert result["status"] == "started"
    assert result["enqueued_count"] == 1
    assert queue_state.queue_items[0]["status"] == "pending"
    assert queue_state.queue_items[0]["device_serial"] == "target"
    assert queue_state.queue_items[0]["goal"] == "Open Settings"
    assert queue_state.wake_event.is_set()


@pytest.mark.asyncio
async def test_idempotent_retry_skips_device_probe_for_active_session(monkeypatch):
    run_probe = AsyncMock()
    monkeypatch.setattr(tasks.readiness_engine, "run_device_submission_probe", run_probe)
    monkeypatch.setattr(tasks.state, "active_session_id", "sdk-task-1")
    monkeypatch.setattr(tasks.state, "active_connections", {})
    monkeypatch.setattr(
        tasks.session_repo,
        "get_session_by_id",
        lambda session_id: None,
    )

    result = await tasks.run_task(
        RunRequest(
            goal="Open Settings",
            session_id="sdk-task-1",
            device_serial="pixel-10",
            ingress="python_sdk",
        )
    )

    assert result["status"] == "running"
    assert result["enqueued_count"] == 0
    assert result["tasks"][0]["session_id"] == "sdk-task-1"
    run_probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_explicit_device_is_rejected_before_readiness_probe(monkeypatch):
    run_probe = AsyncMock()
    monkeypatch.setattr(tasks.readiness_engine, "run_device_submission_probe", run_probe)
    monkeypatch.setattr(tasks.state, "active_session_id", None)
    monkeypatch.setattr(tasks.state, "active_connections", {})
    monkeypatch.setattr(tasks.state, "queue_items", [])
    monkeypatch.setattr(tasks.session_repo, "get_session_by_id", lambda session_id: None)
    monkeypatch.setattr(
        tasks.device_pool,
        "try_list_devices_async",
        AsyncMock(
            return_value=[
                SimpleNamespace(serial="pixel-10", state="device"),
            ]
        ),
    )

    result = await tasks.run_task(
        RunRequest(
            goal="Must not run",
            device_serial="missing-device",
            session_id="00000000-0000-4000-8000-000000000099",
        )
    )

    assert result["status"] == "rejected"
    assert result["tasks"] == []
    assert "not connected" in result["error"]
    run_probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_device_is_rejected_when_attached_but_not_ready(monkeypatch):
    run_probe = AsyncMock()
    monkeypatch.setattr(tasks.readiness_engine, "run_device_submission_probe", run_probe)
    monkeypatch.setattr(tasks.state, "active_session_id", None)
    monkeypatch.setattr(tasks.state, "active_connections", {})
    monkeypatch.setattr(tasks.state, "queue_items", [])
    monkeypatch.setattr(tasks.session_repo, "get_session_by_id", lambda session_id: None)
    monkeypatch.setattr(
        tasks.device_pool,
        "try_list_devices_async",
        AsyncMock(
            return_value=[
                SimpleNamespace(serial="pixel-10", state="unauthorized"),
            ]
        ),
    )

    result = await tasks.run_task(
        RunRequest(
            goal="Must not run",
            device_serial="pixel-10",
            session_id="00000000-0000-4000-8000-000000000100",
        )
    )

    assert result["status"] == "rejected"
    assert "unauthorized" in result["error"]
    run_probe.assert_not_awaited()


@pytest.mark.parametrize("enumeration", [None, []])
@pytest.mark.asyncio
async def test_explicit_device_proceeds_when_enumeration_is_indeterminate(monkeypatch, enumeration):
    """A failed (None) or empty enumeration must never hard-reject an explicit
    serial: the submission queues and fails downstream if the device is truly
    absent. This is the startup-storm regression guard."""
    run_probe = AsyncMock(return_value=None)
    enqueue_tasks = AsyncMock(return_value={"status": "queued", "tasks": []})
    monkeypatch.setattr(tasks.readiness_engine, "run_device_submission_probe", run_probe)
    monkeypatch.setattr(tasks.task_queue_service, "enqueue_tasks", enqueue_tasks)
    monkeypatch.setattr(tasks.state, "active_session_id", None)
    monkeypatch.setattr(tasks.state, "active_connections", {})
    monkeypatch.setattr(tasks.state, "queue_items", [])
    monkeypatch.setattr(tasks.session_repo, "get_session_by_id", lambda session_id: None)
    monkeypatch.setattr(
        tasks.device_pool,
        "try_list_devices_async",
        AsyncMock(return_value=enumeration),
    )

    result = await tasks.run_task(
        RunRequest(
            goal="Queue through the startup storm",
            device_serial="pixel-10",
            session_id="00000000-0000-4000-8000-000000000101",
        )
    )

    assert result["status"] == "queued"
    enqueue_tasks.assert_awaited_once()
    _, kwargs = enqueue_tasks.call_args
    assert kwargs.get("device_serial") == "pixel-10"
