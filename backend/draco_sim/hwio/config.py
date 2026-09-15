"""HwIo configuration. Every number here that isn't in the accepted module
table (docs/tag-database.md / modules.yaml) is a named, flagged placeholder —
see PLACEHOLDER_NOTES. Two kinds:

  ASSUMPTION      - not zero, because the pipeline needs *some* convention to
                    do the conversion at all (e.g. a loop-current range).
                    Picked as the single most standard industry convention,
                    not a Draco-specific datasheet value.
  PLACEHOLDER-ZERO - an error/noise term nobody supplied a number for. Zero
                    means "no injected error"; the field exists so the gap is
                    visible and overridable, not silently assumed away.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HwIoConfig:
    # ---- ASSUMPTION: measurement conventions the pipeline needs to run ----
    pt_loop_ma: tuple[float, float] = (4.0, 20.0)
    cold_junction_degc: float = 25.0
    bridge_excitation_vdc: float = 10.0  # unused by the ratiometric mV/V math; named per house rule only

    # ---- card mode selection ----
    ni9208_mode: str = "high_speed"  # "high_speed" (2 ms/ch) | "high_res" (52 ms x channels-in-scan)

    # ---- PLACEHOLDER-ZERO: unspecified error/noise terms (electrical units) ----
    pressure_transducer_accuracy_ma: float = 0.0
    pressure_noise_density_ma: float = 0.0
    tc_accuracy_mv: float = 0.0
    tc_noise_density_mv: float = 0.0
    cold_junction_accuracy_degc: float = 0.0
    bridge_accuracy_mvv: float = 0.0
    bridge_noise_density_mvv: float = 0.0

    # per-tag overrides, electrical units, empty = "use the global default above"
    per_tag_noise_stddev: dict[str, float] = field(default_factory=dict)
    per_tag_offset: dict[str, float] = field(default_factory=dict)

    seed: int = 0


PLACEHOLDER_NOTES: dict[str, str] = {
    "pt_loop_ma": "ASSUMPTION: standard ISA 4-20 mA current-loop convention; not a Draco transducer datasheet value.",
    "cold_junction_degc": "ASSUMPTION: nominal ambient cold-junction reference (25 degC); no CJC sensor spec was supplied.",
    "bridge_excitation_vdc": "ASSUMPTION: nominal bridge excitation; NOT used by the mV/V ratiometric math, named only per house rule.",
    "pressure_transducer_accuracy_ma": "PLACEHOLDER-ZERO: PT transducer accuracy not specified anywhere in source material.",
    "pressure_noise_density_ma": "PLACEHOLDER-ZERO: PT loop noise density not specified.",
    "tc_accuracy_mv": "PLACEHOLDER-ZERO: thermocouple measurement accuracy not specified.",
    "tc_noise_density_mv": "PLACEHOLDER-ZERO: thermocouple noise density not specified.",
    "cold_junction_accuracy_degc": "PLACEHOLDER-ZERO: cold-junction compensation accuracy not specified.",
    "bridge_accuracy_mvv": "PLACEHOLDER-ZERO: load-cell/bridge accuracy not specified.",
    "bridge_noise_density_mvv": "PLACEHOLDER-ZERO: bridge noise density not specified.",
}
