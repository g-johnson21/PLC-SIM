from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ChannelView:
    """One physical channel on one card instance, assigned or not."""

    module: str
    module_index: int
    channel: int
    tag: Optional[str]
    kind: Optional[str]  # 'analog_in' | 'derived' | 'digital_out' | None (unassigned)
    electrical_value: Optional[float]
    electrical_unit: Optional[str]  # 'mA' | 'mV' | 'mV/V' | 'bit' | None
    raw_code: Optional[int]
    eng_value: Optional[float]
    eng_unit: Optional[str]
    last_refresh_s: Optional[float]
