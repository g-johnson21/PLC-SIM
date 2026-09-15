import numpy as np

from draco_sim.data import load_run

from .conftest import ALL_FIXTURE_CSVS, FUEL_PRESS_CSV, HOTFIRE_RUD_CSV, OPERATOR_OPEN_CSV


def test_s1_s2_valves_are_board_telemetry_or_gc_command(db):
    # D13: board telemetry and the GC's DC1/DC2 command wire to the same solenoid,
    # so valves[tag] is the OR of the two, not board telemetry alone.
    for path in ALL_FIXTURE_CSVS:
        run = load_run(path, tag_db=db)
        for tag, loop in (("S1", "ox"), ("S2", "fuel")):
            board_cmd = np.nan_to_num(run.bbd[loop].press_cmd, nan=0.0).astype(np.int8)
            expected = np.logical_or(board_cmd, run.gc_commands[tag]).astype(np.int8)
            assert np.array_equal(run.valves[tag], expected), f"{path.name}: valves[{tag}] != board OR gc (D13)"
            assert run.valves[tag].dtype == np.int8
            assert set(np.unique(run.valves[tag])).issubset({0, 1})


def test_operator_only_open_still_reads_open_in_valves(db):
    # D13: in Draco_20260911_125242, the operator opened S1 (302.82-330.53s) and
    # S2 (317.08-337.82s) through the GC alone, board telemetry silent throughout.
    # operator_open_125242.csv slices that window; valves must read open there too.
    run = load_run(OPERATOR_OPEN_CSV, tag_db=db)
    for tag, loop in (("S1", "ox"), ("S2", "fuel")):
        board_cmd = np.nan_to_num(run.bbd[loop].press_cmd, nan=0.0).astype(np.int8)
        gc_only_open = (run.gc_commands[tag] == 1) & (board_cmd == 0)
        assert gc_only_open.sum() > 0, f"{tag}: fixture has no GC-only-open rows"
        assert np.all(run.valves[tag][gc_only_open] == 1)


def test_gc_commands_are_the_raw_dc_columns_kept_separately(db):
    for path in ALL_FIXTURE_CSVS:
        run = load_run(path, tag_db=db)
        for tag in ("S1", "S2"):
            assert tag in run.gc_commands
            assert len(run.gc_commands[tag]) == len(run.t)
        # DC2 is 0 in these three fixture slices (data-survey.md addendum) — the fuel
        # board pressurised (123642) without the GC commanding that column here. This
        # is not true of the full 125242 recording: the GC alone drives DC2 high in
        # operator_open_125242.csv's window (D13, see test above).
        assert int(run.gc_commands["S2"].sum()) == 0


def test_s1_board_vs_gc_disagreement_matches_known_figures(db):
    # Cross-check against docs/data-survey.md's addendum, which cites the full
    # Draco_20260911_124919_hotfire.csv recording's S1 mismatch as 112 + 191 = 303
    # rows; the RUD fixture is a contiguous slice of that same file (rows
    # 3740-4339, see fixtures/README.md) so its disagreement count must be <= 303.
    run = load_run(HOTFIRE_RUD_CSV, tag_db=db)
    dis = int((run.valves["S1"].astype(int) != run.gc_commands["S1"].astype(int)).sum())
    assert 0 < dis <= 303


def test_fuel_board_press_column_is_always_zero_while_telemetry_carries_the_real_command(db):
    # data-survey.md addendum: "bb-fuel board press" is 0 in every row of every
    # recording; the real fuel press commands only show up in BBD:F field 3.
    run = load_run(FUEL_PRESS_CSV, tag_db=db)
    assert np.all(run.bb["fuel"].press == 0.0)
    assert run.bbd["fuel"].press_cmd[~np.isnan(run.bbd["fuel"].press_cmd)].sum() > 0
    assert run.valves["S2"].sum() > 0
