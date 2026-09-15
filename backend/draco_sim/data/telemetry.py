"""Parser for the old bang-bang controller board's telemetry lines.

About every 0.1 s the `event` column carries one `[info] BBD:L:...` line (LOX
loop) and/or one `[info] BBD:F:...` line (fuel loop). Field meanings are per
docs/data-survey.md's 2026-09-13 addendum: side, state, press_cmd and psi are
confirmed; deadband is confirmed constant at 15; the rest are tentative or
unknown and are kept as field5/field6/field7/field9/field10/field11 (field1
is the side, used only to route to the ox/fuel dict key, and field8 is named
deadband).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

# [info] BBD:<side L|F>:<state>:<press_cmd 0|1>:<psi>:<field5>:<field6>:<field7>:<deadband>:<field9>:<field10 0|1>:<field11 0|1>
# Not anchored to the whole event cell: a row's event text can carry both the
# L and F lines joined by " | ", and none of these fields can themselves
# contain a space or "|", so a plain (unanchored) match finds each line fine.
_BBD_RE = re.compile(
    r"\[info\] BBD:([LF]):([A-Za-z]+):([01]):([\-0-9.]+):([\-0-9.]+):"
    r"([\-0-9.]+):([\-0-9.]+):([\-0-9.]+):([\-0-9.]+):([01]):([01])"
)
_SIDE_TO_LOOP = {"L": "ox", "F": "fuel"}


@dataclass(frozen=True)
class BoardTelemetry:
    sample_t: np.ndarray  # elapsed_s of each raw BBD line seen for this loop
    state: np.ndarray  # object array: 'OFF'/'SUS', NaN before the first sample
    press_cmd: np.ndarray  # float64 0/1: the board's own press-solenoid command
    psi: np.ndarray
    deadband: np.ndarray
    field5: np.ndarray
    field6: np.ndarray
    field7: np.ndarray
    field9: np.ndarray
    field10: np.ndarray
    field11: np.ndarray


def _zoh_expand(n_rows: int, sample_rows: np.ndarray, values, dtype, fill):
    """Zero-order-hold `values` (one per entry in sample_rows) out to n_rows."""
    last_sample = np.full(n_rows, -1, dtype=np.int64)
    if len(sample_rows):
        last_sample[sample_rows] = np.arange(len(sample_rows))
        last_sample = np.maximum.accumulate(last_sample)
    out = np.empty(n_rows, dtype=dtype)
    have = last_sample >= 0
    values = np.asarray(values, dtype=dtype)
    out[have] = values[last_sample[have]]
    out[~have] = fill
    return out


def parse_bbd(event_col: list[str], t: np.ndarray) -> dict[str, BoardTelemetry]:
    n = len(event_col)
    rows: dict[str, list[int]] = {"ox": [], "fuel": []}
    fields: dict[str, list[tuple]] = {"ox": [], "fuel": []}

    for i, text in enumerate(event_col):
        if not text or "BBD" not in text:
            continue
        for m in _BBD_RE.finditer(text):
            loop = _SIDE_TO_LOOP[m.group(1)]
            rows[loop].append(i)
            fields[loop].append(m.groups()[1:])  # drop the side, keep the rest

    result = {}
    for loop in ("ox", "fuel"):
        idx = np.array(rows[loop], dtype=np.int64)
        rec = fields[loop]
        sample_t = t[idx] if len(idx) else np.array([], dtype=np.float64)

        def numeric(pos: int) -> np.ndarray:
            return np.array([r[pos] for r in rec], dtype=np.float64)

        state_vals = np.array([r[0] for r in rec], dtype=object)
        result[loop] = BoardTelemetry(
            sample_t=sample_t,
            state=_zoh_expand(n, idx, state_vals, dtype=object, fill=np.nan),
            press_cmd=_zoh_expand(n, idx, numeric(1), dtype=np.float64, fill=np.nan),
            psi=_zoh_expand(n, idx, numeric(2), dtype=np.float64, fill=np.nan),
            field5=_zoh_expand(n, idx, numeric(3), dtype=np.float64, fill=np.nan),
            field6=_zoh_expand(n, idx, numeric(4), dtype=np.float64, fill=np.nan),
            field7=_zoh_expand(n, idx, numeric(5), dtype=np.float64, fill=np.nan),
            deadband=_zoh_expand(n, idx, numeric(6), dtype=np.float64, fill=np.nan),
            field9=_zoh_expand(n, idx, numeric(7), dtype=np.float64, fill=np.nan),
            field10=_zoh_expand(n, idx, numeric(8), dtype=np.float64, fill=np.nan),
            field11=_zoh_expand(n, idx, numeric(9), dtype=np.float64, fill=np.nan),
        )
    return result
