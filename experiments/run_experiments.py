"""ARC performance experiments (Review 3: Experimentation & Results).

Produces real measurements used in the final report and presentation:
  E1  trigger->enforcement latency at different sampling intervals
  E2  engine CPU / memory overhead
  E3  restoration correctness (exact revert of nice + affinity)
  E4  enforcement efficacy: effect of nice levels on CPU share
  E5  full live contract lifecycle (trigger -> actions -> restore)
  E6  memory-pressure contract under real load

Run:  sudo python3 experiments/run_experiments.py
Outputs land in experiments/results/ (JSON + CSV + PNG + RESULTS.md).
"""

from __future__ import annotations

import csv
import json
import os
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psutil

from arc import platform_compat as cap
from arc.actions import SystemExecutor
from arc.contracts import validate_contract_dict
from arc.engine import ArcEngine
from arc.logger import ExecutionLog
from arc.monitors import RealMonitor, spawn_dummy

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS, exist_ok=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable


def save(name, obj):
    path = os.path.join(RESULTS, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
    print(f"  saved {path}")


def worker_script(cpu_seconds: float = 0.005) -> str:
    return (
        "import time\n"
        "n = 0\n"
        "end = time.time() + 10000\n"
        "while time.time() < end:\n"
        f"    t = time.time() + {cpu_seconds}\n"
        "    while time.time() < t:\n"
        "        n += 1\n"
        "print(n)\n"
    )


def spawn_cpu_hog(name: str = "arc-hog"):
    return spawn_dummy(name, [PY, "-c", worker_script()])


def sleeper_script(marker: str) -> str:
    return f"# {marker}\nimport time\nwhile True: time.sleep(0.1)\n"


# ---------------------------------------------------------------- E1
def e1_latency(n_trials: int = 10):
    """Latency from process spawn (ground truth) to first enforced action.

    Two modes: debounce=0 (fast path, response within one sampling interval)
    and debounce=0.2s (anti-flap, adds one evaluation interval by design).
    """
    print("\n[E1] trigger->enforcement latency")
    out = {}
    for interval in (0.2, 0.5, 1.0):
        for debounce in (0.0, 0.2):
            latencies = []
            for i in range(n_trials):
                contract = validate_contract_dict({
                    "name": "lat",
                    "trigger": {"type": "process_appears", "match": "arc-target-marker",
                                "debounce_sec": debounce},
                    "actions": [{"type": "set_nice", "target": {"match": "arc-target-marker"}, "nice": 5}],
                    "restore": {"mode": "on_trigger_clear"},
                    "cooldown_sec": 0.05,
                })
                log = ExecutionLog(echo=False)
                eng = ArcEngine([contract], monitor=RealMonitor(), executor=SystemExecutor(),
                                log=log, interval=interval)
                import threading
                t = threading.Thread(target=lambda: eng.run(duration=interval * 3 + 1.5))
                t.start()
                time.sleep(interval + 0.1)          # let the sampler settle
                spawn_ts = time.time()
                p = spawn_dummy("arc-target", [PY, "-c", sleeper_script("arc-target-marker")])
                t.join()
                p.kill()
                applied = [e for e in log.entries if e["event"] == "ACTIONS_APPLIED"]
                if applied:
                    latencies.append(applied[0]["ts"] - spawn_ts)
                eng.shutdown()
            key = f"{interval}s|debounce={debounce}"
            out[key] = {
                "n": len(latencies),
                "mean_ms": round(statistics.mean(latencies) * 1000, 1) if latencies else None,
                "stdev_ms": round(statistics.stdev(latencies) * 1000, 1) if len(latencies) > 1 else None,
                "min_ms": round(min(latencies) * 1000, 1) if latencies else None,
                "max_ms": round(max(latencies) * 1000, 1) if latencies else None,
                "raw_s": [round(x, 4) for x in latencies],
            }
            print(f"  {key:<22} mean={out[key]['mean_ms']}ms  "
                  f"stdev={out[key]['stdev_ms']}ms  n={len(latencies)}")
    save("e1_latency.json", out)
    return out


# ---------------------------------------------------------------- E2
def e2_overhead():
    """Engine CPU and memory overhead while monitoring a busy process table."""
    print("\n[E2] engine overhead")
    hogs = [spawn_cpu_hog(f"arc-noise-{i}") for i in range(20)]
    time.sleep(0.5)
    benign = os.path.join(RESULTS, "benign_contracts.yaml")
    with open(benign, "w") as f:
        f.write(
            "contracts:\n"
            "  - name: idle-watch\n"
            "    trigger: {type: process_appears, match: never-matches-this-xyz}\n"
            "    actions: [{type: log, message: noop}]\n"
        )
    out = {}
    for interval in (0.5, 1.0, 2.0):
        cmd = [PY, "-m", "arc", "run", "--contracts", benign, "--interval", str(interval),
               "--duration", "20", "--log-dir", os.path.join(RESULTS, "logs")]
        proc = psutil.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL)
        watcher = psutil.Process(proc.pid)
        time.sleep(2.0)
        watcher.cpu_percent(None)  # prime
        samples, rss = [], []
        for _ in range(8):
            time.sleep(2.0)
            samples.append(watcher.cpu_percent(None))
            rss.append(watcher.memory_info().rss / 1e6)
        proc.wait()
        out[str(interval)] = {
            "cpu_percent_mean": round(statistics.mean(samples), 2),
            "cpu_percent_max": round(max(samples), 2),
            "rss_mb_mean": round(statistics.mean(rss), 1),
        }
        print(f"  interval={interval}s  cpu={out[str(interval)]['cpu_percent_mean']}%  "
              f"rss={out[str(interval)]['rss_mb_mean']}MB")
    for h in hogs:
        h.kill()
    save("e2_overhead.json", out)
    return out


