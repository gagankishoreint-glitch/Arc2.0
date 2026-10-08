# How ARC Manages Resources — the "dynamic link" explained

The most common question: *"users still type the YAML — how is this dynamic?"*

## The answer in one line

Writing the contract happens **once**. The *dynamic* part is that the engine
**maintains the contract as a live relationship between system state and
resource state**, re-evaluating it every sampling tick — and reverting itself.

## Three paradigms

| | Who watches | Who decides | Who undoes |
|---|---|---|---|
| Manual (`renice 10 -p PID`) | the user | the user | **nobody** (leaks) |
| Rule tables (Ananicy) | nobody (identity → fixed setting) | rule file | nobody |
| **ARC contracts** | **engine, every tick** | contract vs **live state** | **engine** (snapshot restore) |

Ananicy's config is a lookup table: *"app named X gets nice Y"*. ARC's config is
a standing relationship: *"WHILE condition X holds in live state, resources
SHOULD be Y — when X stops, return to the recorded snapshot."*

## What the engine does every tick (no human involved)

```
1. SAMPLE     /proc + psutil  →  CPU, MEM, battery, full process table
2. EVALUATE   trigger predicates against THIS sample
              "any process matching gcc|cc1plus?"  "CPU ≥ 85% for 5s?"
3. STATE      IDLE → PENDING → ACTIVE → RESTORING  (per contract)
4. RESOLVE    targets by regex against the live table — never typed PIDs
5. SNAPSHOT   record current nice/affinity/state before changing anything
6. ENFORCE    setpriority / sched_setaffinity / SIGSTOP/SIGCONT / cgroups
7. RESTORE    condition false? → TRIGGER_OFF → revert snapshots exactly
```

The dynamic link is **condition ↔ resource state**, continuously maintained.

## Evidence from a real run (macOS, unprivileged)

One typed command (`exec -a cc1plus sleep 20`) produced:

```
TRIGGER_ON       compile-boost
ACTIONS_APPLIED  set_nice ×1  pid[81134]              ← matched live
ACTIONS_APPLIED  set_nice ×2  pid[50118, 78537]       ← two procs the user
                                                          never mentioned
TRIGGER_OFF      compile-boost                        ← engine noticed the
                                                          clear on its own
RESTORED         compile-boost  3/3 exact
```

- **3 PIDs managed, 0 PIDs typed.** Targets were resolved by regex from the
  live process table at enforcement time.
- A threshold contract ("deprioritize the *heaviest* process") picks a
  **different PID at different moments** — the decision is state-derived,
  not scripted.
- Restoration ran **without anyone remembering to undo anything** — the
  contract's restore clause closed the loop.

## Sound bites for the review

- "The YAML is intent, not a script — the engine maintains it live."
- "Rules map identity to settings; ARC maps runtime state to policy, with a
  full trigger → actions → restoration lifecycle."
- "The user is never in the loop at runtime — that's the whole point of the
  policy abstraction."

## Where the "dynamic" is visible in the code

| Step | Module |
|---|---|
| live sampling | `arc/monitors.py` (`RealMonitor.sample`) |
| predicate evaluation | `arc/contracts.py` (`trigger_holds`) |
| lifecycle state machine | `arc/engine.py` (`_update_state`) |
| state-derived target resolution | `arc/actions.py` (`resolve`, `limit` = hottest first) |
| snapshot + automatic restoration | `arc/actions.py` (`AppliedChange`, `restore`) |
| proof of every decision | `logs/*.jsonl` + the live dashboard |
