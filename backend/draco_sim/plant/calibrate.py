"""Fit plant constants to the 2026-09-11 recordings and write calibration.yaml.

    python -m draco_sim.plant.calibrate [--data DIR] [--out FILE] [--report]

Deterministic: fixed windows, fixed search brackets and iteration counts, no randomness,
no timestamps in the output. Each fitted constant is written with source `calibrated`
and notes naming its window, method and residual. PlantConfig.calibrated() loads the
file. docs/plant-model.md section 6 explains every window.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import yaml

from draco_sim.data import RunData, load_run

from .config import CALIBRATION_PATH, LBM_KG, PlantConfig
from .plant import VALVES, Plant
from .replay import compare, seed, simulate

RUN_FILES = {
    "12:36": "Draco_20260911_123642_hotfire.csv",
    "12:49": "Draco_20260911_124919_hotfire.csv",
    "12:52": "Draco_20260911_125242_hotfire.csv",
}
DEFAULT_DATA = Path(__file__).resolve().parents[3] / "testdata"
P_ATM_PSI = 14.6959

# (run, valve, response channel, sign of the response) for command-lag measurement
PB_EVENTS = (("12:49", "PB6", "PT4", -1), ("12:49", "PB2", "PT22", -1), ("12:49", "PB4", "PT24", -1),
             ("12:36", "PB1", "PT4", -1), ("12:36", "PB5", "PT4", +1), ("12:36", "PB6", "PT4", -1))
SOLENOID_EVENTS = (("12:49", "S1", "PT4", +1), ("12:36", "S1", "PT4", +1), ("12:36", "S2", "PT14", +1),
                   ("12:52", "S1", "PT1", -1), ("12:52", "S2", "PT11", -1))
LAG_THRESHOLD_PSI = 8.0

# (run, vent command edge s, window end s, LC4 window for the LOX mass). Windows stop
# above ~250 psi: below that the LOX tank flashes and holds up, which the model lacks.
LOX_VENT_WINDOWS = (("12:36", 486.001, 487.6, (484.0, 486.0)),
                    ("12:49", 109.822, 115.0, (111.25, 113.0)))
FUEL_VENT_WINDOW = ("12:49", 109.822, 113.5)

PRESS_RUNS = {"S1": ("12:49", "12:36"), "S2": ("12:36",)}
TANK_TAG = {"S1": "PT4", "S2": "PT14"}
BUS_TAG = {"S1": "PT1", "S2": "PT11"}

# GC-only opens with the tank vent open, bottles isolated (D13): (valve, open s, end s)
VENT_OPEN_WINDOWS = (("S1", 302.824, 312.0), ("S2", 317.085, 327.0))


class Runs:
    def __init__(self, data_dir: Path) -> None:
        self.dir = data_dir
        self._runs: dict[str, RunData] = {}
        self._updates: dict[tuple[str, str], np.ndarray] = {}

    def __getitem__(self, key: str) -> RunData:
        if key not in self._runs:
            self._runs[key] = load_run(self.dir / RUN_FILES[key])
        return self._runs[key]

    def updates(self, key: str, tag: str) -> np.ndarray:
        """Rows where the logged value changed. Transducers refresh about every 0.1 s
        while rows arrive every 26 ms, so repeated rows carry no new information."""
        if (key, tag) not in self._updates:
            x = self[key].signals[tag]
            keep = np.ones(len(x), dtype=bool)
            keep[1:] = x[1:] != x[:-1]
            self._updates[(key, tag)] = np.nonzero(keep)[0]
        return self._updates[(key, tag)]


# ---------------------------------------------------------------------------- helpers
def _with(cfg: PlantConfig, **values: float) -> PlantConfig:
    return replace(cfg, **{n: replace(getattr(cfg, n), value=float(v)) for n, v in values.items()})


def _row(run: RunData, t: float) -> int:
    return int(np.searchsorted(run.t, t))


def _median(run: RunData, tag: str, lo: float, hi: float) -> float:
    t = run.t
    keep = (t >= lo) & (t < hi)
    if tag in run.invalid_from:
        bad = t >= run.invalid_from[tag]
        if tag in run.invalid_to:
            bad &= t < run.invalid_to[tag]
        keep &= ~bad
    return float(np.nanmedian(run.signals[tag][keep]))


def _edges(run: RunData, valve: str, rising: Optional[bool] = True) -> list[int]:
    a = run.valves[valve].astype(np.int8)
    idx = np.nonzero(np.diff(a))[0] + 1
    return [int(i) for i in idx if rising is None or bool(a[i]) == rising]


def _pulses(run: RunData, valve: str) -> list[tuple[float, float]]:
    a = run.valves[valve].astype(np.int8)
    out = []
    for i in _edges(run, valve, True):
        off = np.nonzero(a[i:] == 0)[0]
        if off.size:
            out.append((float(run.t[i]), float(run.t[i + off[0]])))
    return out


def _quiet(run: RunData, valve: str, lo: float, hi: float) -> bool:
    """No other valve is open or changes state in [lo, hi]."""
    i0, i1 = _row(run, lo), _row(run, hi)
    return all(not run.valves[v][i0:i1].any() for v in VALVES if v != valve and v in run.valves)


def _golden(f: Callable[[float], float], lo: float, hi: float, iters: int = 30) -> float:
    g = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(iters):
        if fc <= fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = f(d)
    return 0.5 * (a + b)


def _solve_increasing(f: Callable[[float], float], target: float, lo: float, hi: float,
                      iters: int = 24) -> tuple[float, bool]:
    """x in [lo, hi] with f(x) = target for increasing f; flags a clamped result."""
    if f(lo) >= target:
        return lo, False
    if f(hi) <= target:
        return hi, False
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi), True


def _window(cfg: PlantConfig, run: RunData, i0: int, i1: int, lox_lbm: float, fuel_lbm: float,
            tags: tuple[str, ...], hold: Optional[dict[str, bool]] = None) -> dict[str, np.ndarray]:
    """Seed from row i0 and drive with the logged valves to row i1. `hold` replaces the
    logged state of the named valves for the whole window."""
    plant = Plant(cfg)
    seed(plant, run, lox_lbm, fuel_lbm, row=i0)
    t = run.t
    out = {tag: np.empty(i1 - i0) for tag in tags}
    valves = {v: a for v, a in run.valves.items() if v in VALVES}
    for n, i in enumerate(range(i0, i1)):
        if n:
            cmd = {v: bool(a[i]) for v, a in valves.items()}
            if hold:
                cmd.update(hold)
            plant.step(min(max(float(t[i] - t[i - 1]), 1e-4), 0.1), cmd)
        s = plant.sensors()
        for tag in tags:
            out[tag][n] = s[tag]
    return out


def _log_rms(pred: np.ndarray, obs: np.ndarray) -> float:
    r = np.log((pred + P_ATM_PSI) / (np.maximum(obs, 0.0) + P_ATM_PSI))
    return float(np.sqrt(np.mean(r * r)))


def _psi_rms(pred: np.ndarray, obs: np.ndarray) -> float:
    return float(np.sqrt(np.mean((pred - obs) ** 2)))


def _sig(v: float) -> float:
    return float(f"{v:.3g}")


# ------------------------------------------------------------------------ fits
def fit_dead_time(runs: Runs) -> dict[str, object]:
    def lags(events, isolated: bool = True):
        out = []
        for key, valve, tag, sign in events:
            run = runs[key]
            t, x, upd = run.t, run.signals[tag], runs.updates(key, tag)
            others = [float(t[i]) for v in VALVES if v != valve and v in run.valves
                      for i in _edges(run, v, None)]
            for i in _edges(run, valve):
                te = float(t[i])
                pre = x[_row(run, te - 0.5):i]
                if pre.size < 3 or np.ptp(pre) > LAG_THRESHOLD_PSI / 2:
                    continue
                base = float(np.median(pre))
                k = int(np.searchsorted(upd, i))
                while k < len(upd) and t[upd[k]] - te <= 1.5 and sign * (x[upd[k]] - base) <= LAG_THRESHOLD_PSI:
                    k += 1
                if k >= len(upd) or t[upd[k]] - te > 1.5:
                    continue
                t_hit = float(t[upd[k]])
                t_prev = max(te, float(t[upd[k - 1]])) if k > 0 else te
                if isolated and any(te - 0.3 <= o <= t_hit for o in others):
                    continue
                out.append((key, valve, te, 0.5 * (t_prev + t_hit) - te))
        return out

    pb, sol = lags(PB_EVENTS), lags(SOLENOID_EVENTS)
    pb_lag = float(np.median([e[3] for e in pb]))
    sol_lag = float(np.median([e[3] for e in sol]))
    # the hotfire opens PB2 and PB4 0.5 s apart with S1 cycling, so the isolation rule
    # drops PB4; their venturi channels do not see each other's valve
    run_lines = {e[1]: e[3] for e in lags([ev for ev in PB_EVENTS if ev[1] in ("PB2", "PB4")], isolated=False)}
    return {"value": round(max(0.0, pb_lag - sol_lag), 2), "pb": pb, "sol": sol,
            "pb_lag": pb_lag, "sol_lag": sol_lag, "run_lines": run_lines,
            "fuel_fill": run_lines["PB4"] - run_lines["PB2"]}


def fit_lox_vent(runs: Runs, cfg: PlantConfig) -> dict[str, object]:
    cases = []
    for key, te, t_end, lc4 in LOX_VENT_WINDOWS:
        run = runs[key]
        i0, i1 = _row(run, te) - 1, _row(run, t_end)
        rows = np.array([u - i0 for u in runs.updates(key, "PT4") if _row(run, te) <= u < i1])
        cases.append((key, te, t_end, run, i0, i1, rows, _median(run, "LC4", *lc4)))

    def cost(log_cda: float, only: Optional[int] = None, report: bool = False):
        c = _with(cfg, cda_pb1=10 ** log_cda)
        total, res = 0.0, []
        for n, (key, te, t_end, run, i0, i1, rows, lox) in enumerate(cases):
            if only is not None and n != only:
                continue
            pred = _window(c, run, i0, i1, lox, 0.0, ("PT4",))["PT4"][rows]
            obs = run.signals["PT4"][i0:i1][rows]
            total += _log_rms(pred, obs) ** 2
            res.append((key, te, t_end, lox, _psi_rms(pred, obs), float(obs[0]), float(obs[-1])))
        return res if report else total

    best = _golden(cost, -6.0, -3.5)
    alone = [_sig(10 ** _golden(lambda x, n=n: cost(x, only=n), -6.0, -3.5)) for n in range(len(cases))]
    return {"value": _sig(10 ** best), "windows": cost(best, report=True), "alone": alone}


def fit_gas_volumes(runs: Runs, cfg: PlantConfig) -> dict[str, object]:
    """Mass balance per pressurant pulse, in the model's own gas laws: the bus loses
    dp_bus * V_bus / (n R T_amb), the tank side gains dp_tank * V/(R T)."""
    k = cfg.si()
    t_amb, n = k["ambient_default"], k["polytropic_n"]
    split, count, v_bottle = k["bottle_split_lox"], k["bottle_count"], k["bottle_volume"]

    lox = []
    run = runs["12:49"]
    for on, off in _pulses(run, "S1"):
        if not _quiet(run, "S1", on - 1.5, off + 2.5):
            continue
        dp_b = _median(run, "PT1", on - 1.0, on - 0.1) - _median(run, "PT1", off + 1.0, off + 2.5)
        dp_t = _median(run, "PT4", off + 1.0, off + 2.5) - _median(run, "PT4", on - 1.0, on - 0.1)
        m_lox = _median(run, "LC4", on - 3.0, on - 0.3) * LBM_KG
        v_ull = k["tank_volume"] - m_lox / k["rho_lox"]
        per_r = dp_t * (v_ull / k["lox_ullage_temp"] + (k["vol_lox_press_up"] + k["vol_lox_press_dn"]) / t_amb)
        lox.append((on, dp_b, dp_t, n * t_amb * per_r / dp_b / v_bottle))

    run = runs["12:36"]
    sums = np.zeros(3)
    pulses = [(on, off) for on, off in _pulses(run, "S2") if _quiet(run, "S2", on - 1.5, off + 4.0)]
    for on, off in pulses:
        pre, post = (on - 1.0, on - 0.1), (off + 1.5, off + 4.0)
        sums += [_median(run, "PT11", *pre) - _median(run, "PT11", *post),
                 _median(run, "PT14", *post) - _median(run, "PT14", *pre),
                 _median(run, "PT32", *post) - _median(run, "PT32", *pre)]
    dp_b, dp_t, dp_purge = sums
    v_bus = v_bottle * (count - split)
    gas_per_r = dp_b * v_bus / (n * t_amb)
    lines = dp_t * (k["vol_fuel_press_up"] + k["vol_fuel_press_dn"]) / t_amb + dp_purge * k["vol_purge_bus"] / t_amb
    v_ull = k["fuel_ullage_temp"] * (gas_per_r - lines) / dp_t
    fuel_lbm = max(0.0, (k["tank_volume"] - v_ull) * k["rho_fuel"] / LBM_KG)
    return {"lox_pulses": lox, "fuel_pulses": len(pulses), "fuel_dp": (dp_b, dp_t, dp_purge),
            "fuel_ullage_L": v_ull * 1e3, "fuel_lbm": fuel_lbm,
            "lox_bottles": float(np.mean([p[3] for p in lox])) if lox else math.nan}


def fit_fuel_vent(runs: Runs, cfg: PlantConfig, fuel_lbm: float) -> dict[str, object]:
    key, te, t_end = FUEL_VENT_WINDOW
    run = runs[key]
    i0, i1 = _row(run, te) - 1, _row(run, t_end)
    rows = np.array([u - i0 for u in runs.updates(key, "PT14") if _row(run, te) <= u < i1])
    obs = run.signals["PT14"][i0:i1][rows]
    lox = _median(run, "LC4", 111.25, 113.0)

    def pred(log_cda: float) -> np.ndarray:
        return _window(_with(cfg, cda_pb3=10 ** log_cda), run, i0, i1, lox, fuel_lbm, ("PT14",))["PT14"][rows]

    best = _golden(lambda x: _log_rms(pred(x), obs), -6.0, -3.5)
    return {"value": _sig(10 ** best), "rms": _psi_rms(pred(best), obs), "from": float(obs[0]), "to": float(obs[-1])}


def _observed_rate(runs: Runs, key: str, tag: str, on: float, off: float) -> Optional[tuple[float, int, int]]:
    """Steady rise rate of a pressurant pulse from the transducer updates: the median of
    the interior steps when there are three or more, else the steepest step. Returns
    (psi/s, row the rise starts from, steps)."""
    run = runs[key]
    t, x = run.t, run.signals[tag]
    base = float(np.median(x[_row(run, on - 0.5):_row(run, on)]))
    upd = [int(u) for u in runs.updates(key, tag) if _row(run, on - 0.5) <= u < _row(run, off + 0.6)]
    after = [u for u in upd if t[u] >= on]
    if not after:
        return None
    peak = max(after, key=lambda u: x[u])
    if x[peak] - base < 20.0:
        return None
    starts = [u for u in upd if u < peak and x[u] <= base + 3.0]
    start = starts[-1] if starts else after[0]
    seg = [u for u in upd if start <= u <= peak]
    rates = np.diff(x[seg]) / np.diff(t[seg])
    if rates.size == 0:
        return None
    rate = float(np.median(rates[1:-1])) if rates.size >= 3 else float(rates.max())
    return rate, start, int(rates.size)


def fit_press(runs: Runs, cfg: PlantConfig, valve: str, fuel_lbm: float) -> dict[str, object]:
    tag, name = TANK_TAG[valve], f"cda_{valve.lower()}"
    per = []
    for key in PRESS_RUNS[valve]:
        run = runs[key]
        for on, off in _pulses(run, valve):
            if not _quiet(run, valve, on - 1.0, off + 1.0):
                continue
            got = _observed_rate(runs, key, tag, on, off)
            if got is None:
                continue
            rate, start, steps = got
            lox = _median(run, "LC4", on - 3.0, on - 0.3)
            i1 = _row(run, float(run.t[start]) + 0.35)
            tt = run.t[start:i1] - run.t[start]
            fit_rows = (tt >= 0.1) & (tt <= 0.35)

            def model_rate(log_cda: float) -> float:
                c = _with(cfg, **{name: 10 ** log_cda})
                p = _window(c, run, start, i1, lox, fuel_lbm, (tag,), hold={valve: True})[tag]
                return float(np.polyfit(tt[fit_rows], p[fit_rows], 1)[0])

            x, inside = _solve_increasing(model_rate, rate, -7.0, -3.5)
            per.append((key, on, rate, steps, 10 ** x, inside))
    values = np.array([p[4] for p in per])
    by_run = {key: float(np.median([p[4] for p in per if p[0] == key])) for key in PRESS_RUNS[valve]
              if any(p[0] == key for p in per)}
    return {"value": _sig(float(np.median(values))), "pulses": per, "by_run": by_run,
            "range": (float(values.min()), float(values.max()))}


def vent_open_check(runs: Runs, cfg: PlantConfig, fuel_lbm: float) -> list[dict[str, object]]:
    """12:52 safing: the operator opened S1 and S2 with PB1/PB3 open and the bottles
    isolated, so the bus is a trapped line. Fit that line volume to the bus decay, then
    compare the tank peak, where inflow equals vent outflow."""
    run = runs["12:52"]
    k = cfg.si()
    out = []
    for valve, on, t_end in VENT_OPEN_WINDOWS:
        bus, tank = BUS_TAG[valve], TANK_TAG[valve]
        bottles = k["bottle_split_lox"] if valve == "S1" else k["bottle_count"] - k["bottle_split_lox"]
        i0, i1 = _row(run, on) - 2, _row(run, t_end)
        lox = _median(run, "LC4", on - 3.0, on - 0.1)
        rows = np.array([u - i0 for u in runs.updates("12:52", bus)
                         if _row(run, on) <= u < i1 and run.signals[bus][u] > 30.0])
        obs_bus = run.signals[bus][i0:i1]

        def sim(log_litres: float) -> dict[str, np.ndarray]:
            c = _with(cfg, bottle_volume=10 ** log_litres / bottles)
            return _window(c, run, i0, i1, lox, fuel_lbm, (bus, tank))

        best = _golden(lambda x: _log_rms(sim(x)[bus][rows], obs_bus[rows]), -1.5, 1.0, iters=25)
        pred = sim(best)
        obs_tank = run.signals[tank][i0:i1]
        jo, jp = int(np.argmax(obs_tank)), int(np.argmax(pred[tank]))
        ratio_obs = (obs_tank[jo] + P_ATM_PSI) / (obs_bus[jo] + P_ATM_PSI)
        ratio_pred = (pred[tank][jp] + P_ATM_PSI) / (pred[bus][jp] + P_ATM_PSI)
        out.append({"valve": valve, "line_L": 10 ** best, "bus_rms": _psi_rms(pred[bus][rows], obs_bus[rows]),
                    "tank_peak_obs": float(obs_tank[jo]), "tank_peak_pred": float(pred[tank][jp]),
                    "bus_at_peak_obs": float(obs_bus[jo]), "bus_at_peak_pred": float(pred[bus][jp]),
                    "ratio_obs": float(ratio_obs), "ratio_pred": float(ratio_pred)})
    return out


def vent_open_scenario(cfg: PlantConfig, fuel_lbm: float, vents_open: bool) -> dict[str, float]:
    """Full 4000 psi buses into empty-pressure tanks with S1/S2 held open for 60 s."""
    plant = Plant(cfg)
    plant.set_initial(bottle_psi=4000.0, lox_ullage_psi=0.0, fuel_ullage_psi=0.0, lox_mass_lbm=60.0,
                      fuel_mass_lbm=fuel_lbm, muscle_bus_psi=100.0)
    cmd = {"S1": True, "S2": True, "PB1": vents_open, "PB3": vents_open}
    out: dict[str, float] = {}
    for i in range(1, 3001):
        plant.step(0.02, cmd)
        if i in (250, 750, 3000):
            s = plant.sensors()
            out[f"PT3@{i // 50}s"], out[f"PT13@{i // 50}s"] = s["PT3"], s["PT13"]
    return out


# ---------------------------------------------------------------------------- main
def calibrate(runs: Runs, base: Optional[PlantConfig] = None) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    cfg = base if base is not None else PlantConfig()
    fitted: dict[str, dict[str, object]] = {}
    info: dict[str, object] = {}

    def keep(name: str, value: float, notes: str) -> None:
        nonlocal cfg
        cfg = _with(cfg, **{name: value})
        c = getattr(cfg, name)
        fitted[name] = {"value": value, "units": c.units, "source": "calibrated", "notes": notes}

    dt = fit_dead_time(runs)
    info["dead_time"] = dt
    used = sorted({e[1] for e in dt["pb"]})
    keep("pb_dead_time", dt["value"],
         f"median PB open lag {dt['pb_lag']:.3f} s over {len(dt['pb'])} isolated opens of {', '.join(used)} "
         f"(12:36, 12:49) minus median solenoid lag {dt['sol_lag']:.3f} s over {len(dt['sol'])} S1/S2 "
         "opens, taken as command-logging latency. Lag = midpoint between the last transducer update "
         f"within {LAG_THRESHOLD_PSI:.0f} psi of the pre-command level and the first outside it (updates "
         f"are ~0.1 s apart). PB2 and PB4 lag {dt['run_lines']['PB2']:.3f} and {dt['run_lines']['PB4']:.3f} s "
         "to their venturi, so the fuel run line adds no resolvable fill time.")

    vent = fit_lox_vent(runs, cfg)
    info["lox_vent"] = vent
    keep("cda_pb1", vent["value"],
         "golden-section least squares on log absolute PT4 over the vent blowdowns "
         + "; ".join(f"{w[0]} {w[1]:.2f}-{w[2]:.1f} s ({w[5]:.0f}->{w[6]:.0f} psi, LC4 {w[3]:.0f} lbm, "
                     f"RMS {w[4]:.1f} psi, alone {a:.2e})" for w, a in zip(vent["windows"], vent["alone"]))
         + ". Stops above ~250 psi; below that the LOX flashes and holds the tank up. Valid at "
         "lox_ullage_temp: the fit identifies cda * sqrt(T).")

    vol = fit_gas_volumes(runs, cfg)
    info["volumes"] = vol
    fuel_lbm = vol["fuel_lbm"]

    fv = fit_fuel_vent(runs, cfg, fuel_lbm)
    info["fuel_vent"] = fv
    keep("cda_pb3", fv["value"],
         f"golden-section least squares on log absolute PT14, 12:49 {FUEL_VENT_WINDOW[1]:.2f}-"
         f"{FUEL_VENT_WINDOW[2]:.1f} s ({fv['from']:.0f}->{fv['to']:.0f} psi), RMS {fv['rms']:.1f} psi. "
         f"Fuel load {fuel_lbm:.0f} lbm from the 12:36 S2 mass balance; the fit scales with the "
         "fuel ullage volume, which no load cell measures.")

    for valve in ("S1", "S2"):
        pr = fit_press(runs, cfg, valve, fuel_lbm)
        info[f"press_{valve}"] = pr
        runs_txt = ", ".join(f"{k} median {v:.2e}" for k, v in pr["by_run"].items())
        keep(f"cda_{valve.lower()}", pr["value"],
             f"median over {len(pr['pulses'])} isolated {valve} pulses ({runs_txt}; range "
             f"{pr['range'][0]:.2e}-{pr['range'][1]:.2e}) of the area whose modelled "
             f"{TANK_TAG[valve]} rise rate, 0.1-0.35 s after opening, matches the logged rise rate "
             "(median interior step between transducer updates). Fitted on rate, not on the "
             "telemetry pulse width, per D13."
             + (f" Fuel load {fuel_lbm:.0f} lbm from the 12:36 S2 mass balance." if valve == "S2" else ""))

    info["vent_open_check"] = vent_open_check(runs, cfg, fuel_lbm)
    info["scenario"] = {
        (label, open_): vent_open_scenario(c, fuel_lbm, open_)
        for label, c in (("uncalibrated", base if base is not None else PlantConfig()), ("calibrated", cfg))
        for open_ in (True, False)}
    info["config"] = cfg
    return fitted, info


def write_calibration(fitted: dict[str, dict[str, object]], path: Path) -> None:
    header = ("# Written by `python -m draco_sim.plant.calibrate` from the 2026-09-11 recordings.\n"
              "# Rerun the script instead of editing by hand. PlantConfig.calibrated() loads this\n"
              "# file over the defaults; `replay --uncalibrated` ignores it.\n")
    body = yaml.safe_dump({n: {**d, "value": _sig(float(d["value"]))} for n, d in fitted.items()},
                          sort_keys=False, default_flow_style=False, width=100)
    path.write_text(header + body, encoding="utf-8")


def _print_summary(fitted: dict[str, dict[str, object]], info: dict[str, object]) -> None:
    dt = info["dead_time"]
    print("PB dead time")
    for key, valve, te, lag in dt["pb"]:
        print(f"  {key} {valve} open @{te:8.3f}  lag {lag:.3f} s")
    print(f"  solenoid lags: " + " ".join(f"{e[1]}@{e[2]:.1f}:{e[3]:.3f}" for e in dt["sol"]))
    print(f"  PB median {dt['pb_lag']:.3f} - solenoid median {dt['sol_lag']:.3f} -> pb_dead_time {dt['value']:.2f} s;"
          f" PB4 lag minus PB2 lag (fuel run-line fill) {dt['fuel_fill']:+.3f} s")
    print("LOX vent")
    for (key, te, t_end, lox, rms, p0, p1), alone in zip(info["lox_vent"]["windows"], info["lox_vent"]["alone"]):
        print(f"  {key} {te:.2f}-{t_end:.1f} s  PT4 {p0:.0f}->{p1:.0f} psi  LC4 {lox:.1f} lbm  RMS {rms:.1f} psi"
              f"  (this window alone: {alone:.2e})")
    vol = info["volumes"]
    print("gas volumes")
    for on, dp_b, dp_t, nb in vol["lox_pulses"]:
        print(f"  12:49 S1 @{on:.2f}: PT1 -{dp_b:.0f}, PT4 +{dp_t:.0f} psi -> implies {nb:.2f} bottles on the LOX bus")
    dp_b, dp_t, dp_p = vol["fuel_dp"]
    print(f"  12:36 S2 x{vol['fuel_pulses']}: PT11 -{dp_b:.0f}, PT14 +{dp_t:.0f}, PT32 +{dp_p:.0f} psi -> fuel gas "
          f"volume {vol['fuel_ullage_L']:.1f} L, fuel load {vol['fuel_lbm']:.1f} lbm")
    fv = info["fuel_vent"]
    print(f"fuel vent  12:49 PT14 {fv['from']:.0f}->{fv['to']:.0f} psi  RMS {fv['rms']:.1f} psi")
    for valve in ("S1", "S2"):
        pr = info[f"press_{valve}"]
        print(f"press {valve}")
        for key, on, rate, steps, cda, inside in pr["pulses"]:
            print(f"  {key} @{on:8.2f}  {rate:6.0f} psi/s over {steps} steps -> {cda:.2e}{'' if inside else '  (clamped)'}")
    print("vent-open check, 12:52 GC opens with the vent open")
    for c in info["vent_open_check"]:
        print(f"  {c['valve']}: trapped line {c['line_L']:.2f} L (bus RMS {c['bus_rms']:.0f} psi); tank peak "
              f"{c['tank_peak_obs']:.0f} logged vs {c['tank_peak_pred']:.0f} model; tank/bus absolute ratio at "
              f"the peak {c['ratio_obs']:.3f} logged vs {c['ratio_pred']:.3f} model")
    print("vent-open scenario, 4000 psi buses, S1+S2 held open, LOX 60 lbm")
    for (label, open_), r in info["scenario"].items():
        print(f"  {label:<12} vents {'open  ' if open_ else 'closed'} " + "  ".join(f"{k} {v:6.0f}" for k, v in r.items()))
    print("fitted")
    for name, d in fitted.items():
        print(f"  {name:<14} {_sig(float(d['value']))}")


def report(runs: Runs, cfg: PlantConfig, fuel_lbm: float) -> None:
    tags = ("PT1", "PT2", "PT3", "PT4", "PT5", "PT11", "PT12", "PT13", "PT14", "PT15",
            "PT21", "PT22", "PT23", "PT24")
    print(f"\nreplay RMS psi, uncalibrated -> calibrated (fuel load {fuel_lbm:.0f} lbm, invalid windows excluded)")
    print("run    " + "".join(f"{t:>12}" for t in tags))
    for key in RUN_FILES:
        run = runs[key]
        cells = []
        res = {}
        for label, c in (("u", PlantConfig()), ("c", cfg)):
            _, _, pred, end = simulate(run, c, substep=0.01, fuel_mass=fuel_lbm)
            res[label] = {r["tag"]: r for r in compare(run, pred, end) if r["status"] == "ok"}
        for tag in tags:
            u, c = res["u"].get(tag), res["c"].get(tag)
            cells.append(f"{u['rms']:5.0f}>{c['rms']:<5.0f}" if u and c else f"{'-':>11}")
        print(f"{key:<7}" + " ".join(cells))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m draco_sim.plant.calibrate", description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA, help="directory holding the recordings")
    ap.add_argument("--out", type=Path, default=CALIBRATION_PATH, help="calibration YAML to write")
    ap.add_argument("--report", action="store_true", help="also replay three runs before and after")
    args = ap.parse_args(argv)

    runs = Runs(args.data)
    fitted, info = calibrate(runs)
    _print_summary(fitted, info)
    write_calibration(fitted, args.out)
    print(f"wrote {args.out}")
    if args.report:
        report(runs, info["config"], info["volumes"]["fuel_lbm"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
