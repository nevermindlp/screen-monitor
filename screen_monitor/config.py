from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid config YAML (expected mapping): {p}")
    return data


def save_yaml(path: str | Path, data: dict[str, Any]) -> None:
    p = Path(path)
    p.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


@dataclass(frozen=True)
class MonitorRegion:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class ClickPoint:
    x: int
    y: int


def parse_monitor_region(cfg: dict[str, Any]) -> MonitorRegion:
    r = cfg.get("monitor_region") or {}
    return MonitorRegion(
        x=int(r.get("x", 0)),
        y=int(r.get("y", 0)),
        w=int(r.get("w", 0)),
        h=int(r.get("h", 0)),
    )


def parse_click_point(cfg: dict[str, Any]) -> ClickPoint:
    p = cfg.get("click_point") or {}
    return ClickPoint(x=int(p.get("x", 0)), y=int(p.get("y", 0)))

