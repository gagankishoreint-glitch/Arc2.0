"""ARC engine: monitoring loop, event detection, contract evaluation,
policy enforcement and restoration - with explicit concurrency control.

Design (matches the project's modular architecture goal):
  monitor  ->  sampler thread  ->  event queue  ->  coordinator  ->  executor
                                                    |
                                              contract state
                                              (RLock-guarded)

The sampler thread never performs resource actions; the coordinator applies
and restores actions serially from the queue, so enforcement cannot race
with itself and monitoring stays responsive while actions run.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Optional

from .actions import BaseExecutor, summarize_changes
from .contracts import Contract, ContractRuntime, State, trigger_holds
from .events import EventKind
from .logger import ExecutionLog
from .monitors import RealMonitor


class ArcEngine:
    def __init__(
        self,
        contracts: list,
        monitor=None,
        executor: Optional[BaseExecutor] = None,
        log: Optional[ExecutionLog] = None,
        interval: float = 1.0,
    ):
        self.contracts = [ContractRuntime(c) for c in contracts if c.enabled]
        self.monitor = monitor or RealMonitor()
        self.executor = executor or BaseExecutor()
        self.log = log or ExecutionLog()
        self.interval = interval
        self._events: "queue.Queue" = queue.Queue()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._sampler: Optional[threading.Thread] = None
        self.samples_seen = 0
        self.last_sample = None

    # ------------------------------------------------------------------ #
    def _sample_once(self):
        sample = self.monitor.sample()
        self.samples_seen += 1
        self.last_sample = sample
        now = time.monotonic()
        with self._lock:
            for rt in self.contracts:
                holds = trigger_holds(rt.contract.trigger, sample)
                self._update_state(rt, holds, now, sample)

    def _update_state(self, rt: ContractRuntime, holds: bool, now: float, sample):
        # Runs in the sampler thread; callers hold self._lock.
        c = rt.contract
        hold_time = max(c.trigger.for_sec if c.trigger.type == "metric_threshold" else c.trigger.debounce_sec, 0.0)

        if rt.state in (State.IDLE,):
            if holds:
                if rt.met_since is None:
                    rt.met_since = now
                # Fast path: zero hold-time activates on the very first sample.
                if now - rt.met_since >= hold_time:
                    rt.state = State.PENDING
                    rt.clear_since = None
                    self._events.put(("on", rt, sample.ts))
            else:
                rt.met_since = None

        elif rt.state == State.PENDING:
            if not holds:
                # flapped back before we acted
                rt.state = State.IDLE
                rt.met_since = None
            # otherwise: coordinator performs the activation

        elif rt.state == State.ACTIVE:
            if c.restore_mode == "on_trigger_clear":
                if not holds:
                    if rt.clear_since is None:
                        rt.clear_since = now
                    elif now - rt.clear_since >= 1.0:
                        self._events.put(("off", rt, sample.ts))
                else:
                    rt.clear_since = None
            elif c.restore_mode == "after_timeout":
                if rt.activated_at is not None and now - rt.activated_at >= c.restore_timeout_sec:
                    self._events.put(("off", rt, sample.ts))

    # ------------------------------------------------------------------ #
    def _activate(self, rt: ContractRuntime, wall_ts: float):
        c = rt.contract
        self.log.record(EventKind.TRIGGER_ON.value, c.name, ts=wall_ts,
                        trigger=c.trigger.type, desc=c.description)
        all_changes = []
        for action in c.actions:
            result = self.executor.apply(action, self.last_sample)
            if result.status == "applied":
                all_changes.extend(result.changes)
                self.log.record(EventKind.ACTIONS_APPLIED.value, c.name, ts=time.time(),
                                action=action["type"], targets=summarize_changes(result.changes),
                                note=result.message)
            else:
                self.log.record(EventKind.ACTION_SKIPPED.value, c.name, ts=time.time(),
                                action=action["type"], reason=result.message)
        with self._lock:
            rt.applied_changes = all_changes
            rt.state = State.ACTIVE
            rt.activated_at = time.monotonic()
            rt.activations += 1
            rt.clear_since = None

    def _deactivate(self, rt: ContractRuntime, wall_ts: float):
        c = rt.contract
        with self._lock:
            rt.state = State.RESTORING
            changes = rt.applied_changes
            rt.applied_changes = []
        restored = 0
        for change in reversed(changes):
            if self.executor.restore(change):
                restored += 1
        if changes and restored < len(changes):
            self.log.record(EventKind.WARN.value, c.name, ts=wall_ts,
                            reason=f"restoration incomplete: {restored}/{len(changes)} "
                                   f"(changes left applied - elevated privileges may be required)")
        self.log.record(EventKind.RESTORED.value, c.name, ts=wall_ts,
                        restored=restored, of=len(changes))
        with self._lock:
            rt.state = State.IDLE
            rt.met_since = None
            rt.clear_since = None
            rt.activated_at = None
            rt.restorations += 1
            # Cooldown: suppress immediate re-triggering after restoration.
            rt.cooldown_until = time.monotonic() + c.cooldown_sec

    # ------------------------------------------------------------------ #
    def _sampler_loop(self):
        while not self._stop.is_set():
            try:
                self._sample_once()
            except Exception as e:  # keep the loop alive no matter what
                self.log.record(EventKind.WARN.value, "_sampler", reason=str(e))
            self._stop.wait(self.interval)

    def _process_events(self):
        try:
            kind, rt, wall_ts = self._events.get_nowait()
        except queue.Empty:
            return
        if kind == "on" and rt.state == State.PENDING:
            if time.monotonic() < rt.cooldown_until:
                rt.state = State.IDLE
                rt.met_since = None
                return
            self._activate(rt, wall_ts)
        elif kind == "off" and rt.state == State.ACTIVE:
            self._deactivate(rt, wall_ts)

    def run(self, duration: Optional[float] = None):
        """Run the engine. Blocks until duration elapses or stop() is called."""
        self.log.record(EventKind.ENGINE_START.value, "_engine",
                        contracts=[rt.contract.name for rt in self.contracts],
                        interval=self.interval)
        self._sampler = threading.Thread(target=self._sampler_loop, name="arc-sampler", daemon=True)
        self._sampler.start()
        deadline = time.monotonic() + duration if duration else None
        try:
            while not self._stop.is_set():
                self._process_events()
                if deadline and time.monotonic() >= deadline:
                    break
                time.sleep(min(self.interval / 2, 0.1))
        finally:
            self.shutdown()
            self.log.record(EventKind.ENGINE_STOP.value, "_engine",
                            samples=self.samples_seen, summary=self.log.summary())

    def stop(self):
        self._stop.set()

    def shutdown(self):
        self._stop.set()
        if self._sampler and self._sampler.is_alive():
            self._sampler.join(timeout=2.0)
        # Safety: never leave changes applied when the engine exits.
        for rt in self.contracts:
            if rt.state == State.ACTIVE and rt.applied_changes:
                self._deactivate(rt, time.time())
