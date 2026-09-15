from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class CompileError(Exception):
    """One or more compile-time diagnostics.

    ST diagnostics carry line/col (1-based); LD and SFC diagnostics carry an
    RFC-6901 JSON pointer in `path`. The raised exception always has `.errors`:
    a list of CompileError, one per diagnostic, so an IDE can mark them all.
    """

    def __init__(
        self,
        message: str,
        line: int | None = None,
        col: int | None = None,
        *,
        path: str | None = None,
        program: str | None = None,
        errors: list["CompileError"] | None = None,
    ) -> None:
        self.message = message
        self.line = line
        self.col = col
        self.path = path
        self.program = program
        self.errors: list[CompileError] = list(errors) if errors is not None else [self]
        super().__init__(self._render())

    def location(self) -> str:
        bits = []
        if self.program:
            bits.append(self.program)
        if self.path is not None:
            bits.append(self.path)
        if self.line is not None:
            bits.append(str(self.line))
            bits.append(str(self.col if self.col is not None else 1))
        return ":".join(bits)

    def _render(self) -> str:
        if self.errors and (len(self.errors) > 1 or self.errors[0] is not self):
            head = f"{len(self.errors)} compile errors"
            if self.program:
                head += f" in {self.program}"
            return head + ":\n" + "\n".join("  " + e.one_line() for e in self.errors)
        return self.one_line()

    def one_line(self) -> str:
        loc = self.location()
        return f"{loc}: {self.message}" if loc else self.message

    def as_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "line": self.line,
            "col": self.col,
            "path": self.path,
            "program": self.program,
        }

    @staticmethod
    def raise_all(errors: list["CompileError"], program: str | None = None) -> None:
        if not errors:
            return
        for e in errors:
            if e.program is None:
                e.program = program
        if len(errors) == 1:
            raise errors[0]
        first = errors[0]
        raise CompileError(first.message, first.line, first.col, path=first.path,
                           program=program, errors=errors)


@dataclass
class PlcFault:
    """A runtime fault. The program that raised it is halted until clear_faults()."""

    program: str
    kind: str
    message: str
    line: int | None = None
    col: int | None = None
    path: str | None = None
    scan_index: int = 0
    sim_time_s: float = 0.0

    def __str__(self) -> str:
        loc = ""
        if self.line is not None:
            loc = f":{self.line}:{self.col if self.col is not None else 1}"
        elif self.path:
            loc = f":{self.path}"
        return f"[{self.kind}] {self.program}{loc}: {self.message} (scan {self.scan_index}, t={self.sim_time_s:.3f}s)"


class PlcStateError(Exception):
    """An operation the runtime's current state forbids, such as starting a sequence
    while an abort is latched. Distinct from ValueError (a bad argument) and from
    PlcFault (a program failing during a scan)."""


class PlcFaultSignal(Exception):
    """Internal: raised by executing code, converted to a PlcFault by the runtime."""

    def __init__(self, kind: str, message: str, line: int | None = None,
                 col: int | None = None, path: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.line = line
        self.col = col
        self.path = path
