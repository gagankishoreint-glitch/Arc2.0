import os
import signal
import sys
import threading
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arc import platform_compat as cap
from arc.actions import SystemExecutor, _compile_rx
from arc.monitors import RealMonitor, parse_wsl_battery, wsl_battery
from arc.events import SystemSample, BatteryInfo, ProcessInfo


def sample_with_procs(procs):
    return SystemSample(ts=time.time(), cpu_percent=0, mem_percent=0, load1=0,
                        battery=BatteryInfo(None, None), procs=procs)


PROC = ProcessInfo(pid=4242, name="target", cmdline="target --x", cpu_percent=5.0,
                   mem_percent=1.0, nice=0, status="running", create_time=1.0)


class TestWindowsNativeSafety:
    """Windows native lacks SIGSTOP/SIGCONT - actions must skip, never crash."""

    def test_suspend_skips_when_signal_missing(self):
        with mock.patch.object(signal, "SIGSTOP", None):
            r = SystemExecutor().apply({"type": "suspend", "target": {"pid": 4242}},
                                       sample_with_procs([PROC]))
        assert r.status == "skipped"
        assert "unavailable" in r.message or "not supported" in r.message

    def test_resume_skips_when_signal_missing(self):
        with mock.patch.object(signal, "SIGCONT", None):
            r = SystemExecutor().apply({"type": "resume", "target": {"pid": 4242}},
                                       sample_with_procs([PROC]))
        assert r.status == "skipped"

    def test_suspend_restore_graceful_when_signal_missing(self):
        from arc.actions import AppliedChange
        ch = AppliedChange("suspend", 4242, 1.0, prev={}, new={})
        with mock.patch.object(signal, "SIGCONT", None):
            # target_still_valid fails first for this fake pid - either way must not raise
            ok = SystemExecutor().restore(ch)
        assert ok in (True, False)  # no exception is the contract


class TestWslBatteryBridge:
    def test_parse_valid(self):
        b = parse_wsl_battery("63,1")
        assert b.percent == 63.0 and b.plugged is False
        b = parse_wsl_battery("88,2")
        assert b.percent == 88.0 and b.plugged is True

    def test_parse_garbage(self):
        assert parse_wsl_battery("") == BatteryInfo(None, None)
        assert parse_wsl_battery("none") == BatteryInfo(None, None)
        assert parse_wsl_battery("oops") == BatteryInfo(None, None)

    def test_wsl_battery_uses_cache(self):
        calls = {"n": 0}

        def fake_ps(*a, **k):
            calls["n"] += 1
            class R:
                stdout = "50,1"
            return R()

        m = RealMonitor()  # constructed outside the patch (no WSL here)
        with mock.patch("arc.monitors.cap.is_wsl", return_value=True), \
             mock.patch("subprocess.run", side_effect=fake_ps):
            m._battery_cache = (BatteryInfo(None, None), 0.0)
            b1 = m._battery()
            b2 = m._battery()
        assert b1.percent == 50.0
        assert b2.percent == 50.0
        assert calls["n"] == 1  # second read served from cache


class TestPerfOptimizations:
    def test_regex_cache_hits(self):
        r1 = _compile_rx("gcc|make")
        r2 = _compile_rx("gcc|make")
        assert r1 is r2  # compiled once

    def test_logger_persistent_handles(self):
        from arc.logger import ExecutionLog
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            log = ExecutionLog(log_dir=d, echo=False)
            for i in range(5):
                log.record("TEST", "c", note=i)
            assert log.text_path and os.path.exists(log.text_path)
            assert len(log._handles) == 2  # jsonl + text, opened once
            log.close()
            assert log._handles == {}


class TestSimulateDuration:
    def test_simulate_defaults_to_finite_duration(self):
        import json, tempfile
        from arc.cli import main
        with tempfile.TemporaryDirectory() as d:
            scen = os.path.join(d, "s.json")
            with open(scen, "w") as f:
                json.dump({"steps": [{"t": 0.2, "op": "metric", "cpu_percent": 5.0}]}, f)
            contracts = os.path.join(d, "c.yaml")
            with open(contracts, "w") as f:
                f.write("contracts:\n  - name: x\n    trigger: {type: process_appears, match: zzz}\n"
                        "    actions: [{type: log, message: hi}]\n")
            t0 = time.time()
            rc = main(["simulate", "--contracts", contracts, "--scenario", scen,
                       "--speed", "20", "--log-dir", os.path.join(d, "logs")])
            assert rc == 0
            assert time.time() - t0 < 15  # must not run forever
