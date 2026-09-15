from __future__ import annotations

from .types import BOOL, DINT, INT32_MAX, INT32_MIN, TIME, TIME_EPS, accumulate


class FunctionBlock:
    TYPE = ""
    INPUTS: tuple[str, ...] = ()
    OUTPUTS: tuple[str, ...] = ()
    FIELD_TYPES: dict[str, str] = {}
    __slots__ = ()

    _all_slots: tuple[str, ...] = ()

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        slots: list[str] = []
        for klass in reversed(cls.__mro__):
            slots.extend(getattr(klass, "__slots__", ()))
        cls._all_slots = tuple(slots)

    @property
    def fields(self) -> tuple[str, ...]:
        return self.INPUTS + self.OUTPUTS

    def execute(self, dt: float) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def state(self) -> tuple:
        return tuple(getattr(self, s) for s in self._all_slots)

    def restore(self, st: tuple) -> None:
        for name, value in zip(self._all_slots, st):
            setattr(self, name, value)

    def watch(self) -> dict[str, object]:
        return {f: getattr(self, f) for f in self.fields}

    def __repr__(self) -> str:
        inner = ", ".join(f"{f}={getattr(self, f)!r}" for f in self.fields)
        return f"{self.TYPE}({inner})"


class _Timer(FunctionBlock):
    INPUTS = ("IN", "PT")
    OUTPUTS = ("Q", "ET")
    FIELD_TYPES = {"IN": BOOL, "PT": TIME, "Q": BOOL, "ET": TIME}
    __slots__ = ("IN", "PT", "Q", "ET", "_raw", "_comp", "_prev")

    def __init__(self) -> None:
        self.IN = False
        self.PT = 0.0
        self.Q = False
        self.ET = 0.0
        self._raw = 0.0
        self._comp = 0.0
        self._prev = False

    def _reset_et(self) -> None:
        self._raw = 0.0
        self._comp = 0.0
        self.ET = 0.0

    def _advance(self, dt: float) -> None:
        if self.ET >= self.PT:
            return
        raw, comp = accumulate(self._raw, self._comp, dt)
        if raw + comp >= self.PT:
            self._raw, self._comp = self.PT, 0.0
        else:
            self._raw, self._comp = raw, comp
        self.ET = self._raw + self._comp


class TON(_Timer):
    """On-delay. ET is 0 on the scan IN goes true and accumulates dt from the next."""

    TYPE = "TON"
    __slots__ = ()

    def execute(self, dt: float) -> None:
        if self.IN:
            if self._prev:
                self._advance(dt)
            else:
                self._reset_et()
            self.Q = self.ET >= self.PT - TIME_EPS
        else:
            self._reset_et()
            self.Q = False
        self._prev = self.IN


class TOF(_Timer):
    TYPE = "TOF"
    __slots__ = ()

    def execute(self, dt: float) -> None:
        if self.IN:
            self._reset_et()
            self.Q = True
        elif self._prev:
            self._reset_et()
            if self.PT <= TIME_EPS:
                self.Q = False
        elif self.Q:
            self._advance(dt)
            if self.ET >= self.PT - TIME_EPS:
                self.Q = False
        self._prev = self.IN


class TP(_Timer):
    TYPE = "TP"
    __slots__ = ("_running",)

    def __init__(self) -> None:
        super().__init__()
        self._running = False

    def execute(self, dt: float) -> None:
        if self._running:
            self._advance(dt)
            if self.ET >= self.PT - TIME_EPS:
                self._running = False
                self.Q = False
        elif self.IN and not self._prev:
            self._reset_et()
            if self.PT > TIME_EPS:
                self._running = True
                self.Q = True
            else:
                self.Q = False
        elif not self.IN:
            self._reset_et()
        self._prev = self.IN


class CTU(FunctionBlock):
    TYPE = "CTU"
    INPUTS = ("CU", "R", "PV")
    OUTPUTS = ("Q", "CV")
    FIELD_TYPES = {"CU": BOOL, "R": BOOL, "PV": DINT, "Q": BOOL, "CV": DINT}
    __slots__ = ("CU", "R", "PV", "Q", "CV", "_prev_cu")

    def __init__(self) -> None:
        self.CU = False
        self.R = False
        self.PV = 0
        self.Q = False
        self.CV = 0
        self._prev_cu = False

    def execute(self, dt: float) -> None:
        if self.R:
            self.CV = 0
        elif self.CU and not self._prev_cu and self.CV < INT32_MAX:
            self.CV += 1
        self.Q = self.CV >= self.PV
        self._prev_cu = self.CU


