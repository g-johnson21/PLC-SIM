from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import replace
from pathlib import Path
from typing import Optional

import numpy as np

from draco_sim.data import RunData, load_run

from .config import Constant, PlantConfig
from .plant import SENSOR_TAGS, VALVES, Plant

# LC4 and TC5 both park on this value in the logs when the channel is dead.
STUCK_SENTINEL = 2748.524

# A logged column that changes less often than this is held telemetry rather than a
# live transducer: the old bang-bang board's PT3/PT13 columns step about once a second.
HELD_COLUMN_S = 0.5


def _is_stuck(a: np.ndarray) -> bool:
    if a.size == 0:
        return True
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return True
    return bool(abs(float(finite[0]) - STUCK_SENTINEL) < 1e-2)


def _at(run: RunData, tag: str, row: int) -> Optional[float]:
    a = run.signals.get(tag)
    if a is None or a.size <= row:
        return None
    v = float(a[row])
    return v if math.isfinite(v) else None


def seed(plant: Plant, run: RunData, lox_mass_lbm: Optional[float] = None,
         fuel_mass_lbm: Optional[float] = None, row: int = 0) -> dict[str, object]:
    """Initial conditions and settled valve states from one logged row. Returns what it
    used and why."""
    notes: dict[str, object] = {}
    kw: dict[str, float] = {}

    p1, p11 = _at(run, "PT1", row), _at(run, "PT11", row)
    if p1 is not None:
        kw["bottle_lox_psi"] = p1
    if p11 is not None:
        kw["bottle_fuel_psi"] = p11
    if p1 is not None and p11 is not None:
        notes["bottle_spread_psi"] = round(abs(p1 - p11), 1)

    # PT4/PT14 are the tank-outlet transducers; PT3/PT13 are the board's held columns
    for tags, key in ((("PT4", "PT3"), "lox_ullage_psi"), (("PT14", "PT13"), "fuel_ullage_psi")):
        v = next((x for x in (_at(run, tag, row) for tag in tags) if x is not None), None)
        if v is not None:
            kw[key] = max(0.0, v)
    for tag, key in (("PT31", "muscle_bus_psi"), ("PT32", "purge_bus_psi"), ("PT2", "lox_press_up_psi")):
        v = _at(run, tag, row)
        if v is not None:
            kw[key] = max(0.0, v)

    lc4 = run.signals.get("LC4")
    if lox_mass_lbm is not None:
        kw["lox_mass_lbm"] = lox_mass_lbm
        notes["lox_mass_source"] = "--lox-mass override"
    elif lc4 is not None and not _is_stuck(lc4) and math.isfinite(float(lc4[row])):
        kw["lox_mass_lbm"] = max(0.0, float(lc4[row]) - plant.cfg.lc4_tare.value)
        notes["lox_mass_source"] = "LC4 at the seed row minus lc4_tare"
    else:
        kw["lox_mass_lbm"] = plant.cfg.init_lox_mass.value
        notes["lox_mass_source"] = f"LC4 stuck at {STUCK_SENTINEL}; using config init_lox_mass PLACEHOLDER"

    if fuel_mass_lbm is not None:
        kw["fuel_mass_lbm"] = fuel_mass_lbm
        notes["fuel_mass_source"] = "--fuel-mass override"
    else:
        kw["fuel_mass_lbm"] = plant.cfg.init_fuel_mass.value
        notes["fuel_mass_source"] = ("no fuel tank load cell is logged; config init_fuel_mass "
                                     "PLACEHOLDER (0 lbm => no fuel flow, so PT0/THRUST stay flat)")

    tc = {}
    for i in range(1, 9):
        tag = f"TC{i}"
        a = run.signals.get(tag)
        if a is not None and a.size > row and not _is_stuck(a) and math.isfinite(float(a[row])):
            tc[tag] = float(a[row])
    if tc:
        notes["tc_seeded"] = sorted(tc)

    valves = {v: bool(run.valves[v][row]) for v in VALVES if v in run.valves}
    plant.set_initial(tc_degF=tc or None, valves=valves, **kw)
    notes["seeded"] = {k: round(v, 2) for k, v in kw.items()}
    return notes


def simulate(run: RunData, cfg: PlantConfig, *, substep: Optional[float] = None,
             lox_mass: Optional[float] = None, fuel_mass: Optional[float] = None,
             limit: Optional[float] = None) -> tuple[Plant, dict[str, object], dict[str, np.ndarray], int]:
    """Drive the plant with the logged valve states. Returns the plant, the seed notes,
    predictions per sensor tag, and the number of rows replayed."""
    if substep is not None:
        cfg = replace(cfg, substep_dt=Constant(substep, "s", "PLACEHOLDER", cfg.substep_dt.notes))
    plant = Plant(cfg)
    notes = seed(plant, run, lox_mass, fuel_mass)

    t = run.t
    end = len(t)
    if limit is not None:
        end = max(2, min(int(np.searchsorted(t, t[0] + limit)), len(t)))

    pred = {tag: np.full(end, np.nan) for tag in SENSOR_TAGS}
    valves = {v: a for v, a in run.valves.items() if v in VALVES}
    for i in range(end):
        if i > 0:
            dt = float(t[i] - t[i - 1])
            if math.isfinite(dt) and dt > 0.0:
                plant.step(min(dt, 0.1), {v: bool(a[i]) for v, a in valves.items()})
        s = plant.sensors()
        for tag in SENSOR_TAGS:
            pred[tag][i] = s[tag]
    return plant, notes, pred, end


