from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
import mss


@dataclass(frozen=True)
class CaptureRegion:
    x: int
    y: int
    w: int
    h: int

    @staticmethod
    def from_config(cfg: dict[str, Any]) -> "CaptureRegion":
        r = cfg.get("monitor_region") or {}
        return CaptureRegion(
            x=int(r.get("x", 0)),
            y=int(r.get("y", 0)),
            w=int(r.get("w", 0)),
            h=int(r.get("h", 0)),
        )


class RegionCapturer:
    def __init__(
        self,
        *,
        high_dpi: bool = False,
        capture_scale: float = 1.0,
    ) -> None:
        self._high_dpi = high_dpi and sys.platform == "darwin"
        self._capture_scale = max(0.25, min(4.0, float(capture_scale)))
        self._sct = mss.mss() if not self._high_dpi else None

    def close(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None

    def grab_bgr(self, region: CaptureRegion) -> np.ndarray:
        if region.w <= 0 or region.h <= 0:
            raise ValueError(f"Invalid region size: {region}")

        if self._high_dpi:
            from .capture_darwin import grab_region_bgr
            img = grab_region_bgr(region)
        else:
            mon = {"left": region.x, "top": region.y, "width": region.w, "height": region.h}
            shot = self._sct.grab(mon)
            img = np.asarray(shot, dtype=np.uint8)
            img = img[:, :, :3].copy()

        if self._capture_scale != 1.0:
            h, w = img.shape[:2]
            new_w = int(round(w * self._capture_scale))
            new_h = int(round(h * self._capture_scale))
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

        return img