# ---------------------------------------------------------------- E3
def e3_restoration(n_trials: int = 40):
    """Exact restoration of nice + affinity after contract deactivation."""
    print("\n[E3] restoration correctness")
    ex = SystemExecutor()
    monitor = RealMonitor()
    ok = fail = 0
    for i in range(n_trials):
        p = spawn_dummy(f"arc-restore-{i}", [PY, "-c", "import time\nwhile True: time.sleep(0.1)"])
        time.sleep(0.15)
        s = monitor.sample()
        before = psutil.Process(p.pid).nice()
        before_aff = psutil.Process(p.pid).cpu_affinity() if cap.supports_affinity() else None
        r1 = ex.apply({"type": "set_nice", "target": {"pid": p.pid}, "nice": 10}, s)
        r2 = (ex.apply({"type": "set_affinity", "target": {"pid": p.pid}, "cpus": [0]}, s)
              if cap.supports_affinity() else None)
        changes = r1.changes + (r2.changes if r2 else [])
        restored = all(ex.restore(c) for c in reversed(changes))
        after = psutil.Process(p.pid).nice()
        after_aff = psutil.Process(p.pid).cpu_affinity() if cap.supports_affinity() else None
        exact = restored and after == before and after_aff == before_aff
        ok += bool(exact)
        fail += (not exact)
        p.kill()
    out = {"trials": n_trials, "exact_restores": ok, "failures": fail,
           "rate_percent": round(100 * ok / n_trials, 1)}
    print(f"  exact restores: {ok}/{n_trials} ({out['rate_percent']}%)")
    save("e3_restoration.json", out)
    return out


