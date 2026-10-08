# ARC: Adaptive Resource Contract Engine

An event-driven, user-space policy engine for Linux, WSL, macOS and Windows.
ARC monitors runtime system conditions and maintains user-defined resource
contracts: when a condition holds, resource actions are enforced; when it
stops holding, the previous state is restored automatically.

Operating Systems course project (BCSE303L), School of Computer Science,
Engineering and Information Systems.

---

## Overview

Modern operating systems expose fine-grained resource controls — scheduling
priorities (`nice`, `renice`), CPU affinity (`sched_setaffinity`), control
groups, and process control — but they do not coordinate them. Deciding *when*
to apply a change, *which* processes it should affect, and *when* to undo it is
left to administrators and one-off scripts.

ARC adds a policy layer above these mechanisms. A **resource contract** is a
standing declaration of intent with three parts: a trigger condition, one or
more resource-management actions, and a restoration rule. The user writes the
contract once; the engine evaluates it continuously against live system state
and closes the loop on its own.

```
        runtime system state
                |
           [ monitor ]        samples CPU, memory, process activity, battery
                |
          [ detector ]        trigger conditions tested every tick
                |
        [ contract engine ]   IDLE -> PENDING -> ACTIVE -> RESTORING
                |
         [ executor ]         nice / affinity / suspend / cgroup limits
                |
        resource state -------> back to monitoring
                |
        [ execution log ]     every decision recorded and auditable
```

Compared with existing approaches, the distinction is who participates in the
loop:

| | Manual commands | Rule tools (Ananicy, oomd, TuneD) | ARC |
|---|---|---|---|
| Watches live system state | user | partial / single-purpose | engine, continuously |
| Trigger conditions | none | app identity or one metric | processes, metrics, battery |
| Target selection | typed PIDs | fixed rules | resolved from live state |
| Automatic restoration | none | none | exact, PID-safe |
| Closed policy loop | no | no | yes |

---

## Installation

Requirements: Python 3.10 or newer.

```bash
git clone https://github.com/gagankishoreint-glitch/Arc2.0.git
cd Arc2.0
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt pytest
```

A virtual environment is required on macOS (Homebrew Python is
externally-managed) and recommended everywhere.

---

## Running ARC

| Command | Purpose |
|---|---|
| `python3 -m arc status` | Platform capability report |
| `python3 -m arc validate <file>` | Validate a contract file |
| `python3 -m arc run --contracts <file>` | Enforce contracts on the live system |
| `python3 -m arc dashboard --contracts <file>` | Terminal UI: engine plus live visualisation |
| `python3 -m arc web --contracts <file>` | Browser UI on http://localhost:8777 |
| `python3 -m arc simulate --scenario <json>` | Deterministic scenario replay (no privileges) |
| `python3 -m arc demo` | Guided demonstration, identical on all platforms |
| `python3 -m arc selftest` | Built-in end-to-end smoke test |

A first session typically looks like this:

```bash
python3 -m arc status                                    # what this machine supports
python3 -m arc validate contracts/examples/full_suite.yaml
python3 -m arc dashboard --contracts contracts/examples/full_suite.yaml
```

Then, in a second terminal, `python3 demo/generate_load.py 15` to generate CPU
pressure and watch the `cpu-hot-guard` contract fire, act, and restore.

Run the test suite with `python3 -m pytest tests/ -q` (40 tests). The
experiment suite from the report is reproduced by
`sudo python3 experiments/run_experiments.py`.

---

## Writing contracts

Contracts are plain YAML; policy changes never require code changes.

