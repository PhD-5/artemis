"""Yuri CLI transport contracts; no connected device or Yuri process is used."""

import asyncio
import json
import shlex
from types import SimpleNamespace

import pytest

from artemis.clients.yuri_rpc_client import YuriRpcClient, YuriRpcError


APK = "/data/app/~~Yuri==/com.bricrt.yuri.client-x/base.apk"


def make_client(host="127.0.0.1", port=5037, serial="device-A", identity="shell"):
    ctx = SimpleNamespace(
        device=SimpleNamespace(device_id=serial), adb_client=SimpleNamespace(host=host, port=port)
    )
    config = SimpleNamespace(
        identity=identity,
        compatible_versions=["1.8.6"],
        rpc_timeout_ms=1000,
        job_timeout_s=0.01,
        poll_interval_s=1,
    )
    return YuriRpcClient(ctx, config)


def envelope(data=None, *, ok=True, code="BAD_ARGS", error="failure", ident=1):
    return json.dumps(
        {"id": ident, "ok": True, "data": data}
        if ok
        else {"id": ident, "ok": False, "code": code, "error": error}
    )


class Transport:
    def __init__(self):
        self.commands = []
        self.responses = []

    async def __call__(self, *args, **kwargs):
        self.commands.append(args)
        return self.responses.pop(0)

    def add(self, text, rc=0):
        self.responses.append((rc, text, ""))


def ready(client, transport):
    transport.add("package:" + APK + "\npackage:/data/app/split.apk\n")
    transport.add(envelope({"pong": True, "version": "1.8.6"}))
    return client.probe()


def epoch(transport, *, start="123", pid="345"):
    transport.add(pid)
    transport.add(
        pid + " (com.bricrt.yuri.client) S "
        + " ".join(["0"] * 18 + [start, "0", "0", "0", "4000", "5000"])
    )


@pytest.mark.asyncio
async def test_probe_requires_installed_base_and_version(monkeypatch):
    client = make_client()
    transport = Transport()
    monkeypatch.setattr(client, "_exec", transport)
    await ready(client, transport)
    assert client.version == "1.8.6"
    assert len(transport.commands) == 2  # no process launch or farm probe
    assert transport.commands[0] == ("shell", "pm path com.bricrt.yuri.client")
    client2 = make_client()
    transport2 = Transport()
    monkeypatch.setattr(client2, "_exec", transport2)
    transport2.add("package:/data/app/split.apk")
    with pytest.raises(YuriRpcError, match="base.apk"):
        await client2.probe()
    assert len(transport2.commands) == 1


@pytest.mark.asyncio
async def test_quoted_rpc_params_and_identity(monkeypatch):
    client = make_client(identity="su_brt")
    transport = Transport()
    monkeypatch.setattr(client, "_exec", transport)
    await ready(client, transport)
    value = "Bob's $(touch /tmp/harm); `id`\nnext"
    transport.add(envelope(False))
    assert await client.call("app.isInstalled", {"package": value}) is False
    shell = transport.commands[-1][1]
    assert shell.startswith("/system/bin/su_brt 0 sh -c ")
    inner = shlex.split(shell)[4]
    # A shell parser sees precisely one JSON argument, not executable injection.
    tokens = shlex.split(inner)
    assert tokens[0] == "CLASSPATH=" + APK
    assert tokens[-2] == "app.isInstalled"
    assert json.loads(tokens[-1]) == {"package": value}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,rc",
    [
        ('{"id":1,"ok":true,"data":1}\n{"id":1,"ok":true,"data":2}', 0),
        ('{"id":1,"ok":"true","data":1}', 0),
        (envelope(1), 1),
        (envelope(ok=False), 0),
        ('{"id":2,"ok":true,"data":1}', 0),
        ('{"id":1,"ok":true}', 0),
        ('{"id":1,"ok":true,"ok":false,"data":1}', 0),
        ('{"id":1,"ok":true,"data":NaN}', 0),
    ],
)
async def test_malformed_or_contradictory_envelopes(monkeypatch, payload, rc):
    client = make_client()
    transport = Transport()
    monkeypatch.setattr(client, "_exec", transport)
    await ready(client, transport)
    transport.add(payload, rc)
    with pytest.raises(YuriRpcError) as caught:
        await client.call("device.getGAID", {})
    assert caught.value.code == "INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_rpc_business_failure_and_farm_marker(monkeypatch):
    client = make_client()
    transport = Transport()
    monkeypatch.setattr(client, "_exec", transport)
    await ready(client, transport)
    transport.add(envelope(ok=False, code="BAD_ARGS", error="not allowed"), 1)
    with pytest.raises(YuriRpcError) as caught:
        await client.call("app.launch", {"package": "foo"})
    assert (caught.value.code, str(caught.value)) == ("BAD_ARGS", "not allowed")
    transport.add("")
    with pytest.raises(YuriRpcError) as caught:
        await client.ensure_farm_rom()
    assert caught.value.code == "UNSUPPORTED"
    assert transport.commands[-1] == ("shell", "getprop ro.yuri.rom.version")


