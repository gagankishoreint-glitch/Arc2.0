# ARC — Adaptive Resource Contract Engine

**Event-driven OS policy engine for Linux / macOS / Windows (WSL)**
Operating Systems course project (BCSE303L) — School of Computer Science,
Engineering and Information Systems.

ARC monitors runtime system conditions (CPU, memory, process activity, battery)
and dynamically enforces **user-defined resource contracts**:

```
trigger condition  ->  resource actions  ->  automatic restoration
```

Instead of manually re-configuring priorities and affinities as the workload
changes, you declare *intent* once and ARC follows the workload's lifecycle.

---

## Quick start

**macOS / any PEP 668 Python (Homebrew, etc.) — use a virtual environment:**

```bash
cd Arc2.0
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest
```

Linux: `pip install -r requirements.txt` works directly.

```bash
python3 -m arc status                                   # platform capability report
python3 -m arc validate contracts/examples/full_suite.yaml
python3 -m arc demo                                     # guided demo - works on ALL platforms
python3 -m arc selftest                                 # end-to-end smoke test (safe)
python3 -m pytest tests/ -q                             # 36 tests

# LIVE VISUAL DASHBOARD - best for showing a demo (open http://localhost:8777)
python3 -m arc web --contracts contracts/examples/full_suite.yaml
python3 demo/generate_load.py 15   # in a second terminal - watch contracts fire

bash demo/run_demo.sh             # scripted demo (POSIX shells only)

# live enforcement (WSL/macOS/Ubuntu; use sudo for the full privilege tier)
sudo python3 -m arc run --contracts contracts/examples/full_suite.yaml --interval 1

# deterministic scenario replay on any OS (add --real-actions to really enforce)
python3 -m arc simulate --contracts contracts/examples/full_suite.yaml \
         --scenario demo/scenario_compile_battery.json --speed 3
```

Run the tests: `python3 -m pytest tests/` (36 tests).
Re-run the experiments: `sudo python3 experiments/run_experiments.py`.
Per-platform demo scripts: see **DEMO_GUIDE.md** (WSL / macOS / Windows / Ubuntu).

---

## Contract model

Contracts are plain YAML — no code changes needed to define policy:

```yaml
contracts:
  - name: compile-boost
    description: Prioritise compilation when a compiler appears.
    trigger:
      type: process_appears          # process_appears | process_disappears
      match: "gcc|cc1plus|make"      #   | metric_threshold | battery_below
      debounce_sec: 1.0              # anti-flap window
    actions:
      - type: set_nice               # set_nice | set_affinity | suspend | resume
        target: {match: "cc1plus"}   #   | cgroup_limit | log
        nice: -5
      - type: set_nice
        target: {match: "chromium"}
        nice: 10
    restore:
      mode: on_trigger_clear         # on_trigger_clear | after_timeout | never
    cooldown_sec: 5.0
```

Every applied change is snapshotted (previous nice value / affinity / state) and
**restored exactly** when the contract deactivates; PIDs are re-validated against
process create-times to guard against PID reuse.

## Architecture

```
runtime system state
        |  (psutil / /proc, every --interval seconds)
   [monitor]  --samples-->  [sampler thread]
                                |  events
                          [event queue]  <-- thread-safe
                                |
                        [contract engine]  (IDLE -> PENDING -> ACTIVE -> RESTORING)
                                |
                        [action executor]  (nice / affinity / suspend / cgroup)
                                |
                        Linux resource state ... and repeat
        +  [execution log]  JSONL + human-readable trace of every decision
```

Modules: `monitors.py` (observation), `contracts.py` (schema + state machine),
`actions.py` (enforcement + restore), `engine.py` (coordination & concurrency),
`logger.py` (observability), `platform_compat.py` (capability detection),
`cli.py` (interface). New trigger/action types plug into two registries without
touching the engine core.

## Live dashboard (for demos)

```bash
python3 -m arc web --contracts contracts/examples/full_suite.yaml --port 8777
```

Open http://localhost:8777 — a dark-theme, offline (no CDN) dashboard with:

- live CPU / memory / battery / load gauges,
- contract lifecycle badges (IDLE → PENDING → ACTIVE → RESTORING),
- managed-process table with **before → after** resource state,
- streaming event feed of every policy decision.

In a second terminal run `bash demo/generate_load.sh` (or a `make -j` build) and
watch ARC react live. Everything is inline HTML/JS/SVG — works on Linux, WSL,
macOS and Windows with no extra dependencies.

## Cross-platform support

| Capability | Linux/Ubuntu | WSL | macOS | Windows native |
|---|---|---|---|---|
| Monitoring (CPU/mem/procs) | full | full | full | full |
| Battery trigger | yes | **yes (Win32 interop bridge)** | yes | yes |
| set_nice (deprioritise) | yes | yes | yes | yes |
| set_nice (prioritise/restore) | root | root | root | yes (priority classes) |
| set_affinity | yes | yes | — (skipped) | yes |
| suspend / resume | yes | yes | yes | — (skipped) |
| cgroup limits | root | root | — (skipped) | — (skipped) |
| `arc demo` / `web` / `simulate` | yes | yes | yes | yes (pure Python) |
| dry-run simulate | yes | yes | yes | yes |

Unsupported or unprivileged operations are logged as `ACTION_SKIPPED` /
`WARN` and the engine keeps running — never crashes.

**Privilege tiers:** unprivileged runs can deprioritise workloads and fully use
affinity/suspend lifecycles; restoring a *raised* nice value (and negative nice,
cgroups) requires elevated privileges — run the daemon with `sudo` for the full
contract lifecycle, like other rule-based daemons (ananicy, systemd-oomd).

## Experiments & results

`experiments/run_experiments.py` reproduces the report's numbers
(`experiments/results/` holds JSON, CSV, charts, `RESULTS.md`):

| ID | Experiment | Headline result |
|---|---|---|
| E1 | trigger→enforcement latency | ≈ sampling interval (202 ms @ 0.2 s); stdev < 1 ms |
| E2 | engine overhead | 1.4 % CPU @ 1 Hz, 18.6 MB RSS |
| E3 | restoration correctness | 40 / 40 exact restores (100 %) |
| E4 | nice efficacy under contention | 67 % → 99.6 % CPU share when prioritised |
| E5 | live contract lifecycle | 304 ms trigger→action, exact restore |
| E6 | memory-pressure contract | triggers at 55 % mem, restores after clearance |

## Project structure

```
arc/                  engine package (monitor, contracts, actions, engine, logger, web, cli)
contracts/examples/   sample YAML contracts
tests/                36 unit + integration tests (pytest)
demo/                 scenario demo + portable CPU load generator
experiments/          E1-E6 experiment suite + results/
docs/                 final report (docx) + presentation (pptx) + figures
DEMO_GUIDE.md         3-minute demo scripts per platform (WSL/macOS/Windows/Ubuntu)
GAP_ANALYSIS.md       gap review & optimization report
AUDIT.md              audit trail & review-3 checklist
push_to_github.sh     one-shot publish script
```

## Academic note

Course: BCSE303L Operating Systems. Team: Gagan Kishore (24BDE0073),
Shikhar Sahay (24BYB0029), under the guidance of Dr. Balasubramani M.
Please keep citations and academic-integrity rules in any derived documents.
