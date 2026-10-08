"""System monitors: real (psutil) and synthetic (scenario replay).

A monitor's only job is to produce SystemSample snapshots on demand. The
engine consumes samples and is agnostic to where they come from, which lets
the exact same engine run against a live machine or a replayed scenario
(useful for deterministic demos and experiments on any OS).
"""

from __future__ import annotations

import functools
import re
import subprocess
import threading
import time
from typing import Optional

import psutil

from .events import BatteryInfo, ProcessInfo, SystemSample
from . import platform_compat as cap
from .platform_compat import is_windows


def wsl_battery(timeout: float = 4.0) -> BatteryInfo:
    """Battery status for WSL via Windows interop (PowerShell / Win32_Battery).

    WSL exposes no battery device, so without this the battery-saver contract
    could never fire inside WSL - the primary Windows demo environment. The
    caller caches results because interop invocation is comparatively slow.
    """
    ps = ("$b = Get-CimInstance Win32_Battery | Select-Object -First 1; "
          "if ($b) { Write-Output ($b.EstimatedChargeRemaining.ToString() + ',' + $b.BatteryStatus.ToString()) } "
          "else { Write-Output 'none' }")
    for exe in ("powershell.exe", "pwsh.exe"):
        try:
            out = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, timeout=timeout,
            ).stdout.strip()
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            continue
        return parse_wsl_battery(out)
    return BatteryInfo(None, None)


def parse_wsl_battery(out: str) -> BatteryInfo:
    """"percent,status" -> BatteryInfo. Win32_Battery status: 1=discharging, 2=AC."""
    out = (out or "").strip()
    if not out or out.lower() == "none":
        return BatteryInfo(None, None)
    try:
        pct_s, status_s = out.split(",")[:2]
        percent = float(pct_s)
        plugged = int(status_s) == 2
        return BatteryInfo(percent, plugged)
    except (ValueError, TypeError):
        return BatteryInfo(None, None)