```yaml
contracts:
  - name: compile-boost
    description: Prioritise compilation while a compiler is running.
    trigger:
      type: process_appears          # process_appears | process_disappears
      match: "gcc|cc1plus|make"      #   | metric_threshold | battery_below
      debounce_sec: 1.0
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

Trigger conditions are predicates over live state (process table, CPU, memory,
load, battery), evaluated every sampling interval. Action targets are resolved
by regex against the process table at enforcement time, so the same contract
adapts to whichever processes happen to be running. At activation, ARC
snapshots the current priority, affinity, and state of every target; at
restoration it reverts them exactly, validating PIDs against process
create-times to guard against PID reuse.

Sample contracts covering compilation boosting, CPU-overload guarding, battery
saving and memory-pressure handling are provided in
`contracts/examples/full_suite.yaml`. The full schema reference lives in
[docs/HOW_ARC_WORKS.md](docs/HOW_ARC_WORKS.md).

---

## Demonstrating ARC

Two live visualisations run the same engine:

- **Terminal dashboard** (`arc dashboard`) — a full-screen view of system
  gauges, per-contract lifecycle state, a streaming event feed
  (TRIGGER_ON, ACTIONS_APPLIED, TRIGGER_OFF, RESTORED) and a CPU history
  ribbon. Works over SSH, screen share and projectors; no browser or ports.
- **Web dashboard** (`arc web`) — the same state as an offline single-page UI.

Deterministic scenario replay (`arc demo`, `arc simulate`) demonstrates the
identical engine on any machine without privileges. Per-platform, three-minute
demo scripts for WSL, macOS, Windows and Ubuntu are in
[DEMO_GUIDE.md](DEMO_GUIDE.md).

---

## Platform support

ARC runs on four environments from one code base. Capabilities are detected at
startup; unsupported or unprivileged actions are logged as skipped rather than
failing.

| Capability | Ubuntu Linux | WSL | macOS | Windows native |
|---|---|---|---|---|
| Monitoring (CPU, memory, processes) | full | full | full | full |
| Battery trigger | yes | yes (Windows interop bridge) | yes | yes |
| Set or restore priority | full (sudo tier) | full (sudo tier) | deprioritise; sudo tier | full (priority classes) |
| CPU affinity | yes | yes | skipped | yes |
| Suspend and resume | yes | yes | yes | skipped |
| cgroup limits | root | root | skipped | skipped |
| Demo commands (`demo`, `web`, `simulate`) | yes | yes | yes | yes |

**Privilege tiers.** Unprivileged runs can deprioritise workloads and complete
full affinity and suspend lifecycles. Raising priority, restoring a raised
priority on POSIX systems, and cgroup control require elevated privileges; ARC
clamps such changes safely and records why. Run the engine with `sudo` for the
complete contract lifecycle.

---

## Experimental results

Measured on Linux (2 logical CPUs, 2 GB RAM) with the reproducible suite in
`experiments/`; raw data and charts are in `experiments/results/`.

| Experiment | Result |
|---|---|
| Trigger-to-enforcement latency | 202 ms at 0.2 s sampling; jitter below 6 ms |
| Engine overhead | 1.4 percent CPU, 18.6 MB RAM at 1 Hz sampling |
| Restoration correctness | 40 of 40 trials exact (priority and affinity) |
| Enforcement efficacy | protected workload CPU share 67 to 99.6 percent under contention |
| Live contract lifecycle | 304 ms trigger to action; exact restoration |
| Memory-pressure contract | triggers under real allocation load; restores after clearance |

---

## Repository layout

```
arc/                 engine: monitor, contracts, actions, engine, logger, web, cli
contracts/examples/  sample YAML contracts
tests/               40 unit and integration tests
demo/                scenario files and portable CPU load generator
experiments/         experiment suite and measured results
docs/                final report, presentation, figures, design notes
scripts/             report and presentation builders
```

Documentation index:

- [docs/ARC_Final_Report.docx](docs/ARC_Final_Report.docx) — final project report
- [docs/ARC_Final_Presentation.pptx](docs/ARC_Final_Presentation.pptx) — presentation deck
- [docs/HOW_ARC_WORKS.md](docs/HOW_ARC_WORKS.md) — contract model and the dynamic policy loop
- [DEMO_GUIDE.md](DEMO_GUIDE.md) — per-platform demonstration scripts
- [GAP_ANALYSIS.md](GAP_ANALYSIS.md) — gap review and optimisation notes
- [AUDIT.md](AUDIT.md) — audit trail and review checklist

---

## Project

Course: BCSE303L, Operating Systems.
Team: Gagan Kishore (24BDE0073), Shikhar Sahay (24BYB0029).
Guide: Dr. Balasubramani M.

Released under the MIT License (see LICENSE).
