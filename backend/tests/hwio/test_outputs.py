from draco_sim.hwio import HwIo

# 500 us latency: step in two 300 us increments (300 < 500, 300+300 = 600 >= 500) rather than
# trying to land exactly on the 500 us boundary, to stay clear of float round-off at the edge.
_UNDER = 0.0003
_OVER = 0.0003


def _bit_and_open(hw, tag):
    ch = next(c for c in hw.channels() if c.tag == tag)
    return int(ch.electrical_value), hw.valve_states()[tag]


def test_default_state_has_all_coils_deenergized_matching_normal_state(db):
    hw = HwIo(db)
    assert _bit_and_open(hw, "S1") == (0, False)  # NC: de-energized -> closed
    assert _bit_and_open(hw, "PB1") == (0, True)  # NO: de-energized -> open


def test_nc_valve_polarity_and_latency_both_directions(db):
    hw = HwIo(db)

    hw.write_outputs({"S1": True})
    assert _bit_and_open(hw, "S1") == (0, False)  # not yet
    hw.step(_UNDER)
    assert _bit_and_open(hw, "S1") == (0, False)  # still not yet
    hw.step(_OVER)
    assert _bit_and_open(hw, "S1") == (1, True)  # NC energized -> open

    hw.write_outputs({"S1": False})
    assert _bit_and_open(hw, "S1") == (1, True)
    hw.step(_UNDER)
    assert _bit_and_open(hw, "S1") == (1, True)
    hw.step(_OVER)
    assert _bit_and_open(hw, "S1") == (0, False)  # NC de-energized -> closed


def test_no_valve_polarity_and_latency_both_directions(db):
    hw = HwIo(db)

    hw.write_outputs({"PB1": False})
    assert _bit_and_open(hw, "PB1") == (0, True)  # not yet
    hw.step(_UNDER)
    assert _bit_and_open(hw, "PB1") == (0, True)
    hw.step(_OVER)
    assert _bit_and_open(hw, "PB1") == (1, False)  # NO energized -> closed

    hw.write_outputs({"PB1": True})
    assert _bit_and_open(hw, "PB1") == (1, False)
    hw.step(_UNDER)
    assert _bit_and_open(hw, "PB1") == (1, False)
    hw.step(_OVER)
    assert _bit_and_open(hw, "PB1") == (0, True)  # NO de-energized -> open


def test_simultaneous_writes_latch_independently(db):
    hw = HwIo(db)
    hw.write_outputs({"PB1": False, "S1": True})
    assert _bit_and_open(hw, "PB1") == (0, True)
    assert _bit_and_open(hw, "S1") == (0, False)
    hw.step(_UNDER)
    assert _bit_and_open(hw, "PB1") == (0, True)
    assert _bit_and_open(hw, "S1") == (0, False)
    hw.step(_OVER)
    assert _bit_and_open(hw, "PB1") == (1, False)
    assert _bit_and_open(hw, "S1") == (1, True)


def test_reserved_spare_do_passthrough_and_excluded_from_valve_states(db):
    hw = HwIo(db)
    assert "SPARE_IGNITER" not in hw.valve_states()

    hw.write_outputs({"SPARE_IGNITER": True})
    hw.step(_UNDER)
    hw.step(_OVER)
    ch = next(c for c in hw.channels() if c.tag == "SPARE_IGNITER")
    assert ch.electrical_value == 1.0  # no polarity flip: bit tracks the command directly
    assert ch.eng_value == 1.0
    assert "SPARE_IGNITER" not in hw.valve_states()  # still excluded -- drives nothing physical
