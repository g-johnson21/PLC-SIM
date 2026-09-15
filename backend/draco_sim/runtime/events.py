from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator

LEVELS = ("info", "command", "sequence", "abort", "fault", "warn")


@dataclass(frozen=True)
class Event:
    t: float
    scan: int
    level: str
    text: str
    source: str  # "hmi" | "plc" | "sim"

    def render(self) -> str:
        return f"[{self.level}] t={self.t:8.3f} scan={self.scan:<6d} {self.text}"

    def as_dict(self) -> dict:
        return {"t": self.t, "scan": self.scan, "level": self.level,
                "text": self.text, "source": self.source}


class EventLog:
    """Ring buffer plus fan-out to subscribers. The callbacks run inside the scan,
    so they must be cheap and must not call back into the Simulator."""

    def __init__(self, capacity: int = 2000) -> None:
        self._buf: deque[Event] = deque(maxlen=capacity)
        self._subs: list[Callable[[Event], None]] = []

    def emit(self, event: Event) -> Event:
        self._buf.append(event)
        for cb in self._subs:
            cb(event)
        return event

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        self._subs.append(callback)

    def unsubscribe(self, callback: Callable[[Event], None]) -> None:
        if callback in self._subs:
            self._subs.remove(callback)

    def clear(self) -> None:
        self._buf.clear()

    def since(self, scan: int) -> list[Event]:
        return [e for e in self._buf if e.scan > scan]

    def __iter__(self) -> Iterator[Event]:
        return iter(list(self._buf))

    def __len__(self) -> int:
        return len(self._buf)

    def __getitem__(self, index):
        return list(self._buf)[index]

    def render(self, events: Iterable[Event] | None = None) -> str:
        return "\n".join(e.render() for e in (self if events is None else events))
