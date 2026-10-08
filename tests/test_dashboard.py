import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arc.actions import BaseExecutor
from arc.contracts import validate_contract_dict
from arc.dashboard import TerminalDashboard, _sparkline, HAS_RICH
from arc.engine import ArcEngine
from arc.logger import ExecutionLog
from arc.monitors import SyntheticMonitor


def make_engine():
    c = validate_contract_dict({
        "name": "dash-demo",
        "trigger": {"type": "process_appears", "match": "cc1plus", "debounce_sec": 0.1},
        "actions": [{"type": "set_nice", "target": {"match": "cc1plus"}, "nice": 5}],
        "restore": {"mode": "on_trigger_clear"},
        "cooldown_sec": 0.1,
    })
    mon = SyntheticMonitor(
        [{"t": 0.2, "op": "proc_add", "pid": 9100, "name": "cc1plus", "cmdline": "cc1plus a.c"},
         {"t": 2.4, "op": "proc_del", "pid": 9100}],
        speed=3.0,
    )
    return ArcEngine([c], monitor=mon, executor=BaseExecutor(), log=ExecutionLog(echo=False),
                     interval=0.2)


class TestTerminalDashboard:
    def test_sparkline(self):
        assert _sparkline([]) == ""
        assert _sparkline([0.0]) == "▁"
        assert _sparkline([100.0]) == "█"
        assert len(_sparkline([10.0, 50.0, 90.0])) == 3

    def test_render_smoke(self):
        eng = make_engine()
        dash = TerminalDashboard(eng)
        th = threading.Thread(target=lambda: eng.run(duration=3.0), daemon=True)
        th.start()
        time.sleep(1.0)  # let the contract activate
        frame = dash.build()
        assert frame is not None
        entries = eng.log.entries
        th.join(timeout=5)
        kinds = [e["event"] for e in entries]
        assert "TRIGGER_ON" in kinds
        assert "RESTORED" in kinds

    def test_trigger_off_emitted_on_clear(self):
        eng = make_engine()
        eng.run(duration=3.5)
        kinds = [e["event"] for e in eng.log.entries]
        assert "TRIGGER_OFF" in kinds, kinds
        # lifecycle order: ON ... OFF ... RESTORED
        assert kinds.index("TRIGGER_ON") < kinds.index("TRIGGER_OFF") < kinds.index("RESTORED")

    def test_plain_fallback_renders(self):
        eng = make_engine()
        dash = TerminalDashboard(eng)
        th = threading.Thread(target=lambda: eng.run(duration=2.0), daemon=True)
        th.start()
        time.sleep(0.8)
        line = dash._plain_system()  # must never raise
        assert isinstance(line, str)
        th.join(timeout=5)
