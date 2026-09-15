"""PlantConfig: YAML round trip, validators, and the calibration overlay."""

from __future__ import annotations

import math
from dataclasses import fields

import pytest
import yaml

from draco_sim.plant import Plant, PlantConfig
from draco_sim.plant.config import CALIBRATION_PATH, SOURCES, Constant

from .helpers import CALIBRATED, UNCALIBRATED, with_values


def test_defaults_round_trip_through_yaml(tmp_path):
    path = tmp_path / "plant.yaml"
    text = UNCALIBRATED.to_yaml(path)
    assert path.read_text(encoding="utf-8") == text
    assert PlantConfig.from_yaml(path) == UNCALIBRATED


def test_an_edited_config_round_trips(tmp_path):
    cfg = with_values(CALIBRATED, cda_pb1=1.5e-5, init_lox_mass=12.5)
    cfg.to_yaml(tmp_path / "plant.yaml")
    assert PlantConfig.from_yaml(tmp_path / "plant.yaml") == cfg


def test_a_partial_file_keeps_the_defaults_and_inherits_metadata(tmp_path):
    path = tmp_path / "plant.yaml"
    path.write_text("cda_s1:\n  value: 2.0e-5\n", encoding="utf-8")
    cfg = PlantConfig.from_yaml(path)
    default = UNCALIBRATED.cda_s1
    assert cfg.cda_s1 == Constant(2.0e-5, default.units, default.source, default.notes)
    assert all(getattr(cfg, f.name) == getattr(UNCALIBRATED, f.name) for f in fields(cfg) if f.name != "cda_s1")


def test_an_empty_file_is_the_defaults(tmp_path):
    (tmp_path / "plant.yaml").write_text("", encoding="utf-8")
    assert PlantConfig.from_yaml(tmp_path / "plant.yaml") == UNCALIBRATED


@pytest.mark.parametrize("text, message", [
    ("no_such_constant:\n  value: 1\n", "unknown config keys ['no_such_constant']"),
    ("cda_s1: 2.0e-5\n", "cda_s1 must be a mapping with at least a 'value'"),
    ("cda_s1:\n  units: m^2\n", "cda_s1 must be a mapping with at least a 'value'"),
    ("cda_s1:\n  value: 1\n  source: guess\n", "bad source 'guess'"),
    ("cda_s1:\n  value: 1\n  units: furlongs\n", "unknown units 'furlongs'"),
    ("cda_s1:\n  value: lots\n", "could not convert"),
])
def test_bad_files_are_rejected(tmp_path, text, message):
    path = tmp_path / "plant.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=message.replace("[", r"\[").replace("]", r"\]")):
        PlantConfig.from_yaml(path)


def test_constants_validate_their_source_and_units():
    for source in SOURCES:
        Constant(1.0, "psi", source)
    with pytest.raises(ValueError, match="bad source"):
        Constant(1.0, "psi", "placeholder")
    with pytest.raises(ValueError, match="unknown units"):
        Constant(1.0, "bar", "user")


@pytest.mark.parametrize("value, units, si", [
    (1.0, "psi", 6894.757293168361), (32.0, "degF", 273.15), (212.0, "degF", 373.15),
    (1.0, "lbm", 0.45359237), (1.0, "lbf", 4.4482216152605), (1.0, "gal", 0.003785411784),
    (1.0, "in^2", 0.00064516), (1.0, "L", 1e-3), (1.0, "psi/(kg/s)", 6894.757293168361)])
def test_unit_conversions(value, units, si):
    assert Constant(value, units, "physical-constant").si == pytest.approx(si, rel=1e-12)


def test_every_default_carries_a_source_and_none_claims_calibration():
    for f in fields(UNCALIBRATED):
        c = getattr(UNCALIBRATED, f.name)
        assert c.source in SOURCES and c.source != "calibrated" and math.isfinite(c.si), f.name
    assert {name for name, _ in UNCALIBRATED.placeholders()} == {
        f.name for f in fields(UNCALIBRATED) if getattr(UNCALIBRATED, f.name).source == "PLACEHOLDER"}


def test_the_calibration_file_only_holds_calibrated_constants():
    raw = yaml.safe_load(CALIBRATION_PATH.read_text(encoding="utf-8"))
    assert raw, "calibration.yaml is empty"
    for name, spec in raw.items():
        default = getattr(UNCALIBRATED, name)
        fitted = getattr(CALIBRATED, name)
        assert fitted.source == "calibrated" and fitted.units == default.units, name
        assert fitted.notes.strip() and math.isfinite(fitted.value) and fitted.value > 0.0, name
    assert {name for name, _ in CALIBRATED.placeholders()} == {
        name for name, _ in UNCALIBRATED.placeholders()} - set(raw)


def test_calibrated_overlays_only_the_fitted_constants():
    raw = yaml.safe_load(CALIBRATION_PATH.read_text(encoding="utf-8"))
    for f in fields(UNCALIBRATED):
        if f.name not in raw:
            assert getattr(CALIBRATED, f.name) == getattr(UNCALIBRATED, f.name), f.name


def test_a_missing_calibration_file_falls_back_to_the_defaults(tmp_path):
    assert PlantConfig.calibrated(tmp_path / "absent.yaml") == UNCALIBRATED


def test_the_plant_defaults_to_the_calibrated_config():
    assert Plant().cfg == CALIBRATED
