import shutil

from draco_sim.data import load_run
from draco_sim.data.annotations import invalid_windows_for, load_annotations

from .conftest import HOTFIRE_RUD_CSV, RUD_RECORDING_NAME

_RUD_WINDOWS = {
    "PT0": (108.972, None),
    "LC1": (108.972, None),
    "LC2": (108.972, None),
    "LC3": (108.972, None),
    "THRUST": (108.972, None),
    "LC4": (109.064, 111.194),
}


def test_real_annotations_yaml_has_the_verified_rud_windows():
    doc = load_annotations()
    windows = invalid_windows_for(doc, RUD_RECORDING_NAME)
    assert {w["tag"] for w in windows} == set(_RUD_WINDOWS)
    for w in windows:
        from_s, to_s = _RUD_WINDOWS[w["tag"]]
        assert w["from_s"] == from_s
        assert w.get("to_s") == to_s
        assert w["reason"]  # every window carries a specific reason
    assert "RUD" in load_annotations()["recordings"][RUD_RECORDING_NAME]["note"]


def test_invalid_windows_for_unknown_recording_is_empty():
    doc = load_annotations()
    assert invalid_windows_for(doc, "not_a_real_recording.csv") == []


def test_missing_annotations_file_returns_empty_doc(tmp_path):
    doc = load_annotations(tmp_path / "does_not_exist.yaml")
    assert doc == {"recordings": {}}


def test_custom_annotations_path_round_trips(tmp_path):
    p = tmp_path / "custom.yaml"
    p.write_text(
        "recordings:\n"
        "  some_file.csv:\n"
        "    note: test note\n"
        "    invalid:\n"
        "      - tag: PT9\n"
        "        from_s: 1.5\n"
        "        to_s: 2.5\n"
        "        reason: synthetic\n",
        encoding="utf-8",
    )
    doc = load_annotations(p)
    windows = invalid_windows_for(doc, "some_file.csv")
    assert windows == [{"tag": "PT9", "from_s": 1.5, "to_s": 2.5, "reason": "synthetic"}]


def test_fixture_filename_does_not_accidentally_match_annotations(db):
    # annotations.yaml keys on the exact real filename, so a same-content slice
    # under a different name must not pick up the RUD windows.
    run = load_run(HOTFIRE_RUD_CSV, tag_db=db)
    assert run.invalid_from == {}
    assert run.invalid_to == {}


def test_load_run_wires_invalid_from_and_invalid_to_under_the_real_filename(db, tmp_path):
    renamed = tmp_path / RUD_RECORDING_NAME
    shutil.copyfile(HOTFIRE_RUD_CSV, renamed)

    run = load_run(renamed, tag_db=db)

    expected_from = {tag: frm for tag, (frm, _to) in _RUD_WINDOWS.items()}
    expected_to = {tag: to for tag, (_frm, to) in _RUD_WINDOWS.items() if to is not None}
    assert run.invalid_from == expected_from
    assert run.invalid_to == expected_to
