import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psutil
import pytest

from arc import platform_compat as cap
from arc.actions import AppliedChange, SystemExecutor
from arc.monitors import RealMonitor, spawn_dummy


@pytest.fixture
def dummy():
    p = spawn_dummy()
    time.sleep(0.3)
    yield p
    if p.is_running():
        p.kill()
    try:
        p.wait(timeout=3)
    except psutil.TimeoutExpired:
        pass


class TestResolve:
    def sample_with(self, *procs):
        from arc.events import SystemSample, BatteryInfo
        return SystemSample(ts=time.time(), cpu_percent=0, mem_percent=0, load1=0,
                            battery=BatteryInfo(None, None), procs=list(procs))

    def test_match_and_exclude_self(self, dummy):
        m = RealMonitor()
        ex = SystemExecutor()
        s = m.sample()
        action = {"type": "set_nice", "target": {"match": "python"}}
        found = ex.resolve(action, s)
        pids = {p.pid for p in found}
        assert os.getpid() not in pids
        assert dummy.pid in pids


class TestNiceRestore:
    def test_apply_and_restore_nice(self, dummy):
        ex = SystemExecutor()
        m = RealMonitor()
        s = m.sample()
        before = psutil.Process(dummy.pid).nice()
        result = ex.apply({"type": "set_nice", "target": {"match": "python"}, "nice": 10}, s)
        assert result.status == "applied"
        change = next(c for c in result.changes if c.pid == dummy.pid)
        assert psutil.Process(dummy.pid).nice() == 10
        restored = ex.restore(change)
        if cap.can_raise_priority():
            assert restored is True
            assert psutil.Process(dummy.pid).nice() == before
        else:
            # Documented limitation: lowering nice needs privileges on POSIX.
            assert restored is False

    def test_unprivileged_cannot_raise_priority(self, dummy):
        if cap.can_raise_priority():
            pytest.skip("running privileged")
        ex = SystemExecutor()
        m = RealMonitor()
        s = m.sample()
        result = ex.apply({"type": "set_nice", "target": {"pid": dummy.pid}, "nice": -10}, s)
        assert result.status == "applied"
        change = result.changes[0]
        assert change.new["nice"] == change.prev["nice"]  # clamped

    def test_pid_reuse_guard(self, dummy):
        ex = SystemExecutor()
        m = RealMonitor()
        s = m.sample()
        result = ex.apply({"type": "set_nice", "target": {"pid": dummy.pid}, "nice": 5}, s)
        change = result.changes[0]
        change.create_time = change.create_time - 999  # simulate pid reuse
        assert change.target_still_valid() is False


class TestAffinity:
    def test_apply_and_restore_affinity(self, dummy):
        if not cap.supports_affinity():
            pytest.skip("affinity unsupported on this platform")
        ex = SystemExecutor()
        m = RealMonitor()
        s = m.sample()
        n = cap.cpu_count()
        target_cpu = [n - 1]
        result = ex.apply({"type": "set_affinity", "target": {"pid": dummy.pid}, "cpus": target_cpu}, s)
        assert result.status == "applied"
        assert psutil.Process(dummy.pid).cpu_affinity() == target_cpu
        assert ex.restore(result.changes[0]) is True
        assert len(psutil.Process(dummy.pid).cpu_affinity()) == n


class TestSuspendResume:
    def test_suspend_resume(self, dummy):
        if not cap.supports_suspend():
            pytest.skip("signals unsupported on this platform")
        ex = SystemExecutor()
        m = RealMonitor()
        s = m.sample()
        r1 = ex.apply({"type": "suspend", "target": {"pid": dummy.pid}}, s)
        assert r1.status == "applied"
        time.sleep(0.2)
        assert psutil.Process(dummy.pid).status() == psutil.STATUS_STOPPED
        r2 = ex.apply({"type": "resume", "target": {"pid": dummy.pid}}, s)
        assert r2.status == "applied"
        time.sleep(0.2)
        assert psutil.Process(dummy.pid).status() != psutil.STATUS_STOPPED
