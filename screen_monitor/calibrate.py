from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pyautogui

from .config import load_yaml, save_yaml


def _wait_enter(prompt: str) -> None:
    try:
        input(prompt)
    except KeyboardInterrupt:
        raise SystemExit(130)


def _get_mouse_pos() -> tuple[int, int]:
    p = pyautogui.position()
    return int(p.x), int(p.y)


def _calc_scale(mss_width: int, mss_height: int) -> tuple[float, float]:
    sw, sh = pyautogui.size()
    if sw <= 0 or sh <= 0:
        return 1.0, 1.0
    return (mss_width / sw), (mss_height / sh)


def interactive_select_region(
    *,
    mss_monitor_width: int | None = None,
    mss_monitor_height: int | None = None,
) -> tuple[int, int, int, int]:
    """
    交互式选择屏幕区域：用户将鼠标移到左上角、右下角各按一次回车。
    返回 (x, y, w, h)。若提供 mss 显示器宽高，则返回与 mss 一致的坐标；否则为 pyautogui 逻辑坐标。
    """
    scale_x, scale_y = 1.0, 1.0
    if mss_monitor_width and mss_monitor_height:
        scale_x, scale_y = _calc_scale(int(mss_monitor_width), int(mss_monitor_height))

    print("请依次将鼠标移动到区域的【左上角】和【右下角】，每次移动后按回车。")
    _wait_enter("鼠标移到【左上角】后按回车...")
    x1, y1 = _get_mouse_pos()
    _wait_enter("鼠标移到【右下角】后按回车...")
    x2, y2 = _get_mouse_pos()

    left = min(x1, x2)
    top = min(y1, y2)
    w = abs(x2 - x1)
    h = abs(y2 - y1)
    if w <= 1 or h <= 1:
        print("区域过小，请重试。", file=sys.stderr)
        raise SystemExit(2)

    return (
        int(round(left * scale_x)),
        int(round(top * scale_y)),
        int(round(w * scale_x)),
        int(round(h * scale_y)),
    )


def run_calibrate(config_path: str, *, mss_monitor_width: int | None = None, mss_monitor_height: int | None = None) -> None:
    """
    交互式校准（稳健版）：
    - 让用户用鼠标指向区域左上角 / 右下角并按回车
    - 再指向点击点并按回车
    - 写回 config.yaml

    若提供了 mss_monitor_width/height，则会把 pyautogui 逻辑坐标映射到 mss 像素坐标（用于抓屏区域）。
    """
    cfg: dict[str, Any] = load_yaml(config_path)

    print("将开始校准监控区域与点击点。")
    print("提示：请把要监控的区域尽量框准，模板匹配会更稳定。")
    print()
    x, y, w, h = interactive_select_region(
        mss_monitor_width=mss_monitor_width,
        mss_monitor_height=mss_monitor_height,
    )
    region = {"x": x, "y": y, "w": w, "h": h}

    print()
    _wait_enter("把鼠标移动到【要定期点击的位置】后按回车...")
    cx, cy = _get_mouse_pos()
    click_point = {"x": int(cx), "y": int(cy)}

    cfg["monitor_region"] = region
    cfg["click_point"] = click_point

    save_yaml(Path(config_path), cfg)
    print()
    print("已写入配置：")
    print(f"- monitor_region(mss像素坐标): {region}")
    print(f"- click_point(pyautogui坐标): {click_point}")

