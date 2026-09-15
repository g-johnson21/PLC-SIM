from draco_sim.hwio import HwIo, HwIoConfig
from draco_sim.hwio.core import _LC_CARD_MVV, _PT_CARD_MA, _TC_CARD_MV

_FULL_CODE = (1 << 24) - 1


def _channel(hw, tag):
    return next(c for c in hw.channels() if c.tag == tag)


def test_pressure_clamps_high(db):
    hw = HwIo(db)
    tag = db.by_tag["PT1"]  # range [0, 10000]
    hw.set_physical({"PT1": tag.range[1] * 10})  # way beyond range -> way beyond +20 mA
    hw.step(0.01)
    ch = _channel(hw, "PT1")
    assert ch.electrical_value == _PT_CARD_MA[1]
    assert ch.raw_code == _FULL_CODE


def test_pressure_clamps_low(db):
    hw = HwIo(db)
    tag = db.by_tag["PT1"]
    hw.set_physical({"PT1": -tag.range[1] * 10})  # far below range -> way beyond -20 mA
    hw.step(0.01)
    ch = _channel(hw, "PT1")
    assert ch.electrical_value == _PT_CARD_MA[0]
    assert ch.raw_code == 0


def test_load_cell_clamps_high(db):
    hw = HwIo(db)
    tag = db.by_tag["LC1"]
    hw.set_physical({"LC1": tag.capacity_lbf * 100})  # 100x overload
    hw.step(0.01)
    ch = _channel(hw, "LC1")
    assert ch.electrical_value == _LC_CARD_MVV[1]
    assert ch.raw_code == _FULL_CODE


def test_load_cell_clamps_low(db):
    hw = HwIo(db)
    tag = db.by_tag["LC1"]
    hw.set_physical({"LC1": -tag.capacity_lbf * 100})
    hw.step(0.01)
    ch = _channel(hw, "LC1")
    assert ch.electrical_value == _LC_CARD_MVV[0]
    assert ch.raw_code == 0


def test_thermocouple_clamps_high_via_offset(db):
    # Real K-type EMF (-6.458..54.886 mV) never reaches the +-80 mV card rail on its own; force
    # the clamp path deterministically with the (zero-by-default) per-tag electrical offset knob.
    hw = HwIo(db, config=HwIoConfig(per_tag_offset={"TC1": 1000.0}))
    hw.set_physical({"TC1": 70.0})
    hw.step(0.01)
    ch = _channel(hw, "TC1")
    assert ch.electrical_value == _TC_CARD_MV[1]
    assert ch.raw_code == _FULL_CODE


def test_thermocouple_clamps_low_via_offset(db):
    hw = HwIo(db, config=HwIoConfig(per_tag_offset={"TC1": -1000.0}))
    hw.set_physical({"TC1": 70.0})
    hw.step(0.01)
    ch = _channel(hw, "TC1")
    assert ch.electrical_value == _TC_CARD_MV[0]
    assert ch.raw_code == 0
