from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def utc_ts_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def env_or_empty(name: str) -> str:
    return os.environ.get(name, "").strip()


def mean_abs_diff(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return float("inf")
    aa = a.astype(np.int16)
    bb = b.astype(np.int16)
    return float(np.mean(np.abs(aa - bb)))

