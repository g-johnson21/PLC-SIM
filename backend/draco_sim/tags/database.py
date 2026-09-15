from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Optional

import yaml

from .models import ModuleSpec, Tag

_DIGITAL_KIND = "digital_out"


def _tag_from_dict(d: dict) -> Tag:
    rng = d.get("range")
    return Tag(
        tag=d["tag"],
        pid_tag=d.get("pid_tag"),
        daq_column=d.get("daq_column"),
        aliases=tuple(d.get("aliases") or ()),
        kind=d["kind"],
        signal=d.get("signal"),
        units=d.get("units"),
        range=tuple(rng) if rng is not None else None,
        module=d.get("module"),
        module_index=d.get("module_index"),
        channel=d.get("channel"),
        normal_state=d.get("normal_state"),
        energize_polarity=d.get("energize_polarity"),
        description=d.get("description", ""),
        verified=bool(d.get("verified", False)),
        notes=d.get("notes"),
        capacity_lbf=d.get("capacity_lbf"),
        rated_output_mv_per_v=d.get("rated_output_mv_per_v"),
        dc_index=d.get("dc_index"),
        solenoid_command_index=d.get("solenoid_command_index"),
        reserved=bool(d.get("reserved", False)),
    )


def _module_from_dict(d: dict) -> ModuleSpec:
    return ModuleSpec(
        type=d["type"],
        count=d["count"],
        channels=d["channels"],
        resolution_bits=d.get("resolution_bits"),
        rate=d.get("rate"),
        input_range=d.get("input_range"),
        output_range=d.get("output_range"),
        notes=d.get("notes"),
    )


def _validate(tags: list[Tag], modules: list[ModuleSpec]) -> None:
    errors: list[str] = []

    module_channels = {m.type: m.channels for m in modules}

    seen_tags: dict[str, Tag] = {}
    seen_daq_columns: dict[str, Tag] = {}
    seen_aliases: dict[str, Tag] = {}
    seen_module_slots: dict[tuple[str, Optional[int], Optional[int]], Tag] = {}

    for t in tags:
        if t.tag in seen_tags:
            errors.append(f"duplicate tag name: {t.tag!r}")
        else:
            seen_tags[t.tag] = t

        if t.daq_column is not None:
            if t.daq_column in seen_daq_columns:
                errors.append(
                    f"duplicate daq_column {t.daq_column!r} on tags "
                    f"{seen_daq_columns[t.daq_column].tag!r} and {t.tag!r}"
                )
            else:
                seen_daq_columns[t.daq_column] = t

        for alias in t.aliases:
            if alias in seen_aliases:
                errors.append(
                    f"duplicate alias {alias!r} on tags {seen_aliases[alias].tag!r} and {t.tag!r}"
                )
            else:
                seen_aliases[alias] = t
            if alias in seen_tags and seen_tags[alias] is not t:
                errors.append(f"alias {alias!r} on tag {t.tag!r} collides with canonical tag name")

        if t.module is not None and t.channel is not None:
            slot = (t.module, t.module_index, t.channel)
            if slot in seen_module_slots:
                errors.append(
                    f"module slot {slot!r} used by both "
                    f"{seen_module_slots[slot].tag!r} and {t.tag!r}"
                )
            else:
                seen_module_slots[slot] = t

            count = module_channels.get(t.module)
            if count is None:
                errors.append(f"tag {t.tag!r} references unknown module type {t.module!r}")
            elif not (0 <= t.channel < count):
                errors.append(
                    f"tag {t.tag!r} channel {t.channel} out of range for module "
                    f"{t.module!r} (0..{count - 1})"
                )

        if t.kind == _DIGITAL_KIND and not t.reserved:
            expected = {
                "NC": "open_when_energized",
                "NO": "open_when_deenergized",
            }.get(t.normal_state)
            if expected is None:
                errors.append(f"tag {t.tag!r} has unrecognised normal_state {t.normal_state!r}")
            elif t.energize_polarity != expected:
                errors.append(
                    f"tag {t.tag!r} normal_state={t.normal_state!r} expects "
                    f"energize_polarity={expected!r}, got {t.energize_polarity!r}"
                )

    if errors:
        raise ValueError("tag database validation failed:\n  - " + "\n  - ".join(errors))


class TagDatabase:
    def __init__(self, tags: list[Tag], modules: list[ModuleSpec], meta_columns: list[str]):
        _validate(tags, modules)
        self.tags: list[Tag] = tags
        self.modules: list[ModuleSpec] = modules
        self.meta_columns: tuple[str, ...] = tuple(meta_columns)

        self.by_tag: dict[str, Tag] = {t.tag: t for t in tags}
        self._lookup: dict[str, Tag] = {}
        self.daq_column_map: dict[str, Tag] = {}
        for t in tags:
            for key in (t.tag, *t.aliases):
                self._lookup[key] = t
            if t.daq_column is not None:
                self.daq_column_map[t.daq_column] = t
                self._lookup.setdefault(t.daq_column, t)

    def resolve(self, name: str) -> Tag:
        try:
            return self._lookup[name]
        except KeyError:
            raise KeyError(
                f"unknown tag/alias/daq-column: {name!r}. "
                f"Known tags: {', '.join(sorted(self.by_tag))}"
            ) from None

    @property
    def inputs(self) -> list[Tag]:
        return [t for t in self.tags if t.kind in ("analog_in", "derived")]

    @property
    def outputs(self) -> list[Tag]:
        return [t for t in self.tags if t.kind == _DIGITAL_KIND]

    def for_module(self, module_type: str, index: Optional[int]) -> list[Tag]:
        return [t for t in self.tags if t.module == module_type and t.module_index == index]

    def module_spec(self, module_type: str) -> ModuleSpec:
        for m in self.modules:
            if m.type == module_type:
                return m
        raise KeyError(f"unknown module type: {module_type!r}")

    def plc_specs(self) -> list[dict]:
        specs = []
        for t in self.tags:
            if t.kind in ("analog_in", "derived"):
                direction, dtype = "in", "REAL"
            elif t.kind == _DIGITAL_KIND:
                direction, dtype = "out", "BOOL"
            else:
                continue
            specs.append({"name": t.tag, "direction": direction, "dtype": dtype, "units": t.units})
        return specs


def _default_path() -> Path:
    return resources.files("draco_sim.tags").joinpath("tags.yaml")


def _default_modules_path() -> Path:
    return resources.files("draco_sim.tags").joinpath("modules.yaml")


def load_tag_db(path: Optional[str | Path] = None, modules_path: Optional[str | Path] = None) -> TagDatabase:
    tags_path = Path(path) if path is not None else _default_path()
    mods_path = Path(modules_path) if modules_path is not None else _default_modules_path()

    with open(tags_path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    with open(mods_path, "r", encoding="utf-8") as f:
        mods_doc = yaml.safe_load(f)

    tags = [_tag_from_dict(d) for d in doc["tags"]]
    modules = [_module_from_dict(d) for d in mods_doc["modules"]]
    meta_columns = doc.get("daq_meta_columns", [])

    return TagDatabase(tags, modules, meta_columns)
