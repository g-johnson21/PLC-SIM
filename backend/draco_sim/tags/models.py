from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Tag:
    """One row of the tag database (see docs/tag-database.md)."""

    tag: str
    pid_tag: Optional[str]
    daq_column: Optional[str]
    aliases: tuple[str, ...]
    kind: str  # analog_in | digital_out | derived
    signal: Optional[str]  # pressure | temperature | load_cell | solenoid | pneumatic_ball | derived
    units: Optional[str]
    range: Optional[tuple[float, float]]
    module: Optional[str]
    module_index: Optional[int]
    channel: Optional[int]
    normal_state: Optional[str]  # NO | NC | None
    energize_polarity: Optional[str]
    description: str
    verified: bool
    notes: Optional[str] = None
    # load-cell extras
    capacity_lbf: Optional[float] = None
    rated_output_mv_per_v: Optional[float] = None
    # digital-out extras
    dc_index: Optional[int] = None
    solenoid_command_index: Optional[int] = None
    reserved: bool = False


@dataclass(frozen=True)
class ModuleSpec:
    """One row of modules.yaml — NI hardware specs, nothing simulator-specific."""

    type: str
    count: int
    channels: int
    resolution_bits: Optional[int]
    rate: Optional[str] = None
    input_range: Optional[str] = None
    output_range: Optional[str] = None
    notes: Optional[str] = None