class CTD(FunctionBlock):
    TYPE = "CTD"
    INPUTS = ("CD", "LD", "PV")
    OUTPUTS = ("Q", "CV")
    FIELD_TYPES = {"CD": BOOL, "LD": BOOL, "PV": DINT, "Q": BOOL, "CV": DINT}
    __slots__ = ("CD", "LD", "PV", "Q", "CV", "_prev_cd")

    def __init__(self) -> None:
        self.CD = False
        self.LD = False
        self.PV = 0
        self.Q = False
        self.CV = 0
        self._prev_cd = False

    def execute(self, dt: float) -> None:
        if self.LD:
            self.CV = self.PV
        elif self.CD and not self._prev_cd and self.CV > INT32_MIN:
            self.CV -= 1
        self.Q = self.CV <= 0
        self._prev_cd = self.CD


class CTUD(FunctionBlock):
    TYPE = "CTUD"
    INPUTS = ("CU", "CD", "R", "LD", "PV")
    OUTPUTS = ("QU", "QD", "CV")
    FIELD_TYPES = {"CU": BOOL, "CD": BOOL, "R": BOOL, "LD": BOOL, "PV": DINT,
                   "QU": BOOL, "QD": BOOL, "CV": DINT}
    __slots__ = ("CU", "CD", "R", "LD", "PV", "QU", "QD", "CV", "_prev_cu", "_prev_cd")

    def __init__(self) -> None:
        self.CU = self.CD = self.R = self.LD = False
        self.PV = 0
        self.QU = self.QD = False
        self.CV = 0
        self._prev_cu = self._prev_cd = False

    def execute(self, dt: float) -> None:
        if self.R:
            self.CV = 0
        elif self.LD:
            self.CV = self.PV
        else:
            up = self.CU and not self._prev_cu
            down = self.CD and not self._prev_cd
            if up and not down and self.CV < INT32_MAX:
                self.CV += 1
            elif down and not up and self.CV > INT32_MIN:
                self.CV -= 1
        self.QU = self.CV >= self.PV
        self.QD = self.CV <= 0
        self._prev_cu = self.CU
        self._prev_cd = self.CD


class R_TRIG(FunctionBlock):
    TYPE = "R_TRIG"
    INPUTS = ("CLK",)
    OUTPUTS = ("Q",)
    FIELD_TYPES = {"CLK": BOOL, "Q": BOOL}
    __slots__ = ("CLK", "Q", "_m")

    def __init__(self) -> None:
        self.CLK = False
        self.Q = False
        self._m = False

    def execute(self, dt: float) -> None:
        self.Q = bool(self.CLK) and not self._m
        self._m = bool(self.CLK)


class F_TRIG(FunctionBlock):
    TYPE = "F_TRIG"
    INPUTS = ("CLK",)
    OUTPUTS = ("Q",)
    FIELD_TYPES = {"CLK": BOOL, "Q": BOOL}
    __slots__ = ("CLK", "Q", "_m")

    def __init__(self) -> None:
        self.CLK = False
        self.Q = False
        self._m = True  # IEC: M := 1, so power-up with CLK low is not an edge

    def execute(self, dt: float) -> None:
        self.Q = (not self.CLK) and not self._m
        self._m = not self.CLK


class SR(FunctionBlock):
    """Set-dominant bistable."""

    TYPE = "SR"
    INPUTS = ("S1", "R")
    OUTPUTS = ("Q1",)
    FIELD_TYPES = {"S1": BOOL, "R": BOOL, "Q1": BOOL, "Q": BOOL}
    __slots__ = ("S1", "R", "Q1")

    def __init__(self) -> None:
        self.S1 = False
        self.R = False
        self.Q1 = False

    @property
    def Q(self) -> bool:
        return self.Q1

    def execute(self, dt: float) -> None:
        self.Q1 = bool(self.S1) or (not self.R and self.Q1)


class RS(FunctionBlock):
    """Reset-dominant bistable."""

    TYPE = "RS"
    INPUTS = ("S", "R1")
    OUTPUTS = ("Q1",)
    FIELD_TYPES = {"S": BOOL, "R1": BOOL, "Q1": BOOL, "Q": BOOL}
    __slots__ = ("S", "R1", "Q1")

    def __init__(self) -> None:
        self.S = False
        self.R1 = False
        self.Q1 = False

    @property
    def Q(self) -> bool:
        return self.Q1

    def execute(self, dt: float) -> None:
        self.Q1 = (not self.R1) and (bool(self.S) or self.Q1)


FB_TYPES: dict[str, type[FunctionBlock]] = {
    c.TYPE: c for c in (TON, TOF, TP, CTU, CTD, CTUD, R_TRIG, F_TRIG, SR, RS)
}
