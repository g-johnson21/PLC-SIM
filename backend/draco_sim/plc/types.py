from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

BOOL = "BOOL"
INT = "INT"
DINT = "DINT"
REAL = "REAL"
TIME = "TIME"
STRING = "STRING"

VALUE_TYPES = (BOOL, INT, DINT, REAL, TIME, STRING)
INT_TYPES = (INT, DINT)
NUMERIC_TYPES = (INT, DINT, REAL)

INT32_MIN = -2147483648
INT32_MAX = 2147483647

# Tolerance for TIME comparisons inside function blocks. dt is accumulated with
# compensated summation, so this only absorbs the last ulp.
TIME_EPS = 1e-9


@dataclass(frozen=True)
class TagSpec:
    name: str
    direction: str
    dtype: str
    units: str

    def __post_init__(self) -> None:
        if self.direction not in ("in", "out"):
            raise ValueError(f"tag {self.name!r}: direction must be 'in' or 'out', got {self.direction!r}")
        if self.dtype not in VALUE_TYPES:
            raise ValueError(f"tag {self.name!r}: dtype must be one of {VALUE_TYPES}, got {self.dtype!r}")
        if not self.name or not self.name[0].isalpha() and self.name[0] != "_":
            raise ValueError(f"tag name {self.name!r} is not a valid identifier")

    @classmethod
    def from_mapping(cls, m: Mapping[str, Any]) -> "TagSpec":
        return cls(
            name=str(m["name"]),
            direction=str(m["direction"]),
            dtype=str(m["dtype"]),
            units=str(m.get("units", "")),
        )


def normalise_tags(tags: Iterable[Any]) -> list[TagSpec]:
    out: list[TagSpec] = []
    for t in tags:
        if isinstance(t, TagSpec):
            out.append(t)
        elif isinstance(t, Mapping):
            out.append(TagSpec.from_mapping(t))
        else:
            raise TypeError(f"expected TagSpec or mapping, got {type(t).__name__}")
    seen: dict[str, str] = {}
    for t in out:
        key = t.name.upper()
        if key in seen:
            raise ValueError(f"duplicate tag name {t.name!r}")
        seen[key] = t.name
    return out


def wrap32(v: int) -> int:
    return ((int(v) + 2147483648) & 0xFFFFFFFF) - 2147483648


def default_value(dtype: str) -> Any:
    if dtype == BOOL:
        return False
    if dtype in INT_TYPES:
        return 0
    if dtype == REAL:
        return 0.0
    if dtype == TIME:
        return 0.0
    if dtype == STRING:
        return ""
    raise ValueError(f"unknown data type {dtype!r}")


def coerce_value(value: Any, dtype: str) -> Any:
    if dtype == BOOL:
        return bool(value)
    if dtype in INT_TYPES:
        return wrap32(int(value))
    if dtype in (REAL, TIME):
        return float(value)
    if dtype == STRING:
        return str(value)
    raise ValueError(f"unknown data type {dtype!r}")


def promote(a: str, b: str) -> str | None:
    """Arithmetic result type for two operand types, or None if incompatible."""
    if a == b:
        return a if a in (REAL, TIME) or a in INT_TYPES else None
    if a in INT_TYPES and b in INT_TYPES:
        return DINT
    if a in NUMERIC_TYPES and b in NUMERIC_TYPES:
        return REAL
    return None


def assignable(src: str, dst: str) -> bool:
    if src == dst:
        return True
    if dst in INT_TYPES and src in INT_TYPES:
        return True
    if dst == REAL and src in INT_TYPES:
        return True
    return False


def accumulate(value: float, comp: float, dt: float) -> tuple[float, float]:
    """Neumaier compensated addition: keeps sum(dt) exact to the last ulp."""
    t = value + dt
    if abs(value) >= abs(dt):
        comp += (value - t) + dt
    else:
        comp += (dt - t) + value
    return t, comp


def format_time(seconds: float) -> str:
    if seconds != seconds or math.isinf(seconds):
        return f"T#{seconds}"
    sign = "-" if seconds < 0 else ""
    rest = abs(float(seconds))
    if rest == 0.0:
        return "T#0s"
    parts: list[str] = []
    for unit, scale in (("d", 86400.0), ("h", 3600.0), ("m", 60.0), ("s", 1.0), ("ms", 0.001)):
        n = int(rest / scale + 1e-9)
        if n:
            parts.append(f"{n}{unit}")
            rest -= n * scale
        if abs(rest) < 1e-9:
            rest = 0.0
            break
    if rest > 1e-9 or not parts:
        return f"{sign}T#{abs(float(seconds)):g}s"
    return f"{sign}T#" + "".join(parts)
