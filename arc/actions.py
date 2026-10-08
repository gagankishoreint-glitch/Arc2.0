"""Resource-action execution layer.

Each action type is a small executor that:
  1. resolves its target processes from the latest sample,
  2. snapshots the current resource state,
  3. applies the change through existing OS interfaces (psutil / signals /
     cgroups),
  4. returns AppliedChange records so the engine can restore them later.

Every executor is capability-checked first (see platform_compat) so ARC runs
on Linux, WSL, macOS and Windows, skipping unsupported actions with a log
entry instead of crashing.
"""

from __future__ import annotations

import functools
import dataclasses
import os
import re
import signal
import subprocess
import time
from typing import Optional

import psutil

from . import platform_compat as cap
from .events import ProcessInfo, SystemSample


@functools.lru_cache(maxsize=256)
def _compile_rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


@dataclasses.dataclass
class AppliedChange:
    """One reversible resource change made by an action."""

    action_type: str
    pid: int
    create_time: float
    prev: dict
    new: dict
    detail: str = ""

    def target_still_valid(self) -> bool:
        try:
            p = psutil.Process(self.pid)
            return abs(p.create_time() - self.create_time) < 0.01
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False


@dataclasses.dataclass
class ActionResult:
    status: str  # "applied" | "skipped" | "failed"
    changes: list
    message: str = ""


class BaseExecutor:
    """Interface used by the engine; also the dry-run implementation."""

    def __init__(self, own_pids: Optional[set[int]] = None, journal: Optional[list] = None):
        self.own_pids = own_pids or {os.getpid()}
        self.journal = journal if journal is not None else []

    def _exclude(self) -> set[int]:
        return set(self.own_pids)

    def resolve(self, action: dict, sample: SystemSample) -> list[ProcessInfo]:
        target = action.get("target") or {}
        if "pid" in target:
            found = [p for p in sample.procs if p.pid == int(target["pid"])]
        elif "match" in target:
            rx = _compile_rx(target["match"])
            found = sample.find_procs(rx, exclude_pids=self._exclude())
        else:
            found = []
        limit = target.get("limit")
        if limit:
            # Deterministic policy: hottest consumers are managed first.
            found = sorted(found, key=lambda p: p.cpu_percent, reverse=True)[: int(limit)]
        return found

    def apply(self, action: dict, sample: SystemSample) -> ActionResult:
        """Dry run: record what would happen without touching the OS."""
        if action["type"] == "log":
            self.journal.append({"op": "apply", "action": "log", "pids": [], "ts": time.time()})
            return ActionResult("applied", [], action.get("message", "log action"))
        targets = self.resolve(action, sample)
        if not targets:
            return ActionResult("skipped", [], f"no process matched {action.get('target')}")
        changes = []
        for t in targets:
            change = AppliedChange(
                action_type=action["type"],
                pid=t.pid,
                create_time=t.create_time,
                prev={"nice": t.nice, "status": t.status},
                new={k: v for k, v in action.items() if k not in ("type", "target")},
                detail="dry-run",
            )
            changes.append(change)
        self.journal.append({"op": "apply", "action": action["type"], "pids": [c.pid for c in changes], "ts": time.time()})
        return ActionResult("applied", changes)

    def restore(self, change: AppliedChange) -> bool:
        self.journal.append({"op": "restore", "action": change.action_type, "pid": change.pid, "ts": time.time()})
        return True


