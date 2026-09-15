"""step() sub-steps internally, so the caller's step size must not change the answer
(docs/plant-model.md §4). The scenario presses both tanks, fires, and vents."""

from __future__ import annotations

import pytest

from .helpers import CALIBRATED, with_values, make_plant

SCHEDULE = ((0.0, {"PB1": False, "PB3": False}), (0.5, {"S1": True, "S2": True}),
            (2.5, {"S1": False, "S2": False}), (3.0, {"PB2": True}), (3.5, {"PB4": True}),
            (5.0, {"PB2": False, "PB4": False}), (5.5, {"PB1": True, "PB3": True}))
DURATION_S = 6.0
SAMPLE_S = 0.1


def trace(cfg, dt: float) -> list[dict[str, float]]:
    plant = make_plant(cfg)
    cmd: dict[str, bool] = {}
    out = []
    per_sample = round(SAMPLE_S / dt)
    for i in range(round(DURATION_S / dt)):
        for at, change in SCHEDULE:
            if abs(i * dt - at) < dt / 2:
                cmd.update(change)
        plant.step(dt, cmd)
        if (i + 1) % per_sample == 0:
            out.append(plant.sensors())
    return out


def worst_gap(a, b) -> dict[str, float]:
    return {tag: max(abs(x[tag] - y[tag]) for x, y in zip(a, b)) for tag in a[0]}


@pytest.fixture(scope="module")
def coarse():
    return trace(CALIBRATED, 0.1)


def test_the_scenario_presses_and_fires(coarse):
    assert max(s["PT4"] for s in coarse) > 300.0 and max(s["PT14"] for s in coarse) > 300.0
    assert max(s["PT0"] for s in coarse) > 50.0 and max(s["THRUST"] for s in coarse) > 10.0


def test_1_ms_and_100_ms_steps_agree_at_a_1_ms_substep():
    cfg = with_values(CALIBRATED, substep_dt=0.001)
    gaps = worst_gap(trace(cfg, 0.001), trace(cfg, 0.1))
    assert max(gaps.values()) < 1e-6, gaps


def test_steps_at_or_above_the_substep_agree(coarse):
    gaps = worst_gap(trace(CALIBRATED, 0.01), coarse)
    assert max(gaps.values()) < 1e-6, gaps


def test_1_ms_steps_differ_only_by_integration_error(coarse):
    # a 1 ms step integrates at 1 ms instead of 2 ms; the 0.5 L pocket behind C1 (PT2)
    # and the engine manifolds show it most
    fine = trace(CALIBRATED, 0.001)
    gaps = worst_gap(fine, coarse)
    for tag, gap in gaps.items():
        swing = max(s[tag] for s in fine) - min(s[tag] for s in fine)
        if tag.startswith("PT") and swing >= 50.0:
            assert gap <= 0.05 * swing, (tag, gap, swing)
