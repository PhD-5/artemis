"""Opt-in live-model/device acceptance through the production Flash and Pro SDK.

Run with YURI_PROXY_URL set and --device-id SERIAL --output-dir PATH.
No fake models, transport replacements, Yuri verification APKs or global NAT
flushes. Standard SDK accessibility-helper preparation is unchanged.
The test temporarily changes existing Yuri profile/proxy assets and restores
their exact bytes. Credentials can appear in normal agent traces.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from collections import Counter
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import sys
import time
import signal
import uuid
from urllib.parse import parse_qs, unquote, urlsplit
import xml.etree.ElementTree as ET

from artemis.config import initialize_llm_config, settings
from artemis.config.yuri import YuriConfig
from artemis.sdk.agent import Agent
from artemis.sdk.builders import Builders
from artemis.sdk.types.agent import AgentProfile
from third_party.mobile_use.sdk.types.task import TaskRequest

PACKAGE = "com.bricrt.yuri.client"
CLI = PACKAGE + ".rpc.Cli"
ASSETS = "/data/user/0/" + PACKAGE + "/files/assets/proxy/"
PROFILE = "/data/user/0/" + PACKAGE + "/files/sec.prop"
TOOLS = [
    "yuri_ping", "yuri_app_launch", "yuri_click_text", "yuri_find_text",
    "yuri_job_poll", "yuri_network_start_clash", "yuri_network_start_proxy",
    "yuri_device_modify", "yuri_shell_exec",
]


def ss_node(uri: str) -> str:
    """Normalize the supplied SS/simple-obfs node, not a complete Clash config."""
    url = urlsplit(uri)
    if url.scheme != "ss" or not url.hostname or not url.port or not url.username:
        raise ValueError("Expected an ss:// node with host, port and credentials")
    credentials = unquote(url.username)
    if ":" not in credentials:
        credentials = base64.urlsafe_b64decode(credentials + "=" * (-len(credentials) % 4)).decode()
    cipher, password = credentials.split(":", 1)
    node = {"name": "YuriAcceptance", "type": "ss", "server": url.hostname,
            "port": url.port, "cipher": cipher, "password": password, "udp": True}
    plugin = parse_qs(url.query).get("plugin", [""])[0].split(";")
    if plugin[0]:
        opts = dict(item.split("=", 1) for item in plugin[1:] if "=" in item)
        if plugin[0] not in ("obfs-local", "simple-obfs") or opts.get("obfs") not in ("http", "tls"):
            raise ValueError("This acceptance runner supports simple-obfs http/tls only")
        if opts.get("obfs-uri", "/") != "/":
            raise ValueError("Clash obfs does not support a custom obfs-uri")
        node.update(plugin="obfs", **{"plugin-opts": {"mode": opts["obfs"], "host": opts["obfs-host"]}})
    return base64.b64encode(json.dumps(node, separators=(",", ":")).encode()).decode()


class Device:
    def __init__(self, serial: str, output: Path):
        self.serial, self.output = serial, output
        self.apk = self.shell("pm path " + PACKAGE).splitlines()[0].removeprefix("package:")
        packages = self.shell("pm list packages -U " + PACKAGE)
        uid = re.search(r"^package:" + re.escape(PACKAGE) + r" uid:(\d+)$", packages, re.MULTILINE)
        if uid is None:
            raise RuntimeError("Cannot resolve installed Yuri package UID")
        self.app_uid = int(uid.group(1))

    def command(self, *args: str, input_bytes: bytes | None = None) -> bytes:
        result = subprocess.run(["adb", "-s", self.serial, *args], input=input_bytes,
                                capture_output=True, timeout=45)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))
        return result.stdout

    def shell(self, command: str, root: bool = False) -> str:
        if root:
            command = "/system/bin/su_brt 0 sh -c " + shlex.quote(command)
        return self.command("shell", command).decode().strip()

    def rpc(self, method: str, params: dict | None = None):
        command = ("CLASSPATH=" + shlex.quote(self.apk) + " app_process / " + CLI
                   + " --timeout 30000 " + shlex.quote(method) + " "
                   + shlex.quote(json.dumps(params or {}, separators=(",", ":"))))
        result = json.loads(self.shell(command))
        if not result["ok"]:
            raise RuntimeError(result)
        return result["data"]

    def file(self, path: str) -> bytes | None:
        value = self.shell("if [ -f " + shlex.quote(path) + " ]; then base64 "
                           + shlex.quote(path) + "; else echo ABSENT; fi", root=True)
        return None if value == "ABSENT" else base64.b64decode(value)

    def write_file(self, path: str, value: bytes | None):
        if value is None:
            self.shell("rm -f " + shlex.quote(path), root=True)
        else:
            command = "/system/bin/su_brt 0 sh -c " + shlex.quote("cat > " + shlex.quote(path))
            self.command("shell", command, input_bytes=value)

    def nat(self) -> list[str]:
        return [re.sub(r"\[\d+:\d+\]", "[COUNTERS]", line)
                for line in self.shell("iptables-save -t nat", root=True).splitlines()
                if not line.startswith("#")]

    def properties(self, uid: int | None = None) -> dict[str, str]:
        keys = ("ro.product.brand", "ro.product.model", "ro.product.device", "persist.sys.timezone")
        if uid is None:
            return {key: self.shell("getprop " + key, root=True) for key in keys}
        command = "getprop ro.product.brand; getprop ro.product.model; getprop ro.product.device; getprop persist.sys.timezone"
        values = self.shell("/system/bin/su_brt " + str(uid) + " sh -c " + shlex.quote(command)).splitlines()
        return dict(zip(keys, values, strict=True))

    def proxy_pids(self) -> set[str]:
        pids = set()
        for line in self.shell("ss -lntp", root=True).splitlines():
            if re.search(r"127\.0\.0\.1:(16666|17890)\b", line):
                if not re.search(r'users:\(\("(redsocks2_arm64|clash-linux-arm[^"]*)"', line):
                    raise RuntimeError("Test port is occupied by another executable")
                pids.update(re.findall(r"pid=(\d+)", line))
        return pids

    def screenshot(self, name: str):
        (self.output / (name + ".png")).write_bytes(self.command("exec-out", "screencap -p"))

    def ui(self):
        time.sleep(0.4)  # Same observation settling interval as the production runner.
        path = "/data/local/tmp/yuri-agent-acceptance.xml"
        self.shell("rm -f " + path)
        output = self.shell("uiautomator dump " + path)
        if "dumped to:" not in output:
            raise RuntimeError("Fresh UI dump failed: " + output)
        return ET.fromstring(self.shell("cat " + path))

    def wake(self):
        self.shell("input keyevent KEYCODE_WAKEUP")
        self.shell("wm dismiss-keyguard")

    def client_ip(self, name: str) -> str:
        self.wake()
        self.shell("input keyevent 4")
        self.shell("am start -W -n " + PACKAGE + "/.YuriMainActivity")
        for _ in range(8):
            tree = self.ui()
            button = next((n for n in tree.iter("node") if n.get("resource-id") == PACKAGE + ":id/button"), None)
            if button is not None:
                x1, y1, x2, y2 = map(int, re.findall(r"\d+", button.get("bounds", "")))
                if y2 > y1 and x2 > x1:
                    self.shell(f"input tap {(x1+x2)//2} {(y1+y2)//2}")
                    break
            self.shell("input swipe 540 1850 540 700 350")
        else:
            raise RuntimeError("Yuri client_ip button not found")
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            tree = self.ui()
            if any(n.get("text") == "network.clientIP" for n in tree.iter("node")):
                if any(n.get("text") == "(failed)" for n in tree.iter("node")):
                    raise RuntimeError("Yuri client_ip request failed")
                for node in tree.iter("node"):
                    try:
                        address = str(ipaddress.ip_address(node.get("text", "")))
                    except ValueError:
                        continue
                    self.screenshot(name)
                    self.shell("input keyevent 4")
                    return address
            time.sleep(1)
        raise RuntimeError("Yuri client_ip did not return an IP")


class Fixture:
    def __init__(self, device: Device):
        self.device = device
        self.files = {path: device.file(path) for path in (PROFILE, ASSETS + "clash-temp.yaml",
                                                        ASSETS + "clash.yaml", ASSETS + "redsocks.conf")}
        self.profile = self.files[PROFILE]
        if self.profile is None:
            raise RuntimeError("This restoration-safe acceptance requires an existing sec.prop")
        self.nat = device.nat()
        self.properties = device.properties()
        self.settings = {key: device.shell("settings get global " + key, root=True)
                         for key in ("auto_time", "auto_time_zone")}
        self.rules = device.shell("ip rule", root=True)
        if re.search(r":(?:16666|17890)\b", device.shell("ss -lntp", root=True)):
            raise RuntimeError("Acceptance ports are already in use; refusing to disturb them")
        snapshot = {
            "files": {path: None if value is None else base64.b64encode(value).decode()
                      for path, value in self.files.items()},
            "nat": self.nat, "properties": self.properties,
            "settings": self.settings, "rules": self.rules,
        }
        backup = device.output / "restore.json"
        backup.write_text(json.dumps(snapshot))
        backup.chmod(0o600)

    @classmethod
    def from_backup(cls, device: Device):
        snapshot = json.loads((device.output / "restore.json").read_text())
        fixture = cls.__new__(cls)
        fixture.device = device
        fixture.files = {path: None if value is None else base64.b64decode(value)
                         for path, value in snapshot["files"].items()}
        fixture.profile = fixture.files[PROFILE]
        fixture.nat = snapshot["nat"]
        fixture.properties = snapshot["properties"]
        fixture.settings = snapshot["settings"]
        fixture.rules = snapshot["rules"]
        return fixture

    def prepare_proxy(self):
        # Native startClash fills these three slots: node, node name, extra rules.
        # MATCH must be explicit; an empty rules list otherwise falls back to DIRECT.
        self.device.write_file(ASSETS + "clash-temp.yaml", b"""socks-port: 17890
