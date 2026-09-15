"""Type-K thermocouple reference functions, NIST ITS-90 Thermocouple Database
(NIST Monograph 175) coefficients, embedded verbatim per house rules — public
reference data, not a fabricated spec.
"""
from __future__ import annotations

import math

# E(T): temperature (degC) -> EMF (mV), T in [-270, 0] degC.
_EMF_NEG = (
    0.000000000000e00,
    0.394501280250e-01,
    0.236223735980e-04,
    -0.328589067840e-06,
    -0.499048287770e-08,
    -0.675090591730e-10,
    -0.574103274280e-12,
    -0.310888728940e-14,
    -0.104516093650e-16,
    -0.198892668780e-19,
    -0.163226974860e-22,
)

# E(T): T in [0, 1372] degC, plus the exponential correction term below.
_EMF_POS = (
    -0.176004136860e-01,
    0.389212049750e-01,
    0.185587700320e-04,
    -0.994575928740e-07,
    0.318409457190e-09,
    -0.560728448890e-12,
    0.560750590590e-15,
    -0.320207200030e-18,
    0.971511471520e-22,
    -0.121047212750e-25,
)
_EMF_POS_A0 = 0.118597600000e00
_EMF_POS_A1 = -0.118343200000e-03
_EMF_POS_A2 = 0.126968600000e03

# T(E): EMF (mV) -> temperature (degC), three ranges per the ITS-90 table.
_INV_NEG = (  # E in [-5.891, 0] mV, T in [-200, 0] degC
    0.0000000e00,
    2.5173462e01,
    -1.1662878e00,
    -1.0833638e00,
    -8.9773540e-01,
    -3.7342377e-01,
    -8.6632643e-02,
    -1.0450598e-02,
    -5.1920577e-04,
)
_INV_MID = (  # E in [0, 20.644] mV, T in [0, 500] degC
    0.000000e00,
    2.508355e01,
    7.860106e-02,
    -2.503131e-01,
    8.315270e-02,
    -1.228034e-02,
    9.804036e-04,
    -4.413030e-05,
    1.057734e-06,
    -1.052755e-08,
)
_INV_HIGH = (  # E in [20.644, 54.886] mV, T in [500, 1372] degC
    -1.318058e02,
    4.830222e01,
    -1.646031e00,
    5.464731e-02,
    -9.650715e-04,
    8.802193e-06,
    -3.110810e-08,
)


def _poly(coeffs: tuple[float, ...], x: float) -> float:
    return sum(c * x**i for i, c in enumerate(coeffs))


def emf_from_temp_c(t_c: float) -> float:
    """Type-K EMF (mV) for a junction at t_c degC, referenced to 0 degC."""
    if t_c < 0.0:
        return _poly(_EMF_NEG, t_c)
    return _poly(_EMF_POS, t_c) + _EMF_POS_A0 * math.exp(_EMF_POS_A1 * (t_c - _EMF_POS_A2) ** 2)


def temp_c_from_emf(e_mv: float) -> float:
    """Inverse of emf_from_temp_c: temperature (degC) for EMF e_mv (mV), 0 degC ref."""
    if e_mv < 0.0:
        coeffs = _INV_NEG
    elif e_mv <= 20.644:
        coeffs = _INV_MID
    else:
        coeffs = _INV_HIGH
    return _poly(coeffs, e_mv)
