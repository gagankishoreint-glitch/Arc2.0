"""ARC - Adaptive Resource Contract Engine.

An event-driven Linux/macOS/Windows policy engine that monitors runtime
system conditions and dynamically enforces user-defined resource contracts
(trigger -> actions -> restoration).
"""

__version__ = "1.0.0"
__all__ = ["engine", "contracts", "actions", "monitors", "events", "logger", "config"]
