"""Mass conservation, docs/plant-model.md §3."""

from __future__ import annotations

import pytest

from .helpers import CALIBRATED, VENTS_SHUT, gas_mass, make_plant, with_values

RELIEFS = ("RV1", "RV2", "RV3", "RV5")


def test_gn2_is_conserved_while_pressing_with_the_vents_shut():
    # a 1000 psi charge keeps every relief below its setpoint, so no edge reaches atmosphere
    plant = make_plant(bottle_psi=1000.0, valves=VENTS_SHUT)
    gas0, lox0, fuel0 = gas_mass(plant), plant.lox_mass, plant.fuel_mass
    for _ in range(500):
        plant.step(0.02, {**VENTS_SHUT, "S1": True, "S2": True})
        assert gas_mass(plant) == pytest.approx(gas0, rel=1e-12)
        assert all(plant.flows[r] == 0.0 for r in RELIEFS)
    p = plant.state.node_p_psig
    assert p["lox_ullage"] > 500.0 and p["fuel_ullage"] > 500.0 and p["purge_bus"] > 200.0
    assert (plant.lox_mass, plant.fuel_mass) == (lox0, fuel0)


def test_gas_lost_while_venting_is_exactly_what_the_vents_passed():
    # one sub-step per step, so the reported flows are the whole step's transfer
    plant = make_plant(with_values(CALIBRATED, substep_dt=0.02), bottle_psi=1000.0, valves=VENTS_SHUT)
    for _ in range(100):
        plant.step(0.02, {**VENTS_SHUT, "S1": True, "S2": True})
    vented = False
    for _ in range(300):
        before = gas_mass(plant)
        plant.step(0.02, {"PB1": True, "PB3": True, "S1": False, "S2": False})
        out = (plant.flows["PB1"] + plant.flows["PB3"]) * 0.02
        vented |= out > 0.0
        assert before - gas_mass(plant) == pytest.approx(out, rel=1e-9, abs=1e-15)
    assert vented and plant.state.node_p_psig["lox_ullage"] < 50.0


def test_venting_never_adds_gas():
    plant = make_plant(bottle_psi=1000.0, valves=VENTS_SHUT)
    for _ in range(100):
        plant.step(0.05, {**VENTS_SHUT, "S1": True, "S2": True})
    previous = gas_mass(plant)
    for _ in range(200):
        plant.step(0.05, {"PB1": True, "PB3": True, "S1": False, "S2": False})
        assert gas_mass(plant) <= previous * (1.0 + 1e-12)
        previous = gas_mass(plant)
