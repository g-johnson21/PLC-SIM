import pytest

from draco_sim.tags import load_tag_db


@pytest.fixture(scope="session")
def db():
    return load_tag_db()
