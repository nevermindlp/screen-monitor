from __future__ import annotations

import time
from dataclasses import dataclass

import pyautogui


@dataclass(frozen=True)
class ClickPoint:
    x: int
    y: int


class ClickController:
    def __init__(self, point: ClickPoint) -> None:
        self.point = point
        self._last_click_ts: float | None = None

    @property
    def last_click_ts(self) -> float | None:
        return self._last_click_ts

    def click_now(self) -> None:
        pyautogui.click(self.point.x, self.point.y)
        self._last_click_ts = time.time()

    def click_if_due(self, interval_sec: float) -> bool:
        if interval_sec <= 0:
            return False
        now = time.time()
        if self._last_click_ts is None or (now - self._last_click_ts) >= interval_sec:
            self.click_now()
            return True
        return False

