"""Builders shared by the plant tests.

Initial conditions come from the demo's recorded pre-fire configuration
(`draco_sim.runtime.demo.INITIAL`). Tests assert properties and error ceilings, never the
value of a PLACEHOLDER constant; calibration is expected to move the constants.
"""

from __future__ import annotations

from dataclasses import replace

from draco_sim.plant import Plant, PlantConfig
from draco_sim.runtime.demo import INITIAL

CALIBRATED = PlantConfig.calibrated()
UNCALIBRATED = PlantConfig()

# docs/plant-model.md §6: the fuel load implied by the 12:36 S2 mass balance
FUEL_LBM = 39.5

VENTS_SHUT = {"PB1": False, "PB3": False}


def with_values(cfg: PlantConfig, **values: float) -> PlantConfig:
    return replace(cfg, **{n: replace(getattr(cfg, n), value=float(v)) for n, v in values.items()})


def make_plant(cfg: PlantConfig = CALIBRATED, **initial) -> Plant:
    plant = Plant(cfg)
    plant.set_initial(**{**INITIAL, **initial})
    return plant


def gas_mass(plant: Plant) -> float:
    """GN2 in every node but the muscle bus, which holds compressor air."""
    return sum(node.mass for name, node in plant.nodes.items() if name != "muscle_bus")
