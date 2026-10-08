"""ARC terminal dashboard - the live demo centerpiece.

    python3 -m arc dashboard --contracts contracts/examples/full_suite.yaml

A full-screen terminal UI (rich) showing system gauges, per-contract
lifecycle state, the live event stream, and a CPU/event history ribbon.
It runs the engine in-process, so one command produces the whole closed
loop in motion: monitor -> detect -> decide -> enforce -> restore.

Works over SSH, screen share, or a projector - no browser, no ports.
Falls back to a plain refresh loop if `rich` is not installed.
"""

from __future__ import annotations

import time
from collections import deque

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    HAS_RICH = True
except ImportError:  # pragma: no cover - fallback path
    HAS_RICH = False

SPARK = "▁▂▃▄▅▆▇█"
EVT_MARK = {"TRIGGER_ON": "▲", "TRIGGER_OFF": "▼", "RESTORED": "✔",
            "ACTIONS_APPLIED": "●", "WARN": "!"}
EVT_COLOR = {"TRIGGER_ON": "bold yellow", "TRIGGER_OFF": "bold blue",
             "ACTIONS_APPLIED": "bold cyan", "RESTORED": "bold green",
             "ACTION_SKIPPED": "magenta", "WARN": "bold red",
             "ENGINE_START": "dim", "ENGINE_STOP": "dim"}


def _sparkline(values) -> str:
    if not values:
        return ""
    out = []
    for v in values:
        idx = int(max(0.0, min(100.0, v)) / 100 * len(SPARK))
        out.append(SPARK[min(idx, len(SPARK) - 1)])
    return "".join(out)


def _fmt_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    return f"{int(seconds) // 60}m{int(seconds) % 60:02d}s"


