"""The hardware I/O simulation layer: physical truth -> transducer electrical
output -> card sampling (timing + quantisation) -> engineering value, and the
reverse path for the 11 valve outputs. See docs/hwio.md for the pipeline
narrative.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Mapping, Optional

import numpy as np

from draco_sim.tags import Tag, TagDatabase

from . import scaling, thermocouple
from .channels import ChannelView
from .config import HwIoConfig

logger = logging.getLogger(__name__)

_DO_LATENCY_S = 500e-6  # NI-9476 update latency, from the module table

# card ADC/DAC electrical full-scale spans, from the accepted module table
_PT_CARD_MA = (-21.5, 21.5)
_TC_CARD_MV = (-80.0, 80.0)
_LC_CARD_MVV = (-25.0, 25.0)
_PT_CARD_BITS = 24
_TC_CARD_BITS = 24
_LC_CARD_BITS = 24  # modules.yaml leaves NI-9237 resolution_bits null; task brief says 24-bit for all three


@dataclass
class _InputChannel:
    tag: Tag
    period_s: float
    last_refresh_s: float = -math.inf
    electrical_value: Optional[float] = None
    electrical_unit: Optional[str] = None
    raw_code: Optional[int] = None
    eng_value: float = 0.0
    passthrough: bool = False  # PT0: no range, no transducer/card model


@dataclass
class _OutputChannel:
    tag: Tag
    bit: int = 0
    pending: Optional[tuple[float, int]] = None
    last_refresh_s: Optional[float] = None


class HwIo:
    def __init__(self, db: TagDatabase, config: Optional[HwIoConfig] = None):
        self.db = db
        self.config = config if config is not None else HwIoConfig()
        self._t = 0.0
        self._rng = np.random.default_rng(self.config.seed)
        self._warned: set[str] = set()
        self._physical: dict[str, float] = {}
        self._inputs: dict[str, _InputChannel] = {}
        self._outputs: dict[str, _OutputChannel] = {}
        self._build_channels()

    # ------------------------------------------------------------------ setup

    def _build_channels(self) -> None:
        for tag in self.db.inputs:
            if tag.module is None:
                continue  # THRUST: derived, no physical channel
            self._inputs[tag.tag] = _InputChannel(
                tag=tag,
                period_s=self._card_period_s(tag),
                passthrough=(tag.signal == "pressure" and tag.range is None),
            )
        for tag in self.db.outputs:
            self._outputs[tag.tag] = _OutputChannel(tag=tag)

    def _card_period_s(self, tag: Tag) -> float:
        if tag.module == "NI-9208":
            if self.config.ni9208_mode == "high_speed":
                return 0.002
            if self.config.ni9208_mode == "high_res":
                n = len(self.db.for_module("NI-9208", tag.module_index))
                return 0.052 * max(n, 1)
            raise ValueError(f"unknown ni9208_mode {self.config.ni9208_mode!r}")
        if tag.module == "NI-9211":
            return 1.0 / 14.0
        if tag.module == "NI-9237":
            return 1.0 / 50_000.0
        raise ValueError(f"no card timing model for module {tag.module!r} (tag {tag.tag!r})")

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            logger.warning(message)

    # -------------------------------------------------------------- inputs

    def set_physical(self, values: Mapping[str, float]) -> None:
        for name, value in values.items():
            tag = self.db.by_tag.get(name)
            if tag is None:
                raise ValueError(f"unknown input tag: {name!r}")
            if tag.kind == "derived":
                continue  # THRUST etc.: no physical channel, always recomputed in read_inputs()
            if tag.kind != "analog_in":
                raise ValueError(f"{name!r} is not a physical input tag (kind={tag.kind!r})")
            self._physical[tag.tag] = float(value)

    def _noise_stddev(self, tag: Tag, kind: str) -> float:
        override = self.config.per_tag_noise_stddev.get(tag.tag)
        if override is not None:
            return override
        cfg = self.config
        if kind == "pressure":
            a, b = cfg.pressure_transducer_accuracy_ma, cfg.pressure_noise_density_ma
        elif kind == "temperature":
            a, b = cfg.tc_accuracy_mv, cfg.tc_noise_density_mv
        else:
            a, b = cfg.bridge_accuracy_mvv, cfg.bridge_noise_density_mvv
        return math.hypot(a, b)

    def _offset(self, tag: Tag) -> float:
        return self.config.per_tag_offset.get(tag.tag, 0.0)

    def _refresh_input(self, ch: _InputChannel) -> None:
        tag = ch.tag
        physical = self._physical.get(tag.tag, 0.0)
        cfg = self.config

        if ch.passthrough:
            self._warn_once(
                tag.tag,
                f"{tag.tag}: no engineering range defined; passing physical value through unscaled "
                "(no transducer/card model applied)",
            )
            ch.electrical_value = None
            ch.electrical_unit = None
            ch.raw_code = None
            ch.eng_value = physical
            return

        if tag.signal == "pressure":
            raw_ma = scaling.pressure_to_current_ma(physical, tag.range, cfg.pt_loop_ma)
            raw_ma += self._offset(tag)
            sd = self._noise_stddev(tag, "pressure")
            if sd:
                raw_ma += self._rng.normal(0.0, sd)
            q, code = scaling.quantize(raw_ma, *_PT_CARD_MA, _PT_CARD_BITS)
            ch.electrical_value, ch.electrical_unit, ch.raw_code = q, "mA", code
            ch.eng_value = scaling.current_ma_to_pressure(q, tag.range, cfg.pt_loop_ma)

        elif tag.signal == "temperature":
            t_hot_c = (physical - 32.0) * 5.0 / 9.0
            cj_c = cfg.cold_junction_degc + cfg.cold_junction_accuracy_degc
            e_cj = thermocouple.emf_from_temp_c(cj_c)
            e_measured = thermocouple.emf_from_temp_c(t_hot_c) - e_cj
            e_measured += self._offset(tag)
            sd = self._noise_stddev(tag, "temperature")
            if sd:
                e_measured += self._rng.normal(0.0, sd)
            q, code = scaling.quantize(e_measured, *_TC_CARD_MV, _TC_CARD_BITS)
            ch.electrical_value, ch.electrical_unit, ch.raw_code = q, "mV", code
            t_hot_recovered_c = thermocouple.temp_c_from_emf(q + e_cj)
            ch.eng_value = t_hot_recovered_c * 9.0 / 5.0 + 32.0

        elif tag.signal == "load_cell":
            raw_mvv = scaling.force_to_bridge_mvv(physical, tag.capacity_lbf, tag.rated_output_mv_per_v)
            raw_mvv += self._offset(tag)
            sd = self._noise_stddev(tag, "load_cell")
            if sd:
                raw_mvv += self._rng.normal(0.0, sd)
            q, code = scaling.quantize(raw_mvv, *_LC_CARD_MVV, _LC_CARD_BITS)
            ch.electrical_value, ch.electrical_unit, ch.raw_code = q, "mV/V", code
            ch.eng_value = scaling.bridge_mvv_to_force(q, tag.capacity_lbf, tag.rated_output_mv_per_v)

        else:
            raise ValueError(f"no conversion model for signal {tag.signal!r} (tag {tag.tag!r})")

    def read_inputs(self) -> dict[str, float]:
        out = {name: ch.eng_value for name, ch in self._inputs.items()}
        if "THRUST" in self.db.by_tag:
            out["THRUST"] = out["LC1"] + out["LC2"] + out["LC3"]
        return out

    # ------------------------------------------------------------- outputs

    def _polarity_bit(self, tag: Tag, commanded_open: bool) -> int:
        if tag.energize_polarity == "open_when_energized":
            return 1 if commanded_open else 0
        if tag.energize_polarity == "open_when_deenergized":
            return 0 if commanded_open else 1
        # reserved spares: no polarity semantics, no field device -- bit tracks command directly
        return 1 if commanded_open else 0

    def _bit_to_open(self, tag: Tag, bit: int) -> bool:
        if tag.energize_polarity == "open_when_deenergized":
            return not bool(bit)
        return bool(bit)

    def write_outputs(self, values: Mapping[str, bool]) -> None:
        for name, value in values.items():
            out = self._outputs.get(name)
            if out is None:
                tag = self.db.by_tag.get(name)
                if tag is None or tag.kind != "digital_out":
                    raise ValueError(f"unknown output tag: {name!r}")
                out = self._outputs[tag.tag]
            bit = self._polarity_bit(out.tag, bool(value))
            out.pending = (self._t + _DO_LATENCY_S, bit)

    def valve_states(self) -> dict[str, bool]:
        return {
            name: self._bit_to_open(ch.tag, ch.bit)
            for name, ch in self._outputs.items()
            if not ch.tag.reserved
        }

    # --------------------------------------------------------------- step

    def step(self, dt_s: float) -> None:
        self._t += dt_s
        for ch in self._inputs.values():
            if (self._t - ch.last_refresh_s) >= ch.period_s:
                self._refresh_input(ch)
                ch.last_refresh_s = self._t
        for out in self._outputs.values():
            if out.pending is not None and self._t >= out.pending[0]:
                out.bit = out.pending[1]
                out.last_refresh_s = self._t
                out.pending = None

    # ------------------------------------------------------------ channels

    def channels(self) -> list[ChannelView]:
        views: list[ChannelView] = []
        for module in self.db.modules:
            for idx in range(module.count):
                by_channel = {t.channel: t for t in self.db.for_module(module.type, idx)}
                for c in range(module.channels):
                    tag = by_channel.get(c)
                    if tag is None:
                        views.append(
                            ChannelView(module.type, idx, c, None, None, None, None, None, None, None, None)
                        )
                        continue
                    if tag.kind == "digital_out":
                        out = self._outputs[tag.tag]
                        open_ = self._bit_to_open(tag, out.bit)
                        views.append(
                            ChannelView(
                                module=module.type,
                                module_index=idx,
                                channel=c,
                                tag=tag.tag,
                                kind=tag.kind,
                                electrical_value=float(out.bit),
                                electrical_unit="bit",
                                raw_code=out.bit,
                                eng_value=1.0 if open_ else 0.0,
                                eng_unit="open",
                                last_refresh_s=out.last_refresh_s,
                            )
                        )
                    else:
                        inp = self._inputs[tag.tag]
                        views.append(
                            ChannelView(
                                module=module.type,
                                module_index=idx,
                                channel=c,
                                tag=tag.tag,
                                kind=tag.kind,
                                electrical_value=inp.electrical_value,
                                electrical_unit=inp.electrical_unit,
                                raw_code=inp.raw_code,
                                eng_value=inp.eng_value,
                                eng_unit=tag.units,
                                last_refresh_s=(None if inp.last_refresh_s == -math.inf else inp.last_refresh_s),
                            )
                        )
        return views

    # --------------------------------------------------------------- reset

    def reset(self) -> None:
        self._t = 0.0
        self._rng = np.random.default_rng(self.config.seed)
        self._warned.clear()
        self._physical.clear()
        self._inputs.clear()
        self._outputs.clear()
        self._build_channels()
