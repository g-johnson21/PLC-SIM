from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from draco_sim.hwio import HwIoConfig
from draco_sim.plant import PlantConfig

ROLES = ("regulation", "sequence", "monitor", "other")
OPS = (">", ">=", "<", "<=")

PLACEHOLDER_LABEL = "PLACEHOLDER -- operator-set"

NOTICE = ("Programming environment is a custom IEC 61131-3-style language, NOT the "
          "cRIO-9047's native LabVIEW FPGA/RT environment.")


@dataclass(frozen=True)
class ProgramSource:
    """One program as the IDE hands it over: text for ST, a JSON document (text or
    dict) for LD/SFC. `role` is the scan loop's own classification, not the
    language's: it decides what an abort switches off and what locks manual control
    out. `None` means "infer it at load time" (Simulator.infer_role); an explicit
    value overrides the inference."""

    name: str
    language: Literal["ST", "LD", "SFC"]
    source: Any
    role: Literal["regulation", "sequence", "monitor", "other"] | None = None

    def __post_init__(self) -> None:
        if str(self.language).upper() not in ("ST", "LD", "SFC"):
            raise ValueError(f"language must be ST, LD or SFC, got {self.language!r}")
        if self.role is not None and self.role not in ROLES:
            raise ValueError(f"role must be one of {ROLES} or None, got {self.role!r}")

    def as_dict(self) -> dict:
        return {"name": self.name, "language": str(self.language).upper(),
                "source": self.source, "role": self.role}


@dataclass
class AbortThreshold:
    """One row of the auto-abort table, evaluated against the PLC input image every
    scan. Nothing in the source material gives a real trip value, so every default
    is disabled at 0.0 and says so."""

    tag: str
    op: Literal[">", ">=", "<", "<="] = ">"
    value: float = 0.0
    enabled: bool = False
    label: str = PLACEHOLDER_LABEL

    def __post_init__(self) -> None:
        if self.op not in OPS:
            raise ValueError(f"op must be one of {OPS}, got {self.op!r}")
        self.tag = str(self.tag)
        self.value = float(self.value)
        self.enabled = bool(self.enabled)

    def test(self, reading: float) -> bool:
        if self.op == ">":
            return reading > self.value
        if self.op == ">=":
            return reading >= self.value
        if self.op == "<":
            return reading < self.value
        return reading <= self.value

    def as_dict(self) -> dict:
        return {"tag": self.tag, "op": self.op, "value": self.value,
                "enabled": self.enabled, "label": self.label}

    @classmethod
    def from_any(cls, item: "AbortThreshold | dict") -> "AbortThreshold":
        if isinstance(item, AbortThreshold):
            return cls(item.tag, item.op, item.value, item.enabled, item.label)
        d = dict(item)
        unknown = set(d) - {"tag", "op", "value", "enabled", "label"}
        if unknown:
            raise ValueError(f"unknown threshold field(s): {sorted(unknown)}")
        if "tag" not in d:
            raise ValueError("threshold needs a 'tag'")
        return cls(d["tag"], d.get("op", ">"), d.get("value", 0.0),
                   d.get("enabled", False), d.get("label", PLACEHOLDER_LABEL))


@dataclass
class BbLoopConfig:
    """Which VAR_GLOBALs of the loaded regulation programs the HMI bang-bang entries
    mirror into, and which solenoid the loop drives. The names are the ones the
    shipped examples declare."""

    setpoint: str
    deadband: str
    enable: str
    solenoid: str


def _default_bb_globals() -> dict[str, BbLoopConfig]:
    return {
        "lox": BbLoopConfig("setpoint", "deadband", "bb_lox_enable", "S1"),
        "fuel": BbLoopConfig("setpoint_fuel", "deadband_fuel", "bb_fuel_enable", "S2"),
    }


def _default_bb_defaults() -> dict[str, dict[str, Any]]:
    # Recorded pre-fire configuration of 2026-09-11 (the same values the example
    # programs carry as their VAR_GLOBAL initialisers). Not a calibrated setpoint.
    return {
        "lox": {"setpoint": 904.0, "deadband": 15.0, "enable": False},
        "fuel": {"setpoint": 870.0, "deadband": 15.0, "enable": False},
    }


def _default_thresholds() -> list[AbortThreshold]:
    # The three readings examples/abort_monitor.st watches. Disabled at 0.0: no
    # source material gives a trip pressure for any of them.
    return [AbortThreshold("PT0", ">", 0.0, False, PLACEHOLDER_LABEL + " (chamber)"),
            AbortThreshold("PT5", ">", 0.0, False, PLACEHOLDER_LABEL + " (LOX manifold)"),
            AbortThreshold("PT15", ">", 0.0, False, PLACEHOLDER_LABEL + " (fuel manifold)")]


@dataclass
class SimConfig:
    scan_hz: float = 50.0
    hwio: HwIoConfig = field(default_factory=HwIoConfig)
    plant: PlantConfig = field(default_factory=PlantConfig.calibrated)

    bb_globals: dict[str, BbLoopConfig] = field(default_factory=_default_bb_globals)
    bb_defaults: dict[str, dict[str, Any]] = field(default_factory=_default_bb_defaults)

    abort_thresholds: list[AbortThreshold] = field(default_factory=_default_thresholds)
    # VAR_GLOBAL a loaded program may raise to request an abort (examples/abort_monitor.st)
    auto_abort_global: str = "auto_abort_request"

    event_capacity: int = 2000
    sim_version: str = "0.1.0"
    notice: str = NOTICE
    examples_dir: str | None = None  # default: backend/examples next to the package

    def __post_init__(self) -> None:
        self.scan_hz = float(self.scan_hz)
        if self.scan_hz <= 0.0:
            raise ValueError("scan_hz must be > 0")
        self.abort_thresholds = [AbortThreshold.from_any(t) for t in self.abort_thresholds]

    @property
    def dt(self) -> float:
        return 1.0 / self.scan_hz