@pytest.mark.asyncio
async def test_job_pending_timeout_and_resume_false(monkeypatch):
    client = make_client()
    transport = Transport()
    monkeypatch.setattr(client, "_exec", transport)
    await ready(client, transport)
    epoch(transport)
    transport.add(envelope({"jobId": "j-1"}))
    epoch(transport)
    epoch(transport)
    transport.add(envelope({"id": "j-1", "state": "running"}))
    epoch(transport)
    with pytest.raises(YuriRpcError) as caught:
        await client.run_job("app.dataClear", {"package": "example"})
    assert caught.value.code == "JOB_TIMEOUT"
    handle = caught.value.data["job_id"]
    assert caught.value.data["state"] == "unknown" and handle != "j-1"
    epoch(transport)
    transport.add(envelope({"id": "j-1", "state": "done", "result": False}))
    epoch(transport)
    assert await client.poll_job(handle) == {"job_id": handle, "state": "done", "result": False}
    assert (
        len(
            [
                args
                for args in transport.commands
                if args[0] == "shell" and "app.dataClear" in args[1]
            ]
        )
        == 1
    )


@pytest.mark.asyncio
async def test_failed_stale_and_foreign_jobs_never_poll_wrong_process(monkeypatch):
    first = make_client()
    second = make_client(host="remote.example", port=5038, serial="device-B")
    a, b = Transport(), Transport()
    monkeypatch.setattr(first, "_exec", a)
    monkeypatch.setattr(second, "_exec", b)
    await ready(first, a)
    await ready(second, b)
    epoch(a)
    a.add(envelope({"jobId": "j-1"}))
    epoch(a)
    epoch(a)
    a.add(envelope({"id": "j-1", "state": "failed", "error": "bad disk"}))
    epoch(a)
    with pytest.raises(YuriRpcError) as caught:
        await first.run_job("app.dataClear", {})
    assert caught.value.code == "JOB_FAILED"
    handle = caught.value.data["job_id"]
    assert caught.value.data["state"] == "failed"
    with pytest.raises(YuriRpcError) as foreign:
        await second.poll_job(handle)
    assert foreign.value.code == "FOREIGN_JOB" and len(b.commands) == 2
    epoch(a, start="456")
    with pytest.raises(YuriRpcError) as stale:
        await first.poll_job(handle)
    assert stale.value.code == "STALE_JOB" and stale.value.data["job_id"] == handle
    assert not a.responses


@pytest.mark.asyncio
async def test_restart_during_poll_rejects_reused_raw_job_id(monkeypatch):
    client = make_client()
    transport = Transport()
    monkeypatch.setattr(client, "_exec", transport)
    await ready(client, transport)
    client._epoch = ("345", "123", "4000:5000")
    client._jobs["opaque"] = ("j-1", client._epoch)
    epoch(transport)
    transport.add(envelope({"id": "j-1", "state": "done", "result": True}))
    epoch(transport, start="456")
    with pytest.raises(YuriRpcError) as caught:
        await client.poll_job("opaque")
    assert caught.value.code == "STALE_JOB"
    assert caught.value.data["job_id"] == "opaque"