def invalid_rows(run: RunData, tag: str, end: int) -> np.ndarray:
    """Rows inside the tag's annotated invalid window (data/annotations.yaml)."""
    t = run.t[:end]
    if tag not in run.invalid_from:
        return np.zeros(end, dtype=bool)
    bad = t >= run.invalid_from[tag]
    if tag in run.invalid_to:
        bad &= t < run.invalid_to[tag]
    return bad


def held_like(pred: np.ndarray, obs: np.ndarray) -> np.ndarray:
    """Sample the prediction only where the logged column updates and hold it in between,
    so a held telemetry column is compared like for like."""
    changed = np.ones(len(obs), dtype=bool)
    changed[1:] = obs[1:] != obs[:-1]
    last = np.maximum.accumulate(np.where(changed, np.arange(len(obs)), 0))
    return pred[last]


def is_held_column(run: RunData, obs: np.ndarray) -> bool:
    changes = np.nonzero(np.diff(obs) != 0)[0] + 1
    return len(changes) > 2 and float(np.median(np.diff(run.t[changes]))) > HELD_COLUMN_S


def _stats(pred: np.ndarray, obs: np.ndarray, keep: np.ndarray) -> tuple[float, float, float, float, float, int]:
    ok = np.isfinite(pred) & np.isfinite(obs) & keep
    n = int(ok.sum())
    if n < 2:
        return (math.nan,) * 5 + (n,)
    p, o = pred[ok], obs[ok]
    err = p - o
    rms = float(np.sqrt(np.mean(err ** 2)))
    mx = float(np.max(np.abs(err)))
    bias = float(np.mean(err))
    sp, so = float(p.std()), float(o.std())
    corr = float(np.corrcoef(p, o)[0, 1]) if sp > 1e-9 and so > 1e-9 else math.nan
    return rms, mx, bias, corr, so, n


def compare(run: RunData, pred: dict[str, np.ndarray], end: int) -> list[dict[str, object]]:
    """Per-tag error statistics, excluding annotated invalid windows."""
    rows: list[dict[str, object]] = []
    for tag in SENSOR_TAGS:
        obs = run.signals.get(tag)
        if obs is None:
            rows.append({"tag": tag, "status": "not logged"})
            continue
        obs = obs[:end]
        if _is_stuck(obs):
            rows.append({"tag": tag, "status": f"channel stuck at {STUCK_SENTINEL} - skipped"})
            continue
        held = is_held_column(run, obs)
        p = held_like(pred[tag][:end], obs) if held else pred[tag][:end]
        bad = invalid_rows(run, tag, end)
        rms, mx, bias, corr, sd, n = _stats(p, obs, ~bad)
        good = obs[~bad]
        rows.append({
            "tag": tag, "status": "ok", "rms": rms, "max": mx, "bias": bias, "corr": corr,
            "obs_sd": sd, "pred_sd": float(np.nanstd(p[~bad])), "n": n, "held": held,
            "excluded": int(bad.sum()),
            "obs_rng": (float(np.nanmin(good)), float(np.nanmax(good))),
            "pred_rng": (float(np.nanmin(p[~bad])), float(np.nanmax(p[~bad]))),
        })
    return rows