class RealMonitor:
    """Samples real system state through psutil (/proc on Linux)."""

    def __init__(self, battery_ttl: float = 10.0):
        self._proc_handles: dict[int, psutil.Process] = {}
        self._psutil = psutil
        self._battery_cache = (BatteryInfo(None, None), 0.0)
        self._battery_ttl = battery_ttl
        # Prime per-process cpu counters (first call returns 0.0 by design).
        self.sample()

    def _battery(self) -> BatteryInfo:
        try:
            b = psutil.sensors_battery()
        except (AttributeError, NotImplementedError):
            b = None
        if b is not None:
            # psutil reports negative sentinel values for "unknown"/"unlimited"
            # time remaining (POWER_TIME_UNKNOWN / POWER_TIME_UNLIMITED).
            secs = getattr(b, "secsleft", None)
            if secs is not None and secs < 0:
                secs = None
            return BatteryInfo(b.percent, b.power_plugged, secs)
        # WSL has no battery device; ask Windows for it (cached - interop is slow).
        if cap.is_wsl():
            return self._wsl_battery()
        return BatteryInfo(None, None)

    def _wsl_battery(self) -> BatteryInfo:
        now = time.time()
        cached, at = self._battery_cache
        if now - at < self._battery_ttl:
            return cached
        info = wsl_battery()
        self._battery_cache = (info, now)
        return info

    def sample(self) -> SystemSample:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        try:
            load1 = psutil.getloadavg()[0]
        except (AttributeError, OSError):
            load1 = None

        procs: list[ProcessInfo] = []
        fresh: dict[int, psutil.Process] = {}
        # attrs= lets psutil batch reads via oneshot; far fewer syscalls per sample.
        for p in psutil.process_iter(["name", "cmdline", "nice", "status",
                                      "create_time", "num_threads", "memory_percent"]):
            try:
                pid = p.pid
                if pid not in self._proc_handles:
                    fresh[pid] = psutil.Process(pid)
                else:
                    fresh[pid] = self._proc_handles[pid]
                handle = fresh[pid]
                info = p.info
                name = info.get("name") or "unknown"
                cmdline = " ".join(info.get("cmdline") or []) or name
                procs.append(
                    ProcessInfo(
                        pid=pid,
                        name=name,
                        cmdline=cmdline,
                        cpu_percent=handle.cpu_percent(None),
                        mem_percent=info.get("memory_percent") or 0.0,
                        nice=info.get("nice"),
                        status=info.get("status") or "?",
                        create_time=info.get("create_time") or 0.0,
                        num_threads=info.get("num_threads") or 1,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        self._proc_handles = fresh
        return SystemSample(
            ts=time.time(),
            cpu_percent=cpu,
            mem_percent=mem,
            load1=load1,
            battery=self._battery(),
            procs=procs,
        )


class SyntheticMonitor:
    """Replays a scripted scenario against a virtual process table.

    Scenario steps: {"t": seconds, "op": "proc_add"|"proc_del"|"metric"|
    "battery"|"load", ...}. Virtual time advances with wall-clock time times
    `speed`, so demos run deterministically and fast on any machine.
    """

    def __init__(self, scenario: list[dict], speed: float = 1.0, start_procs: list[dict] | None = None):
        self.scenario = sorted(scenario, key=lambda s: s["t"])
        self.speed = speed
        self._t0 = time.monotonic()
        self._cursor = 0
        self.cpu = 5.0
        self.mem = 30.0
        self.load1 = 0.5
        self.battery = BatteryInfo(80.0, True)
        self.procs: dict[int, ProcessInfo] = {}
        self._next_pid = 1000
        for spec in start_procs or []:
            self._add_proc(spec)
        self._lock = threading.Lock()

    def _vnow(self) -> float:
        return (time.monotonic() - self._t0) * self.speed

    def _add_proc(self, spec: dict) -> ProcessInfo:
        pid = spec.get("pid") or self._next_pid
        if pid >= self._next_pid:
            self._next_pid = pid + 1
        info = ProcessInfo(
            pid=pid,
            name=spec.get("name", "proc"),
            cmdline=spec.get("cmdline", spec.get("name", "proc")),
            cpu_percent=spec.get("cpu_percent", 0.0),
            mem_percent=spec.get("mem_percent", 0.1),
            nice=spec.get("nice", 0),
            status="running",
            create_time=time.time(),
            num_threads=spec.get("num_threads", 1),
        )
        self.procs[pid] = info
        return info

    def sample(self) -> SystemSample:
        with self._lock:
            t = self._vnow()
            while self._cursor < len(self.scenario) and self.scenario[self._cursor]["t"] <= t:
                step = self.scenario[self._cursor]
                op = step["op"]
                if op == "proc_add":
                    self._add_proc(step)
                elif op == "proc_del":
                    self.procs.pop(step["pid"], None)
                elif op == "metric":
                    if "cpu_percent" in step:
                        self.cpu = step["cpu_percent"]
                    if "mem_percent" in step:
                        self.mem = step["mem_percent"]
                    if "load1" in step:
                        self.load1 = step["load1"]
                elif op == "battery":
                    self.battery = BatteryInfo(step.get("percent"), step.get("plugged"))
                elif op == "load":
                    self.load1 = step.get("load1", self.load1)
                self._cursor += 1
            return SystemSample(
                ts=time.time(),
                cpu_percent=self.cpu,
                mem_percent=self.mem,
                load1=self.load1,
                battery=self.battery,
                procs=list(self.procs.values()),
            )


def spawn_dummy(name: str = "arc-dummy-sleep", args: Optional[list[str]] = None) -> psutil.Process:
    """Spawn a harmless background workload used by tests and experiments."""
    cmd = args or ["python3", "-c", "import time\nwhile True: time.sleep(0.2)"]
    if is_windows():
        cmd = args or ["python", "-c", "import time\nwhile True: time.sleep(0.2)"]
    p = psutil.Popen(cmd)
    p.name()  # force creation bookkeeping
    return p


def regex_compile(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


@functools.lru_cache(maxsize=256)
def regex_compile_cached(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)
