import pytest


def test_resolve_by_canonical_name(db):
    assert db.resolve("PT0").tag == "PT0"
    assert db.resolve("S1").tag == "S1"


def test_resolve_by_alias(db):
    assert db.resolve("SV-LOXBB") is db.by_tag["S1"]
    assert db.resolve("DC1") is db.by_tag["S1"]  # DC1 is an S1 alias, not a separate tag
    assert db.resolve("SV-LOX-FILL") is db.by_tag["PB5"]


def test_resolve_by_daq_column(db):
    assert db.resolve("PT0 Chamber (psi)") is db.by_tag["PT0"]
    assert db.resolve("DC1 LOx Tank BB (state)") is db.by_tag["S1"]
    # the bang-bang board's own psi feedback columns are PT3/PT13, not meta columns
    assert db.resolve("bb-ox board psi") is db.by_tag["PT3"]
    assert db.resolve("bb-fuel board psi") is db.by_tag["PT13"]


def test_resolve_unknown_raises_with_helpful_message(db):
    with pytest.raises(KeyError) as exc:
        db.resolve("NOT_A_TAG")
    msg = str(exc.value)
    assert "NOT_A_TAG" in msg
    assert "PT0" in msg  # known-tags listing


def test_daq_column_map_is_the_inverse_of_each_tags_daq_column(db):
    assert len(db.daq_column_map) == sum(1 for t in db.tags if t.daq_column is not None)
    for column, tag in db.daq_column_map.items():
        assert tag.daq_column == column
        assert db.resolve(column) is tag


def test_by_tag_covers_every_tag_exactly_once(db):
    assert len(db.by_tag) == len(db.tags)
    assert all(db.by_tag[t.tag] is t for t in db.tags)


def test_for_module_and_module_spec(db):
    pt_module0 = db.for_module("NI-9208", 0)
    assert {t.tag for t in pt_module0} == {t.tag for t in db.tags if t.module == "NI-9208" and t.module_index == 0}
    assert db.module_spec("NI-9208").channels == 16
    with pytest.raises(KeyError):
        db.module_spec("NI-9999")