@pytest.mark.asyncio
async def test_target_isolation_and_local_timeout_cancel(monkeypatch):
    left = make_client(serial="A")
    right = make_client(host="10.0.0.8", port=5038, serial="B")
    monkeypatch.setattr(left._session, "adb_path", "adb")
    monkeypatch.setattr(right._session, "adb_path", "adb")
    assert left._argv("shell", "id") == [
        "adb",
        "-H",
        "127.0.0.1",
        "-P",
        "5037",
        "-s",
        "A",
        "shell",
        "id",
    ]
    assert right._argv("shell", "id") == [
        "adb",
        "-H",
        "10.0.0.8",
        "-P",
        "5038",
        "-s",
        "B",
        "shell",
        "id",
    ]

    class Process:
        def __init__(self):
            self.returncode = None
            self.killed = False

        async def communicate(self):
            if not self.killed:
                await asyncio.Event().wait()
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9

    processes = []

    async def spawn(*argv, **kwargs):
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL
        assert kwargs["stdout"] == kwargs["stderr"] == asyncio.subprocess.PIPE
        p = Process()
        processes.append(p)
        return p

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(asyncio.TimeoutError):
        await left._exec("shell", "ping", timeout=0.001)
    assert processes[-1].killed
    task = asyncio.create_task(right._exec("shell", "ping", timeout=10))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[-1].killed


@pytest.mark.asyncio
async def test_rpc_timeout_and_cancel_never_resubmit(monkeypatch):
    client = make_client()
    transport = Transport()
    monkeypatch.setattr(client, "_exec", transport)
    await ready(client, transport)
    calls = []

    async def timeout(*args):
        calls.append(args)
        raise TimeoutError

    monkeypatch.setattr(client, "_exec", timeout)
    with pytest.raises(YuriRpcError) as caught:
        await client.call("app.launch", {"package": "com.example"})
    assert caught.value.code == "TIMEOUT"
    assert len(calls) == 1

    async def cancelled(*args):
        calls.append(args)
        raise asyncio.CancelledError

    monkeypatch.setattr(client, "_exec", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await client.call("app.launch", {"package": "com.example"})
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_screenshot_safe_destination(monkeypatch, tmp_path):
    client = make_client()
    transport = Transport()
    monkeypatch.setattr(client, "_exec", transport)
    await ready(client, transport)
    monkeypatch.setattr("artemis.clients.yuri_rpc_client.get_temp_dir", lambda _: tmp_path)
    with pytest.raises(YuriRpcError) as caught:
        await client.pull_screenshot("/sdcard/../secret")
    assert caught.value.code == "BAD_ARGS"
    transport.add("pulled")
    with pytest.raises(YuriRpcError) as caught:
        await client.pull_screenshot("/sdcard/shot.png")
    assert caught.value.code == "PULL_FAILED"  # fake ADB wrote no image
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_explicit_root_identity_reads_private_screenshot_as_binary(monkeypatch, tmp_path):
    client = make_client(identity="su")
    transport = Transport()
    monkeypatch.setattr(client, "_exec", transport)
    await ready(client, transport)
    monkeypatch.setattr("artemis.clients.yuri_rpc_client.get_temp_dir", lambda _: tmp_path)
    commands = []

    async def raw(*args, **kwargs):
        commands.append(args)
        return 0, b"\x89PNG\r\n\x1a\n\xff", b""

    monkeypatch.setattr(client, "_run", raw)
    remote = "/data/user/0/com.bricrt.yuri.client/files/screen_shot/a'b.png"
    local = await client.pull_screenshot(remote)
    assert (tmp_path / local.split("/")[-1]).read_bytes() == b"\x89PNG\r\n\x1a\n\xff"
    assert commands == [("exec-out", "su -c " + shlex.quote("cat " + shlex.quote(remote)))]


@pytest.mark.asyncio
async def test_close_reaps_an_inflight_local_process(monkeypatch):
    import sys

    client = make_client()
    started = asyncio.Event()
    processes = []
    real_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        proc = await real_spawn(sys.executable, "-c", "import time; time.sleep(30)", **kwargs)
        processes.append(proc)
        started.set()
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(client._exec("shell", "read-only-probe", timeout=30))
    await started.wait()
    await client.aclose()
    await task
    assert processes[0].returncode is not None and processes[0].returncode != 0
    with pytest.raises(YuriRpcError) as caught:
        await client.call("ping", {})
    assert caught.value.code == "NOT_PROBED"


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["shell", "su_brt", "su"])
async def test_jobs_read_protected_process_identity_only_with_explicit_root(monkeypatch, identity):
    class ProtectedProcess(Transport):
        async def __call__(self, *args, **kwargs):
            if args[1] == "cat /proc/345/stat":
                self.commands.append(args)
                return 1, "", "Permission denied"
            return await super().__call__(*args, **kwargs)

    client = make_client(identity=identity)
    transport = ProtectedProcess()
    monkeypatch.setattr(client, "_exec", transport)
    await ready(client, transport)
    epoch(transport)
    transport.add(envelope({"jobId": "j-1"}))
    epoch(transport)
    epoch(transport)
    transport.add(envelope({"id": "j-1", "state": "done", "result": True}))
    epoch(transport)

    if identity == "shell":
        with pytest.raises(YuriRpcError) as denied:
            await client.run_job("app.dataClear", {"package": "com.example"})
        assert denied.value.code == "PROCESS_UNAVAILABLE"
        assert not any(
            "su" in command[1] or "app.dataClear" in command[1] for command in transport.commands
        )
    else:
        result = await client.run_job("app.dataClear", {"package": "com.example"})
        assert result["state"] == "done" and result["result"] is True
        assert sum("app.dataClear" in command[1] for command in transport.commands) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reexec", [False, True])
