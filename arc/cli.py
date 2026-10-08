"""ARC command-line interface.

Commands:
  validate   - check a contract file against the schema
  run        - run the engine against the live system
  simulate   - replay a synthetic scenario through the same engine
  selftest   - built-in end-to-end smoke test (safe, no privileges needed)
  status     - print capability report for the current platform
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__
from .actions import BaseExecutor, SystemExecutor
from .contracts import ContractError, load_contracts
from .engine import ArcEngine
from .logger import ExecutionLog
from .monitors import SyntheticMonitor
from .platform_compat import capabilities


def cmd_validate(args) -> int:
    try:
        contracts = load_contracts(args.contracts)
    except (ContractError, OSError, json.JSONDecodeError) as e:
        print(f"INVALID: {e}")
        return 1
    for c in contracts:
        print(f"OK  {c.name:<22} trigger={c.trigger.type:<18} actions={[a['type'] for a in c.actions]} restore={c.restore_mode}")
    print(f"{len(contracts)} contract(s) valid.")
    return 0


def _run_engine(args, monitor, executor, log_dir, echo=True):
    contracts = load_contracts(args.contracts)
    log = ExecutionLog(log_dir=log_dir, echo=echo)
    engine = ArcEngine(contracts, monitor=monitor, executor=executor, log=log,
                       interval=args.interval)
    engine.run(duration=args.duration)
    return engine


def cmd_run(args) -> int:
    executor = SystemExecutor()
    engine = _run_engine(args, monitor=None, executor=executor, log_dir=args.log_dir)
    print("summary:", json.dumps(engine.log.summary()))
    return 0


def cmd_simulate(args) -> int:
    import os
    with open(args.scenario, encoding="utf-8") as f:
        scenario = json.load(f)
    speed = args.speed
    steps = scenario["steps"]
    monitor = SyntheticMonitor(steps, speed=speed, start_procs=scenario.get("start_procs", []))
    executor = SystemExecutor() if args.real_actions else BaseExecutor()
    total_t = max((s["t"] for s in steps), default=1.0) / speed
    if args.duration is None:
        # Default: just past the end of the virtual timeline (never runs forever).
        args.duration = total_t + 2.0
    engine = _run_engine(args, monitor=monitor, executor=executor, log_dir=args.log_dir)
    print("simulation finished; virtual timeline:", round(total_t, 2), "s")
    print("summary:", json.dumps(engine.log.summary()))
    engine.log.close()
    return 0


def cmd_demo(args) -> int:
    """Guided, cross-platform demonstration of the full ARC story.

    Pure Python (no bash): runs identically on Windows, WSL, macOS and Linux.
    """
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    contracts = args.contracts or os.path.join(root, "contracts", "examples", "full_suite.yaml")
    scenario = args.scenario or os.path.join(root, "demo", "scenario_compile_battery.json")

    banner = "=" * 68
    print(f"{banner}\n  ARC LIVE DEMO  -  Adaptive Resource Contract Engine\n"
          f"  trigger -> actions -> restoration, on this machine, right now\n{banner}")

    print("\n[1/4] Platform capability report")
    args.func = None
    rc = cmd_status(args)
    if rc:
        return rc

    print("\n[2/4] Contract validation")
    class _A:  # tiny args shim
        pass
    a = _A()
    a.contracts = contracts
    rc = cmd_validate(a)
    if rc:
        return rc

    print("\n[3/4] Scenario replay (compiler appears, CPU rises, battery drops)")
    s = _A()
    s.contracts = contracts
    s.scenario = scenario
    s.speed = args.speed
    s.interval = 1.0
    s.duration = None
    s.log_dir = args.log_dir
    s.real_actions = False
    cmd_simulate(s)

    print("\n[4/4] Built-in end-to-end selftest")
    cmd_selftest(args)

    print(f"\n{banner}\n  NEXT:  python3 -m arc web --contracts {os.path.relpath(contracts, root)}"
          f"\n         open http://localhost:8777 and run: python3 demo/generate_load.py 15\n"
          f"         to watch contracts fire on the live dashboard\n{banner}")
    return 0


def cmd_status(args) -> int:
    caps = capabilities()
    print(f"ARC {__version__} platform capability report")
    for k, v in caps.items():
        print(f"  {k:<16} {v}")
    return 0


def cmd_web(args) -> int:
    """Run the engine together with the live dashboard (for demonstrations)."""
    from .actions import SystemExecutor
    from .web import serve

    contracts = load_contracts(args.contracts)
    log = ExecutionLog(log_dir=args.log_dir, echo=True)
    engine = ArcEngine(contracts, monitor=None, executor=SystemExecutor(), log=log,
                       interval=args.interval)
    httpd = serve(engine, host=args.host, port=args.port)
    print(f"\n  ARC live dashboard:  http://localhost:{args.port}")
    print(f"  (open in a browser; generate load in another terminal to watch contracts fire)\n")
    try:
        engine.run(duration=args.duration)
    except KeyboardInterrupt:
        print("\ninterrupted; restoring any applied policies ...")
    finally:
        httpd.shutdown()
    return 0


def cmd_selftest(args) -> int:
    """Deterministic end-to-end check using a synthetic scenario + dry run."""
    scenario = {
        "start_procs": [{"pid": 2001, "name": "idle-daemon", "cmdline": "idle-daemon --quiet"}],
        "steps": [
            {"t": 1.0, "op": "proc_add", "pid": 2002, "name": "cc1plus", "cmdline": "cc1plus -O2 main.c"},
            {"t": 6.0, "op": "proc_del", "pid": 2002},
        ],
    }
    contracts = [{
        "name": "selftest-compile",
        "description": "selftest",
        "trigger": {"type": "process_appears", "match": "cc1plus", "debounce_sec": 0.2},
        "actions": [
            {"type": "set_nice", "target": {"match": "cc1plus"}, "nice": -5},
            {"type": "set_nice", "target": {"match": "idle-daemon"}, "nice": 10},
        ],
        "restore": {"mode": "on_trigger_clear"},
        "cooldown_sec": 0.5,
    }]
    from .contracts import validate_contract_dict
    cs = [validate_contract_dict(c, i) for i, c in enumerate(contracts)]
    monitor = SyntheticMonitor(scenario["steps"], speed=2.0, start_procs=scenario["start_procs"])
    journal: list = []
    log = ExecutionLog(echo=True)
    engine = ArcEngine(cs, monitor=monitor, executor=BaseExecutor(journal=journal), log=log, interval=0.25)
    engine.run(duration=5.0)
    applies = [j for j in journal if j["op"] == "apply"]
    restores = [j for j in journal if j["op"] == "restore"]
    ok = len(applies) >= 2 and len(restores) >= 2
    print(f"\nSELFTEST {'PASSED' if ok else 'FAILED'} (applies={len(applies)}, restores={len(restores)})")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arc", description="Adaptive Resource Contract Engine")
    p.add_argument("--version", action="version", version=f"arc {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="validate a contract file")
    v.add_argument("contracts")
    v.set_defaults(func=cmd_validate)

    for name, fn in (("run", cmd_run), ("simulate", cmd_simulate)):
        sp = sub.add_parser(name)
        sp.add_argument("--contracts", required=True, help="YAML contract file")
        sp.add_argument("--interval", type=float, default=1.0)
        sp.add_argument("--duration", type=float, default=None, help="stop after N seconds")
        sp.add_argument("--log-dir", default="logs")
        if name == "simulate":
            sp.add_argument("--scenario", required=True, help="JSON scenario file")
            sp.add_argument("--speed", type=float, default=1.0, help="virtual-time acceleration")
            sp.add_argument("--real-actions", action="store_true",
                            help="really apply actions to matched live processes")
        sp.set_defaults(func=fn)

    st = sub.add_parser("status", help="platform capability report")
    st.set_defaults(func=cmd_status)

    wb = sub.add_parser("web", help="run engine + live dashboard for demos")
    wb.add_argument("--contracts", required=True)
    wb.add_argument("--interval", type=float, default=1.0)
    wb.add_argument("--duration", type=float, default=None)
    wb.add_argument("--log-dir", default="logs")
    wb.add_argument("--port", type=int, default=8777)
    wb.add_argument("--host", default="0.0.0.0")
    wb.set_defaults(func=cmd_web)

    dm = sub.add_parser("demo", help="guided cross-platform demonstration (pure Python)")
    dm.add_argument("--contracts", default=None)
    dm.add_argument("--scenario", default=None)
    dm.add_argument("--speed", type=float, default=3.0)
    dm.add_argument("--log-dir", default="logs")
    dm.set_defaults(func=cmd_demo)

    se = sub.add_parser("selftest", help="built-in end-to-end smoke test")
    se.set_defaults(func=cmd_selftest)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "run" and args.duration is None:
        args.duration = None  # run until interrupted
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted; restoring any applied policies ...")
        return 130
    except ContractError as e:
        print(f"contract error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
