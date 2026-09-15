from __future__ import annotations

import math

_TINY = 1e-12


def series_cda(*cdas: float) -> float:
    """Effective CdA of orifices in series, from 1/A^2 = sum 1/Ai^2."""
    inv = 0.0
    for a in cdas:
        if a <= _TINY:
            return 0.0
        inv += 1.0 / (a * a)
    if inv <= 0.0:
        return 0.0
    return 1.0 / math.sqrt(inv)


def liquid_mdot(cda: float, rho: float, dp: float) -> float:
    if cda <= _TINY or dp <= 0.0:
        return 0.0
    return cda * math.sqrt(2.0 * rho * dp)


def liquid_dp(cda: float, rho: float, mdot: float) -> float:
    if cda <= _TINY:
        return 0.0
    return (mdot * mdot) / (2.0 * rho * cda * cda)


def gas_mdot(cda: float, p_up: float, t_up: float, p_dn: float, gamma: float, rgas: float) -> float:
    """Isentropic compressible flow through an orifice, absolute pressures in Pa.

    Returns kg/s, positive from up to dn, zero if p_dn >= p_up."""
    if cda <= _TINY or t_up <= 0.0 or p_up <= 0.0:
        return 0.0
    if p_dn >= p_up:
        return 0.0
    crit = (2.0 / (gamma + 1.0)) ** (gamma / (gamma - 1.0))
    r = max(p_dn, 0.0) / p_up
    coef = cda * p_up / math.sqrt(rgas * t_up)
    if r <= crit:
        return coef * math.sqrt(gamma) * (2.0 / (gamma + 1.0)) ** ((gamma + 1.0) / (2.0 * (gamma - 1.0)))
    term = r ** (2.0 / gamma) - r ** ((gamma + 1.0) / gamma)
    if term <= 0.0:
        return 0.0
    return coef * math.sqrt(2.0 * gamma / (gamma - 1.0) * term)


def ramp(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 1.0 if x >= hi else 0.0
    return min(1.0, max(0.0, (x - lo) / (hi - lo)))


def lag_alpha(dt: float, tau: float) -> float:
    """Exact first-order step factor; stable for any dt."""
    if tau <= 0.0:
        return 1.0
    return 1.0 - math.exp(-dt / tau)


def bisect(f, lo: float, hi: float, iters: int) -> float:
    """Root of a monotone-decreasing f on [lo, hi]. Never raises; returns the
    bracket end if the root is outside."""
    flo = f(lo)
    if flo <= 0.0:
        return lo
    fhi = f(hi)
    if fhi >= 0.0:
        return hi
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
