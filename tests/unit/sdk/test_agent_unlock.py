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
import threading

from types import SimpleNamespace

import pytest

from artemis.sdk.agent import Agent
from third_party.mobile_use.sdk.types.exceptions import AgentError


class StatefulDevice:
    def __init__(self, *, locked=True, secure=False, current_id=0, marker=True, settle_reads=0):
        self.locked = locked
        self.secure = secure
        self.current_id = current_id
        self.marker = marker
        self.settle_reads = settle_reads
        self.trust_secure = True
        self.initial_unknown = False
        self.commands = []
        self.woken = False
        self.dismissed = False
        self.policy_reads_after_dismiss = 0
        self.error_command = None
        self.error = None
        self.unknown = False

    def open_transport(self, *, timeout):
        return DeviceTransport(self, timeout)

    def shell(self, command, *, timeout):
        assert 0 < timeout <= 2
        self.commands.append(command)
        if command == self.error_command:
            raise self.error
        if command == "dumpsys window policy":
            if self.dismissed:
                self.policy_reads_after_dismiss += 1
                if self.policy_reads_after_dismiss > self.settle_reads:
                    self.locked = False
            if self.unknown or (self.initial_unknown and not self.woken):
                return ""
            return (
                "KeyguardServiceDelegate\n"
                f"  showing={str(self.locked).lower()}\n"
                f"  secure={str(self.secure).lower()}\n"
            )
        if command == "dumpsys trust":
            if self.unknown or (self.initial_unknown and not self.woken):
                return ""
            owner_id = self.current_id
            other_id = 10 if owner_id == 0 else 0
            suffix = " (current)" if self.marker else ""
            owner_secure = f" deviceSecure={int(self.secure)}" if self.trust_secure else ""
            return (
                f'User "Work" (id={other_id}, flags=0x20): deviceLocked=1 deviceSecure=1\n'
                f'User "Owner" (id={owner_id}, flags=0xc13){suffix}: '
                f'deviceLocked={int(self.locked)}{owner_secure}\n'
            )
        if command == "am get-current-user":
            return str(self.current_id)
        if command == "input keyevent KEYCODE_WAKEUP":
            self.woken = True
            return ""
        if command == "wm dismiss-keyguard":
            assert self.woken and not self.secure
            self.dismissed = True
            return ""
        raise AssertionError(f"Unexpected shell command: {command}")


class DeviceTransport:
    def __init__(self, device, timeout):
        self.device = device
        self.timeout = timeout
        self.command = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def send_command(self, command):
        assert command.startswith("shell:")
        self.command = command.removeprefix("shell:")

    def check_okay(self):
        assert self.command is not None

    def read_until_close(self):
        return self.device.shell(self.command, timeout=self.timeout)


class TargetedADB:
    def __init__(self, device):
        self.target = device
        self.serials = []

    def device(self, *, serial):
        self.serials.append(serial)
        if serial != "target-serial":
            raise AssertionError(f"Unexpected device serial: {serial}")
        return self.target


def make_agent(device):
    agent = object.__new__(Agent)
    agent._device_context = SimpleNamespace(device_id="target-serial")
    agent._session_id = "session-123"
    agent._adb_client = TargetedADB(device)
    return agent


def fast_deadline(monkeypatch):
    # Advance the unlock polling clock independently of asyncio's event-loop clock.
    from artemis.sdk import agent as agent_module

    clock = iter(range(0, 100, 4))
    monkeypatch.setattr(agent_module, "time", SimpleNamespace(monotonic=lambda: next(clock)))


@pytest.mark.asyncio
async def test_screen_off_swipe_lock_wakes_and_dismisses_after_animation():
    device = StatefulDevice(settle_reads=2)
    agent = make_agent(device)

    await agent._ensure_device_unlocked()

    assert device.commands.count("input keyevent KEYCODE_WAKEUP") == 1
    assert device.commands.count("wm dismiss-keyguard") == 1
    assert device.policy_reads_after_dismiss >= 3
    assert device.locked is False
    assert agent._adb_client.serials == ["target-serial"]


@pytest.mark.asyncio
async def test_unknown_state_before_wake_then_nonsecure_lock_can_be_dismissed():
    device = StatefulDevice()
    device.initial_unknown = True
    agent = make_agent(device)

    await agent._ensure_device_unlocked()

    assert device.commands.count("input keyevent KEYCODE_WAKEUP") == 1
    assert device.commands.count("wm dismiss-keyguard") == 1
    assert device.locked is False


