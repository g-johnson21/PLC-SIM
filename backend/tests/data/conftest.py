from pathlib import Path

import pytest

from draco_sim.tags import load_tag_db

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# (fixture filename, real recording it's a verbatim slice of) — see fixtures/README.md
FUEL_PRESS_CSV = FIXTURES_DIR / "fuel_press_123642.csv"
HOTFIRE_RUD_CSV = FIXTURES_DIR / "hotfire_rud_124919.csv"
LOX_VENT_CSV = FIXTURES_DIR / "lox_vent_125242.csv"
ALL_FIXTURE_CSVS = (FUEL_PRESS_CSV, HOTFIRE_RUD_CSV, LOX_VENT_CSV)

# D13: GC-only S1/S2 opens (board telemetry silent) — not in ALL_FIXTURE_CSVS,
# used by the dedicated operator-open test only.
OPERATOR_OPEN_CSV = FIXTURES_DIR / "operator_open_125242.csv"

# the real recording the RUD fixture is sliced from — the one name annotations.yaml keys on
RUD_RECORDING_NAME = "Draco_20260911_124919_hotfire.csv"


@pytest.fixture(scope="session")
def db():
    return load_tag_db()