# ---------------------------------------------------------------- E4
def e4_nice_efficacy(window: float = 8.0):
    """Effect of scheduling priority on CPU share under contention."""
    print("\n[E4] nice efficacy under contention")
    counts = {}
    for label, worker_nice, hog_nice in (
        ("all-nice-0", 0, 0),
        ("worker--5-hogs-0", -5, 0),
        ("worker-0-hogs-19", 0, 19),
        ("worker-19-hogs-0", 19, 0),
    ):
        hogs = [spawn_cpu_hog(f"e4-hog-{j}") for j in range(2)]
        w = spawn_dummy("e4-worker", [PY, "-c", worker_script(0.001)])
        time.sleep(0.4)
        try:
            if worker_nice != 0:
                psutil.Process(w.pid).nice(worker_nice)
            if hog_nice != 0:
                for h in hogs:
                    psutil.Process(h.pid).nice(hog_nice)
        except psutil.AccessDenied as e:
            print("   (nice denied:", e, ")")
        # count worker loop progress via CPU time consumed
        t0 = psutil.Process(w.pid).cpu_times().user + psutil.Process(w.pid).cpu_times().system
        time.sleep(window)
        t1 = psutil.Process(w.pid).cpu_times().user + psutil.Process(w.pid).cpu_times().system
        counts[label] = round((t1 - t0) / window * 100, 1)  # effective % of one core
        print(f"  {label:<22} worker cpu share = {counts[label]}% of one core")
        w.kill()
        for h in hogs:
            h.kill()
        time.sleep(0.3)
    save("e4_nice_efficacy.json", {"window_s": window, "worker_cpu_share_percent": counts})
    return {"window_s": window, "worker_cpu_share_percent": counts}


# ---------------------------------------------------------------- E5
def e5_live_lifecycle():
    """Full live contract: boost a 'compiler', deprioritise a background hog,
    restore everything when the compiler exits."""
    print("\n[E5] live contract lifecycle (real processes, real actions)")
    log = ExecutionLog(log_dir=os.path.join(RESULTS, "logs"), echo=True, prefix="e5")
    contract = validate_contract_dict({
        "name": "compile-boost-live",
        "trigger": {"type": "process_appears", "match": "arc-compiler", "debounce_sec": 0.05},
        "actions": [
            {"type": "set_nice", "target": {"match": "arc-compiler"}, "nice": -5},
            {"type": "set_nice", "target": {"match": "arc-background"}, "nice": 10},
        ],
        "restore": {"mode": "on_trigger_clear"},
        "cooldown_sec": 0.2,
    })
    bg = spawn_dummy("arc-background", [PY, "-c", sleeper_script("arc-background")])
    time.sleep(0.2)
    bg_nice_before = psutil.Process(bg.pid).nice()
    eng = ArcEngine([contract], monitor=RealMonitor(), executor=SystemExecutor(), log=log, interval=0.2)
    import threading
    th = threading.Thread(target=lambda: eng.run(duration=14.0))
    th.start()
    time.sleep(1.5)
    spawn_ts = time.time()
    compiler = spawn_dummy("arc-compiler", [PY, "-c", sleeper_script("arc-compiler")])
    time.sleep(4.0)
    compiler.kill()
    th.join()
    bg_nice_after = psutil.Process(bg.pid).nice()
    bg.kill()

    events = {e["event"]: [] for e in log.entries}
    for e in log.entries:
        events.setdefault(e["event"], []).append(e["ts"])
    latency = None
    if events.get("ACTIONS_APPLIED"):
        latency = round((events["ACTIONS_APPLIED"][0] - spawn_ts) * 1000, 1)
    restored = events.get("RESTORED", [])
    out = {
        "trigger_to_action_ms": latency,
        "restored_events": len(restored),
        "background_nice_before": bg_nice_before,
        "background_nice_after_restore": bg_nice_after,
        "restore_exact": bg_nice_before == bg_nice_after,
        "timeline": log.entries,
    }
    print(f"  trigger->action latency: {latency}ms; restore exact: {out['restore_exact']}")
    save("e5_lifecycle.json", out)
    return out


