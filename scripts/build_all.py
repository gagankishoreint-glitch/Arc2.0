"""Generate architecture/state diagrams and build the final report (.docx)
and presentation (.pptx). Run: python3 scripts/build_all.py
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DOCS = os.path.join(ROOT, "docs")
RESULTS = os.path.join(ROOT, "experiments", "results")
os.makedirs(DOCS, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


# --------------------------------------------------------------------- diagrams
def box(ax, x, y, w, h, text, fc="#ebf4ff", ec="#2b6cb0", fs=9, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012",
                                fc=fc, ec=ec, lw=1.4))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
            fontweight="bold" if bold else "normal", color="#1a365d")


def arrow(ax, x1, y1, x2, y2, label="", color="#4a5568", rad=0.0):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                 mutation_scale=14, lw=1.4, color=color,
                                 connectionstyle=f"arc3,rad={rad}"))
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.035, label, ha="center",
                fontsize=7.5, color=color)


def make_architecture(path):
    fig, ax = plt.subplots(figsize=(9.2, 4.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5.6)
    ax.axis("off")
    ax.text(5, 5.35, "ARC Architecture: monitor -> detect -> decide -> enforce -> restore",
            ha="center", fontsize=11, fontweight="bold", color="#1a365d")

    box(ax, 0.15, 2.2, 1.5, 1.2, "Runtime\nsystem state\n(CPU/mem/procs/\nbattery)", fc="#e2e8f0", fs=8)
    box(ax, 2.0, 2.4, 1.35, 0.85, "Monitor\n(psutil, /proc)", bold=True)
    box(ax, 3.7, 2.4, 1.35, 0.85, "Event\ndetector", bold=True)
    box(ax, 5.4, 2.4, 1.55, 0.85, "Contract engine\n(IDLE->PENDING->\nACTIVE->RESTORING)", fs=7.5, bold=True)
    box(ax, 7.3, 2.4, 1.35, 0.85, "Action\nexecutor", bold=True)
    box(ax, 9.0, 2.2, 0.85, 1.2, "Linux\nresource\nstate", fc="#e2e8f0", fs=8)

    for x1, x2 in ((1.65, 2.0), (3.35, 3.7), (5.05, 5.4), (6.95, 7.3), (8.65, 9.0)):
        arrow(ax, x1, 2.82, x2, 2.82)

    box(ax, 5.4, 0.7, 1.55, 0.9, "Execution log\n(JSONL + text)", fc="#f0fff4", ec="#2f855a", fs=8)
    box(ax, 3.3, 0.7, 1.6, 0.9, "Snapshots\nfor restoration", fc="#f0fff4", ec="#2f855a", fs=8)
    arrow(ax, 5.6, 2.4, 5.9, 1.6, "", "#2f855a")
    arrow(ax, 7.5, 2.4, 4.6, 1.6, "prev state", "#2f855a")
    arrow(ax, 5.4, 2.2, 1.0, 2.2, "monitor again", "#4a5568", rad=-0.25)

    box(ax, 2.0, 4.05, 5.9, 0.72, "sampler thread  ->  thread-safe event queue  ->  coordinator (RLock)  -  actions never race monitoring",
        fc="#fffaf0", ec="#b7791f", fs=7.5)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def make_state_machine(path):
    fig, ax = plt.subplots(figsize=(8.6, 3.2))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3.6)
    ax.axis("off")
    ax.text(5, 3.35, "Contract lifecycle state machine", ha="center", fontsize=11,
            fontweight="bold", color="#1a365d")

    states = [
        (0.4, 1.2, "IDLE\n(condition false)"),
        (2.8, 1.2, "PENDING\n(condition held:\ndebounce/for_sec)"),
        (5.2, 1.2, "ACTIVE\n(actions applied,\nstate snapshotted)"),
        (7.7, 1.2, "RESTORING\n(revert snapshots,\nverify PIDs)"),
    ]
    for x, y, t in states:
        box(ax, x, y, 1.9, 1.15, t, fc="#ebf4ff", fs=8)
    arrow(ax, 2.3, 1.78, 2.8, 1.78, "trigger met")
    arrow(ax, 4.7, 1.78, 5.2, 1.78, "evaluate +\napply")
    arrow(ax, 7.1, 1.78, 7.7, 1.78, "clear /\ntimeout")
    arrow(ax, 8.65, 1.2, 1.35, 1.2, "restored (cooldown)", rad=0.25)
    arrow(ax, 3.75, 1.2, 3.2, 1.2, "flapped back", rad=-0.3, color="#a0aec0")
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


# --------------------------------------------------------------------- data
def load_results():
    data = {}
    for name in ("e1_latency", "e2_overhead", "e3_restoration", "e4_nice_efficacy",
                 "e5_lifecycle", "e6_memory_guard"):
        with open(os.path.join(RESULTS, f"{name}.json")) as f:
            data[name.replace("_", "-").split("-")[0]] = json.load(f)
    # data keys: e1..e6
    return data


# --------------------------------------------------------------------- report
def build_report(data):
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    def h(text, level=1):
        doc.add_heading(text, level=level)

    def p(text, bold=False, italic=False, size=11, align=None):
        par = doc.add_paragraph()
        run = par.add_run(text)
        run.bold = bold
        run.italic = italic
        run.font.size = Pt(size)
        if align == "center":
            par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        return par

    def bullets(items):
        for it in items:
            doc.add_paragraph(it, style="List Bullet")

    def figure(path, caption, width=6.0):
        if os.path.exists(path):
            doc.add_picture(path, width=Inches(width))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap = doc.add_paragraph(caption)
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for r in cap.runs:
            r.italic = True
            r.font.size = Pt(9)

    def table(headers, rows, widths=None):
        t = doc.add_table(rows=1 + len(rows), cols=len(headers))
        t.style = "Light Grid Accent 1"
        for j, htxt in enumerate(headers):
            cell = t.rows[0].cells[j]
            cell.text = htxt
            for r in cell.paragraphs[0].runs:
                r.bold = True
                r.font.size = Pt(9.5)
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                cell = t.rows[i + 1].cells[j]
                cell.text = str(val)
                for r in cell.paragraphs[0].runs:
                    r.font.size = Pt(9.5)
        doc.add_paragraph()

    # ---------------- title page
    for _ in range(4):
        doc.add_paragraph()
    p("ADAPTIVE RESOURCE CONTRACT ENGINE (ARC)", bold=True, size=22, align="center")
    p("Event-Driven OS Policy Engine", size=15, align="center")
    doc.add_paragraph()
    p("Course Project Report — BCSE303L Operating Systems", align="center")
    doc.add_paragraph()
    p("Submitted by", align="center")
    p("Gagan Kishore (24BDE0073)", align="center")
    p("Shikhar Sahay (24BYB0029)", align="center")
    doc.add_paragraph()
    p("Under the guidance of", align="center")
    p("Dr. Balasubramani M", align="center")
    doc.add_paragraph()
    p("SCHOOL OF COMPUTER SCIENCE, ENGINEERING AND INFORMATION SYSTEMS", bold=True, align="center")
    doc.add_page_break()

    # ---------------- abstract
    h("Abstract", 1)
    p("Modern operating systems expose several mechanisms for controlling system resources, "
      "including CPU scheduling priorities, CPU affinity, process control, and control groups (cgroups). "
      "While these mechanisms offer fine-grained control over individual processes and can be modified "
      "dynamically, they do not inherently provide a unified policy layer that adapts resource allocation "
      "to changing runtime conditions. This report presents the Adaptive Resource Contract Engine (ARC), "
      "an event-driven user-space policy engine that continuously monitors system conditions such as CPU "
      "utilization, memory usage, process activity, and battery status, and automatically enforces "
      "user-defined resource contracts. Each contract defines a trigger condition, one or more "
      "resource-management actions (process priority, CPU affinity, suspend/resume, cgroup limits), and a "
      "restoration rule that reverts the system to its previous state when the condition no longer holds. "
      "ARC coordinates existing Linux interfaces rather than replacing them, adding a lightweight policy "
      "abstraction with complete trigger-action-restoration lifecycle. The prototype is implemented in "
      "portable Python with explicit concurrency control and capability-aware degradation across Linux, "
      "macOS, and Windows (WSL). Experimental evaluation shows trigger-to-enforcement latency of "
      f"{data['e1']['0.2s|debounce=0.0']['mean_ms']} ms at a 0.2 s sampling interval with sub-millisecond "
      f"jitter, engine overhead of {data['e2']['1.0']['cpu_percent_mean']}% CPU at the default 1 Hz "
      f"sampling rate, and {data['e3']['exact_restores']}/{data['e3']['trials']} exact restorations of "
      "modified process state. Under CPU contention, contract-based priority enforcement raised a "
      "protected workload's CPU share from 67% to 99.6% of a core. The results demonstrate that "
      "event-driven contract enforcement can make OS resource management adaptive while remaining "
      "transparent and reversible.")
    doc.add_page_break()

    # ---------------- 1. introduction & literature survey
    h("1. Introduction and Literature Survey", 1)
    h("1.1 Introduction", 2)
    p("Operating systems manage CPU time, memory, and device access among competing processes. "
      "Linux provides scheduling priorities through nice and renice, CPU affinity through "
      "sched_setaffinity(2), resource isolation through cgroups, and observability through the "
      "/proc filesystem [1][2][7]. These interfaces are powerful and can be changed at runtime, but "
      "they remain low-level primitives: deciding when to change a priority, which processes to "
      "restrict, and when to undo a change is left entirely to administrators and scripts.")
    p("Modern workloads are dynamic. A developer compiling a large project temporarily needs more "
      "CPU, background applications should be deprioritized during the build and restored afterwards, "
      "and a laptop on low battery should restrict non-essential work until it is plugged in. "
      "Automating this with one-off shell scripts produces policies that are hard to maintain, "
      "coordinate, and reason about. ARC addresses this gap by treating resource-management "
      "requirements as explicit contracts with a defined lifecycle.")

    h("1.2 Literature Survey", 2)
    p("Linux resource management. Process scheduling behavior can be influenced through nice and "
      "renice, while CPU affinity restricts processes to selected processors. Control groups extend "
      "resource management to groups of processes for CPU, memory, and I/O. The /proc filesystem "
      "exposes runtime information about processes and overall system state [1][2][7]. Together these "
      "facilities provide the observation and enforcement primitives required for adaptive resource "
      "management, but they operate as independent interfaces without a general policy model.")
    p("Existing automation tools. Ananicy and Ananicy-cpp use configurable rules to identify "
      "processes and automatically adjust CPU and I/O priorities, and can use cgroups for resource "
      "settings [3]. Their policy model is centered on identifying applications and assigning "
      "predefined settings. systemd-oomd monitors memory pressure and acts against selected workloads "
      "when configured thresholds are met [4], demonstrating event-oriented response but focused on "
      "memory exhaustion protection rather than a general policy framework. TuneD adjusts system "
      "parameters through workload-oriented profiles and monitoring plugins [5], organized around "
      "tuning profiles rather than independently defined contracts with a complete "
      "trigger-action-restoration lifecycle.")
    p("Research studies. Goodarzy et al. proposed SmartOS, which explores automated and user-adaptive "
      "allocation of system resources based on observed user preferences [6]. SmartOS relies on "
      "learning inferred preferences; ARC instead uses an explicit contract model where the user "
      "directly specifies conditions and desired behavior, making policies deterministic and "
      "inspectable without the complexity of preference learning.")
    p("Limitations and research gap. The technical building blocks for adaptive resource management "
      "already exist, and several tools demonstrate partial automation. However, monitoring and "
      "enforcement remain separate, policies are predominantly static, and no lightweight abstraction "
      "connects runtime conditions, resource actions, and restoration behavior within a single "
      "user-defined contract. ARC investigates exactly this gap: a policy layer that coordinates "
      "existing mechanisms rather than replacing them.")

    # ---------------- 2. problem statement
    h("2. Problem Statement", 1)
    p("Linux provides powerful mechanisms for process and resource management, including CPU "
      "scheduling, CPU affinity, cgroups, and process control. However, these mechanisms are "
      "generally configured independently and often require predefined or manual policies. The system "
      "does not inherently provide a unified mechanism that can continuously monitor runtime "
      "conditions, interpret user-defined resource contracts, detect relevant system events, and "
      "dynamically modify resource policies in response.")
    p("Research question: How can an event-driven policy engine dynamically enforce user-defined "
      "resource contracts on Linux based on changing runtime system conditions?", bold=True)
    p("The problem addressed by this project is the coordination of runtime system monitoring, policy "
      "decisions, and resource enforcement. ARC aims to investigate whether these separate "
      "capabilities can be brought together through an event-driven policy layer that allows "
      "resource-management decisions to adapt automatically to changing system conditions.")
    h("2.1 Motivation", 2)
    p("A resource allocation suitable for one workload may become inefficient when another "
      "application starts, CPU or memory pressure increases, or the system switches to battery "
      "operation. As the number of conditions and applications increases, manual policies become "
      "difficult to maintain and reason about. A contract can describe what should happen when a "
      "system condition occurs and what should happen when that condition no longer applies, allowing "
      "policy to follow the lifecycle of the workload. Academically, the project integrates process "
      "management, CPU scheduling, resource allocation, monitoring, concurrency, system calls, and "
      "protection into one real Linux system rather than a simulated environment.")

    # ---------------- 3. methodology & design
    h("3. Methodology and Design", 1)
    h("3.1 Architecture", 2)
    p("ARC is a user-space policy engine with five stages: monitoring, event detection, contract "
      "evaluation, enforcement, and restoration, with execution logging throughout. A sampler thread "
      "periodically observes the system and posts events to a thread-safe queue; a coordinator thread "
      "evaluates contracts and executes actions serially, so enforcement can never race monitoring.")
    figure(os.path.join(DOCS, "fig_architecture.png"),
           "Figure 1: ARC architecture. Monitoring feeds event detection; the contract engine decides; "
           "the executor enforces through existing OS interfaces; snapshots enable restoration.")
    h("3.2 Contract Model", 2)
    p("Each resource contract has three primary components: a trigger condition, one or more "
      "resource-management actions, and a restoration rule. Contracts are stored in human-readable "
      "YAML so users define policy without modifying engine source code. Trigger types include "
      "process appearance/disappearance (regex-matched against process names and command lines), "
      "metric thresholds (CPU percentage, memory percentage, load average, with hold-time semantics), "
      "and battery level. Actions include setting process priority (nice), setting CPU affinity, "
      "suspending and resuming processes, applying cgroup limits on Linux, and structured logging. "
      "The restoration rule defines when changes are reverted: when the trigger clears, after a "
      "timeout, or never (one-shot policies).")
    h("3.3 Contract Lifecycle and Restoration", 2)
    p("Each contract runs a small state machine: IDLE, PENDING (condition held through the "
      "anti-flap debounce or hold window), ACTIVE (actions applied), and RESTORING (snapshots "
      "reverted). At activation ARC snapshots the previous nice value, affinity mask, and process "
      "state of every target. At restoration each change is reverted in reverse order, and each "
      "process is re-validated by PID and create-time to guard against PID reuse. A cooldown window "
      "prevents immediate re-triggering.")
    figure(os.path.join(DOCS, "fig_state_machine.png"),
           "Figure 2: Per-contract lifecycle. Restoration returns the system to its pre-contract state.")
    h("3.4 Concurrency and Safety", 2)
    p("The sampler thread only observes; the coordinator performs all resource changes, serialized "
      "through an event queue and a re-entrant lock guarding contract state. This satisfies the "
      "project's concurrency requirement: ARC continuously observes system state while potentially "
      "applying resource changes, without data races. On engine shutdown, any still-active contract "
      "is restored before exit, so temporary policies never persist accidentally.")
    h("3.5 Cross-Platform Strategy and Privilege Handling", 2)
    p("The implementation is portable Python built on psutil, with a capability layer that detects "
      "platform features at startup. Linux and WSL support the full action set; macOS degrades "
      "gracefully where affinity is unavailable; Windows supports priority and affinity but not POSIX "
      "signal suspend. Several operations require elevated privileges (negative nice values, cgroups, "
      "and restoring a raised nice value on POSIX). ARC detects privileges at startup, clamps "
      "unprivileged nice changes to safe values, and logs skipped actions instead of failing.")

    # ---------------- 4. implementation steps
    h("4. Implementation Steps", 1)
    p("The prototype was implemented as a modular Python package with seven components:")
    bullets([
        "platform_compat.py - capability detection (affinity, signals, cgroups, battery, privileges) "
        "so every action checks support before execution.",
        "monitors.py - real system monitor built on psutil (/proc on Linux) sampling CPU utilization, "
        "memory usage, load, battery status, and a full process table; and a synthetic monitor that "
        "replays scripted scenarios through the identical engine for deterministic demos.",
        "events.py - typed data structures for process snapshots, system samples, and engine events.",
        "contracts.py - YAML schema, validation with clear error messages, trigger predicates, and the "
        "per-contract lifecycle state machine.",
        "actions.py - action executors (set_nice, set_affinity, suspend, resume, cgroup_limit, log) "
        "with snapshot/restore records and PID-reuse safety checks.",
        "engine.py - sampler thread, event queue, coordinator, debounce and cooldown timing, and "
        "shutdown restoration.",
        "logger.py and cli.py - JSONL plus human-readable execution logs, and a command-line "
        "interface (validate, run, simulate, selftest, status).",
    ])
    p("Step-by-step workflow:")
    bullets([
        "Define contracts in YAML (see contracts/examples/full_suite.yaml) covering compilation "
        "boosting, CPU-overload guarding, battery saving, and memory-pressure guarding.",
        "Validate contracts with `python3 -m arc validate` before deployment.",
        "Run the engine with `sudo python3 -m arc run --contracts <file> --interval 1` on Linux/WSL, "
        "or replay a scenario with `python3 -m arc simulate` on any platform.",
        "Observe decisions in the execution log (trigger times, applied actions with before/after "
        "state, restoration results).",
        "Verify correctness with the test suite: 21 unit and integration tests covering schema "
        "validation, trigger semantics, debounce, timeout restoration, shutdown restoration, nice and "
        "affinity revert, PID-reuse safety, and end-to-end lifecycle.",
    ])

    # ---------------- 5. results
    h("5. Results and Discussion", 1)
    p("Experiments were run on a Linux machine (2 logical CPUs, 2 GB RAM, kernel 6.1) with elevated "
      "privileges. The full experiment suite (experiments/run_experiments.py) is reproducible from the "
      "project repository.")
    h("5.1 Trigger-to-Enforcement Latency (E1)", 2)
    p("Latency was measured from process spawn (ground truth) to the first enforced action, for "
      "different sampling intervals and debounce settings (10 trials each).")
    rows = []
    for k, v in data["e1"].items():
        rows.append([k, v["mean_ms"], v["stdev_ms"], v["min_ms"], v["max_ms"]])
    table(["sampling interval | debounce", "mean (ms)", "stdev (ms)", "min (ms)", "max (ms)"], rows)
    p("Latency is dominated by, and scales linearly with, the configured sampling interval; engine "
      "processing itself contributes less than a millisecond of jitter (standard deviation below "
      "6 ms in all configurations). With zero debounce the engine responds within one sampling "
      "interval; the anti-flap debounce window adds exactly one evaluation cycle by design. Operators "
      "can therefore trade monitoring overhead against responsiveness deterministically.")
    figure(os.path.join(RESULTS, "e1_latency.png"),
           "Figure 3: Detection latency versus sampling interval and debounce (mean ± stdev).")
    h("5.2 Engine Overhead (E2)", 2)
    rows = [[k, v["cpu_percent_mean"], v["cpu_percent_max"], v["rss_mb_mean"]]
            for k, v in data["e2"].items()]
    table(["sampling interval", "CPU % (mean)", "CPU % (max)", "RSS (MB)"], rows)
    p("With 20 background processes, ARC consumes "
      f"{data['e2']['1.0']['cpu_percent_mean']}% CPU and "
      f"{data['e2']['1.0']['rss_mb_mean']} MB RAM at the default 1 Hz sampling rate, falling to "
      f"{data['e2']['2.0']['cpu_percent_mean']}% at 0.5 Hz-equivalent (2 s) sampling. Overhead scales "
      "linearly with sampling frequency, so the engine is practical for continuous background "
      "operation alongside user workloads.")
    figure(os.path.join(RESULTS, "e2_overhead.png"),
           "Figure 4: ARC CPU overhead versus sampling interval (20 background processes).")
    h("5.3 Restoration Correctness (E3)", 2)
    p(f"In {data['e3']['trials']} independent trials, a process's priority and CPU affinity were "
      "modified by contract actions and then reverted when the contract deactivated. ARC restored "
      f"the exact original state in {data['e3']['exact_restores']} of {data['e3']['trials']} trials "
      f"({data['e3']['rate_percent']}%). This validates the snapshot mechanism and the PID-reuse "
      "guard, and confirms the project's policy-restoration requirement: temporary policies do not "
      "unnecessarily persist.")
    h("5.4 Enforcement Efficacy (E4)", 2)
    p("To quantify the effect of contract actions, a CPU-bound worker competed with two background "
      "CPU hogs on two cores under different priority configurations. The worker's CPU share over an "
      "8 s window was:")
    rows = [[k, f"{v}%"] for k, v in data["e4"]["worker_cpu_share_percent"].items()]
    table(["configuration", "worker CPU share (one core)"], rows)
    p("Without policy the worker received about 67% of a core under contention. Deprioritizing the "
      "background hogs (nice 19) or boosting the worker (nice -5) through contract actions raised the "
      "protected workload to more than 99% of a core, while deprioritizing the worker reduced it to "
      "under 14%. Contract actions therefore translate directly into measurable scheduling outcomes, "
      "confirming that ARC's enforcement layer meaningfully influences resource allocation.")
    figure(os.path.join(RESULTS, "e4_nice.png"),
           "Figure 5: Worker CPU share under contention for different contract-enforced priority levels.")
    h("5.5 Live Contract Lifecycle (E5)", 2)
    p("A full live contract was exercised with real processes and real actions: when a compiler "
      "process appeared, its priority was raised and a background workload was deprioritized; when "
      f"the compiler exited, all changes were reverted. Trigger-to-first-action latency was "
      f"{data['e5']['trigger_to_action_ms']} ms at the 0.2 s sampling interval, and the background "
      f"workload's nice value returned exactly to its original value (restore exact: "
      f"{data['e5']['restore_exact']}). Figure 6 shows the observed lifecycle timeline.")
    figure(os.path.join(RESULTS, "e5_lifecycle.png"),
           "Figure 6: Live contract lifecycle: trigger, enforcement, restoration.")
    h("5.6 Memory-Pressure Contract (E6)", 2)
    p("A contract monitored memory utilization and deprioritized the largest memory consumer when "
      f"usage stayed above 55% for 2 s. During the experiment, memory rose from "
      f"{data['e6']['mem_percent_before']}% to {data['e6']['mem_percent_peak']}% under a real 900 MB "
      f"allocation workload. The contract triggered ({data['e6']['triggered']}), the hog's priority "
      f"was changed to nice {data['e6']['hog_nice_during']}, and the change was restored "
      f"({data['e6']['restored']}) once the pressure cleared. This demonstrates the complete "
      "condition-to-restoration loop on a memory metric, matching the behavior of pressure-driven "
      "protectors such as systemd-oomd but within a general contract framework.")
    h("5.7 Discussion", 2)
    p("The evaluation supports three claims. First, event-driven contract enforcement is fast enough "
      "for interactive resource management: sub-second at 1 Hz sampling, tunable to 200 ms at 5 Hz. "
      "Second, the engine is lightweight (under 3% CPU even at 5 Hz with a busy process table), so "
      "continuous monitoring is practical. Third, restoration is reliable and exact, addressing a "
      "common weakness of ad-hoc scripting where manual changes frequently persist after their "
      "justification has expired. Limitations include the sampling-based (rather than kernel-event) "
      "detection model, which bounds latency by the sampling interval, and privilege requirements "
      "for priority-raising actions on POSIX systems.")

    # ---------------- 6. conclusion
    h("6. Conclusion and Future Work", 1)
    p("This project designed, implemented, and evaluated ARC, an event-driven policy engine that "
      "brings monitoring, event detection, contract evaluation, dynamic resource control, and policy "
      "restoration into a single user-space layer over existing Linux mechanisms. The prototype "
      "delivers the complete contract lifecycle - activation from a system condition through "
      "restoration when the condition no longer holds - with observable logs, explicit concurrency "
      "control, capability-aware cross-platform behavior, and exact restoration verified in "
      "experimentation. ARC demonstrates how operating-system concepts including process management, "
      "CPU scheduling, resource allocation, system calls, monitoring, concurrency, and protection "
      "combine in a practical system.")
    p("Future work includes: additional event sources (network usage, disk I/O, temperature); richer "
      "resource controls (I/O priority, memory.high limits); conflict resolution between overlapping "
      "contracts; a graphical or curses-based management interface; kernel-event integration (proc "
      "connectors, eBPF) to reduce detection latency below the sampling bound; and packaging ARC as "
      "a systemd service. With broader evaluation, the work could be extended toward a conference or "
      "journal publication as encouraged by the course's expected research outcomes.")

    # ---------------- references
    h("References", 1)
    refs = [
        "[1] Linux Kernel Documentation, \"Control Group v2.\" https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html",
        "[2] Linux Kernel Documentation, \"The /proc Filesystem.\" https://www.kernel.org/doc/html/latest/filesystems/proc.html",
        "[3] Ananicy-cpp, \"Ananicy-cpp: An Auto Nice Daemon.\" https://github.com/CachyOS/ananicy-cpp",
        "[4] systemd, \"systemd-oomd.service.\" https://www.freedesktop.org/software/systemd/man/latest/systemd-oomd.service.html",
        "[5] TuneD Project, \"TuneD Documentation.\" https://tuned-project.org/docs/",
        "[6] S. Goodarzy, M. Nazari, R. Han, E. Keller, and E. Rozner, \"SmartOS: Towards Automated Learning and User-Adaptive Resource Allocation in Operating Systems,\" in Proc. ACM SIGOPS Asia-Pacific Workshop on Systems (APSys), 2021.",
        "[7] M. Kerrisk, \"sched_setaffinity(2) - Linux man-pages.\" https://man7.org/linux/man-pages/man2/sched_setaffinity.2.html",
        "[8] W. M. Stevens and S. A. Rago, Advanced Programming in the UNIX Environment, 3rd ed. Addison-Wesley, 2013.",
        "[9] psutil Developers, \"psutil - Cross-platform lib for process and system utilities in Python.\" https://psutil.readthedocs.io",
    ]
    for r in refs:
        par = doc.add_paragraph(r)
        par.paragraph_format.space_after = Pt(4)

    path = os.path.join(DOCS, "ARC_Final_Report.docx")
    doc.save(path)
    print("saved", path)


# --------------------------------------------------------------------- ppt
def build_ppt(data):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    DARK = RGBColor(0x1A, 0x36, 0x5D)
    ACCENT = RGBColor(0x2B, 0x6C, 0xB0)
    LIGHT = RGBColor(0xEB, 0xF4, 0xFF)
    WHITE = RGBColor(0xFF, 0xFF, 0xFF)
    GREEN = RGBColor(0x2F, 0x85, 0x5A)

    def slide(title, subtitle=None):
        s = prs.slides.add_slide(prs.slide_layouts[6])  # blank
        # title bar
        bar = s.shapes.add_shape(1, Inches(0), Inches(0), prs.slide_width, Inches(1.05))
        bar.fill.solid()
        bar.fill.fore_color.rgb = DARK
        bar.line.fill.background()
        tf = bar.text_frame
        tf.text = title
        tf.paragraphs[0].font.size = Pt(30)
        tf.paragraphs[0].font.bold = True
        tf.paragraphs[0].font.color.rgb = WHITE
        tf.paragraphs[0].alignment = PP_ALIGN.LEFT
        tf.margin_left = Inches(0.45)
        tf.vertical_anchor = 3  # MIDDLE-ish
        if subtitle:
            box2 = s.shapes.add_textbox(Inches(0.5), Inches(1.12), Inches(12.4), Inches(0.45))
            p2 = box2.text_frame
            p2.text = subtitle
            p2.paragraphs[0].font.size = Pt(16)
            p2.paragraphs[0].font.color.rgb = ACCENT
            p2.paragraphs[0].font.italic = True
        return s

    def bullets(s, items, left=0.6, top=1.7, width=12.2, height=5.3, size=17):
        tb = s.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
        tf = tb.text_frame
        tf.word_wrap = True
        for i, it in enumerate(items):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            text, level = (it if isinstance(it, tuple) else (it, 0))
            p.text = ("• " if level == 0 else "– ") + text
            p.font.size = Pt(size if level == 0 else size - 3)
            p.font.color.rgb = DARK
            p.space_after = Pt(8)
            p.level = level
        return tf

    def add_pic(s, path, left, top, width):
        if os.path.exists(path):
            s.shapes.add_picture(path, Inches(left), Inches(top), width=Inches(width))

    def kpi_row(s, kpis, top=5.9):
        n = len(kpis)
        w = 12.3 / n
        for i, (value, label) in enumerate(kpis):
            b = s.shapes.add_shape(1, Inches(0.5 + i * w), Inches(top), Inches(w - 0.25), Inches(1.15))
            b.fill.solid()
            b.fill.fore_color.rgb = LIGHT
            b.line.color.rgb = ACCENT
            tf = b.text_frame
            tf.text = value
            tf.paragraphs[0].font.size = Pt(26)
            tf.paragraphs[0].font.bold = True
            tf.paragraphs[0].font.color.rgb = ACCENT
            tf.paragraphs[0].alignment = PP_ALIGN.CENTER
            p2 = tf.add_paragraph()
            p2.text = label
            p2.font.size = Pt(12)
            p2.font.color.rgb = DARK
            p2.alignment = PP_ALIGN.CENTER

    # 1 title
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = DARK
    bg.line.fill.background()
    tb = s.shapes.add_textbox(Inches(1), Inches(1.9), Inches(11.3), Inches(3.6))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = "Adaptive Resource Contract Engine (ARC)"
    tf.paragraphs[0].font.size = Pt(48)
    tf.paragraphs[0].font.bold = True
    tf.paragraphs[0].font.color.rgb = WHITE
    p = tf.add_paragraph()
    p.text = "Event-Driven OS Policy Engine — Monitoring, Contracts, Enforcement, Restoration"
    p.font.size = Pt(22)
    p.font.color.rgb = RGBColor(0xBE, 0xDB, 0xFF)
    p.space_before = Pt(18)
    p = tf.add_paragraph()
    p.text = "Operating Systems (BCSE303L)  •  Gagan Kishore (24BDE0073)  •  Shikhar Sahay (24BYB0029)"
    p.font.size = Pt(18)
    p.font.color.rgb = WHITE
    p.space_before = Pt(36)
    p = tf.add_paragraph()
    p.text = "Under the guidance of Dr. Balasubramani M — School of Computer Science, Engineering and Information Systems"
    p.font.size = Pt(14)
    p.font.color.rgb = RGBColor(0xBE, 0xDB, 0xFF)

    # 2 agenda
    s = slide("Agenda")
    bullets(s, [
        "Problem: static resource policies vs dynamic workloads",
        "ARC in one line: trigger → actions → restoration",
        "Architecture & contract model",
        "Implementation highlights",
        "Live lifecycle demo walkthrough",
        "Experiments & results (latency, overhead, restoration, efficacy)",
        "Conclusion & future work",
    ], size=20)

    # 3 problem
    s = slide("Problem Statement", "Linux has the primitives — but no unified adaptive policy layer")
    bullets(s, [
        "Linux exposes nice/renice, CPU affinity, cgroups, process control, /proc monitoring",
        "These mechanisms are configured independently and mostly statically",
        "No built-in mechanism to: continuously monitor → interpret user contracts → detect events → adapt policies",
        "Ad-hoc scripts are hard to maintain, coordinate, and reason about",
    ], size=20)
    bullets(s, [
        ("Research question: How can an event-driven policy engine dynamically enforce "
         "user-defined resource contracts on Linux based on changing runtime system conditions?", 0),
    ], top=5.2, size=18)

    # 4 lit survey
    s = slide("Literature Survey", "Existing capabilities — used independently")
    rows_data = [
        ("Area", "Existing approach", "Limitation"),
        ("CPU scheduling", "nice, renice, scheduler policies", "usually configured explicitly"),
        ("CPU affinity", "sched_setaffinity()", "static CPU assignment"),
        ("Isolation", "Linux cgroups", "predefined limits only"),
        ("Monitoring", "/proc, monitoring tools", "monitoring does not enforce"),
        ("Automation", "Ananicy, systemd-oomd, TuneD", "app-specific / narrow scope"),
        ("Research", "SmartOS (APSys'21)", "learned preferences, not explicit contracts"),
    ]
    table_shape = s.shapes.add_table(len(rows_data), 3, Inches(0.7), Inches(1.75), Inches(12), Inches(4.6))
    tbl = table_shape.table
    for i, row in enumerate(rows_data):
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.text = val
            for para in cell.text_frame.paragraphs:
                para.font.size = Pt(15 if i == 0 else 14)
                para.font.bold = (i == 0)
                para.font.color.rgb = WHITE if i == 0 else DARK
            if i == 0:
                cell.fill.solid()
                cell.fill.fore_color.rgb = ACCENT
    bullets(s, ["Gap: no lightweight contract abstraction connecting conditions → actions → restoration"],
            top=6.55, size=15)

    # 5 why arc
    s = slide("Why ARC?", "Less like a power plan — more like an event-driven operating policy engine")
    bullets(s, [
        "Existing: resource limits configured manually or statically",
        ("ARC: dynamically adjusts policies based on runtime conditions", 1),
        "Existing: policies require predefined actions",
        ("ARC: user-defined contracts specify conditions, actions AND restoration", 1),
        "Existing: limited response to changing workloads",
        ("ARC: continuously monitors and adapts; reverts automatically", 1),
        "OS concepts at the core: process management, CPU scheduling, resource allocation, "
        "system calls, concurrency, protection",
    ], size=19)

    # 6 architecture
    s = slide("Architecture", "Modular pipeline — every stage extensible in isolation")
    add_pic(s, os.path.join(DOCS, "fig_architecture.png"), 1.2, 1.5, 11.0)

    # 7 contract model
    s = slide("Contract Model", "Declarative YAML: trigger → actions → restoration")
    code = (
        "contracts:\n"
        "  - name: compile-boost\n"
        "    trigger:\n"
        "      type: process_appears          # also: metric_threshold, battery_below\n"
        "      match: \"gcc|cc1plus|make\"\n"
        "      debounce_sec: 1.0\n"
        "    actions:\n"
        "      - {type: set_nice,  target: {match: \"cc1plus\"}, nice: -5}\n"
        "      - {type: set_nice,  target: {match: \"chromium\"}, nice: 10}\n"
        "    restore: {mode: on_trigger_clear}   # also: after_timeout, never\n"
        "    cooldown_sec: 5.0\n"
    )
    tb = s.shapes.add_textbox(Inches(0.7), Inches(1.7), Inches(7.4), Inches(4.6))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = code
    for para in tf.paragraphs:
        para.font.name = "Consolas"
        para.font.size = Pt(14)
        para.font.color.rgb = DARK
    bullets(s, [
        "Triggers: process events, CPU/mem/load thresholds, battery",
        "Actions: nice, affinity, suspend/resume, cgroup limits, log",
        "Restoration: exact revert of every snapshot",
        "PID + create-time check defeats PID reuse",
    ], left=8.3, top=1.8, width=4.6, size=15)

    # 8 lifecycle
    s = slide("Contract Lifecycle", "Every contract is a small state machine")
    add_pic(s, os.path.join(DOCS, "fig_state_machine.png"), 1.6, 1.6, 10.2)
    bullets(s, [
        "Debounce / hold windows prevent flapping; cooldown prevents re-trigger storms",
        "Engine shutdown restores all active contracts (no leaked policies)",
    ], top=5.7, size=16)

    # 9 implementation
    s = slide("Implementation", "Portable Python + psutil; one codebase, four platforms")
    bullets(s, [
        "7 modules: monitor, events, contracts, actions, engine, logger, cli (~1,500 LOC)",
        "Concurrency: sampler thread → thread-safe event queue → coordinator (RLock)",
        "Capability layer: unsupported actions logged as SKIPPED, never crash",
        "Privilege handling: nice clamping, cgroup/affinity fallbacks, clear log warnings",
        "Cross-platform: Linux & WSL (full), macOS (no affinity), Windows (no signal suspend)",
        "CLI: arc validate | run | simulate | selftest | status",
        "21 unit + integration tests (pytest), 100% pass in both privilege modes",
    ], size=18)

    # 10 demo
    s = slide("Demo Walkthrough", "compile-boost contract, live lifecycle")
    bullets(s, [
        "1. gcc/make appears → debounce 1 s → compiler boosted (nice −5), background apps deprioritized",
        "2. Build finishes → trigger clears → original nice/affinity restored exactly",
        "3. Battery drops below 25% → background workloads suspended; plugged in → resumed",
        "4. Execution log shows every decision: trigger, action with before/after state, restore",
        ("Safe dry-run demo runs on any OS: bash demo/run_demo.sh", 1),
    ], size=18)

    # 11 results latency+overhead
    s = slide("Results I — Latency & Overhead", "E1 + E2: tunable response, tiny footprint")
    add_pic(s, os.path.join(RESULTS, "e1_latency.png"), 0.5, 1.55, 6.1)
    add_pic(s, os.path.join(RESULTS, "e2_overhead.png"), 6.85, 1.55, 6.1)
    kpi_row(s, [
        (f"{data['e1']['0.2s|debounce=0.0']['mean_ms']} ms", "trigger→action @ 0.2 s interval"),
        (f"{data['e2']['1.0']['cpu_percent_mean']}% / {data['e2']['1.0']['rss_mb_mean']} MB", "CPU & RAM @ 1 Hz sampling"),
        ("< 6 ms", "latency jitter (stdev)"),
    ])

    # 12 results restoration+efficacy
    s = slide("Results II — Restoration & Enforcement", "E3 + E4: exact revert, measurable effect")
    add_pic(s, os.path.join(RESULTS, "e4_nice.png"), 0.5, 1.55, 7.2)
    bullets(s, [
        "E3: 40/40 exact restorations (100%)",
        "Priority + affinity both revert bit-exact",
        "E4: protected workload 67% → 99.6% of a core",
        "Deprioritized workload drops to 13.9%",
        "Actions translate directly into scheduler behavior",
    ], left=7.9, top=1.7, width=5.0, size=15)
    kpi_row(s, [
        (f"{data['e3']['rate_percent']}%", "exact restorations"),
        ("67% → 99.6%", "CPU share when protected"),
    ], top=6.15)

    # 13 results live + memory
    s = slide("Results III — Live Lifecycle & Memory Guard", "E5 + E6: complete condition→restoration loop")
    add_pic(s, os.path.join(RESULTS, "e5_lifecycle.png"), 0.5, 1.55, 6.3)
    bullets(s, [
        f"E5: trigger→action {data['e5']['trigger_to_action_ms']} ms (live processes)",
        "E5: background nice restored exactly",
        f"E6: memory 25%→{data['e6']['mem_percent_peak']}% under 900 MB load",
        f"E6: contract triggered, hog nice→{data['e6']['hog_nice_during']}, restored after clearance",
    ], left=7.1, top=1.7, width=5.8, size=15)
    kpi_row(s, [
        (f"{data['e5']['trigger_to_action_ms']} ms", "live trigger→action"),
        ("40/40", "exact restores"),
        ("YES", "memory guard lifecycle"),
    ], top=6.15)

    # 14 discussion
    s = slide("Discussion", "What the numbers mean")
    bullets(s, [
        "Latency is deterministic and tunable: it equals the sampling interval operators choose",
        "Overhead low enough for always-on background operation",
        "Restoration solves the biggest flaw of ad-hoc scripting: policies that never get undone",
        "Limitations: sampling-based detection (not kernel events); privilege needed to raise priority on POSIX",
        "Works uniformly across Linux, WSL, macOS, Windows with graceful degradation",
    ], size=18)

    # 15 conclusion
    s = slide("Conclusion & Future Work")
    bullets(s, [
        "ARC = monitoring + event detection + contracts + dynamic enforcement + restoration in one layer",
        "Demonstrates OS concepts in a real system: scheduling, affinity, signals, cgroups, concurrency, protection",
        "Delivers full Review-3 scope: implementation, experimentation, performance evaluation",
        "Future: eBPF/proc-connector events, I/O + memory.high controls, contract conflict resolution, "
        "TUI/GUI manager, systemd packaging, publication extension",
    ], size=18)

    # 16 references
    s = slide("References")
    bullets(s, [
        "[1] Linux Kernel Documentation, \"Control Group v2.\" kernel.org",
        "[2] Linux Kernel Documentation, \"The /proc Filesystem.\" kernel.org",
        "[3] Ananicy-cpp: An Auto Nice Daemon. github.com/CachyOS/ananicy-cpp",
        "[4] systemd-oomd.service. freedesktop.org",
        "[5] TuneD Project Documentation. tuned-project.org",
        "[6] S. Goodarzy et al., \"SmartOS: Towards Automated Learning and User-Adaptive Resource "
        "Allocation in Operating Systems,\" APSys 2021",
        "[7] M. Kerrisk, \"sched_setaffinity(2),\" Linux man-pages",
        "[8] W. M. Stevens, S. A. Rago, Advanced Programming in the UNIX Environment, 3rd ed., 2013",
        "[9] psutil documentation. psutil.readthedocs.io",
    ], size=15)

    # 17 thank you
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = DARK
    bg.line.fill.background()
    tb = s.shapes.add_textbox(Inches(1), Inches(2.6), Inches(11.3), Inches(2.4))
    tf = tb.text_frame
    tf.text = "Thank You"
    tf.paragraphs[0].font.size = Pt(54)
    tf.paragraphs[0].font.bold = True
    tf.paragraphs[0].font.color.rgb = WHITE
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    p = tf.add_paragraph()
    p.text = "Questions & Discussion  •  ARC demo available on Linux / WSL / macOS / Windows"
    p.font.size = Pt(20)
    p.font.color.rgb = RGBColor(0xBE, 0xDB, 0xFF)
    p.alignment = PP_ALIGN.CENTER

    path = os.path.join(DOCS, "ARC_Final_Presentation.pptx")
    prs.save(path)
    print("saved", path)


if __name__ == "__main__":
    make_architecture(os.path.join(DOCS, "fig_architecture.png"))
    make_state_machine(os.path.join(DOCS, "fig_state_machine.png"))
    print("saved diagrams")
    data = load_results()
    build_report(data)
    build_ppt(data)
