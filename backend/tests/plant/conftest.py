import shutil
from pathlib import Path

import pytest

from draco_sim.plant.calibrate import RUN_FILES, Runs

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# calibrate's run keys -> the committed slice of that recording (fixtures/README.md)
SLICES = {"12:36": "fuel_press_123642.csv", "12:49": "hotfire_rud_124919.csv",
          "12:52": "operator_open_125242.csv"}


@pytest.fixture(scope="session")
def runs(tmp_path_factory) -> Runs:
    """The slices under their recordings' real names, so calibrate.Runs finds them and
    data/annotations.yaml marks the 12:49 RUD windows invalid."""
    root = tmp_path_factory.mktemp("recordings")
    for key, name in SLICES.items():
        shutil.copyfile(FIXTURES_DIR / name, root / RUN_FILES[key])
    return Runs(root)
