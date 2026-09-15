"""calibrate.py piece by piece on the fixture slices, docs/plant-model.md §6.

The full script takes about 70 s over whole recordings, so these tests run its fits on
the windows the slices cover and check that each committed constant still sits in the
valley of its own cost function, rather than pinning fitted values."""

from __future__ import annotations

import numpy as np
import pytest
import yaml

from draco_sim.plant import calibrate as cal
from draco_sim.plant.config import CALIBRATION_PATH, PlantConfig

from .helpers import CALIBRATED, FUEL_LBM, with_values


def test_golden_section_finds_a_minimum():
    assert cal._golden(lambda x: (x - 0.3) ** 2, -1.0, 1.0) == pytest.approx(0.3, abs=1e-5)


def test_the_increasing_solver_flags_clamped_results():
    x, inside = cal._solve_increasing(lambda v: v ** 3, 0.125, 0.0, 1.0)
    assert inside and x == pytest.approx(0.5, abs=1e-6)
    assert cal._solve_increasing(lambda v: v, 5.0, 0.0, 1.0) == (1.0, False)
    assert cal._solve_increasing(lambda v: v, -5.0, 0.0, 1.0) == (0.0, False)


def test_the_run_valves_share_one_actuation_delay(runs):
    first, second = cal.fit_dead_time(runs), cal.fit_dead_time(runs)
    assert first == second
    lags = first["run_lines"]
    # D15: PB4 reaches its venturi as fast as PB2 does, so there is no fuel run-line fill
    assert abs(lags["PB4"] - lags["PB2"]) < 0.05
    assert 0.0 < CALIBRATED.pb_dead_time.value < lags["PB2"]


def test_the_s2_pulse_rise_rate_is_deterministic(runs):
    (on, off), = cal._pulses(runs["12:36"], "S2")
    rate = cal._observed_rate(runs, "12:36", "PT14", on, off)
    assert rate == cal._observed_rate(runs, "12:36", "PT14", on, off)
    assert rate[0] > 0.0 and rate[2] >= 3


def test_the_s2_pulse_fits_near_the_calibrated_area(runs):
    fit = cal.fit_press(runs, CALIBRATED, "S2", FUEL_LBM)
    assert fit == cal.fit_press(runs, CALIBRATED, "S2", FUEL_LBM)
    (_, _, _, _, area, inside), = fit["pulses"]
    assert inside and 0.5 < area / CALIBRATED.cda_s2.value < 2.0


def test_the_s2_mass_balance_implies_a_physical_fuel_load(runs):
    vol = cal.fit_gas_volumes(runs, CALIBRATED)
    assert vol == cal.fit_gas_volumes(runs, CALIBRATED)
    assert vol["fuel_pulses"] == 1 and all(dp > 0.0 for dp in vol["fuel_dp"])
    k = CALIBRATED.si()
    capacity_lbm = k["tank_volume"] * k["rho_fuel"] / cal.LBM_KG
    assert 0.0 < vol["fuel_lbm"] < capacity_lbm


def _vent_cost(runs, name: str, tag: str, start: float, end: float, lox_window, fuel_lbm: float, scale: float):
    run = runs["12:49"]
    i0, i1 = cal._row(run, start) - 1, cal._row(run, end)
    rows = np.array([u - i0 for u in runs.updates("12:49", tag) if cal._row(run, start) <= u < i1])
    obs = run.signals[tag][i0:i1][rows]
    cfg = with_values(CALIBRATED, **{name: getattr(CALIBRATED, name).value * scale})
    pred = cal._window(cfg, run, i0, i1, cal._median(run, "LC4", *lox_window), fuel_lbm, (tag,))[tag][rows]
    return cal._log_rms(pred, obs), cal._psi_rms(pred, obs)


def test_the_lox_vent_area_sits_in_the_12_49_blowdown_valley(runs):
    key, start, end, lox_window = cal.LOX_VENT_WINDOWS[1]
    assert key == "12:49"
    cost = {s: _vent_cost(runs, "cda_pb1", "PT4", start, end, lox_window, 0.0, s) for s in (0.5, 1.0, 2.0)}
    assert cost[1.0][0] < min(cost[0.5][0], cost[2.0][0])
    assert cost[1.0][1] < 40.0


def test_the_fuel_vent_area_is_the_12_49_blowdown_optimum(runs):
    key, start, end = cal.FUEL_VENT_WINDOW
    assert key == "12:49"
    lox_window = cal.LOX_VENT_WINDOWS[1][3]
    cost = {s: _vent_cost(runs, "cda_pb3", "PT14", start, end, lox_window, FUEL_LBM, s) for s in (0.8, 1.0, 1.25)}
    assert cost[1.0][0] < min(cost[0.8][0], cost[1.25][0])
    assert cost[1.0][1] < 50.0


def test_the_calibration_file_is_exactly_what_the_script_writes(tmp_path):
    fitted = yaml.safe_load(CALIBRATION_PATH.read_text(encoding="utf-8"))
    cal.write_calibration(fitted, tmp_path / "a.yaml")
    cal.write_calibration(fitted, tmp_path / "b.yaml")
    written = (tmp_path / "a.yaml").read_bytes()
    assert written == (tmp_path / "b.yaml").read_bytes()
    assert written.replace(b"\r\n", b"\n") == CALIBRATION_PATH.read_bytes().replace(b"\r\n", b"\n")
    assert PlantConfig.calibrated(tmp_path / "a.yaml") == CALIBRATED
