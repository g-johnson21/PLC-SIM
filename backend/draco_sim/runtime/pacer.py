"""The only module in the package that is allowed to look at a clock.

The Simulator is a pure function of its inputs and the dt in SimConfig; nothing
inside it reads wall time. An async server calls `due_scans(now)` and then calls
`sim.step()` that many times, so pacing policy stays out of the scan loop.
"""
from __future__ import annotations

from time import monotonic, perf_counter

__all__ = ["Pacer", "monotonic", "perf_counter"]


class Pacer:
    """Turns elapsed monotonic time into a number of scans to run.

    realtime=False runs as fast as the caller can go (`batch` scans per call).
    speed multiplies simulated time against wall time. When the backlog exceeds
    `max_batch` scans the surplus is dropped rather than chased: a slow host
    falls behind in simulated time instead of spiralling.
    """

    def __init__(self, sim, realtime: bool = True, speed: float = 1.0,
                 max_batch: int = 10, batch: int = 50) -> None:
        self.sim = sim
        self.realtime = bool(realtime)
        self.speed = float(speed)
        self.max_batch = int(max_batch)
        self.batch = int(batch)
        self.dropped_scans = 0
        self._anchor: float | None = None
        self._credit = 0.0

    def reset(self, now: float | None = None) -> None:
        self._anchor = now
        self._credit = 0.0

    def due_scans(self, now: float) -> int:
        """How many times step() should be called at this instant."""
        if self.sim.paused:
            self._anchor = now
            self._credit = 0.0
            return 0
        if not self.realtime:
            self._anchor = now
            return self.batch
        if self._anchor is None:
            self._anchor = now
            return 0
        elapsed = now - self._anchor
        self._anchor = now
        if elapsed <= 0.0:
            return 0
        self._credit += elapsed * self.speed
        dt = self.sim.dt
        n = int(self._credit / dt)
        if n <= 0:
            return 0
        self._credit -= n * dt
        if n > self.max_batch:
            self.dropped_scans += n - self.max_batch
            self._credit = 0.0
            n = self.max_batch
        return n

    def sleep_time(self, now: float) -> float:
        """Seconds until the next scan is due — what an async loop should await."""
        if self.sim.paused or not self.realtime:
            return 0.0
        dt = self.sim.dt
        remaining = dt - self._credit
        if self.speed <= 0.0:
            return dt
        return max(0.0, remaining / self.speed)
