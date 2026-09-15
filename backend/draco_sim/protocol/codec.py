"""JSON wire format for the protocol: strict JSON out (no NaN/Infinity), with a
documented escape hatch for the plant's non-finite floats (see docs/protocol.md,
Server -> "Non-finite values")."""
from __future__ import annotations

import json
import math
from typing import Any


def _walk(obj: Any, path: str, names: list[str]) -> Any:
    if isinstance(obj, float):
        if math.isfinite(obj):
            return obj
        names.append(path)
        return None
    if isinstance(obj, dict):
        return {k: _walk(v, f"{path}.{k}" if path else str(k), names) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_walk(v, f"{path}[{i}]", names) for i, v in enumerate(obj)]
    return obj


def sanitize_nonfinite(obj: Any) -> tuple[Any, list[str]]:
    """Replace every inf/-inf/nan float anywhere in `obj` with None. Returns the
    cleaned copy and the dotted path of each value replaced, e.g. "plant.thrust_lbf"
    or "inputs.PT7", for the state.nonfinite list."""
    names: list[str] = []
    return _walk(obj, "", names), names


def dumps(obj: Any) -> str:
    return json.dumps(obj, allow_nan=False, separators=(",", ":"))
