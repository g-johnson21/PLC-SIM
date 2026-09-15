import pytest

from draco_sim.hwio import HwIo


def test_thrust_equals_sum_of_load_cells(db):
    hw = HwIo(db)
    hw.set_physical({"LC1": 500.0, "LC2": 480.0, "LC3": 510.0})
    hw.step(0.01)
    rb = hw.read_inputs()
    assert rb["THRUST"] == rb["LC1"] + rb["LC2"] + rb["LC3"]


def test_set_physical_silently_ignores_derived_tags(db):
    # Plant.sensors()-shaped input: all 32 PLC input tags including THRUST, which has no
    # physical channel of its own -- HwIo must accept the dict as-is (see docs/hwio.md).
    hw = HwIo(db)
    hw.set_physical({"LC1": 500.0, "LC2": 480.0, "LC3": 510.0, "THRUST": 999.0})
    hw.step(0.01)
    rb = hw.read_inputs()
    assert rb["THRUST"] == rb["LC1"] + rb["LC2"] + rb["LC3"]
    assert rb["THRUST"] != 999.0  # the bogus derived input must never leak through


def test_set_physical_unknown_tag_raises(db):
    hw = HwIo(db)
    with pytest.raises(ValueError, match="NOPE"):
        hw.set_physical({"NOPE": 1.0})


def test_set_physical_output_tag_raises(db):
    hw = HwIo(db)
    with pytest.raises(ValueError, match="PB1"):
        hw.set_physical({"PB1": 1.0})


def test_write_outputs_unknown_tag_raises(db):
    hw = HwIo(db)
    with pytest.raises(ValueError, match="NOPE"):
        hw.write_outputs({"NOPE": True})


def test_write_outputs_input_tag_raises(db):
    hw = HwIo(db)
    with pytest.raises(ValueError, match="PT1"):
        hw.write_outputs({"PT1": True})