allow-lan: false
bind-address: 127.0.0.1
mode: rule
log-level: info
ipv6: false
tun:
  enable: false
proxies:
  - %s
proxy-groups:
  - name: Proxy
    type: select
    proxies:
      - '%s'
rules:
%s  - MATCH,Proxy
""")

    def restore(self):
        device = self.device
        added = Counter(device.nat()) - Counter(self.nat)
        for rule, count in added.items():
            if not rule.startswith("-A OUTPUT ") or "127.0.0.1:16666" not in rule:
                raise RuntimeError("Unexpected NAT mutation; refusing a global flush: " + rule)
            for _ in range(count):
                device.shell("iptables -t nat " + rule.replace("-A OUTPUT", "-D OUTPUT", 1), root=True)
        for pid in device.proxy_pids():
            device.shell("kill " + pid, root=True)
        if device.file(PROFILE) != self.files[PROFILE]:
            profile = self.profile
            if profile is None:
                raise RuntimeError("Profile backup is missing")
            job = device.rpc("device.modifyProfile", {"device_info": base64.b64encode(profile).decode(), "package": ""})
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                result = device.rpc("job.poll", {"id": job["jobId"]})
                if result["state"] in ("done", "failed"):
                    if result["state"] != "done" or result.get("result") is not True:
                        raise RuntimeError("Profile restoration failed: " + str(result))
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Profile restoration outcome unknown")
        for key, value in self.settings.items():
            device.shell("settings put global " + key + " " + shlex.quote(value), root=True)
        device.shell("service call alarm 3 s16 " + shlex.quote(self.properties["persist.sys.timezone"]), root=True)
        for path, value in self.files.items():
            device.write_file(path, value)
        if device.nat() != self.nat or device.shell("ip rule", root=True) != self.rules:
            raise RuntimeError("Network rules differ after restoration")
        if device.properties() != self.properties or any(device.file(p) != v for p, v in self.files.items()):
            raise RuntimeError("Device state differs after restoration")


def trace_evidence(session: str) -> dict:
    with sqlite3.connect("file:" + str(settings.DATA_ENGINE_DB_PATH) + "?mode=ro", uri=True) as db:
        traces = db.execute("SELECT name,type,status,payload FROM traces WHERE session_id=? ORDER BY timestamp", (session,)).fetchall()
        steps = db.execute("SELECT action_taken,last_execution_result FROM steps WHERE session_id=? ORDER BY step_number", (session,)).fetchall()
    return {"traces": [{"name": n, "type": t, "status": s, "payload": json.loads(p or "{}")} for n, t, s, p in traces],
            "steps": [{"action": a, "result": r} for a, r in steps]}


def require_plugin_actions(case: dict, expected: set[str]) -> None:
    """Reject success via a generic ADB escape hatch instead of the plugin."""
    actions = set()
    for step in case["evidence"]["steps"]:
        payload = json.loads(step["action"]) if step["action"] else None
        for action in payload if isinstance(payload, list) else [payload]:
            if isinstance(action, dict) and str(action.get("action", "")).startswith("yuri_"):
                actions.add(action["action"])
    case["executed_plugin_actions"] = sorted(actions)
    missing = expected - actions
    if missing:
        raise RuntimeError("Production runner did not execute Yuri actions: " + str(sorted(missing)))


async def run(args) -> dict:
    if os.getenv("ARTEMIS_FAKE_LLM") == "1":
        raise RuntimeError("Live acceptance refuses ARTEMIS_FAKE_LLM")
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    device = Device(args.device_id, output)
    ping = device.rpc("ping")
    if ping != {"pong": True, "version": "1.8.6"}:
        raise RuntimeError("Compatible running Yuri is required")
    fixture = Fixture(device)
    node = ss_node(args.proxy_url_file.read_text().strip() if args.proxy_url_file else os.environ[args.proxy_url_env])
    llm = initialize_llm_config()
    cfg = (Builders.AgentConfig.with_default_profile(AgentProfile(name="default", llm_config=llm))
           .for_device_serial(args.device_id).with_yuri(YuriConfig(enabled=True, identity="su_brt", allowed_tools=TOOLS))
           .build())
    report = {"device": args.device_id, "model": llm.operator.model, "provider": llm.operator.provider,
              "ping": ping, "baseline_properties": fixture.properties, "cases": []}
    calls: list[tuple[float, str]] = []
    capturing = False

    def audit(event, values):
        if event == "subprocess.Popen" and capturing:
            command = str(values[1])
            method = re.search(r"rpc\.Cli --timeout \d+ ([A-Za-z.]+)", command)
            if method or "pm path " + PACKAGE in command or "pidof " + PACKAGE in command:
                calls.append((round(time.monotonic(), 3), method.group(1) if method else "metadata"))

    def signal_restore(signum, frame):
        fixture.restore()
        raise SystemExit("Restored device state after signal " + str(signum))

    sys.addaudithook(audit)
    signal.signal(signal.SIGTERM, signal_restore)
    signal.signal(signal.SIGINT, signal_restore)
    try:
        report["baseline_ip"] = device.client_ip("baseline-ip")
        for mode in args.modes:
            prompts = {
                "proxy": ("使用 Yuri 测试代理。当前 Clash 模板已准备好（回环 SOCKS 17890、无 TUN、全部流量走代理组），不要修改模板。"
                          "先通过 Yuri 启动以下 base64 单节点（这是一个节点对象，不是完整 Clash 配置）：" + node + "。"
                          "然后只对 com.bricrt.yuri.client 启动代理：remote_host=127.0.0.1、remote_port=17890、local_port=16666、relay_type=socks5，并等待 job 完成。"
                          "最后打开已安装的 Yuri 客户端，滚动到工具区，点击‘检测客户端 IP’，把弹窗里显示的出口 IP 原样报告。"
                          "不要安装应用、停止代理、清空 iptables、改动其他应用或重启服务；保留代理供外部验收。"),
                "modify": ("使用 Yuri 为已安装的 com.bricrt.yuri.client 改机：seed=1780012345，brand=Samsung_GalaxyA90，country=JP，等 job 完成并确认返回成功。"
                           "通过实际应用 UID 的属性读取确认生效；客户端‘改机状态’一行只能作为辅助证据，不要只读缓存文件就报告成功。"
                           f"通过 Yuri shell 在目标应用 UID {device.app_uid} 下执行 /system/bin/su_brt {device.app_uid} sh -c 'getprop ro.product.brand; getprop ro.product.model; getprop ro.product.device; getprop persist.sys.timezone'，报告实际值（应为 samsung、SM-A908N、r3q、Asia/Tokyo）。root UID 0 看不到目标应用的虚拟属性。不要点击‘设备模拟配置’或‘清除设备模拟’按钮；"
                           "不要安装任何应用、清数据、重启或自行恢复，保留配置供外部验收。"),
                "ordinary": "读取当前 Android 设备的型号和系统版本并报告，不修改设备状态。",
            }
            for kind, goal in prompts.items():
                session = str(uuid.uuid4())
                started = time.monotonic()
                case = {"mode": mode, "kind": kind, "session": session, "status": "failed"}
                report["cases"].append(case)
                agent = Agent(config=cfg, session_id=session)
                calls.clear()
                try:
                    if kind == "proxy":
                        fixture.prepare_proxy()
                    await agent.init()
                    capturing = True
                    task = asyncio.create_task(agent.run_task(request=TaskRequest(
                        goal=goal, profile=mode, task_name="yuri-e2e-" + mode + "-" + kind,
                        trace_path=output / "traces", max_steps=40,
                    )))
                    try:
                        result = await asyncio.wait_for(asyncio.shield(task), timeout=args.task_timeout)
                    except TimeoutError:
                        agent.stop_current_task()
                        try:
                            await asyncio.wait_for(task, timeout=180)
                        except Exception:  # pylint: disable=broad-exception-caught
                            pass
                        raise RuntimeError(f"Agent task exceeded {args.task_timeout}s")
                    finally:
                        capturing = False
                    case.update(result=result, task_status=agent._tasks[-1].status,
                                rpc_calls=[name for _, name in calls],
                                rpc_timing=[list(call) for call in calls],
                                wall_seconds=round(time.monotonic() - started, 1))
                    case["evidence"] = trace_evidence(session)
                    summary = result.get("test_summary") if isinstance(result, dict) else None
                    if summary:
                        case["checker_summary"] = summary
                        if summary.get("failed", 0):
                            raise RuntimeError("Agent verification contains failed checks")
                        if summary.get("inconclusive", 0):
                            case["verification_warning"] = "Internal Checker inconclusive; device proof is independent"
                    if case["task_status"] != "completed":
                        raise RuntimeError("Agent task did not complete: " + str(result))
                    if kind == "proxy":
                        require_plugin_actions(case, {"yuri_network_start_clash", "yuri_network_start_proxy"})
                        if not {"network.startClash", "network.startProxy"}.issubset(case["rpc_calls"]):
                            raise RuntimeError("Agent bypassed required Yuri proxy tools")
                        if "127.0.0.1:16666" not in "\n".join(device.nat()):
                            raise RuntimeError("UID proxy rule missing")
                        case["effective_ip"] = device.client_ip(mode + "-proxy-ip")
                        if case["effective_ip"] == report["baseline_ip"]:
                            raise RuntimeError("Proxy exit IP equals direct baseline; proxy not effective")
                    elif kind == "modify":
                        require_plugin_actions(case, {"yuri_device_modify"})
                        if "device.modify" not in case["rpc_calls"]:
                            raise RuntimeError("Agent bypassed required Yuri modification tool")
                        applied = device.file(PROFILE) or b""
                        expected = [b"# Device: Samsung_GalaxyA90", b"# Seed: 1780012345",
                                    b"package=>com.bricrt.yuri.client"]
                        missing = [mark.decode() for mark in expected if mark not in applied]
                        if missing:
                            raise RuntimeError("Applied profile lacks " + str(missing))
                        case["applied_profile_head"] = applied[:160].decode(errors="replace")
                        case["effective_properties"] = device.properties(uid=device.app_uid)
                        expected_props = dict(zip(fixture.properties, ("samsung", "SM-A908N", "r3q", "Asia/Tokyo"), strict=True))
                        if case["effective_properties"] != expected_props:
                            raise RuntimeError("Target UID does not see the requested identity")
                        device.screenshot(mode + "-modify")
                    elif case["rpc_calls"]:
                        raise RuntimeError("Ordinary task invoked Yuri")
                    case["status"] = "passed"
                except Exception as error:
                    case["error"] = str(error)
                    case["rpc_calls"] = case.get("rpc_calls") or [name for _, name in calls]
                    case["evidence"] = trace_evidence(session)
                finally:
                    capturing = False
                    agent.stop_current_task()
                    await agent.clean(force=True)
                    fixture.restore()
                    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
                print("YURI_E2E_CASE", mode, kind, case["status"], case.get("error", ""), flush=True)
        report["restored_properties"] = device.properties()
        report["restored_ip"] = device.client_ip("restored-ip")
        restored_profile = device.file(PROFILE)
        if restored_profile is None:
            raise RuntimeError("Restored profile is missing")
        report["restored_profile_sha256"] = hashlib.sha256(restored_profile).hexdigest()
        report["status"] = "passed" if all(c["status"] == "passed" for c in report["cases"]) else "failed"
    finally:
        fixture.restore()
        device.shell("rm -f /data/local/tmp/yuri-agent-acceptance.xml")
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--proxy-url-env", default="YURI_PROXY_URL")
    parser.add_argument("--modes", nargs="+", choices=("flash", "pro"), default=["flash", "pro"])
    parser.add_argument("--proxy-url-file", type=Path)
    parser.add_argument("--restore-only", action="store_true")
    parser.add_argument("--task-timeout", type=float, default=600)
    args = parser.parse_args()
    if args.restore_only:
        fixture = Fixture.from_backup(Device(args.device_id, Path(args.output_dir).resolve()))
        fixture.restore()
        print("YURI_E2E_RESTORED", flush=True)
        return 0
    report = asyncio.run(run(args))
    print("YURI_E2E_RESULT", report["status"], flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