class TerminalDashboard:
    """Renders live engine state; call run() in the main thread."""

    def __init__(self, engine, title: str = "ARC  ·  Adaptive Resource Contract Engine"):
        self.engine = engine
        self.title = title
        self.cpu_hist: deque = deque(maxlen=64)
        self.evt_hist: deque = deque(maxlen=64)
        self._seen_events = 0

    # ------------------------------------------------------------------ #
    def _system_line(self):
        s = self.engine.last_sample
        if s is None:
            return Text("waiting for first sample...", style="dim")
        bat = s.battery
        if bat.percent is None:
            bat_s = "AC (no battery sensor)"
        else:
            bat_s = f"{bat.percent:.0f}% ({'AC' if bat.plugged else 'BAT'})"
        t = Text()
        t.append("  System   ", style="bold white")
        t.append(f"CPU {s.cpu_percent:4.0f}%   ", style="bold cyan" if s.cpu_percent < 85 else "bold red")
        t.append(f"MEM {s.mem_percent:4.0f}%   ", style="bold cyan" if s.mem_percent < 85 else "bold red")
        t.append(f"LOAD {('%0.2f' % s.load1) if s.load1 is not None else 'n/a':>4}   ", style="white")
        t.append(f"BAT {bat_s}", style="bold green" if (bat.percent is None or bat.plugged) else "bold yellow")
        t.append(f"        samples {self.engine.samples_seen}", style="dim")
        return t

    def _contracts_panel(self):
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="left")
        now_mono = time.monotonic()
        for rt in self.engine.contracts:
            state = rt.state.value
            if state == "ACTIVE":
                dot, style = "●", "bold green"
                extra = f"({len(rt.applied_changes)} changes · {_fmt_elapsed(now_mono - rt.activated_at)})"
            elif state == "PENDING":
                dot, style = "●", "bold yellow"
                held = (now_mono - rt.met_since) if rt.met_since else 0
                hold = rt.contract.trigger.for_sec if rt.contract.trigger.type == "metric_threshold" else rt.contract.trigger.debounce_sec
                extra = f"hold {max(0.0, hold - held):0.1f}s remaining"
            elif state == "RESTORING":
                dot, style = "●", "bold blue"
                extra = "reverting snapshots"
            else:
                dot, style = "○", "dim"
                extra = "—"
            n_actions = len(rt.contract.actions)
            table.add_row(
                Text(f"{dot} {rt.contract.name}", style=style),
                Text(f"{state:<11}", style=style),
                Text(f"{n_actions} action{'s' if n_actions != 1 else ''}", style="white"),
                Text(extra, style="dim"),
            )
        return Panel(table, title="Contracts", border_style="blue", padding=(0, 1))

    def _events_panel(self, height: int = 9):
        entries = self.engine.log.entries[-height:]
        text = Text()
        for e in entries:
            kind = e.get("event", "?")
            text.append(f"  {e.get('wall', '')}  ", style="dim")
            text.append(f"{kind:<15}", style=EVT_COLOR.get(kind, "white"))
            text.append(f"{e.get('contract', ''):<18}", style="white")
            text.append(self._detail(e), style="dim")
            text.append("\n")
        return Panel(text or Text("  waiting for events...", style="dim"),
                     title="Live Events", border_style="blue", padding=(0, 1))

    @staticmethod
    def _detail(e: dict) -> str:
        if "targets" in e:
            tg = e["targets"] or []
            act = e.get("action", "")
            if tg:
                pids = ",".join(str(t.get("pid", "?")) for t in tg[:4])
                bits = []
                if tg and "new" in tg[0]:
                    bits.append(" ".join(f"{k}={v}" for k, v in (tg[0]["new"] or {}).items()))
                return f"{act} ×{len(tg)} pid[{pids}] {' '.join(bits)}".strip()
            return f"{act} (no targets)"
        if "restored" in e:
            return f"{e['restored']}/{e['of']} exact"
        if "reason" in e:
            return str(e["reason"])[:70]
        if "note" in e:
            return str(e["note"])[:70]
        return ""

    def _history_panel(self):
        text = Text()
        text.append("  CPU  ", style="bold white")
        text.append(_sparkline(self.cpu_hist) + "\n", style="cyan")
        text.append("  EVT  ", style="bold white")
        marks = list(self.evt_hist)
        text.append("  ".join(m if m != "·" else "·" for m in marks), style="yellow")
        return Panel(text, title="History", border_style="blue", padding=(0, 1))

    def _tick_history(self):
        s = self.engine.last_sample
        self.cpu_hist.append(s.cpu_percent if s else 0.0)
        entries = self.engine.log.entries
        mark = "·"
        for e in entries[self._seen_events:]:
            mark = EVT_MARK.get(e.get("event", ""), "·") if mark == "·" else mark
        self._seen_events = len(entries)
        self.evt_hist.append(mark)

    def build(self):
        self._tick_history()
        header = Panel(self._system_line(), title=self.title, border_style="bold blue",
                       padding=(0, 1))
        return Group(header, self._contracts_panel(), self._events_panel(), self._history_panel())

    # ------------------------------------------------------------------ #
    def run(self, interval: float = 0.5, duration: float | None = None, screen: bool = True):
        deadline = time.monotonic() + duration if duration else None
        if not HAS_RICH:
            return self._run_plain(interval, deadline)
        console = Console()
        with Live(self.build(), console=console, refresh_per_second=4, screen=screen) as live:
            while True:
                time.sleep(interval)
                live.update(self.build())
                if not any(t.is_alive() for t in self._threads()):
                    break
                if deadline and time.monotonic() >= deadline:
                    break
        console.print(self.build())

    def _threads(self):
        import threading
        return [t for t in threading.enumerate() if t.name.startswith("arc-")]

    def _run_plain(self, interval: float, deadline):
        """Degraded mode when `rich` is missing - same data, plain text."""
        import os
        while True:
            if os.name == "posix":
                os.system("clear" if os.environ.get("TERM") != "dumb" else "true")
            print("ARC  ·  Adaptive Resource Contract Engine (plain mode)\n")
            print(" System  ", self._plain_system())
            for rt in self.engine.contracts:
                print(f"  {rt.state.value:<10} {rt.contract.name}")
            print("\n Events")
            for e in self.engine.log.entries[-8:]:
                print(f"  {e.get('wall','')}  {e.get('event',''):<15} {e.get('contract','')}")
            print("\n CPU  " + _sparkline(self.cpu_hist))
            self._tick_history()
            time.sleep(interval)
            if not any(t.is_alive() for t in self._threads()):
                break
            if deadline and time.monotonic() >= deadline:
                break

    def _plain_system(self):
        s = self.engine.last_sample
        if not s:
            return "(sampling...)"
        return (f"CPU {s.cpu_percent:.0f}%  MEM {s.mem_percent:.0f}%  "
                f"LOAD {s.load1 if s.load1 is not None else 'n/a'}  "
                f"BAT {s.battery.percent if s.battery.percent is not None else 'AC'}")