# ---------------------------------------------------------------- E6
def e6_memory_guard():
    """Memory-pressure contract under real allocation load."""
    print("\n[E6] memory-pressure contract")
    hog_code = (
        "# arc-memhog\n"
        "import time\n"
        "x = bytearray(900 * 1024 * 1024)\n"
        "for i in range(0, len(x), 4096):\n"
        "    x[i] = 1\n"
        "time.sleep(30)\n"
    )
    contract = validate_contract_dict({
        "name": "memory-guard-live",
        "trigger": {"type": "metric_threshold", "metric": "mem_percent", "op": ">=", "threshold": 55, "for_sec": 2.0},
        "actions": [{"type": "set_nice", "target": {"match": "arc-memhog"}, "nice": 10}],
        "restore": {"mode": "on_trigger_clear"},
        "cooldown_sec": 1.0,
    })
    log = ExecutionLog(log_dir=os.path.join(RESULTS, "logs"), echo=True, prefix="e6")
    eng = ArcEngine([contract], monitor=RealMonitor(), executor=SystemExecutor(), log=log, interval=0.5)
    import threading
    th = threading.Thread(target=lambda: eng.run(duration=28.0))
    th.start()
    time.sleep(1.0)
    mem_before = psutil.virtual_memory().percent
    hog = spawn_dummy("arc-memhog", [PY, "-c", hog_code])
    time.sleep(12.0)
    mem_peak = psutil.virtual_memory().percent
    hog_nice_mid = psutil.Process(hog.pid).nice()
    hog.kill()
    th.join()
    events = {}
    for e in log.entries:
        events.setdefault(e["event"], []).append(e)
    out = {
        "mem_percent_before": mem_before,
        "mem_percent_peak": mem_peak,
        "triggered": bool(events.get("TRIGGER_ON")),
        "hog_nice_during": hog_nice_mid,
        "restored": bool(events.get("RESTORED")),
        "timeline": log.entries,
    }
    print(f"  mem {mem_before}% -> {mem_peak}%, triggered={out['triggered']}, "
          f"hog nice={hog_nice_mid}, restored={out['restored']}")
    save("e6_memory_guard.json", out)
    return out


# ---------------------------------------------------------------- summary
def write_summary(all_results: dict):
    lines = ["# ARC Experiment Results", "",
             f"Machine: {psutil.cpu_count()} logical CPUs, "
             f"{round(psutil.virtual_memory().total / 1e9, 1)} GB RAM, platform={cap.capabilities()['platform']}, "
             f"elevated={cap.can_raise_priority()}", ""]
    lines += ["## E1 Trigger->enforcement latency", "",
              "| sampling interval | mean (ms) | stdev (ms) | min | max |", "|---|---|---|---|---|"]
    for k, v in all_results["e1"].items():
        lines.append(f"| {k}s | {v['mean_ms']} | {v['stdev_ms']} | {v['min_ms']} | {v['max_ms']} |")
    lines += ["", "## E2 Engine overhead (20 background processes)", "",
              "| sampling interval | CPU % (mean) | CPU % (max) | RSS (MB) |", "|---|---|---|---|"]
    for k, v in all_results["e2"].items():
        lines.append(f"| {k}s | {v['cpu_percent_mean']} | {v['cpu_percent_max']} | {v['rss_mb_mean']} |")
    r = all_results["e3"]
    lines += ["", "## E3 Restoration correctness", "",
              f"- Exact restores: **{r['exact_restores']}/{r['trials']} ({r['rate_percent']}%)** (nice + affinity)", ""]
    lines += ["## E4 Enforcement efficacy (worker CPU share under contention)", "",
              "| configuration | worker CPU share (% of one core) |", "|---|---|"]
    for k, v in all_results["e4"]["worker_cpu_share_percent"].items():
        lines.append(f"| {k} | {v} |")
    e5 = all_results["e5"]
    lines += ["", "## E5 Live contract lifecycle", "",
              f"- trigger -> first action: **{e5['trigger_to_action_ms']} ms**",
              f"- restoration events: {e5['restored_events']}",
              f"- background nice {e5['background_nice_before']} -> restored {e5['background_nice_after_restore']} "
              f"(exact: {e5['restore_exact']})", ""]
    e6 = all_results["e6"]
    lines += ["## E6 Memory-pressure contract", "",
              f"- memory {e6['mem_percent_before']}% -> peak {e6['mem_percent_peak']}%",
              f"- contract triggered: {e6['triggered']}, hog nice during enforcement: {e6['hog_nice_during']}, "
              f"- restored after pressure cleared: {e6['restored']}", ""]
    path = os.path.join(RESULTS, "RESULTS.md")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print("  saved", path)


