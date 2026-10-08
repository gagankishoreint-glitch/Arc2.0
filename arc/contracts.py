"""Contract model and per-contract lifecycle state machine.

A resource contract has three primary components (per the ARC design):
  * a trigger condition   - when the policy should activate,
  * one or more actions   - what resource changes to enforce,
  * a restoration rule    - when and how to revert those changes.

Lifecycle:  IDLE -> PENDING -> ACTIVE -> RESTORING -> IDLE (cooldown)
"""

from __future__ import annotations

import dataclasses
import re
import time
from enum import Enum
from typing import Optional

from .events import SystemSample

VALID_TRIGGER_TYPES = {"process_appears", "process_disappears", "metric_threshold", "battery_below"}
VALID_METRICS = {"cpu_percent", "mem_percent", "load1"}
VALID_ACTION_TYPES = {"set_nice", "set_affinity", "suspend", "resume", "cgroup_limit", "log"}
VALID_RESTORE_MODES = {"on_trigger_clear", "after_timeout", "never"}
OPS = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b, "<=": lambda a, b: a <= b, "==": lambda a, b: a == b}


class ContractError(ValueError):
    pass


class State(str, Enum):
    IDLE = "IDLE"
    PENDING = "PENDING"   # trigger seen, waiting out debounce / hold time
    ACTIVE = "ACTIVE"     # actions applied
    RESTORING = "RESTORING"


@dataclasses.dataclass
class Trigger:
    type: str
    match: Optional[str] = None
    metric: Optional[str] = None
    op: str = ">="
    threshold: Optional[float] = None
    for_sec: float = 0.0          # how long the condition must hold
    debounce_sec: float = 0.5     # anti-flap for process events
    _rx: Optional[re.Pattern] = dataclasses.field(default=None, repr=False)

    def compile(self):
        if self.match:
            self._rx = re.compile(self.match, re.IGNORECASE)
        return self


@dataclasses.dataclass
class Contract:
    name: str
    description: str
    trigger: Trigger
    actions: list
    restore_mode: str = "on_trigger_clear"
    restore_timeout_sec: Optional[float] = None
    cooldown_sec: float = 3.0
    enabled: bool = True


@dataclasses.dataclass
class ContractRuntime:
    """Mutable state owned by the engine for one contract."""

    contract: Contract
    state: State = State.IDLE
    met_since: Optional[float] = None
    clear_since: Optional[float] = None
    activated_at: Optional[float] = None
    applied_changes: list = dataclasses.field(default_factory=list)
    activations: int = 0
    restorations: int = 0
    last_error: str = ""
    cooldown_until: float = 0.0


# ---------------------------------------------------------------------------
# Trigger evaluation
# ---------------------------------------------------------------------------

def trigger_holds(trigger: Trigger, sample: SystemSample) -> bool:
    """Pure predicate: is the contract's trigger condition true right now?"""
    t = trigger
    if t.type == "process_appears":
        return len(sample.find_procs(t._rx)) > 0
    if t.type == "process_disappears":
        return len(sample.find_procs(t._rx)) == 0
    if t.type == "metric_threshold":
        value = {"cpu_percent": sample.cpu_percent, "mem_percent": sample.mem_percent, "load1": sample.load1}[t.metric]
        if value is None:
            return False
        return OPS[t.op](value, t.threshold)
    if t.type == "battery_below":
        b = sample.battery
        if b.percent is None:
            return False
        return b.percent < t.threshold and not b.plugged
    return False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_contract_dict(d: dict, index: int = 0) -> Contract:
    where = f"contract #{index + 1}" + (f" ({d.get('name')})" if d.get("name") else "")
    if not d.get("name"):
        raise ContractError(f"{where}: missing 'name'")
    trig = d.get("trigger")
    if not isinstance(trig, dict):
        raise ContractError(f"{where}: missing 'trigger' block")
    ttype = trig.get("type")
    if ttype not in VALID_TRIGGER_TYPES:
        raise ContractError(f"{where}: trigger.type must be one of {sorted(VALID_TRIGGER_TYPES)}")
    if ttype in ("process_appears", "process_disappears") and not trig.get("match"):
        raise ContractError(f"{where}: trigger.match regex required for {ttype}")
    if ttype == "metric_threshold":
        if trig.get("metric") not in VALID_METRICS:
            raise ContractError(f"{where}: trigger.metric must be one of {sorted(VALID_METRICS)}")
        if trig.get("op", ">=") not in OPS:
            raise ContractError(f"{where}: unknown trigger.op {trig.get('op')!r}")
        if trig.get("threshold") is None:
            raise ContractError(f"{where}: trigger.threshold required")
    if ttype == "battery_below" and trig.get("threshold") is None:
        raise ContractError(f"{where}: trigger.threshold required for battery_below")

    actions = d.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ContractError(f"{where}: 'actions' must be a non-empty list")
    for a in actions:
        if a.get("type") not in VALID_ACTION_TYPES:
            raise ContractError(f"{where}: unknown action.type {a.get('type')!r}")
        if a["type"] != "log" and not (a.get("target") or {}).get("match") and not (a.get("target") or {}).get("pid"):
            raise ContractError(f"{where}: action {a['type']} needs target.match or target.pid")

    restore = d.get("restore") or {}
    mode = restore.get("mode", "on_trigger_clear")
    if mode not in VALID_RESTORE_MODES:
        raise ContractError(f"{where}: restore.mode must be one of {sorted(VALID_RESTORE_MODES)}")
    if mode == "after_timeout" and not restore.get("timeout_sec"):
        raise ContractError(f"{where}: restore.timeout_sec required for after_timeout")

    try:
        trigger = Trigger(
            type=ttype,
            match=trig.get("match"),
            metric=trig.get("metric"),
            op=trig.get("op", ">="),
            threshold=trig.get("threshold"),
            for_sec=float(trig.get("for_sec", 0.0)),
            debounce_sec=float(trig.get("debounce_sec", 0.5)),
        ).compile()
    except re.error as e:
        raise ContractError(f"{where}: bad trigger.match regex: {e}") from e

    return Contract(
        name=str(d["name"]),
        description=str(d.get("description", "")),
        trigger=trigger,
        actions=actions,
        restore_mode=mode,
        restore_timeout_sec=restore.get("timeout_sec"),
        cooldown_sec=float(d.get("cooldown_sec", 3.0)),
        enabled=bool(d.get("enabled", True)),
    )


def load_contracts(path: str) -> list:
    import yaml

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or "contracts" not in data:
        raise ContractError("file must contain a top-level 'contracts' list")
    return [validate_contract_dict(c, i) for i, c in enumerate(data["contracts"])]
