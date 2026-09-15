"""Extreme but meaningful configurations keep every output finite."""

from __future__ import annotations

import math

import pytest

from draco_sim.plant import Plant
from draco_sim.plant.plant import VALVES

from .helpers import UNCALIBRATED, with_values

EXTREMES = {
    "zero line volumes": dict(vol_lox_press_up=0, vol_lox_press_dn=0, vol_fuel_press_up=0,
                              vol_fuel_press_dn=0, vol_purge_bus=0, vol_muscle_bus=0),
    "huge areas": dict(cda_s1=1, cda_s2=1, cda_pb1=1, cda_pb2=1, cda_pb3=1, cda_pb4=1,
                       cda_inj_lox=1, cda_inj_fuel=1, cda_relief=1, cda_r1=1),
    "closed areas": dict(cda_s1=0, cda_pb2=0, cda_venturi=0, cda_lox_tank_outlet=0, cda_check_gas=0),
    "instant lags": dict(pb_stroke_tau=0, solenoid_tau=0, tc_tau=0, lc_tau=0, chamber_tau=0),
    "one coarse substep": dict(substep_dt=10, max_substeps=1),
    "no bottles": dict(bottle_count=0, bottle_volume=0, bottle_split_lox=5),
    "isothermal bottles, gamma near 1": dict(polytropic_n=1.0, gamma_n2=1.01),
    "common manifold": dict(bottles_common_manifold=1),
    "no actuation air": dict(init_muscle=0, compressor_mdot=0),
    "sharp reliefs, regulator and checks": dict(relief_band=0, r1_band=0, check_crack=0),
    "full venturi recovery, flat tank": dict(venturi_recovery=1, tank_height=0),
    "no venturi recovery": dict(venturi_recovery=0),
    "ullage floor at the whole tank": dict(min_ullage_frac=1),
    "long PB dead time": dict(pb_dead_time=5),
    "no combustion": dict(cstar=0, cf=0, ignition_min_mdot=0),
    "no bisection": dict(bisect_iters=0),
}
STEPS = (0.001, 0.1, 0.25, 0.02)


def drive(plant: Plant, steps: int = 24) -> None:
    for i in range(steps):
        cmd = {v: (i // (3 + j)) % 2 == 0 for j, v in enumerate(VALVES)}
        plant.step(STEPS[i % len(STEPS)], cmd)
        assert_finite(plant)


def assert_finite(plant: Plant) -> None:
    s = plant.state
    bad = [k for k, v in plant.sensors().items() if not math.isfinite(v)]
    bad += [k for k, v in s.node_mass_kg.items() if not math.isfinite(v) or v < 0.0]
    bad += [k for k, v in {**s.node_p_psig, **s.node_t_degF, **s.flow_kgps, **s.valve_pos}.items()
            if not math.isfinite(v)]
    bad += [k for k in ("lox_mass_kg", "fuel_mass_kg", "chamber_p_psig", "thrust_lbf")
            if not math.isfinite(getattr(s, k))]
    assert not bad, bad
    assert 0.0 <= s.lox_level_frac <= 1.0 and 0.0 <= s.fuel_level_frac <= 1.0
    assert s.lox_mass_kg >= 0.0 and s.fuel_mass_kg >= 0.0


def loaded(cfg, propellant_lbm: float) -> Plant:
    plant = Plant(cfg)
    plant.set_initial(bottle_psi=6000.0, lox_ullage_psi=900.0, fuel_ullage_psi=900.0,
                      lox_mass_lbm=propellant_lbm, fuel_mass_lbm=propellant_lbm)
    return plant


@pytest.mark.parametrize("propellant_lbm", [0.0, 500.0], ids=["dry", "overfilled"])
@pytest.mark.parametrize("values", EXTREMES.values(), ids=EXTREMES.keys())
def test_extreme_configs_stay_finite(values, propellant_lbm):
    drive(loaded(with_values(UNCALIBRATED, **values), propellant_lbm))


@pytest.mark.xfail(strict=True, raises=ZeroDivisionError, reason=(
    "Plant._update_ullage_volumes floors the ullage at tank_volume * min_ullage_frac and "
    "assigns GasNode.volume directly, bypassing the constructor's 1e-6 m^3 floor, so a zero "
    "floor with a full tank gives a zero volume and GasNode.pressure divides by it"))
def test_a_zero_ullage_floor_stays_finite():
    drive(loaded(with_values(UNCALIBRATED, min_ullage_frac=0), 500.0))


@pytest.mark.xfail(strict=True, raises=ZeroDivisionError, reason=(
    "Plant._substep divides by throat_area for the chamber pressure target once both "
    "propellants flow and ignite"))
def test_a_zero_throat_area_stays_finite():
    drive(loaded(with_values(UNCALIBRATED, throat_area=0), 500.0))


@pytest.mark.parametrize("dt", [0.0, -0.1, math.nan, math.inf])
def test_a_meaningless_step_changes_nothing(dt):
    plant = loaded(UNCALIBRATED, 60.0)
    before = plant.state.node_mass_kg
    plant.step(dt, {"S1": True, "PB2": True})
    assert plant.t == 0.0 and plant.state.node_mass_kg == before and plant.cmd["S1"] is False


def test_a_long_step_is_capped_and_warned():
    plant = loaded(UNCALIBRATED, 60.0)
    plant.step(10.0, {"S1": True})
    assert plant.t == 10.0
    assert plant.warnings == ["dt 10.0000 s needs 5000 sub-steps, capped at 200"]
    assert_finite(plant)


def test_negative_initial_pressures_clamp_to_vacuum():
    plant = Plant(UNCALIBRATED)
    plant.set_initial(bottle_psi=-100.0, lox_ullage_psi=-100.0, fuel_ullage_psi=-100.0,
                      muscle_bus_psi=-100.0, purge_bus_psi=-100.0)
    assert all(m == 0.0 for m in plant.state.node_mass_kg.values())
    drive(plant, steps=8)
