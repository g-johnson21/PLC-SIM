"""Transducer <-> electrical scaling for the signal types that don't need the
thermocouple polynomials (pressure loop current, load-cell bridge output).
"""
from __future__ import annotations


def pressure_to_current_ma(physical: float, rng: tuple[float, float], loop_ma: tuple[float, float]) -> float:
    lo, hi = rng
    lo_ma, hi_ma = loop_ma
    frac = (physical - lo) / (hi - lo)
    return lo_ma + frac * (hi_ma - lo_ma)


def current_ma_to_pressure(ma: float, rng: tuple[float, float], loop_ma: tuple[float, float]) -> float:
    lo, hi = rng
    lo_ma, hi_ma = loop_ma
    frac = (ma - lo_ma) / (hi_ma - lo_ma)
    return lo + frac * (hi - lo)


def force_to_bridge_mvv(force: float, capacity_lbf: float, rated_mv_per_v: float) -> float:
    return rated_mv_per_v * (force / capacity_lbf)


def bridge_mvv_to_force(mvv: float, capacity_lbf: float, rated_mv_per_v: float) -> float:
    return capacity_lbf * (mvv / rated_mv_per_v)


def quantize(value: float, lo: float, hi: float, bits: int) -> tuple[float, int]:
    """Clamp value to [lo, hi] and quantise it to `bits` over that span.
    Returns (quantised_value, raw_code).
    """
    n_codes = (1 << bits) - 1
    clamped = min(max(value, lo), hi)
    frac = (clamped - lo) / (hi - lo)
    code = round(frac * n_codes)
    code = min(max(code, 0), n_codes)
    q = lo + (code / n_codes) * (hi - lo)
    return q, code
