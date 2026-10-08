"""Execution logging: machine-readable JSONL plus a human-readable trace.

Every detected event, evaluated contract and applied/restored action is
recorded so that ARC's decisions remain observable and auditable.
"""

from __future__ import annotations

import json
import os
import threading
import time


class ExecutionLog:
    """Thread-safe writer for ARC's execution log (JSONL + plain text)."""

    def __init__(self, log_dir: str | None = None, echo: bool = True, prefix: str = "arc"):
        self.echo = echo
        self._lock = threading.Lock()
        self.entries: list[dict] = []
        self._handles: dict[str, "object"] = {}
        self.jsonl_path = None
        self.text_path = None
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self.jsonl_path = os.path.join(log_dir, f"{prefix}-{stamp}.jsonl")
            self.text_path = os.path.join(log_dir, f"{prefix}-{stamp}.log")

    def record(self, event_kind: str, contract: str, ts: float | None = None, **detail):
        entry = {
            "ts": round(ts if ts is not None else time.time(), 6),
            "wall": time.strftime("%H:%M:%S", time.localtime(ts if ts is not None else time.time())),
            "event": event_kind,
            "contract": contract,
            **detail,
        }
        with self._lock:
            self.entries.append(entry)
            if self.jsonl_path:
                self._append(self.jsonl_path, json.dumps(entry, default=str) + "\n")
            if self.text_path:
                self._append(self.text_path, self._format(entry) + "\n")
        if self.echo:
            print(self._format(entry), flush=True)
        return entry

    def _append(self, path: str, text: str):
        """Append via a persistent handle (keeps open/close cost off the hot path)."""
        h = self._handles.get(path)
        if h is None or h.closed:
            h = open(path, "a", encoding="utf-8")
            self._handles[path] = h
        h.write(text)
        h.flush()

    def close(self):
        with self._lock:
            for h in self._handles.values():
                try:
                    h.close()
                except OSError:
                    pass
            self._handles.clear()

    @staticmethod
    def _format(entry: dict) -> str:
        detail = {k: v for k, v in entry.items() if k not in ("ts", "wall", "event", "contract")}
        suffix = ""
        if detail:
            compact = "; ".join(f"{k}={v}" for k, v in detail.items())
            suffix = " | " + compact
        return f"[{entry['wall']}] {entry['event']:<15} {entry['contract']}{suffix}"

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for e in self.entries:
            counts[e["event"]] = counts.get(e["event"], 0) + 1
        return counts
