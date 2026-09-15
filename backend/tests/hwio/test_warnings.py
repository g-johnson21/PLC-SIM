import logging

from draco_sim.hwio import HwIo

_LOGGER_NAME = "draco_sim.hwio.core"


def test_pt0_null_range_warns_exactly_once_per_instance_via_logging(db, caplog, capsys):
    hw = HwIo(db)
    hw.set_physical({"PT0": 42.0})
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        for _ in range(6):
            hw.step(0.01)

    pt0_records = [
        r for r in caplog.records
        if r.name == _LOGGER_NAME and "PT0" in r.message and "no engineering range" in r.message
    ]
    assert len(pt0_records) == 1
    assert pt0_records[0].levelno == logging.WARNING

    # via logging, not print
    assert capsys.readouterr().out == ""


def test_pt0_warning_is_independent_per_instance(db, caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        hw_a = HwIo(db)
        hw_b = HwIo(db)
        hw_a.set_physical({"PT0": 1.0})
        hw_b.set_physical({"PT0": 1.0})
        hw_a.step(0.01)
        hw_a.step(0.01)
        hw_b.step(0.01)

    pt0_records = [r for r in caplog.records if r.name == _LOGGER_NAME and "PT0" in r.message]
    assert len(pt0_records) == 2  # one per instance, not one globally
