# ARC Project Audit & Review-3 Readiness

**Project:** Adaptive Resource Contract Engine (ARC) — BCSE303L Operating Systems
**Team:** Gagan Kishore (24BDE0073), Shikhar Sahay (24BYB0029)
**Audit date:** 2026-10-08 (night before Review 3 submission)

---

## 1. Audit of existing work (teammate repository)

| Check | Result |
|---|---|
| `https://github.com/shikhar-sahay/arc` reachable anonymously | **NO — HTTP 404** |
| Repo listed in Shikhar's public GitHub repos | **NO** (account has 12 public repos; none named `arc`) |
| GitHub API `repos/shikhar-sahay/arc` | **404 Not Found** |
| Code review of teammate's implementation | **IMPOSSIBLE until access is granted** |

**Finding A-1 (blocking):** The repository is either private, renamed, un-pushed, or
deleted. No code could be fetched, forked, or reviewed. Two actions required from
the team: (a) ask Shikhar to make the repository public (or add collaborators), or
(b) send a ZIP of the working tree for review.

**Finding A-2:** Because Review 3 is due the next morning, the engine was
re-implemented to full working state in this repository so that the team has a
complete, tested, documented deliverable regardless of the other repo's status.

**Finding A-3 (when the ZIP arrives, merge protocol):**
1. Diff module-by-module against `arc/` (monitor, contracts, actions, engine, logger).
2. Prefer teammate's contract-schema names if their PPT/report already references them.
3. Port any extra features on top of this code base; keep the test suite green
   (`python3 -m pytest tests/`).
4. Re-run experiments if behaviour changes.

---

## 2. Review-3 completeness checklist (course requirements)

| Requirement | Status | Evidence |
|---|---|---|
| Full implementation | **DONE** | `arc/` package — 6 modules, CLI, 21 tests passing |
| Contract definition (human-readable config) | **DONE** | YAML schema + `arc validate`, 4 example contracts |
| Runtime monitoring (CPU, memory, process activity, battery) | **DONE** | `monitors.py` (psutil + /proc) |
| Event detection | **DONE** | process appear/disappear, metric thresholds, battery |
| Policy evaluation & enforcement | **DONE** | `engine.py` + `actions.py` (nice, affinity, suspend/resume, cgroups) |
| Policy restoration lifecycle | **DONE** | state machine IDLE→PENDING→ACTIVE→RESTORING; E3: 40/40 exact |
| Policy observability (logging) | **DONE** | JSONL + human-readable log (`logger.py`) |
| Concurrency / safe coordination | **DONE** | sampler thread + event queue + RLock-guarded state |
| Permission & privilege handling | **DONE** | capability detection, graceful degradation, clamping |
| Experimentation & results | **DONE** | 6 experiments, real numbers, charts (`experiments/results/`) |
| Performance evaluation | **DONE** | latency, overhead, restoration accuracy, enforcement efficacy |
| Final report | **DONE** | `docs/ARC_Final_Report.docx` (required structure) |
| PPT | **DONE** | `docs/ARC_Final_Presentation.pptx` |
| Cross-platform claim (macOS / Windows+WSL / Linux) | **DONE** | capability matrix; dry-run simulate works everywhere |
| 0% AI plagiarism / <10% overall | **TEAM MUST VERIFY** | run through institutional checker; rephrase flagged lines |

---

## 3. What remains for the team (short list)

1. **Get Shikhar's code** (public repo or ZIP) and run the merge protocol above.
2. **Run the plagiarism/AI checker** on the final report; adjust phrasing where flagged.
3. **Push this repository to GitHub** — see `push_to_github.sh`.
4. **Live demo rehearsal** (5 min): `bash demo/run_demo.sh` (safe anywhere), then
   `sudo python3 -m arc run --contracts contracts/examples/full_suite.yaml --duration 60`
   on a Linux/WSL machine while running a build (`make -j`) to show `compile-boost`.
