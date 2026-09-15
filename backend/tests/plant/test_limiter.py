"""The no-overshoot limiter in Plant._move, docs/plant-model.md §4."""

from __future__ import annotations

import itertools

import pytest

from draco_sim.plant import Plant, PlantConfig
from draco_sim.plant.plant import GasNode

from .helpers import CALIBRATED, VENTS_SHUT, make_plant, with_values

VOLUMES = (1e-6, 1e-3, 1.0)
AREAS = (1e-8, 1e-5, 1e-2)
STEPS = (1e-4, 0.1, 10.0)


def _pair(plant: Plant, v_up: float, v_dn: float, p_up: float, p_dn: float) -> tuple[GasNode, GasNode]:
    up, dn = GasNode("up", v_up, 293.0), GasNode("dn", v_dn, 90.0)
    up.set_pressure(p_up, plant.rgas)
    dn.set_pressure(p_dn, plant.rgas)
    return up, dn


@pytest.mark.parametrize("v_up, v_dn", list(itertools.product(VOLUMES, repeat=2)))
def test_a_transfer_never_inverts_the_pair(v_up, v_dn):
    plant = Plant(PlantConfig())
    for cda, dt in itertools.product(AREAS, STEPS):
        up, dn = _pair(plant, v_up, v_dn, 3.0e7, 1.0e5)
        total = up.mass + dn.mass
        assert plant._move(up, dn, cda, dt) >= 0.0
        assert dn.pressure(plant.rgas) <= up.pressure(plant.rgas) * (1.0 + 1e-9)
        assert up.mass + dn.mass == pytest.approx(total, rel=1e-12)


@pytest.mark.parametrize("volume", VOLUMES)
def test_a_vent_never_drops_a_node_below_its_sink(volume):
    plant = Plant(PlantConfig())
    for cda, dt in itertools.product(AREAS, STEPS):
        node = GasNode("tank", volume, 293.0)
        node.set_pressure(3.0e7, plant.rgas)
        plant._move(node, None, cda, dt)
        assert node.mass > 0.0 and node.pressure(plant.rgas) >= plant.p_atm * (1.0 - 1e-9)


def test_no_flow_runs_backwards():
    plant = Plant(PlantConfig())
    up, dn = _pair(plant, 1e-3, 1e-3, 1.0e5, 3.0e7)
    masses = (up.mass, dn.mass)
    assert plant._move(up, dn, 1e-2, 10.0) == 0.0 and (up.mass, dn.mass) == masses


@pytest.mark.parametrize("substep", [0.002, 0.1])
def test_the_pressurant_chain_stays_ordered_through_a_press_and_vent(substep):
    cfg = with_values(CALIBRATED, substep_dt=substep, max_substeps=1000,
                      cda_lox_press_line=1e-2, cda_fuel_press_line=1e-2)
    plant = make_plant(cfg, bottle_psi=1000.0, valves=VENTS_SHUT)
    chain = (("bottles_lox", "lox_press_up"), ("lox_press_up", "lox_press_dn"), ("lox_press_dn", "lox_ullage"),
             ("bottles_fuel", "fuel_press_up"), ("fuel_press_up", "fuel_press_dn"), ("fuel_press_dn", "fuel_ullage"))
    peak = 0.0
    for i in range(80):
        cmd = {**VENTS_SHUT, "S1": True, "S2": True} if i < 40 else {"PB1": True, "PB3": True, "S1": False, "S2": False}
        plant.step(0.1, cmd)
        p = plant.state.node_p_psig
        peak = max(peak, p["lox_ullage"])
        for hi, lo in chain:
            assert p[hi] >= p[lo] - 1e-6, (i, hi, lo, p[hi], p[lo])
    assert peak > 300.0
