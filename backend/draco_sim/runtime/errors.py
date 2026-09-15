from __future__ import annotations

from typing import Any


class SimError(Exception):
    """Base for every refusal the Simulator issues. `code` is a protocol error code
    (docs/protocol.md), so task 6 can map any of these onto an `error` frame."""

    code = "rejected"

    def __init__(self, message: str, code: str | None = None,
                 details: dict[str, Any] | None = None) -> None:
        self.message = message
        if code is not None:
            self.code = code
        self.details: dict[str, Any] = dict(details or {})
        super().__init__(message)


class SimRejected(SimError):
    """A read/write/command the current state does not allow."""


class SimStateError(SimError):
    """An operation forbidden by the simulator's lifecycle, such as loading programs
    while the PLC is running."""

    code = "plc_running"
