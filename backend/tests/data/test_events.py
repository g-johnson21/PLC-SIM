import csv
import math

import numpy as np

from draco_sim.data import load_run
from draco_sim.data.loader import _to_float_array, _to_int8_array

from .conftest import ALL_FIXTURE_CSVS, HOTFIRE_RUD_CSV


def test_to_float_array_maps_empty_cells_to_nan():
    arr = _to_float_array(["1.5", "", "-2", "0.0"])
    assert arr.dtype == np.float64
    assert arr[0] == 1.5 and arr[2] == -2.0 and arr[3] == 0.0
    assert math.isnan(arr[1])


def test_to_int8_array_maps_empty_cells_to_zero():
    arr = _to_int8_array(["1", "", "0", "1"])
    assert arr.dtype == np.int8
    assert list(arr) == [1, 0, 0, 1]


def test_events_are_parsed_for_every_nonempty_event_cell(db):
    for path in ALL_FIXTURE_CSVS:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)
        event_idx = header.index("event")
        expected_n = sum(1 for r in rows if r[event_idx])

        run = load_run(path, tag_db=db)
        assert len(run.events) == expected_n, path.name


def test_event_fields_and_ordering(db):
    run = load_run(HOTFIRE_RUD_CSV, tag_db=db)
    assert len(run.events) > 0
    ts = [e.t for e in run.events]
    assert ts == sorted(ts)  # events stay in row order, i.e. non-decreasing elapsed_s
    for e in run.events:
        assert isinstance(e.t, float)
        assert e.text  # non-empty by construction
        assert isinstance(e.timestamp, str) and e.timestamp  # every row has a timestamp


def test_signals_have_no_nan_for_fully_logged_pressure_channels(db):
    # PT0 is logged on every row of every 2026-09-11 recording (it's only its
    # *value* that's suspect after the RUD, per annotations — the column itself
    # is never blank), so NaN here would mean a column-lookup regression.
    for path in ALL_FIXTURE_CSVS:
        run = load_run(path, tag_db=db)
        assert not np.isnan(run.signals["PT0"]).any(), path.name


def test_timestamp_column_strips_trailing_z(db):
    run = load_run(HOTFIRE_RUD_CSV, tag_db=db)
    assert run.timestamp.dtype == np.dtype("datetime64[ms]")
    assert len(run.timestamp) == len(run.t)
