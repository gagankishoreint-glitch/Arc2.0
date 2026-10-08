# ARC Demo Guide — per platform (3-minute scripts)

One project, four environments. Everything below uses only:
`python3 -m arc ...` and `python3 demo/generate_load.py` — no bash required.

---

## 0. Setup cheat-sheet

**Windows WSL (Ubuntu on Windows)**
```powershell
wsl                                   # open your WSL distro
sudo apt update && sudo apt install -y python3 python3-venv python3-pip
cd /mnt/c/path/to/Arc2.0              # or wherever you cloned
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
```

**macOS (Homebrew Python is PEP 668-managed → use a venv)**
```bash
cd Arc2.0
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
```

**Windows native (PowerShell)**
```powershell
cd Arc2.0
py -3 -m venv .venv
.venv\Scripts\Activate.ps1            # or .venv\Scripts\activate.bat
pip install -r requirements.txt pytest
```

**Ubuntu Linux**
```bash
sudo apt install -y python3 python3-venv python3-pip
cd Arc2.0 && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
```

---

## 1. The 3-minute demo script (identical on all four platforms)

**Terminal 1 — the guided story (works everywhere, no privileges needed):**
```bash
python3 -m arc demo
```
> Talking point: *"same code base detects the platform and degrades gracefully —
> on WSL you get the full Linux action set, on macOS affinity is skipped, on
> Windows signals are skipped. Nothing crashes; everything is logged."*

**Terminal 1 — the live visual (demo centerpiece):**
```bash
python3 -m arc dashboard --contracts contracts/examples/full_suite.yaml
```
> Full-screen terminal UI: system gauges, contract badges moving
> `IDLE → PENDING → ACTIVE → RESTORING`, live event feed
> (`TRIGGER_ON → ACTIONS_APPLIED → TRIGGER_OFF → RESTORED`), CPU sparkline
> with event markers. Works on a projector, over SSH, or in any terminal —
> no browser or ports. (Browser alternative: `python3 -m arc web` →
> http://localhost:8777.)

**Terminal 2 — generate pressure and watch contracts fire:**
```bash
python3 demo/generate_load.py 15
```
> Point at the screen: CPU sparkline spikes → `cpu-hot-guard` turns green
> **ACTIVE** with a live elapsed timer → events stream in → load stops →
> `TRIGGER_OFF` → **RESTORED 2/2 exact**. *"Trigger, actions, restoration —
> the whole gap-closing loop, visible in motion."*

**Battery moment (platform-specific, pick yours):**

| Platform | How to fire `battery-saver` live |
|---|---|
| WSL | Unplug the laptop — the PowerShell interop bridge reads Windows battery |
| macOS | Unplug the MacBook (battery sensor is native) |
| Windows native | Unplug; native sensor |
| Ubuntu laptop | Unplug; native sensor |
| Desktop (no battery) | Skip — show `simulate` instead: `python3 -m arc simulate --contracts contracts/examples/full_suite.yaml --scenario demo/scenario_compile_battery.json --speed 3` |

**Privileged finale (WSL/Ubuntu/macOS — full restore including priority boost):**
```bash
sudo python3 -m arc web --contracts contracts/examples/full_suite.yaml
python3 -m arc simulate --contracts contracts/examples/full_suite.yaml \
         --scenario demo/scenario_compile_battery.json --speed 3 --real-actions
```
> Talking point: *"with elevated privileges ARC can also raise priority and
> restore it — without privileges it clamps safely and logs why. That's the
> privilege-handling design from the report."*

---

## 2. Platform-specific talking points (likely questions)

- **WSL:** *"WSL is a real Linux kernel — full affinity/cgroups/suspend support.
  The one WSL quirk is that the battery lives in Windows, so ARC bridges to
  Win32_Battery via interop and caches it — contract logic is unchanged."*
- **macOS:** *"macOS has no CPU-affinity API for user space and no cgroups; ARC
  detects that at startup and logs those actions as SKIPPED — the contract
  lifecycle still completes with nice and suspend/resume."*
- **Windows native:** *"SIGSTOP/SIGCONT don't exist on Windows, so suspend
  actions are skipped; nice maps to priority classes and works both ways —
  apply and restore — even without admin."*
- **Ubuntu:** *"the reference environment — every action available; sudo unlocks
  the full tier."*

## 3. If anything misbehaves mid-demo

```bash
python3 -m arc status      # capability report - explain skips as designed
python3 -m arc selftest    # proves the full lifecycle in 5 seconds
python3 -m pytest tests/ -q   # 36 tests
```
Logs of every decision: `logs/*.log` and `logs/*.jsonl`.
