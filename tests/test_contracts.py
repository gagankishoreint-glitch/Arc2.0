import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from arc.contracts import (
    ContractError,
    trigger_holds,
    validate_contract_dict,
    load_contracts,
)
from arc.events import BatteryInfo, ProcessInfo, SystemSample

HERE = os.path.dirname(os.path.abspath(__file__))
SUITE = os.path.join(HERE, "..", "contracts", "examples", "full_suite.yaml")


def make_sample(procs=None, cpu=10.0, mem=40.0, load1=1.0, battery=BatteryInfo(80.0, True)):
    return SystemSample(ts=0.0, cpu_percent=cpu, mem_percent=mem, load1=load1,
                        battery=battery, procs=procs or [])


def proc(name, cmdline=None, pid=1, **kw):
    return ProcessInfo(pid=pid, name=name, cmdline=cmdline or name,
                       cpu_percent=kw.pop("cpu_percent", 0.1),
                       mem_percent=kw.pop("mem_percent", 0.1),
                       nice=kw.pop("nice", 0), status="running",
                       create_time=1.0, num_threads=1)


def minimal(**over):
    d = {
        "name": "t1",
        "trigger": {"type": "process_appears", "match": "gcc"},
        "actions": [{"type": "set_nice", "target": {"match": "gcc"}, "nice": 5}],
    }
    d.update(over)
    return d


class TestValidation:
    def test_example_suite_loads(self):
        contracts = load_contracts(SUITE)
        names = {c.name for c in contracts}
        assert {"compile-boost", "cpu-hot-guard", "battery-saver", "memory-guard"} <= names

    def test_minimal_valid(self):
        c = validate_contract_dict(minimal())
        assert c.name == "t1"
        assert c.restore_mode == "on_trigger_clear"

    def test_missing_name(self):
        with pytest.raises(ContractError):
            validate_contract_dict({"trigger": {"type": "process_appears", "match": "x"}, "actions": [{"type": "log"}]})

    def test_bad_trigger_type(self):
        with pytest.raises(ContractError):
            validate_contract_dict(minimal(trigger={"type": "telepathy"}))

    def test_bad_regex(self):
        with pytest.raises(ContractError):
            validate_contract_dict(minimal(trigger={"type": "process_appears", "match": "([unclosed"}))

    def test_timeout_needs_seconds(self):
        with pytest.raises(ContractError):
            validate_contract_dict(minimal(restore={"mode": "after_timeout"}))

    def test_action_needs_target(self):
        with pytest.raises(ContractError):
            validate_contract_dict(minimal(actions=[{"type": "set_nice", "nice": 5}]))


class TestTriggerEval:
    def test_process_appears(self):
        t = validate_contract_dict(minimal()).trigger
        assert trigger_holds(t, make_sample([proc("bash")])) is False
        assert trigger_holds(t, make_sample([proc("gcc", "gcc -c a.c")])) is True

    def test_metric_threshold(self):
        d = minimal(trigger={"type": "metric_threshold", "metric": "cpu_percent", "op": ">=", "threshold": 80})
        t = validate_contract_dict(d).trigger
        assert trigger_holds(t, make_sample(cpu=79.9)) is False
        assert trigger_holds(t, make_sample(cpu=85.0)) is True

    def test_battery_below_requires_unplugged(self):
        d = minimal(trigger={"type": "battery_below", "threshold": 25})
        t = validate_contract_dict(d).trigger
        assert trigger_holds(t, make_sample(battery=BatteryInfo(20.0, True))) is False
        assert trigger_holds(t, make_sample(battery=BatteryInfo(20.0, False))) is True
        assert trigger_holds(t, make_sample(battery=BatteryInfo(None, None))) is False

    def test_process_disappears(self):
        d = minimal(trigger={"type": "process_disappears", "match": "render"})
        t = validate_contract_dict(d).trigger
        assert trigger_holds(t, make_sample([proc("render")])) is False
        assert trigger_holds(t, make_sample([proc("bash")])) is True
