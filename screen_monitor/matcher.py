from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import cv2
import numpy as np


_METHODS: dict[str, int] = {
    "TM_CCOEFF": cv2.TM_CCOEFF,
    "TM_CCOEFF_NORMED": cv2.TM_CCOEFF_NORMED,
    "TM_CCORR": cv2.TM_CCORR,
    "TM_CCORR_NORMED": cv2.TM_CCORR_NORMED,
    "TM_SQDIFF": cv2.TM_SQDIFF,
    "TM_SQDIFF_NORMED": cv2.TM_SQDIFF_NORMED,
}


@dataclass(frozen=True)
class MatchResult:
    score: float
    top_left: tuple[int, int]
    template_size: tuple[int, int]
    scale: float


def _to_gray(img_bgr: np.ndarray) -> np.ndarray:
    if img_bgr.ndim != 3 or img_bgr.shape[2] < 3:
        raise ValueError("Expected BGR image")
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)


def _preprocess(gray: np.ndarray) -> np.ndarray:
    # 轻度去噪，避免 UI 细微抖动导致分数波动过大
    return cv2.GaussianBlur(gray, (3, 3), 0)


def _get_method(name: str) -> int:
    n = (name or "").strip()
    if n in _METHODS:
        return _METHODS[n]
    raise ValueError(f"Unknown matchTemplate method: {name}. Expected one of: {sorted(_METHODS.keys())}")


def _is_sqdiff(method: int) -> bool:
    return method in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED)


class TemplateMatcher:
    def __init__(self, template_path: str, *, method: str = "TM_CCOEFF_NORMED") -> None:
        self.template_path = template_path
        self.method_name = method
        self.method = _get_method(method)
        tmpl = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if tmpl is None:
            raise FileNotFoundError(f"Template not found or unreadable: {template_path}")
        self._tmpl_bgr = tmpl

    def match(
        self,
        search_bgr: np.ndarray,
        *,
        multiscale_enabled: bool = False,
        scales: Iterable[float] | None = None,
    ) -> MatchResult:
        search_gray = _preprocess(_to_gray(search_bgr))
        base_tmpl_gray = _preprocess(_to_gray(self._tmpl_bgr))

        if scales is None:
            scales = [1.0]
        scales_list = list(scales) if multiscale_enabled else [1.0]

        best: MatchResult | None = None
        for s in scales_list:
            if s <= 0:
                continue
            tmpl = base_tmpl_gray
            if abs(s - 1.0) > 1e-6:
                nh = max(1, int(round(base_tmpl_gray.shape[0] * s)))
                nw = max(1, int(round(base_tmpl_gray.shape[1] * s)))
                tmpl = cv2.resize(base_tmpl_gray, (nw, nh), interpolation=cv2.INTER_AREA)

            th, tw = tmpl.shape[:2]
            sh, sw = search_gray.shape[:2]
            if th > sh or tw > sw:
                continue

            res = cv2.matchTemplate(search_gray, tmpl, self.method)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

            if _is_sqdiff(self.method):
                # SQDIFF 越小越好；把它映射为“越大越好”的 score 便于统一阈值逻辑
                score = float(1.0 - min_val)
                loc = (int(min_loc[0]), int(min_loc[1]))
            else:
                score = float(max_val)
                loc = (int(max_loc[0]), int(max_loc[1]))

            cand = MatchResult(score=score, top_left=loc, template_size=(tw, th), scale=float(s))
            if best is None or cand.score > best.score:
                best = cand

        if best is None:
            # 退化情况：模板比搜索图大或 scales 都无效
            return MatchResult(score=float("-inf"), top_left=(0, 0), template_size=(0, 0), scale=1.0)
        return best


def matcher_from_config(cfg: dict[str, Any]) -> tuple[TemplateMatcher, float, dict[str, Any]]:
    tcfg = cfg.get("template") or {}
    path = str(tcfg.get("path", "template.png"))
    method = str(tcfg.get("method", "TM_CCOEFF_NORMED"))
    threshold = float(tcfg.get("threshold", 0.92))
    mcfg = tcfg.get("multiscale") or {}
    multiscale = {
        "enabled": bool(mcfg.get("enabled", False)),
        "scales": list(mcfg.get("scales", [1.0])),
    }
    return TemplateMatcher(path, method=method), threshold, multiscale