async def test_modify_can_change_virtual_boot_id_but_cannot_accept_a_new_runtime(monkeypatch, reexec):
    client = make_client(identity="su_brt")
    commands = []
    boot = "original-virtual-boot"
    code_start = "4000"

    async def transport(*args, **kwargs):
        nonlocal boot, code_start
        command = args[1]
        commands.append(command)
        if command.startswith("/system/bin/su_brt"):
            command = shlex.split(command)[4]
        if command == "pm path com.bricrt.yuri.client":
            return 0, "package:" + APK, ""
        if command == "cat /proc/sys/kernel/random/boot_id":
            return 0, boot, ""
        if command.startswith("pidof "):
            return 0, "345", ""
        if command == "cat /proc/345/stat":
            fields = ["S"] + ["0"] * 18 + ["123", "0", "0", "0", code_start, "5000"]
            return 0, "345 (com.bricrt.yuri.client) " + " ".join(fields), ""
        tokens = shlex.split(command)
        method = tokens[-2]
        if method == "ping":
            data = {"pong": True, "version": "1.8.6"}
        elif method == "device.modify":
            boot = "new-spoofed-boot-id"
            data = {"jobId": "j-1"}
        elif method == "job.poll":
            if reexec:
                code_start = "4500"
            data = {"id": "j-1", "state": "done", "result": True}
        else:
            raise AssertionError(method)
        return 0, envelope(data), ""

    monkeypatch.setattr(client, "_exec", transport)
    await client.probe()
    if reexec:
        with pytest.raises(YuriRpcError) as stale:
            await client.run_job("device.modify", {})
        assert stale.value.code == "STALE_JOB"
    else:
        result = await client.run_job("device.modify", {})
        assert result["state"] == "done" and result["result"] is True
    assert sum("device.modify" in command for command in commands) == 1


@pytest.mark.asyncio
async def test_hidden_executable_identity_blocks_job_before_submission(monkeypatch):
    client = make_client()
    transport = Transport()
    monkeypatch.setattr(client, "_exec", transport)
    await ready(client, transport)
    transport.add("345")
    transport.add("345 (com.bricrt.yuri.client) S " + " ".join(["0"] * 18 + ["123", "0", "0", "0", "1", "0"]))
    with pytest.raises(YuriRpcError) as unavailable:
        await client.run_job("app.dataClear", {"package": "com.example"})
    assert unavailable.value.code == "PROCESS_UNAVAILABLE"
    assert not any("app.dataClear" in command[1] or "su_brt" in command[1] for command in transport.commands)
