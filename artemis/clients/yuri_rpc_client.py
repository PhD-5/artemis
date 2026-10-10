"""Read-only discovery and explicitly targeted, one-shot Yuri RPC transport.

The caller gates this optional client on task intent. Construction is inert: no ADB
I/O takes place until probe(), and neither discovery nor probing starts Yuri.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import shlex
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from artemis.config.paths import get_temp_dir
from artemis.runtime.adb_endpoint import AdbEndpoint, AdbSession, AdbTarget


_PACKAGE = "com.bricrt.yuri.client"
_MAIN = "com.bricrt.yuri.client.rpc.Cli"
_APK_PATH = re.compile(r"^/[A-Za-z0-9_./+@=~\-]+/base\.apk$")
_METHOD = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> None:
    raise ValueError("invalid JSON constant: " + value)


class YuriRpcError(Exception):
    """A transport, protocol, business, or job error with structured context."""

    def __init__(self, code: str, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class YuriRpcClient:
    """Task-bound client; job handles are unforgeable and local to this instance."""

    def __init__(self, ctx: Any, config: Any) -> None:
        serial = getattr(ctx.device, "device_id", None)
        if not isinstance(serial, str) or not serial or serial == "default-device":
            raise YuriRpcError("INVALID_TARGET", "A fixed device serial is required")
        target = getattr(ctx, "adb_target", None)
        if isinstance(target, AdbTarget):
            if target.serial is not None and target.serial != serial:
                raise YuriRpcError("INVALID_TARGET", "Task device differs from ADB target")
            endpoint = target.endpoint
        else:
            adb_client = getattr(ctx, "adb_client", None)
            host = getattr(adb_client, "host", None)
            port = getattr(adb_client, "port", None)
            if host is None or port is None:
                raise YuriRpcError("INVALID_TARGET", "Task ADB client endpoint is required")
            endpoint = AdbEndpoint.create(host, port)
        self._serial = serial
        self._endpoint = endpoint
        self._session = AdbSession(endpoint)
        self._config = config
        self._identity = config.identity
        if self._identity not in ("shell", "su_brt", "su"):
            raise YuriRpcError("INVALID_IDENTITY", "Unsupported Yuri RPC identity")
        self._apk: str | None = None
        self._epoch: tuple[str, str, str] | None = None
        self._jobs: dict[str, tuple[str, tuple[str, str, str]]] = {}
        self._closed = False
        self.version: str | None = None
        self._processes: set[asyncio.subprocess.Process] = set()

    def _argv(self, *args: str) -> list[str]:
        try:
            return self._session.command(["-s", self._serial, *args])
        except FileNotFoundError as exc:
            raise YuriRpcError("ADB_UNAVAILABLE", str(exc)) from exc

    async def _run(self, *args: str, timeout: float | None = None) -> tuple[int, bytes, bytes]:
        if self._closed:
            raise YuriRpcError("CLIENT_CLOSED", "Yuri RPC client is closed")
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._argv(*args),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._session.environment(),
            )
        except OSError as exc:
            raise YuriRpcError("ADB_UNAVAILABLE", str(exc)) from exc
        if self._closed:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            raise YuriRpcError("CLIENT_CLOSED", "Yuri client closed during process creation")
        self._processes.add(proc)
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=timeout or self._config.rpc_timeout_ms / 1000 + 5
            )
        except (TimeoutError, asyncio.CancelledError):
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            # Reap only the local adb process; never claim remote work was cancelled.
            await asyncio.shield(proc.communicate())
            raise
        finally:
            self._processes.discard(proc)
        return proc.returncode, out, err

    async def _exec(self, *args: str, timeout: float | None = None) -> tuple[int, str, str]:
        rc, out, err = await self._run(*args, timeout=timeout)
        return rc, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    async def _shell(self, command: str) -> str:
        try:
            rc, out, err = await self._exec("shell", self._as_identity(command))
        except TimeoutError as exc:
            raise YuriRpcError("TIMEOUT", "ADB read-only discovery timed out") from exc
        if rc != 0:
            raise YuriRpcError(
                "ADB_ERROR", err.strip() or "ADB shell command failed", {"exit_code": rc}
            )
        return out.strip()

    async def _process_epoch(self) -> tuple[str, str, str]:
        """Bind to process birth/exec, not identity fields that Yuri can spoof."""
        pids = (await self._shell("pidof " + shlex.quote(_PACKAGE))).split()
        if len(pids) != 1 or not pids[0].isdigit():
            raise YuriRpcError("PROCESS_UNAVAILABLE", "Yuri process identity is unavailable")
        pid = pids[0]
        stat = await self._shell("cat /proc/" + pid + "/stat")
        close = stat.rfind(")")
        fields = stat[close + 1 :].split() if close != -1 else []
        # fields[0] is field 3; starttime/startcode/endcode are fields 22/26/27.
        # boot_id changes during device.modify. The executable's ASLR bounds
        # instead distinguish a new runtime even if PID/start ticks are reused.
        if (
            not stat.startswith(pid + " (")
            or len(fields) <= 24
            or not all(fields[index].isdigit() for index in (19, 23, 24))
        ):
            raise YuriRpcError("PROCESS_UNAVAILABLE", "Cannot verify Yuri process birth/exec")
        if int(fields[23]) <= 1 or int(fields[24]) <= int(fields[23]):
            raise YuriRpcError(
                "PROCESS_UNAVAILABLE",
                "Yuri executable identity is protected; explicitly configure su_brt/su identity",
            )
        return pid, fields[19], fields[23] + ":" + fields[24]

    def _as_identity(self, command: str) -> str:
        if self._identity == "su_brt":
            return "/system/bin/su_brt 0 sh -c " + shlex.quote(command)
        if self._identity == "su":
            return "su -c " + shlex.quote(command)
        return command

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        if self._apk is None:
            raise YuriRpcError("NOT_PROBED", "Probe Yuri before making RPC calls")
        if (
            not isinstance(method, str)
            or not _METHOD.fullmatch(method)
            or not isinstance(params, dict)
        ):
            raise YuriRpcError("BAD_ARGS", "RPC method and object params are required")
        try:
            payload = json.dumps(params, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise YuriRpcError("BAD_ARGS", "RPC params must be JSON serializable") from exc
        command = (
            "CLASSPATH="
            + shlex.quote(self._apk)
            + " app_process / "
            + _MAIN
            + " --timeout "
            + str(self._config.rpc_timeout_ms)
            + " "
            + shlex.quote(method)
            + " "
            + shlex.quote(payload)
        )
        command = self._as_identity(command)
        try:
            rc, stdout, stderr = await self._exec("shell", command)
        except TimeoutError as exc:
            raise YuriRpcError("TIMEOUT", "Yuri RPC timed out; remote work may continue") from exc
        if rc not in (0, 1):
            raise YuriRpcError(
                "TRANSPORT_ERROR",
                stderr.strip() or stdout.strip() or "Yuri CLI transport failed",
                {"exit_code": rc, "stdout": stdout, "stderr": stderr},
            )
        try:
            text = stdout.strip()
            envelope = json.loads(
                text,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_non_json_constant,
            )
        except (ValueError, TypeError) as exc:
            raise YuriRpcError(
                "INVALID_RESPONSE",
                "Yuri did not return one JSON envelope",
                {"stdout": stdout, "stderr": stderr, "exit_code": rc},
            ) from exc
        if (
            not isinstance(envelope, dict)
            or type(envelope.get("ok")) is not bool
            or type(envelope.get("id")) is not int
            or envelope["id"] != 1
        ):
            raise YuriRpcError("INVALID_RESPONSE", "Malformed Yuri RPC envelope", envelope)
        if envelope["ok"]:
            if rc != 0 or "data" not in envelope or "code" in envelope or "error" in envelope:
                raise YuriRpcError(
                    "INVALID_RESPONSE",
                    "Contradictory Yuri success envelope",
                    {"envelope": envelope, "exit_code": rc},
                )
            return envelope["data"]
        if (
            rc != 1
            or not isinstance(envelope.get("code"), str)
            or not envelope["code"]
            or not isinstance(envelope.get("error"), str)
            or "data" in envelope
        ):
            raise YuriRpcError(
                "INVALID_RESPONSE",
                "Contradictory Yuri error envelope",
                {"envelope": envelope, "exit_code": rc},
            )
        raise YuriRpcError(envelope["code"], envelope["error"], envelope)

    async def probe(self) -> dict[str, Any]:
        """Discover installed base.apk and ping the already running Yuri server."""
        if self._apk is None:
            try:
                rc, out, err = await self._exec("shell", "pm path " + _PACKAGE)
            except TimeoutError as exc:
                raise YuriRpcError("TIMEOUT", "Yuri package discovery timed out") from exc
            if rc != 0:
                raise YuriRpcError("NOT_INSTALLED", err.strip() or "Yuri package not installed")
            candidates = [
                line.removeprefix("package:")
                for line in out.splitlines()
                if line.startswith("package:") and line.endswith("/base.apk")
            ]
            if (
                len(candidates) != 1
                or not _APK_PATH.fullmatch(candidates[0])
                or ".." in PurePosixPath(candidates[0]).parts
            ):
                raise YuriRpcError("NOT_INSTALLED", "Unique Yuri base.apk was not found")
            self._apk = candidates[0]
        try:
            pong = await self._rpc("ping", {})
            if (
                not isinstance(pong, dict)
                or pong.get("pong") is not True
                or not isinstance(pong.get("version"), str)
                or not pong["version"]
            ):
                raise YuriRpcError("INVALID_RESPONSE", "Invalid Yuri ping/version response", pong)
            if pong["version"] not in self._config.compatible_versions:
                raise YuriRpcError(
                    "INCOMPATIBLE_VERSION", "Unsupported Yuri version: " + pong["version"], pong
                )
            # Process identity is needed only for jobs; ordinary calls work even
            # when the device restricts /proc access to the shell UID.
        except BaseException:
            self.version = None
            self._apk = None
            self._epoch = None
            raise
        self.version = pong["version"]
        return pong

    async def call(self, method: str, params: dict[str, Any]) -> Any:
        if self.version is None:
            raise YuriRpcError("NOT_PROBED", "Successful Yuri probe required")
        return await self._rpc(method, params)

    async def ensure_farm_rom(self) -> None:
        """Reject proprietary modify/reset operations outside a Yuri farm ROM."""
        if self.version is None:
            raise YuriRpcError("NOT_PROBED", "Successful Yuri probe required")
        version = (await self._shell("getprop ro.yuri.rom.version")).strip()
        if not version or version.lower() in ("unknown", "null", "none"):
            raise YuriRpcError("UNSUPPORTED", "Yuri farm ROM is required for device modification")

    async def _checked_epoch(self, handle: str | None = None) -> tuple[str, str, str]:
        try:
            current = await self._process_epoch()
        except YuriRpcError as exc:
            raise YuriRpcError(
                "STALE_JOB", "Cannot verify original Yuri process", {"job_id": handle}
            ) from exc
        if current != self._epoch:
            raise YuriRpcError(
                "STALE_JOB", "Yuri process restarted; job cannot be polled", {"job_id": handle}
            )
        return current

    async def poll_job(self, job_id: str) -> dict[str, Any]:
        entry = self._jobs.get(job_id) if isinstance(job_id, str) else None
        if entry is None:
            raise YuriRpcError(
                "FOREIGN_JOB", "Unknown or foreign Yuri job handle", {"job_id": job_id}
            )
        raw_id, epoch = entry
        if epoch != self._epoch:
            raise YuriRpcError(
                "STALE_JOB", "Yuri process restarted; job cannot be polled", {"job_id": job_id}
            )
        await self._checked_epoch(job_id)
        try:
            data = await self.call("job.poll", {"id": raw_id})
        except YuriRpcError as exc:
            await self._checked_epoch(job_id)
            raise YuriRpcError(
                exc.code, str(exc), {"job_id": job_id, "state": "unknown", "detail": exc.data}
            ) from exc
        # The server can restart while the one-shot CLI is in flight. Never
        # accept a recycled raw j-N even if it returned a valid result.
        await self._checked_epoch(job_id)
        if (
            not isinstance(data, dict)
            or data.get("id") != raw_id
            or data.get("state") not in ("running", "done", "failed")
        ):
            raise YuriRpcError(
                "INVALID_RESPONSE", "Invalid Yuri job status", {"job_id": job_id, "response": data}
            )
        state = data["state"]
        if state == "failed":
            raise YuriRpcError(
                "JOB_FAILED",
                str(data.get("error") or "Yuri job failed"),
                {"job_id": job_id, "state": state, "error": data.get("error")},
            )
        if state == "done":
            if "result" not in data:
                raise YuriRpcError(
                    "INVALID_RESPONSE",
                    "Job completed without a result",
                    {"job_id": job_id, "state": state},
                )
            return {"job_id": job_id, "state": state, "result": data["result"]}
        return {"job_id": job_id, "state": state}

    async def run_job(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.version is None:
            raise YuriRpcError("NOT_PROBED", "Successful Yuri probe required")
        if self._epoch is None:
            try:
                observed = await self._process_epoch()
            except YuriRpcError as exc:
                raise YuriRpcError(
                    "PROCESS_UNAVAILABLE", "Cannot identify Yuri process for jobs"
                ) from exc
            # Two concurrent submissions must not silently replace each other's
            # process identity if Yuri restarts during the initial observation.
            if self._epoch is None:
                self._epoch = observed
            elif self._epoch != observed:
                raise YuriRpcError("STALE_JOB", "Yuri process restarted before submission")
        else:
            await self._checked_epoch()
        response = await self.call(method, params)
        if (
            not isinstance(response, dict)
            or not isinstance(response.get("jobId"), str)
            or not re.fullmatch(r"j-[1-9][0-9]*", response["jobId"])
        ):
            raise YuriRpcError("INVALID_RESPONSE", "Yuri did not return a job ID", response)
        handle = secrets.token_urlsafe(24)
        self._jobs[handle] = (response["jobId"], self._epoch)
        await self._checked_epoch(handle)
        try:
            async with asyncio.timeout(self._config.job_timeout_s):
                while True:
                    status = await self.poll_job(handle)
                    if status["state"] == "done":
                        return status
                    await asyncio.sleep(self._config.poll_interval_s)
        except TimeoutError as exc:
            raise YuriRpcError(
                "JOB_TIMEOUT",
                "Yuri job is not confirmed complete; remote work may continue",
                {"job_id": handle, "state": "unknown"},
            ) from exc

    async def pull_screenshot(self, remote_path: str) -> str:
        if self.version is None:
            raise YuriRpcError("NOT_PROBED", "Successful Yuri probe required")
        if (
            not isinstance(remote_path, str)
            or not remote_path.startswith("/")
            or "\x00" in remote_path
            or "\n" in remote_path
            or "\r" in remote_path
            or ".." in PurePosixPath(remote_path).parts
        ):
            raise YuriRpcError("BAD_ARGS", "Screenshot requires a safe absolute device path")
        # mkstemp chooses a private host path; the remote path never chooses a host destination.
        import os

        fd, local = tempfile.mkstemp(prefix="yuri-shot-", suffix=".png", dir=get_temp_dir("yuri"))
        os.close(fd)
        try:
            try:
                if self._identity == "shell":
                    rc, _, err = await self._exec("pull", remote_path, local)
                else:
                    # Yuri stores screenshots under its app-private files dir.
                    # Only an explicitly requested root identity may read it.
                    cmd = self._as_identity("cat " + shlex.quote(remote_path))
                    rc, image, diagnostic = await self._run("exec-out", cmd)
                    err = diagnostic.decode("utf-8", "replace")
                    if rc == 0:
                        Path(local).write_bytes(image)
            except TimeoutError as exc:
                raise YuriRpcError("TIMEOUT", "Yuri screenshot pull timed out") from exc
            if rc != 0 or not Path(local).is_file() or Path(local).stat().st_size == 0:
                raise YuriRpcError("PULL_FAILED", err.strip() or "Could not pull Yuri screenshot")
            return local
        except BaseException:
            Path(local).unlink(missing_ok=True)
            raise

    async def aclose(self) -> None:
        self._closed = True
        processes = tuple(self._processes)
        for proc in processes:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        if processes:
            await asyncio.gather(*(proc.wait() for proc in processes))
        self._jobs.clear()
        self._apk = None
        self._epoch = None
        self.version = None
