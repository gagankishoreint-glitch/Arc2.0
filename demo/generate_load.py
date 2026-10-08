#!/usr/bin/env python3
"""Portable CPU load generator (Windows / WSL / macOS / Linux).

Spawns N busy-loop workers for the given duration so a threshold contract
(cpu-hot-guard) fires live on the dashboard - no bash/yes/taskkill needed.

Usage:  python3 demo/generate_load.py [seconds] [workers]
"""

import os
import sys
import time


def hog(stop_at: float) -> None:
    x = 0
    while time.time() < stop_at:
        x += 1


def main() -> int:
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else (os.cpu_count() or 4)
    stop_at = time.time() + secs
    print(f"spawning {workers} CPU workers for {secs:.0f}s - watch the dashboard light up...")
    if os.name == "posix":
        pids = []
        for _ in range(workers):
            pid = os.fork()
            if pid == 0:  # child
                hog(stop_at)
                os._exit(0)
            pids.append(pid)
        try:
            for pid in pids:
                os.waitpid(pid, 0)
        except KeyboardInterrupt:
            for pid in pids:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
    else:
        import multiprocessing as mp
        procs = [mp.Process(target=hog, args=(stop_at,)) for _ in range(workers)]
        for p in procs:
            p.start()
        try:
            for p in procs:
                p.join()
        except KeyboardInterrupt:
            for p in procs:
                p.terminate()
    print("load stopped - contracts should RESTORE shortly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