def run_replay(path: Path, cfg: PlantConfig, out: Optional[Path], every: int,
               substep: Optional[float], lox_mass: Optional[float], fuel_mass: Optional[float],
               limit: Optional[float], label: str = "") -> int:
    run = load_run(path)
    plant, notes, pred, end = simulate(run, cfg, substep=substep, lox_mass=lox_mass,
                                       fuel_mass=fuel_mass, limit=limit)
    t = run.t
    missing = [v for v in VALVES if v not in run.valves]

    print(f"\n=== replay: {path.name} {label}===")
    print(f"rows {end} of {len(t)}   t {t[0]:.2f} .. {t[end - 1]:.2f} s   median dt {run.sample_period_s * 1000:.1f} ms")
    print(f"sub-step {plant.k['substep_dt'] * 1000:.1f} ms")
    if missing:
        print(f"valve channels absent from the log (held de-energised): {', '.join(missing)}")
    print("seed: " + ", ".join(f"{k}={v}" for k, v in notes["seeded"].items()))
    print(f"      LOX mass <- {notes['lox_mass_source']}")
    print(f"      fuel mass <- {notes['fuel_mass_source']}")
    if "tc_seeded" in notes:
        print(f"      thermocouples seeded from row 0: {', '.join(notes['tc_seeded'])}")
    if "bottle_spread_psi" in notes:
        print(f"      PT1/PT11 differ by {notes['bottle_spread_psi']} psi at t0 "
              f"(bottles_common_manifold={'on' if plant.common_bottles else 'off'})")

    rows = compare(run, pred, end)
    hdr = f"{'tag':<8}{'units':>6}{'obs rng':>20}{'pred rng':>20}{'RMS':>10}{'maxerr':>10}{'bias':>10}{'corr':>8}"
    print("\n" + hdr)
    print("-" * len(hdr))
    for r in rows:
        tag = r["tag"]
        units = "psi" if tag.startswith("PT") else ("degF" if tag.startswith("TC") else "lbf")
        if r["status"] != "ok":
            print(f"{tag:<8}{units:>6}  {r['status']}")
            continue
        (o_lo, o_hi), (p_lo, p_hi) = r["obs_rng"], r["pred_rng"]
        flags = ("  held" if r["held"] else "") + (f"  {r['excluded']} rows invalid" if r["excluded"] else "")
        print(f"{tag:<8}{units:>6}{o_lo:>9.1f}..{o_hi:<10.1f}{p_lo:>9.1f}..{p_hi:<10.1f}"
              f"{r['rms']:>10.1f}{r['max']:>10.1f}{r['bias']:>10.1f}{r['corr']:>8.3f}{flags}")
    if any(r.get("held") for r in rows):
        print("held = logged column is held telemetry; the prediction is sampled where it updates")

    print("\nsign check (does the model move the right way?)")
    ok_rows = [r for r in rows if r["status"] == "ok"]
    bad = [r["tag"] for r in ok_rows
           if math.isfinite(r["corr"]) and r["corr"] < 0.0 and r["obs_sd"] > 1.0 and r["pred_sd"] > 1.0]
    flat = [r["tag"] for r in ok_rows if r["pred_sd"] <= 1.0 < r["obs_sd"]]
    if bad:
        print("  NEGATIVE correlation where BOTH logged and predicted channels moved.")
        print("  That is a topology symptom, not a constant that needs tuning:")
        print("    " + ", ".join(bad))
    else:
        print("  no channel where the model and the log both moved and moved opposite ways")
    if flat:
        print("  model flat while the log moved (nothing drove it - check the seed and the drive coverage):")
        print("    " + ", ".join(flat))

    print("\ndrive coverage (what the log actually commanded)")
    for v in VALVES:
        a = run.valves.get(v)
        if a is None:
            continue
        a = a[:end].astype(int)
        trans = int((np.diff(a) != 0).sum()) if a.size > 1 else 0
        print(f"  {v:<4} open {int(a.sum()):>6} of {a.size} rows, {trans} transitions"
              + ("   <-- never commanded open" if a.sum() == 0 else ""))

    if out is not None:
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            cols = [t_ for t_ in SENSOR_TAGS if t_ in run.signals]
            w.writerow(["t"] + [f"{c}_obs" for c in cols] + [f"{c}_pred" for c in cols]
                       + [f"v_{v}" for v in VALVES if run.valves.get(v) is not None])
            for i in range(0, end, max(1, every)):
                row = [f"{t[i]:.3f}"]
                row += [f"{run.signals[c][i]:.4g}" for c in cols]
                row += [f"{pred[c][i]:.4g}" for c in cols]
                row += [int(run.valves[v][i]) for v in VALVES if run.valves.get(v) is not None]
                w.writerow(row)
        print(f"\nwrote {out} (every {every} rows)")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m draco_sim.plant.replay",
        description="Drive the plant model with a recorded DAQ run and compare, tag by tag. "
                    "Uses the calibrated constants unless told otherwise; negative correlations "
                    "point at topology, not at a constant.")
    ap.add_argument("csv", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="coarse predicted-vs-logged time series CSV")
    ap.add_argument("--every", type=int, default=40, help="write every Nth row to --out (default 40)")
    ap.add_argument("--config", type=Path, default=None, help="PlantConfig YAML (replaces the calibration)")
    ap.add_argument("--uncalibrated", action="store_true", help="plain PlantConfig() defaults")
    ap.add_argument("--substep", type=float, default=0.01,
                    help="integration sub-step in s (default 0.01; 0 = use config)")
    ap.add_argument("--lox-mass", type=float, default=None, help="override initial LOX mass, lbm")
    ap.add_argument("--fuel-mass", type=float, default=None,
                    help="override initial fuel mass, lbm (no fuel load cell exists, so the engine "
                         "stays dead without this)")
    ap.add_argument("--limit", type=float, default=None, help="only replay the first N seconds")
    args = ap.parse_args(argv)

    if args.config:
        cfg, label = PlantConfig.from_yaml(args.config), f"({args.config.name}) "
    elif args.uncalibrated:
        cfg, label = PlantConfig(), "(uncalibrated) "
    else:
        cfg, label = PlantConfig.calibrated(), "(calibrated) "
    substep = args.substep if args.substep and args.substep > 0 else None
    return run_replay(args.csv, cfg, args.out, args.every, substep, args.lox_mass,
                      args.fuel_mass, args.limit, label)


if __name__ == "__main__":
    sys.exit(main())
