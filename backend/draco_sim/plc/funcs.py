from __future__ import annotations

import math

from .types import BOOL, DINT, INT_TYPES, NUMERIC_TYPES, REAL, TIME, promote, wrap32


def _common(types: list[str]) -> str | None:
    acc = types[0]
    for t in types[1:]:
        if acc == t:
            continue
        p = promote(acc, t)
        if p is None:
            return None
        acc = p
    return acc


def _num_or_time(t: str) -> bool:
    return t in NUMERIC_TYPES or t == TIME


def _abs(x):
    return wrap32(abs(x)) if isinstance(x, int) and not isinstance(x, bool) else abs(x)


def _limit(mn, x, mx):
    return mn if x < mn else (mx if x > mx else x)


def _sel(g, a, b):
    return b if g else a


def _mux(k, *args):
    if k < 0 or k >= len(args):
        raise ValueError(f"MUX selector {k} out of range 0..{len(args) - 1}")
    return args[k]


def _trunc(x):
    return wrap32(int(x))


def _real_to_int(x):
    return wrap32(int(round(x)))


_SIMPLE_MATH = {
    "SQRT": math.sqrt,
    "EXP": math.exp,
    "LN": math.log,
    "LOG": math.log10,
    "SIN": math.sin,
    "COS": math.cos,
    "TAN": math.tan,
}

FUNCTION_NAMES = tuple(sorted(
    ("ABS", "MIN", "MAX", "LIMIT", "SEL", "MUX", "TRUNC", "REAL_TO_INT", "INT_TO_REAL",
     "BOOL_TO_INT", "TIME_TO_REAL", "REAL_TO_TIME") + tuple(_SIMPLE_MATH)))


def resolve_function(name: str, arg_types: list[str]) -> tuple[str, object]:
    """Return (result_type, callable) or raise ValueError with a diagnostic."""
    up = name.upper()
    n = len(arg_types)

    if up in _SIMPLE_MATH:
        if n != 1:
            raise ValueError(f"{up} takes 1 argument, got {n}")
        if arg_types[0] not in NUMERIC_TYPES:
            raise ValueError(f"{up} expects a numeric argument, got {arg_types[0]}")
        return REAL, _SIMPLE_MATH[up]

    if up == "ABS":
        if n != 1 or not _num_or_time(arg_types[0]):
            raise ValueError("ABS takes 1 numeric or TIME argument")
        return arg_types[0], _abs

    if up in ("MIN", "MAX"):
        if n < 2:
            raise ValueError(f"{up} takes at least 2 arguments")
        if not all(_num_or_time(t) for t in arg_types):
            raise ValueError(f"{up} expects numeric or TIME arguments")
        t = _common(arg_types)
        if t is None:
            raise ValueError(f"{up} arguments have incompatible types {arg_types}")
        return t, (min if up == "MIN" else max)

    if up == "LIMIT":
        if n != 3:
            raise ValueError("LIMIT takes 3 arguments (MN, IN, MX)")
        if not all(_num_or_time(t) for t in arg_types):
            raise ValueError("LIMIT expects numeric or TIME arguments")
        t = _common(arg_types)
        if t is None:
            raise ValueError(f"LIMIT arguments have incompatible types {arg_types}")
        return t, _limit

    if up == "SEL":
        if n != 3:
            raise ValueError("SEL takes 3 arguments (G, IN0, IN1)")
        if arg_types[0] != BOOL:
            raise ValueError("SEL selector G must be BOOL")
        t = _common(arg_types[1:]) if arg_types[1] != arg_types[2] else arg_types[1]
        if t is None:
            raise ValueError(f"SEL branches have incompatible types {arg_types[1:]}")
        return t, _sel

    if up == "MUX":
        if n < 3:
            raise ValueError("MUX takes a selector and at least 2 inputs")
        if arg_types[0] not in INT_TYPES:
            raise ValueError("MUX selector K must be INT or DINT")
        rest = arg_types[1:]
        t = rest[0] if all(x == rest[0] for x in rest) else _common(rest)
        if t is None:
            raise ValueError(f"MUX inputs have incompatible types {rest}")
        return t, _mux

    if up == "TRUNC":
        if n != 1 or arg_types[0] not in NUMERIC_TYPES:
            raise ValueError("TRUNC takes 1 numeric argument")
        return DINT, _trunc

    if up == "REAL_TO_INT":
        if n != 1 or arg_types[0] not in NUMERIC_TYPES:
            raise ValueError("REAL_TO_INT takes 1 numeric argument")
        return DINT, _real_to_int

    if up == "INT_TO_REAL":
        if n != 1 or arg_types[0] not in INT_TYPES:
            raise ValueError("INT_TO_REAL takes 1 INT/DINT argument")
        return REAL, float

    if up == "BOOL_TO_INT":
        if n != 1 or arg_types[0] != BOOL:
            raise ValueError("BOOL_TO_INT takes 1 BOOL argument")
        return DINT, int

    if up == "TIME_TO_REAL":
        if n != 1 or arg_types[0] != TIME:
            raise ValueError("TIME_TO_REAL takes 1 TIME argument")
        return REAL, float

    if up == "REAL_TO_TIME":
        if n != 1 or arg_types[0] not in NUMERIC_TYPES:
            raise ValueError("REAL_TO_TIME takes 1 numeric argument")
        return TIME, float

    raise ValueError(f"unknown function {name!r}")
