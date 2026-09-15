import logging

from draco_sim.hwio import HwIo

_LOGGER_NAME = "draco_sim.hwio.core"


def test_reset_restores_default_valve_states(db):
    hw = HwIo(db)
    hw.write_outputs({"S1": True})
    hw.step(0.0003)
    hw.step(0.0003)
    assert hw.valve_states()["S1"] is True

    hw.reset()
    assert hw.valve_states()["S1"] is False  # back to NC default (closed)
    assert hw.valve_states()["PB1"] is True  # back to NO default (open)


def test_reset_makes_input_behaviour_match_a_fresh_instance(db):
    hw = HwIo(db)
    hw.set_physical({"PT1": 9000.0})
    hw.step(0.01)
    assert hw.read_inputs()["PT1"] > 1000.0

    hw.reset()
    fresh = HwIo(db)
    hw.set_physical({"PT1": 4000.0})
    fresh.set_physical({"PT1": 4000.0})
    hw.step(0.01)
    fresh.step(0.01)
    assert hw.read_inputs()["PT1"] == fresh.read_inputs()["PT1"]


def test_reset_clears_pt0_warning_dedup(db, caplog):
    hw = HwIo(db)
    hw.set_physical({"PT0": 1.0})
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        hw.step(0.01)
        hw.step(0.01)  # still within the same instance -- must not warn again
        hw.reset()
        hw.set_physical({"PT0": 1.0})
        hw.step(0.01)  # fresh instance state -- warns once more

    pt0_records = [r for r in caplog.records if r.name == _LOGGER_NAME and "PT0" in r.message]
    assert len(pt0_records) == 2
