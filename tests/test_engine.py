import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arc.actions import BaseExecutor
from arc.contracts import validate_contract_dict
from arc.engine import ArcEngine
from arc.logger import ExecutionLog
from arc.monitors import SyntheticMonitor


def engine_for(contract_dict, steps, start_procs=None, speed=4.0, interval=0.2):
    contract = validate_contract_dict(contract_dict)
    journal = []
    log = ExecutionLog(echo=False)
    monitor = SyntheticMonitor(steps, speed=speed, start_procs=start_procs or [])
    eng = ArcEngine([contract], monitor=monitor, executor=BaseExecutor(journal=journal),
                    log=log, interval=interval)
    return eng, journal, log


CONTRACT = {
    "name": "e2e",
    "trigger": {"type": "process_appears", "match": "cc1plus", "debounce_sec": 0.2},
    "actions": [
        {"type": "set_nice", "target": {"match": "cc1plus"}, "nice": -5},
        {"type": "set_nice", "target": {"match": "idle"}, "nice": 10},
    ],
    "restore": {"mode": "on_trigger_clear"},
    "cooldown_sec": 0.2,
}


class TestEndToEnd:
    def test_activate_and_restore(self):
        steps = [
            {"t": 0.5, "op": "proc_add", "pid": 3001, "name": "cc1plus", "cmdline": "cc1plus a.c"},
            {"t": 4.0, "op": "proc_del", "pid": 3001},
        ]
        eng, journal, log = engine_for(
            CONTRACT, steps, start_procs=[{"pid": 3002, "name": "idle", "cmdline": "idle"}]
        )
        eng.run(duration=6.0 / 4.0 + 1.0)  # speed=4 -> ~2.5s wall
        applies = [j for j in journal if j["op"] == "apply"]
        restores = [j for j in journal if j["op"] == "restore"]
        assert len(applies) == 2, journal   # both actions fired
        assert len(restores) == 2, journal  # both restored
        kinds = [e["event"] for e in log.entries]
        assert "TRIGGER_ON" in kinds and "RESTORED" in kinds

    def test_debounce_suppresses_flap(self):
        steps = [
            {"t": 0.5, "op": "proc_add", "pid": 3001, "name": "cc1plus"},
            {"t": 0.8, "op": "proc_del", "pid": 3001},  # gone before debounce 1.0
        ]
        contract = dict(CONTRACT)
        contract["trigger"] = {"type": "process_appears", "match": "cc1plus", "debounce_sec": 1.5}
        eng, journal, log = engine_for(contract, steps)
        eng.run(duration=4.0 / 4.0 + 1.0)
        assert not [j for j in journal if j["op"] == "apply"]

    def test_timeout_restore(self):
        steps = [
            {"t": 0.3, "op": "metric", "cpu_percent": 95.0},
            {"t": 10.0, "op": "metric", "cpu_percent": 10.0},
        ]
        contract = {
            "name": "timeout",
            "trigger": {"type": "metric_threshold", "metric": "cpu_percent", "op": ">=", "threshold": 90, "for_sec": 0.3},
            "actions": [{"type": "log", "message": "hot"}],
            "restore": {"mode": "after_timeout", "timeout_sec": 1.5},
            "cooldown_sec": 0.2,
        }
        # note: log-only action produces no changes; use set_nice on synthetic proc
        contract["actions"] = [{"type": "set_nice", "target": {"match": "worker"}, "nice": 19}]
        steps.append({"t": 0.0, "op": "proc_add", "pid": 4001, "name": "worker"})
        eng, journal, log = engine_for(contract, steps, speed=2.0)
        eng.run(duration=8.0)
        applies = [j for j in journal if j["op"] == "apply"]
        restores = [j for j in journal if j["op"] == "restore"]
        assert len(applies) >= 1
        assert len(restores) >= 1

    def test_shutdown_restores_active_policies(self):
        steps = [{"t": 0.2, "op": "proc_add", "pid": 5001, "name": "cc1plus"}]
        eng, journal, log = engine_for(CONTRACT, steps,
                                      start_procs=[{"pid": 5002, "name": "idle", "cmdline": "idle"}])
        eng.run(duration=1.5)  # engine exits while contract still active
        restores = [j for j in journal if j["op"] == "restore"]
        assert len(restores) == 2, "engine shutdown must restore applied changes"
