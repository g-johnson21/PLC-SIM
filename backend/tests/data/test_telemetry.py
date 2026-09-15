import math

import numpy as np

from draco_sim.data import load_run
from draco_sim.data.telemetry import parse_bbd

from .conftest import ALL_FIXTURE_CSVS, HOTFIRE_RUD_CSV

# Verbatim line copied from tests/fixtures/hotfire_rud_124919.csv's event column
# (real recording, both loops reporting SUSpended/closed). Field order per
# docs/data-survey.md's 2026-09-13 addendum.
_REAL_BBD_LINE = (
    "[info] BBD:L:SUS:0:796.57:-5.31:796.57:914.00:15:163.5:1:1 | "
    "[info] BBD:F:SUS:0:779.22:-0.00:779.22:880.00:15:163.5:1:1"
)


def test_parse_bbd_field_order_on_a_real_line():
    t = np.array([0.0])
    result = parse_bbd([_REAL_BBD_LINE], t)

    for loop, psi, field6, deadband in (("ox", 796.57, 796.57, 15.0), ("fuel", 779.22, 779.22, 15.0)):
        bt = result[loop]
        assert bt.state[0] == "SUS"
        assert bt.press_cmd[0] == 0.0
        assert bt.psi[0] == psi
        assert bt.field6[0] == field6  # filtered pressure, mirrors psi when settled
        assert bt.deadband[0] == deadband
        assert bt.field10[0] == 1.0
        assert bt.field11[0] == 1.0
    assert result["ox"].field5[0] == -5.31
    assert result["fuel"].field5[0] == -0.00


def test_parse_bbd_is_nan_before_first_sample_and_holds_between_samples():
    event_col = ["", _REAL_BBD_LINE, "", "", _REAL_BBD_LINE.replace("796.57", "800.00", 1)]
    t = np.array([0.0, 0.025, 0.05, 0.075, 0.1])
    bt = parse_bbd(event_col, t)["ox"]

    assert len(bt.press_cmd) == len(event_col)  # full length, not just the sample count
    assert len(bt.sample_t) == 2
    assert math.isnan(bt.psi[0])  # nothing parsed yet
    assert isinstance(bt.state[0], float) and math.isnan(bt.state[0])
    assert bt.psi[1] == 796.57
    assert bt.psi[2] == 796.57 and bt.psi[3] == 796.57  # held through rows with no BBD line
    assert bt.psi[4] == 800.00  # the second sample only changed the LOX-side psi field


def test_parse_bbd_ignores_rows_without_bbd_text():
    event_col = ["[info] something unrelated", "", "[info] BBD not really"]
    t = np.array([0.0, 0.01, 0.02])
    result = parse_bbd(event_col, t)
    assert len(result["ox"].sample_t) == 0
    assert len(result["fuel"].sample_t) == 0
    assert all(math.isnan(x) for x in result["ox"].psi)


def test_bbd_sampled_at_roughly_10hz_against_40hz_daq(db):
    run = load_run(HOTFIRE_RUD_CSV, tag_db=db)
    ratio = len(run.t) / len(run.bbd["ox"].sample_t)
    assert 3.0 < ratio < 5.0  # ~40 Hz DAQ vs ~10 Hz board telemetry


def test_bangbang_trace_fields_are_full_length_not_empty(db):
    # Regression for the fixed loader bug (docs/data-survey.md addendum, 2026-09-13):
    # bb-*'s state/press/vent/psi columns carry a "board" word the old suffix map
    # dropped, so col_by_name.get(...) missed and these came back length-0.
    for path in ALL_FIXTURE_CSVS:
        run = load_run(path, tag_db=db)
        n = len(run.t)
        assert n > 0
        for loop in ("ox", "fuel"):
            trace = run.bb[loop]
            for field in ("setpoint", "enabled", "state", "press", "vent", "psi"):
                arr = getattr(trace, field)
                assert len(arr) == n, f"{path.name} bb[{loop}].{field} length {len(arr)} != {n}"
