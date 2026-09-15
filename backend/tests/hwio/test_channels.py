from draco_sim.hwio import HwIo


def test_channels_total_count_matches_all_card_instances(db):
    hw = HwIo(db)
    chans = hw.channels()
    # 2x16 (NI-9208) + 2x4 (NI-9211) + 2x4 (NI-9237) + 1x32 (NI-9476) + 1x32 (NI-9205)
    assert len(chans) == 112


def test_channels_assigned_set_matches_tag_database(db):
    hw = HwIo(db)
    chans = hw.channels()
    assigned = [c for c in chans if c.tag is not None]
    expected_tags = {t.tag for t in db.tags if t.module is not None}  # excludes THRUST (derived)
    assert {c.tag for c in assigned} == expected_tags
    assert len(assigned) == len(expected_tags)  # no channel double-counts a tag


def test_ni9205_is_present_but_fully_idle(db):
    hw = HwIo(db)
    ni9205_chans = [c for c in hw.channels() if c.module == "NI-9205"]
    assert len(ni9205_chans) == 32
    assert all(c.module_index == 0 for c in ni9205_chans)
    assert all(
        c.tag is None and c.kind is None and c.electrical_value is None and c.eng_value is None
        for c in ni9205_chans
    )
