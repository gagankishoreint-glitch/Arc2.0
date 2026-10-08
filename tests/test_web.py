import json
import os
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arc.actions import BaseExecutor
from arc.contracts import validate_contract_dict
from arc.engine import ArcEngine
from arc.logger import ExecutionLog
from arc.monitors import SyntheticMonitor
from arc.web import Dashboard, serve


def make_engine():
    c = validate_contract_dict({
        "name": "web-demo",
        "trigger": {"type": "process_appears", "match": "cc1plus", "debounce_sec": 0.1},
        "actions": [{"type": "set_nice", "target": {"match": "cc1plus"}, "nice": 5}],
        "restore": {"mode": "on_trigger_clear"},
        "cooldown_sec": 0.1,
    })
    mon = SyntheticMonitor(
        [{"t": 0.2, "op": "proc_add", "pid": 9001, "name": "cc1plus", "cmdline": "cc1plus a.c"}],
        speed=3.0,
    )
    return ArcEngine([c], monitor=mon, executor=BaseExecutor(), log=ExecutionLog(echo=False),
                     interval=0.2)


class TestDashboard:
    def test_state_shape(self):
        eng = make_engine()
        state = Dashboard(eng).state()
        for key in ("ts", "caps", "metrics", "contracts", "events", "samples"):
            assert key in state
        assert state["contracts"][0]["name"] == "web-demo"
        assert state["contracts"][0]["state"] in ("IDLE", "PENDING", "ACTIVE", "RESTORING")

    def test_http_endpoint_and_live_transition(self):
        eng = make_engine()
        t = threading.Thread(target=lambda: eng.run(duration=3.0), daemon=True)
        t.start()
        httpd = serve(eng, host="127.0.0.1", port=0)  # random free port
        port = httpd.server_address[1]
        time.sleep(1.2)  # let the synthetic trigger fire
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as r:
            state = json.loads(r.read())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            html = r.read().decode()
        httpd.shutdown()
        t.join(timeout=5)
        assert "<title>ARC" in html
        assert state["contracts"][0]["activations"] >= 1
        kinds = [e["event"] for e in state["events"]]
        assert "TRIGGER_ON" in kinds and "ACTIONS_APPLIED" in kinds