class SystemExecutor(BaseExecutor):
    """Real executor backed by OS interfaces (psutil, signals, cgroups)."""

    def apply(self, action: dict, sample: SystemSample) -> ActionResult:
        atype = action["type"]
        handler = {
            "set_nice": self._set_nice,
            "set_affinity": self._set_affinity,
            "suspend": self._suspend,
            "resume": self._resume,
            "cgroup_limit": self._cgroup_limit,
            "log": self._log_only,
        }.get(atype)
        if handler is None:
            return ActionResult("failed", [], f"unknown action type {atype!r}")
        return handler(action, sample)

    # -- individual actions -------------------------------------------------

    def _set_nice(self, action: dict, sample: SystemSample) -> ActionResult:
        wanted = int(action.get("nice", 0))
        targets = self.resolve(action, sample)
        if not targets:
            return ActionResult("skipped", [], f"no process matched {action.get('target')}")
        changes, messages = [], []
        for t in targets:
            try:
                p = psutil.Process(t.pid)
                prev_nice = p.nice()
                effective = wanted
                if cap.is_posix() and not cap.can_raise_priority() and wanted < prev_nice:
                    # Unprivileged processes may only increase nice (deprioritise).
                    effective = prev_nice
                    messages.append(f"clamped nice {wanted}->{effective} on pid {t.pid} (no privilege)")
                p.nice(effective)
                changes.append(
                    AppliedChange(
                        "set_nice", t.pid, t.create_time,
                        prev={"nice": prev_nice}, new={"nice": effective},
                        detail="; ".join(messages),
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError, OSError) as e:
                messages.append(f"pid {t.pid}: {e}")
        if changes:
            self.journal.append({"op": "apply", "action": "set_nice", "pids": [c.pid for c in changes], "ts": time.time()})
            return ActionResult("applied", changes, "; ".join(messages))
        return ActionResult("failed", [], "; ".join(messages) or "set_nice failed")

    def _set_affinity(self, action: dict, sample: SystemSample) -> ActionResult:
        if not cap.supports_affinity():
            return ActionResult("skipped", [], "CPU affinity not supported on this platform")
        cpus = [int(c) for c in action.get("cpus", [])]
        n = cap.cpu_count()
        cpus = [c for c in cpus if 0 <= c < n]
        if not cpus:
            return ActionResult("skipped", [], f"invalid cpu list {action.get('cpus')} for {n} cpus")
        targets = self.resolve(action, sample)
        if not targets:
            return ActionResult("skipped", [], f"no process matched {action.get('target')}")
        changes = []
        for t in targets:
            try:
                p = psutil.Process(t.pid)
                prev = p.cpu_affinity()
                p.cpu_affinity(cpus)
                changes.append(AppliedChange("set_affinity", t.pid, t.create_time, prev={"cpus": prev}, new={"cpus": cpus}))
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, AttributeError) as e:
                return ActionResult("failed", changes, str(e))
        self.journal.append({"op": "apply", "action": "set_affinity", "pids": [c.pid for c in changes], "ts": time.time()})
        return ActionResult("applied", changes)

    def _suspend(self, action: dict, sample: SystemSample) -> ActionResult:
        return self._signal_action(action, sample, "SIGSTOP", "suspend")

    def _resume(self, action: dict, sample: SystemSample) -> ActionResult:
        return self._signal_action(action, sample, "SIGCONT", "resume")

    def _signal_action(self, action: dict, sample: SystemSample, sig_name: str, name: str) -> ActionResult:
        if not cap.supports_suspend():
            return ActionResult("skipped", [], f"{name} not supported on this platform")
        # Resolve the signal lazily: signal.SIGSTOP/SIGCONT do not exist on Windows.
        sig = getattr(signal, sig_name, None)
        if sig is None:
            return ActionResult("skipped", [], f"{sig_name} unavailable on this platform")
        targets = self.resolve(action, sample)
        if not targets:
            return ActionResult("skipped", [], f"no process matched {action.get('target')}")
        changes = []
        for t in targets:
            try:
                os.kill(t.pid, sig)
                changes.append(AppliedChange(name, t.pid, t.create_time, prev={"status": t.status}, new={"signal": int(sig)}))
            except (ProcessLookupError, PermissionError, OSError) as e:
                return ActionResult("failed", changes, str(e))
        self.journal.append({"op": "apply", "action": name, "pids": [c.pid for c in changes], "ts": time.time()})
        return ActionResult("applied", changes)

    def _cgroup_limit(self, action: dict, sample: SystemSample) -> ActionResult:
        if not cap.supports_cgroups():
            return ActionResult("skipped", [], "cgroups not available on this platform")
        root = "/sys/fs/cgroup"
        try:
            base = open("/proc/self/cgroup").read().strip().split(":")[-1] or "/"
        except OSError:
            base = "/"
        group_name = action.get("group", "arc_managed")
        group_path = os.path.join(root, group_name)
        try:
            os.makedirs(group_path, exist_ok=True)
            if "cpu_quota" in action:  # e.g. 50000 (us) with period 100000
                with open(os.path.join(group_path, "cpu.max"), "w") as f:
                    f.write(f"{int(action['cpu_quota'])} 100000")
            if "mem_max" in action:  # bytes, e.g. 512 * 1024**2
                with open(os.path.join(group_path, "memory.max"), "w") as f:
                    f.write(str(int(action["mem_max"])))
        except (OSError, PermissionError) as e:
            return ActionResult("skipped", [], f"cgroup setup failed (need root?): {e}")
        targets = self.resolve(action, sample)
        if not targets:
            return ActionResult("skipped", [], f"no process matched {action.get('target')}")
        changes = []
        for t in targets:
            try:
                with open(os.path.join(group_path, "cgroup.procs"), "w") as f:
                    f.write(str(t.pid))
                changes.append(
                    AppliedChange("cgroup_limit", t.pid, t.create_time, prev={"cgroup": base}, new={"cgroup": group_name})
                )
            except OSError as e:
                return ActionResult("failed", changes, str(e))
        self.journal.append({"op": "apply", "action": "cgroup_limit", "pids": [c.pid for c in changes], "ts": time.time()})
        return ActionResult("applied", changes)

    def _log_only(self, action: dict, sample: SystemSample) -> ActionResult:
        return ActionResult("applied", [], action.get("message", "log action"))

    # -- restoration -------------------------------------------------------

    def restore(self, change: AppliedChange) -> bool:
        if not change.target_still_valid():
            self.journal.append({"op": "restore", "action": change.action_type, "pid": change.pid, "ts": time.time(), "dead": True})
            return False
        try:
            p = psutil.Process(change.pid)
            if change.action_type == "set_nice":
                p.nice(change.prev["nice"])
            elif change.action_type == "set_affinity":
                p.cpu_affinity(change.prev["cpus"])
            elif change.action_type == "suspend":
                cont = getattr(signal, "SIGCONT", None)
                if cont is None:
                    return False
                os.kill(change.pid, cont)  # restoring means "running again"
            elif change.action_type == "resume":
                pass  # resume has no inverse other than suspend; lifecycle handles ordering
            elif change.action_type == "cgroup_limit":
                try:
                    with open("/sys/fs/cgroup/cgroup.procs", "w") as f:
                        f.write(str(change.pid))
                except OSError:
                    return False
            self.journal.append({"op": "restore", "action": change.action_type, "pid": change.pid, "ts": time.time()})
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as e:
            self.journal.append({"op": "restore", "action": change.action_type, "pid": change.pid, "ts": time.time(), "error": str(e)})
            return False


def summarize_changes(changes: list) -> list[dict]:
    return [
        {"action": c.action_type, "pid": c.pid, "prev": c.prev, "new": c.new, "detail": c.detail}
        for c in changes
    ]
