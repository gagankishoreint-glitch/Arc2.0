"""Core data types shared across the ARC engine: samples and events."""

from __future__ import annotations

import dataclasses
import enum
import time
from typing import Optional


class EventKind(str, enum.Enum):
    """Events emitted by the engine and recorded in the execution log."""

    TRIGGER_ON = "TRIGGER_ON"
    TRIGGER_OFF = "TRIGGER_OFF"
    ACTIONS_APPLIED = "ACTIONS_APPLIED"
    RESTORED = "RESTORED"
    ACTION_SKIPPED = "ACTION_SKIPPED"
    WARN = "WARN"
    ENGINE_START = "ENGINE_START"
    ENGINE_STOP = "ENGINE_STOP"


@dataclasses.dataclass
class ProcessInfo:
    """Snapshot of a single process at sampling time."""

    pid: int
    name: str
    cmdline: str
    cpu_percent: float
    mem_percent: float
    nice: Optional[int]
    status: str
    create_time: float
    num_threads: int = 1

    def matches(self, regex) -> bool:
        """True if the regex matches the process name or command line."""
        return bool(regex.search(self.name) or regex.search(self.cmdline))


@dataclasses.dataclass
class BatteryInfo:
    percent: Optional[float]
    plugged: Optional[bool]
    secs_left: Optional[float] = None


@dataclasses.dataclass
class SystemSample:
    """One observation of the whole system, produced by a monitor."""

    ts: float
    cpu_percent: float
    mem_percent: float
    load1: Optional[float]
    battery: BatteryInfo
    procs: list

    def find_procs(self, regex, exclude_pids=None):
        exclude_pids = exclude_pids or set()
        return [p for p in self.procs if p.pid not in exclude_pids and p.matches(regex)]


@dataclasses.dataclass
class Event:
    """Internal engine event, later serialised into the execution log."""

    kind: EventKind
    contract: str
    ts: float
    payload: dict = dataclasses.field(default_factory=dict)


def now() -> float:
    return time.time()
