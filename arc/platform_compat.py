"""Cross-platform capability detection.

ARC degrades gracefully: every resource action checks the capability first and
is logged as SKIPPED when the platform (or privileges) do not support it.
This keeps one code base working on Linux, WSL, macOS and Windows.
"""

from __future__ import annotations

import os
import sys

import psutil


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return sys.platform in ("win32", "cygwin")


def is_wsl() -> bool:
    """True when running inside Windows Subsystem for Linux."""
    if not is_linux():
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        with open("/proc/version", encoding="utf-8", errors="ignore") as f:
            v = f.read().lower()
        return "microsoft" in v or "wsl" in v
    except OSError:
        return False


def is_posix() -> bool:
    return os.name == "posix"


def has_battery_sensor() -> bool:
    try:
        return psutil.sensors_battery() is not None  # type: ignore[attr-defined]
    except (AttributeError, NotImplementedError):
        return False


def supports_affinity() -> bool:
    """psutil exposes cpu_affinity on Linux and Windows, not on macOS."""
    return hasattr(psutil.Process, "cpu_affinity") and not is_macos()


def supports_suspend() -> bool:
    """SIGSTOP/SIGCONT based suspend is POSIX-only."""
    return is_posix()


def supports_cgroups() -> bool:
    """cgroup v1/v2 control is Linux-only and typically needs root."""
    return is_linux() and os.path.isdir("/sys/fs/cgroup")


def can_raise_priority() -> bool:
    """Lowering nice (raising priority) requires elevated privileges on POSIX."""
    if is_posix():
        try:
            return os.geteuid() == 0
        except AttributeError:
            return False
    return True  # Windows allows priority-class changes without root


def cpu_count() -> int:
    return psutil.cpu_count(logical=True) or 1


def capabilities() -> dict:
    return {
        "platform": sys.platform,
        "cpu_count": cpu_count(),
        "battery_sensor": has_battery_sensor(),
        "affinity": supports_affinity(),
        "suspend_resume": supports_suspend(),
        "cgroups": supports_cgroups(),
        "raise_priority": can_raise_priority(),
    }
