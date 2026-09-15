import pytest

from draco_sim.tags import ModuleSpec, Tag, TagDatabase

_MODULES = [ModuleSpec(type="NI-9208", count=1, channels=4, resolution_bits=24)]


def _tag(tag, **overrides):
    fields = dict(
        tag=tag,
        pid_tag=None,
        daq_column=None,
        aliases=(),
        kind="analog_in",
        signal="pressure",
        units="psi",
        range=(0, 100),
        module=None,
        module_index=None,
        channel=None,
        normal_state=None,
        energize_polarity=None,
        description="",
        verified=False,
    )
    fields.update(overrides)
    return Tag(**fields)


def _errors(tags, modules=_MODULES):
    with pytest.raises(ValueError) as exc:
        TagDatabase(tags, modules, meta_columns=[])
    return str(exc.value)


def test_real_tag_database_loads_and_partitions_cleanly(db):
    assert len(db.tags) == 46
    assert len(db.by_tag) == 46
    assert len(db.inputs) + len(db.outputs) == len(db.tags)  # only analog_in/derived/digital_out exist


def test_duplicate_tag_name_raises():
    msg = _errors([_tag("PT1"), _tag("PT1")])
    assert "duplicate tag name: 'PT1'" in msg


def test_duplicate_daq_column_raises():
    msg = _errors([_tag("PT1", daq_column="X"), _tag("PT2", daq_column="X")])
    assert "duplicate daq_column 'X'" in msg


def test_duplicate_alias_raises():
    msg = _errors([_tag("PT1", aliases=("SPARE",)), _tag("PT2", aliases=("SPARE",))])
    assert "duplicate alias 'SPARE'" in msg


def test_alias_colliding_with_canonical_tag_name_raises():
    # canonical tag "LC1" must be seen before another tag aliases that same name —
    # this ordering is exactly how tags.yaml protects LC4 (pid_tag "LC1") from ever
    # resolving to the wrong load cell.
    msg = _errors([_tag("LC1"), _tag("LC4", aliases=("LC1",))])
    assert "alias 'LC1' on tag 'LC4' collides with canonical tag name" in msg


def test_module_slot_reused_raises():
    msg = _errors(
        [
            _tag("PT1", module="NI-9208", module_index=0, channel=0),
            _tag("PT2", module="NI-9208", module_index=0, channel=0),
        ]
    )
    assert "module slot" in msg and "PT1" in msg and "PT2" in msg


def test_unknown_module_type_raises():
    msg = _errors([_tag("PT1", module="NI-9999", module_index=0, channel=0)])
    assert "unknown module type 'NI-9999'" in msg


def test_channel_out_of_range_raises():
    msg = _errors([_tag("PT1", module="NI-9208", module_index=0, channel=99)])
    assert "channel 99 out of range" in msg


@pytest.mark.parametrize(
    "normal_state,energize_polarity",
    [("NC", "open_when_deenergized"), ("NO", "open_when_energized"), ("MAYBE", "open_when_energized")],
)
def test_digital_out_polarity_mismatch_raises(normal_state, energize_polarity):
    msg = _errors(
        [_tag("S9", kind="digital_out", normal_state=normal_state, energize_polarity=energize_polarity)]
    )
    assert "S9" in msg


@pytest.mark.parametrize(
    "normal_state,energize_polarity",
    [("NC", "open_when_energized"), ("NO", "open_when_deenergized")],
)
def test_digital_out_correct_polarity_is_accepted(normal_state, energize_polarity):
    db = TagDatabase(
        [_tag("S9", kind="digital_out", normal_state=normal_state, energize_polarity=energize_polarity)],
        _MODULES,
        meta_columns=[],
    )
    assert db.by_tag["S9"].normal_state == normal_state


def test_reserved_digital_out_skips_polarity_check():
    db = TagDatabase(
        [_tag("SPARE1", kind="digital_out", normal_state=None, energize_polarity=None, reserved=True)],
        _MODULES,
        meta_columns=[],
    )
    assert db.by_tag["SPARE1"].reserved is True


def test_all_real_non_reserved_digital_outputs_have_consistent_no_nc_polarity(db):
    expected = {"NC": "open_when_energized", "NO": "open_when_deenergized"}
    checked = 0
    for t in db.outputs:
        if t.reserved:
            continue
        assert t.normal_state in expected, f"{t.tag}: unrecognised normal_state {t.normal_state!r}"
        assert t.energize_polarity == expected[t.normal_state], f"{t.tag}: polarity/normal_state mismatch"
        checked += 1
    assert checked == 11  # 14 digital outputs - 3 reserved spares


def test_lc1_alias_rule(db):
    # P&ID calls the LOX tank weight cell "LC1", but the DAQ's own LC1 is thrust cell A.
    # pid_tag is informational only — it must never be usable to resolve to the wrong tag.
    lc4 = db.by_tag["LC4"]
    assert lc4.pid_tag == "LC1"
    assert "LC1" not in lc4.aliases

    resolved = db.resolve("LC1")
    assert resolved.tag == "LC1"
    assert resolved is not lc4
    assert resolved is db.by_tag["LC1"]


def test_plc_specs_keys_are_exactly_name_direction_dtype_units(db):
    specs = db.plc_specs()
    assert len(specs) == len(db.inputs) + len(db.outputs)
    for spec in specs:
        assert set(spec.keys()) == {"name", "direction", "dtype", "units"}
        tag = db.by_tag[spec["name"]]
        assert spec["units"] == tag.units
        if tag.kind == "digital_out":
            assert (spec["direction"], spec["dtype"]) == ("out", "BOOL")
        else:
            assert (spec["direction"], spec["dtype"]) == ("in", "REAL")
