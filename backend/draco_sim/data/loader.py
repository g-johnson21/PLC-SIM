from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from draco_sim.tags import TagDatabase, load_tag_db

from .annotations import invalid_windows_for, load_annotations
from .telemetry import BoardTelemetry, parse_bbd

logger = logging.getLogger(__name__)

# bb-<loop> column suffixes: setpoint/enabled are logged bare, the rest carry
# a "board" word the tag name doesn't (e.g. "bb-ox board psi").
_BB_COLUMN_SUFFIX = {
    "setpoint": "setpoint",
    "enabled": "enabled",
    "state": "board state",
    "press": "board press",
    "vent": "board vent",
    "psi": "board psi",
}


@dataclass(frozen=True)
class Event:
    t: float
    timestamp: str
    text: str


@dataclass(frozen=True)
class BangBangTrace:
    setpoint: np.ndarray
    enabled: np.ndarray
    state: np.ndarray
    press: np.ndarray
    vent: np.ndarray
    psi: np.ndarray


@dataclass
class RunData:
    path: Path
    t: np.ndarray
    timestamp: np.ndarray
    signals: dict[str, np.ndarray]
    valves: dict[str, np.ndarray]
    bb: dict[str, BangBangTrace]
    armed: np.ndarray
    sequence: np.ndarray
    events: list[Event]
    bbd: dict[str, BoardTelemetry]
    gc_commands: dict[str, np.ndarray]
    invalid_from: dict[str, float]
    invalid_to: dict[str, float]

    @property
    def duration_s(self) -> float:
        if len(self.t) == 0:
            return 0.0
        return float(self.t[-1] - self.t[0])

    @property
    def sample_period_s(self) -> float:
        if len(self.t) < 2:
            return float("nan")
        return float(np.median(np.diff(self.t)))


def list_runs(dir: str | Path = "testdata") -> list[Path]:
    return sorted(Path(dir).glob("*.csv"))


def _to_float_array(col: list[str]) -> np.ndarray:
    return np.array([c if c != "" else "nan" for c in col], dtype=np.float64)


def _to_int8_array(col: list[str]) -> np.ndarray:
    return np.array([int(c) if c != "" else 0 for c in col], dtype=np.int8)


def load_run(path: str | Path, tag_db: Optional[TagDatabase] = None) -> RunData:
    path = Path(path)
    if tag_db is None:
        tag_db = load_tag_db()

    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    columns = list(zip(*rows)) if rows else [() for _ in header]
    col_by_name = {name: list(col) for name, col in zip(header, columns)}

    known = set(tag_db.daq_column_map) | set(tag_db.meta_columns)
    for name in header:
        if name not in known:
            logger.warning("unrecognised column %r in %s — skipping", name, path)

    if "elapsed_s" not in col_by_name:
        raise ValueError(f"{path}: missing required 'elapsed_s' column")
    t = _to_float_array(col_by_name["elapsed_s"])

    ts_raw = col_by_name.get("timestamp", [])
    timestamp = np.array([s.rstrip("Z") for s in ts_raw], dtype="datetime64[ms]")

    signals: dict[str, np.ndarray] = {}
    for tag in tag_db.inputs:
        if tag.daq_column and tag.daq_column in col_by_name:
            signals[tag.tag] = _to_float_array(col_by_name[tag.daq_column])

    valves: dict[str, np.ndarray] = {}
    for tag in tag_db.outputs:
        if tag.reserved or not tag.daq_column:
            continue
        if tag.daq_column in col_by_name:
            valves[tag.tag] = _to_int8_array(col_by_name[tag.daq_column])

    bb: dict[str, BangBangTrace] = {}
    for loop, prefix in (("ox", "bb-ox"), ("fuel", "bb-fuel")):
        kwargs = {}
        for f_name, suffix in _BB_COLUMN_SUFFIX.items():
            col = col_by_name.get(f"{prefix} {suffix}", [])
            if f_name == "enabled":
                kwargs[f_name] = _to_int8_array(col)
            elif f_name == "state":
                kwargs[f_name] = np.array(col, dtype="<U8")
            else:
                kwargs[f_name] = _to_float_array(col)
        bb[loop] = BangBangTrace(**kwargs)

    armed = _to_int8_array(col_by_name.get("armed", []))
    sequence = np.array(col_by_name.get("sequence", []), dtype="<U32")

    event_col = col_by_name.get("event", [])
    events: list[Event] = []
    for i, text in enumerate(event_col):
        if text:
            events.append(Event(t=float(t[i]), timestamp=str(ts_raw[i]) if i < len(ts_raw) else "", text=text))

    # The previous system's bang-bang board and the GC's DC1/DC2 command both
    # wire to S1/S2 in parallel — the 125242 recording's operator-only opens
    # (S1 302.82-330.53s, S2 317.08-337.82s, board telemetry off throughout,
    # PT1/PT11 draining) show either one can open the solenoid on its own.
    # Keep the raw DC columns as gc_commands and OR them with the held board
    # command for valve truth.
    bbd = parse_bbd(event_col, t)
    gc_commands: dict[str, np.ndarray] = {}
    for tag_name, loop in (("S1", "ox"), ("S2", "fuel")):
        board_cmd = np.nan_to_num(bbd[loop].press_cmd, nan=0.0).astype(np.int8)
        if tag_name in valves:
            gc_commands[tag_name] = valves[tag_name]
            valves[tag_name] = np.logical_or(board_cmd, gc_commands[tag_name]).astype(np.int8)
        else:
            valves[tag_name] = board_cmd

    ann_doc = load_annotations()
    invalid_from: dict[str, float] = {}
    invalid_to: dict[str, float] = {}
    for entry in invalid_windows_for(ann_doc, path.name):
        tag_name = entry["tag"]
        invalid_from[tag_name] = float(entry["from_s"])
        if entry.get("to_s") is not None:
            invalid_to[tag_name] = float(entry["to_s"])

    return RunData(
        path=path,
        t=t,
        timestamp=timestamp,
        signals=signals,
        valves=valves,
        bb=bb,
        armed=armed,
        sequence=sequence,
        events=events,
        bbd=bbd,
        gc_commands=gc_commands,
        invalid_from=invalid_from,
        invalid_to=invalid_to,
    )
