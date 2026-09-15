"""Scan loop: the PLC runtime, the card simulation and the plant driven together.

`Simulator` is the whole backend behind one synchronous, deterministic object;
task 6 maps its methods onto the WebSocket messages in docs/protocol.md. The scan
order it enforces is documented in docs/runtime.md and is a safety rule, not an
implementation detail.
"""

from .config import (AbortThreshold, BbLoopConfig, NOTICE, PLACEHOLDER_LABEL,
                     ProgramSource, SimConfig)
from .errors import SimError, SimRejected, SimStateError
from .events import Event, EventLog
from .pacer import Pacer
from .simulator import CompileResult, GROUPS, Simulator

__all__ = [
    "AbortThreshold",
    "BbLoopConfig",
    "CompileResult",
    "Event",
    "EventLog",
    "GROUPS",
    "NOTICE",
    "PLACEHOLDER_LABEL",
    "Pacer",
    "ProgramSource",
    "SimConfig",
    "SimError",
    "SimRejected",
    "SimStateError",
    "Simulator",
]
