"""Loader for hand-maintained recording annotations (testdata/ stays read-only)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Optional

import yaml


def _default_path() -> Path:
    return resources.files("draco_sim.data").joinpath("annotations.yaml")


def load_annotations(path: Optional[str | Path] = None) -> dict:
    p = Path(path) if path is not None else _default_path()
    if not p.exists():
        return {"recordings": {}}
    with open(p, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    doc.setdefault("recordings", {})
    return doc


def invalid_windows_for(doc: dict, filename: str) -> list[dict]:
    rec = doc.get("recordings", {}).get(filename)
    if not rec:
        return []
    return rec.get("invalid", [])