@pytest.mark.asyncio
async def test_already_unlocked_secure_device_does_not_mutate_keyguard():
    device = StatefulDevice(locked=False, secure=True)
    agent = make_agent(device)

    await agent._ensure_device_unlocked()

    assert all(command.startswith(("dumpsys ", "am get-current-user")) for command in device.commands)
    assert agent._adb_client.serials == ["target-serial"]


@pytest.mark.asyncio
async def test_current_user_selected_by_id_when_trust_has_no_current_marker():
    device = StatefulDevice(locked=False, secure=False, current_id=10, marker=False)
    agent = make_agent(device)

    await agent._ensure_device_unlocked()

    assert all(command.startswith(("dumpsys ", "am get-current-user")) for command in device.commands)
    assert agent._adb_client.serials == ["target-serial"]


@pytest.mark.asyncio
async def test_secure_keyguard_requires_manual_pin_password_or_pattern(monkeypatch):
    fast_deadline(monkeypatch)
    device = StatefulDevice(secure=True, marker=False)
    agent = make_agent(device)

    with pytest.raises(AgentError, match="PIN, password, or pattern requires manual unlock"):
        await agent._ensure_device_unlocked()

    assert "input keyevent KEYCODE_WAKEUP" in device.commands
    assert "wm dismiss-keyguard" not in device.commands
    assert "am get-current-user" in device.commands
    assert agent._adb_client.serials == ["target-serial"]


@pytest.mark.asyncio
async def test_policy_secure_field_prevents_dismiss_when_trust_omits_device_secure(monkeypatch):
    fast_deadline(monkeypatch)
    device = StatefulDevice(secure=True)
    device.trust_secure = False
    agent = make_agent(device)

    with pytest.raises(AgentError, match="manual unlock"):
        await agent._ensure_device_unlocked()

    assert "wm dismiss-keyguard" not in device.commands


@pytest.mark.asyncio
async def test_nonsecure_keyguard_that_stays_locked_fails(monkeypatch):
    fast_deadline(monkeypatch)
    device = StatefulDevice(settle_reads=100)
    agent = make_agent(device)

    with pytest.raises(AgentError, match="nonsecure keyguard could not be dismissed"):
        await agent._ensure_device_unlocked()

    assert device.commands.count("wm dismiss-keyguard") == 1
    assert device.locked is True


@pytest.mark.asyncio
async def test_unknown_user_lock_state_fails_closed_without_dismissal(monkeypatch):
    fast_deadline(monkeypatch)
    device = StatefulDevice()
    device.unknown = True
    agent = make_agent(device)

    with pytest.raises(AgentError, match="could not be confirmed"):
        await agent._ensure_device_unlocked()

    assert "input keyevent KEYCODE_WAKEUP" in device.commands
    assert "wm dismiss-keyguard" not in device.commands


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "message"),
    [(ConnectionError("offline"), "disconnected"), (TimeoutError(), "timed out")],
)
async def test_adb_query_failure_fails_closed_before_mutation(error, message):
    device = StatefulDevice()
    device.error_command = "dumpsys trust"
    device.error = error
    agent = make_agent(device)

    with pytest.raises(AgentError, match=message):
        await agent._ensure_device_unlocked()

    assert "input keyevent KEYCODE_WAKEUP" not in device.commands
    assert "wm dismiss-keyguard" not in device.commands


@pytest.mark.asyncio
async def test_cancellation_during_lock_query_propagates():
    device = StatefulDevice()
    device.error_command = "dumpsys trust"
    device.error = asyncio.CancelledError()
    agent = make_agent(device)

    with pytest.raises(asyncio.CancelledError):
        await agent._ensure_device_unlocked()

    assert "input keyevent KEYCODE_WAKEUP" not in device.commands


@pytest.mark.asyncio
async def test_cancellation_waits_for_inflight_wake_before_returning():
    device = StatefulDevice()
    entered = threading.Event()
    release = threading.Event()
    original_shell = device.shell

    def delayed_shell(command, *, timeout):
        if command == "input keyevent KEYCODE_WAKEUP":
            entered.set()
            assert release.wait(1.5)
        return original_shell(command, timeout=timeout)

    device.shell = delayed_shell
    agent = make_agent(device)
    operation = asyncio.create_task(agent._ensure_device_unlocked())
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        operation.cancel()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(operation), timeout=0.05)
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation

    assert device.woken is True
    assert device.dismissed is False
