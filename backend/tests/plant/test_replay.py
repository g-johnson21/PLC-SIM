"""Calibrated replay error ceilings on the fixture slices, docs/plant-model.md §6.

Ceilings sit about 25 % above the RMS measured when the suite was written, so a
recalibration that holds its ground passes and a regression does not. Settings match
`calibrate --report`: 10 ms sub-step and the 39.5 lbm fuel load."""

from __future__ import annotations

import numpy as np
import pytest

from draco_sim.plant import replay

from .helpers import CALIBRATED, FUEL_LBM, UNCALIBRATED

CEILINGS_PSI = {
    "12:36": {"PT11": 25, "PT13": 50, "PT14": 50, "PT23": 50, "PT32": 30},
    "12:49": {"PT1": 50, "PT3": 200, "PT4": 190, "PT11": 25, "PT13": 165, "PT14": 160, "PT22": 325, "PT24": 310},
    "12:52": {"PT3": 700, "PT4": 590, "PT13": 630, "PT14": 560},
}

_CACHE: dict[tuple[str, str], dict[str, dict]] = {}


def stats(runs, key: str, label: str) -> dict[str, dict]:
    if (key, label) not in _CACHE:
        cfg = CALIBRATED if label == "calibrated" else UNCALIBRATED
        _, _, pred, end = replay.simulate(runs[key], cfg, substep=0.01, fuel_mass=FUEL_LBM)
        _CACHE[(key, label)] = {r["tag"]: r for r in replay.compare(runs[key], pred, end) if r["status"] == "ok"}
    return _CACHE[(key, label)]


@pytest.mark.parametrize("key, tag, ceiling", [
    (key, tag, ceiling) for key, tags in CEILINGS_PSI.items() for tag, ceiling in tags.items()])
def test_calibrated_replay_stays_under_its_ceiling(runs, key, tag, ceiling):
    assert stats(runs, key, "calibrated")[tag]["rms"] <= ceiling


@pytest.mark.parametrize("key", ["12:49", "12:52"])
def test_calibration_improves_the_tank_channels_with_a_vent_open(runs, key):
    for tag in ("PT4", "PT14"):
        assert stats(runs, key, "calibrated")[tag]["rms"] <= 0.6 * stats(runs, key, "uncalibrated")[tag]["rms"], tag


def test_the_12_49_fuel_side_tracks_its_blowdown(runs):
    for tag in ("PT13", "PT14"):
        assert stats(runs, "12:49", "calibrated")[tag]["corr"] >= 0.85, tag


def test_the_rud_windows_are_excluded(runs):
    rows = stats(runs, "12:49", "calibrated")
    assert rows["PT0"]["excluded"] > 0 and rows["LC4"]["excluded"] > 0


def test_replay_is_deterministic(runs):
    first = replay.simulate(runs["12:49"], CALIBRATED, substep=0.01, fuel_mass=FUEL_LBM)[2]
    second = replay.simulate(runs["12:49"], CALIBRATED, substep=0.01, fuel_mass=FUEL_LBM)[2]
    assert all(np.array_equal(first[tag], second[tag], equal_nan=True) for tag in first)