def make_charts(all_results):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # E1 latency chart
    keys = list(all_results["e1"].keys())
    means = [all_results["e1"][k]["mean_ms"] for k in keys]
    stds = [all_results["e1"][k]["stdev_ms"] or 0 for k in keys]
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    ax.bar(range(len(keys)), means, yerr=stds, capsize=5,
           color=["#2b6cb0" if "debounce=0.0" in k else "#718096" for k in keys])
    ax.set_xticks(range(len(keys)))
    ax.set_xticklabels(keys, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("trigger -> enforcement latency (ms)")
    ax.set_title("E1: Detection latency vs sampling interval & debounce")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "e1_latency.png"), dpi=150)
    plt.close(fig)

    # E2 overhead
    ivals = list(all_results["e2"].keys())
    cpu = [all_results["e2"][k]["cpu_percent_mean"] for k in ivals]
    fig, ax = plt.subplots(figsize=(6, 3.6))
    ax.bar([f"{k}s" for k in ivals], cpu, color="#2f855a")
    ax.set_xlabel("sampling interval")
    ax.set_ylabel("engine CPU usage (%)")
    ax.set_title("E2: ARC engine overhead")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "e2_overhead.png"), dpi=150)
    plt.close(fig)

    # E4 nice efficacy
    labels = list(all_results["e4"]["worker_cpu_share_percent"].keys())
    vals = [all_results["e4"]["worker_cpu_share_percent"][k] for k in labels]
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    ax.barh(labels, vals, color="#805ad5")
    ax.set_xlabel("worker CPU share (% of one core)")
    ax.set_title("E4: Effect of nice level on CPU share (3 CPU-bound tasks, 2 cores)")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "e4_nice.png"), dpi=150)
    plt.close(fig)

    # E5 timeline
    entries = all_results["e5"].get("timeline", [])
    key = {"TRIGGER_ON": 1, "ACTIONS_APPLIED": 2, "RESTORED": 3}
    rows = [(e["ts"], key.get(e["event"], 0), e["event"]) for e in entries if e["event"] in key]
    if rows:
        t0 = rows[0][0]
        fig, ax = plt.subplots(figsize=(7, 2.8))
        colors = {"TRIGGER_ON": "#d69e2e", "ACTIONS_APPLIED": "#2b6cb0", "RESTORED": "#2f855a"}
        for ts, y, name in rows:
            ax.scatter(ts - t0, [y], color=colors[name], s=90, zorder=3)
        ax.set_yticks([1, 2, 3])
        ax.set_yticklabels(["TRIGGER_ON", "ACTIONS_APPLIED", "RESTORED"])
        ax.set_xlabel("seconds since first event")
        ax.set_title("E5: Live contract lifecycle timeline")
        fig.tight_layout()
        fig.savefig(os.path.join(RESULTS, "e5_lifecycle.png"), dpi=150)
        plt.close(fig)
    print("  saved charts e1/e2/e4/e5 .png")


if __name__ == "__main__":
    print("ARC experiments - privileges elevated:", cap.can_raise_priority())
    results = {
        "e1": e1_latency(),
        "e2": e2_overhead(),
        "e3": e3_restoration(),
        "e4": e4_nice_efficacy(),
        "e5": e5_live_lifecycle(),
        "e6": e6_memory_guard(),
    }
    write_summary(results)
    make_charts(results)
    print("\nDONE - results in", RESULTS)
