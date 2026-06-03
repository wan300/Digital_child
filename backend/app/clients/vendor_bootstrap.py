from __future__ import annotations

import sys
from pathlib import Path


def add_vendor_paths() -> None:
    root = Path(__file__).resolve().parents[2] / "vendor"
    for child in ("mem0", "graphiti-core", "lightrag-hku"):
        path = str(root / child)
        if path not in sys.path:
            sys.path.insert(0, path)
