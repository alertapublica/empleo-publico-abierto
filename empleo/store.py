"""Datos en JSON ordenado dentro del repositorio: legibles, auditables y con historia."""
from __future__ import annotations

import json
import os
from pathlib import Path


def load(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
