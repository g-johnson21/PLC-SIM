from __future__ import annotations

from .types import TagSpec

# Stand-in for TagDatabase.plc_specs() (decisions D7) so that the examples and the
# IDE can run before task 1 lands. The real list replaces this at integration time;
# nothing in the engine depends on it.

_PT = ("PT0", "PT1", "PT2", "PT3", "PT4", "PT5", "PT11", "PT12", "PT13", "PT14", "PT15",
       "PT21", "PT22", "PT23", "PT24", "PT31", "PT32", "PT33")
_TC = ("TC1", "TC2", "TC3", "TC4", "TC5", "TC6", "TC7", "TC8")
_LC = ("LC1", "LC2", "LC3", "LC4", "LC_FUEL")
_OUT = ("S1", "S2", "S3", "S4", "S5", "PB1", "PB2", "PB3", "PB4", "PB5", "PB6",
        "SPARE_IGNITER", "SPARE_CAMERA_TRIGGER", "SPARE_COMPRESSOR")

DRACO_TAGSPECS_PLACEHOLDER: list[TagSpec] = (
    [TagSpec(n, "in", "REAL", "psi") for n in _PT]
    + [TagSpec(n, "in", "REAL", "degF") for n in _TC]
    + [TagSpec(n, "in", "REAL", "lbf") for n in _LC]
    + [TagSpec("THRUST", "in", "REAL", "lbf")]
    + [TagSpec(n, "out", "BOOL", "") for n in _OUT]
)
