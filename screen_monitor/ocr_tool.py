from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import pytesseract


def _preprocess(path: Path, scale: float = 2.0, use_otsu: bool = True):
    """
    读取图片并做预处理，输出适合 Tesseract 的二值图。
    Tesseract 识别效果最好的是：黑字白底、足够分辨率。
    """
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)

    if scale != 1.0 and scale > 0:
        h, w = img.shape[:2]
        img = cv2.resize(
            img,
            (int(w * scale), int(h * scale)),
            interpolation=cv2.INTER_CUBIC,
        )

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if use_otsu:
        # 大津法：适合“前景/背景对比明显”的图，比自适应阈值更稳
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        th = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            10,
        )

    # Tesseract 默认训练数据是“黑字白底”，若当前是白字黑底则反转
    if np.mean(th) < 127:
        th = cv2.bitwise_not(th)

    return th


def ocr_image(
    path: str | Path,
    *,
    whitelist: Optional[str] = None,
    psm: int = 7,
    scale: float = 2.0,
    use_otsu: bool = True,
    lang: Optional[str] = None,
) -> str:
    """
    对本地图片做一次 OCR 并返回识别文本（已 strip）。

    - path: 图片路径
    - whitelist: 可选，限定允许出现的字符集合，例如 '0123456789'
    - psm: Tesseract 页面分割模式，7 表示单行文本
    - scale: 预处理时放大倍数，小图可适当放大（默认 2.0）
    - use_otsu: True 用大津法二值化（高对比图推荐），False 用自适应阈值
    - lang: 语言，如 'eng'，不传则用 Tesseract 默认
    """
    p = Path(path)
    img = _preprocess(p, scale=scale, use_otsu=use_otsu)

    config_parts = [f"--psm {psm}"]
    if whitelist:
        config_parts.append(f"-c tessedit_char_whitelist={whitelist}")
    if lang:
        config_parts.append(f"-l {lang}")
    config = " ".join(config_parts)

    text = pytesseract.image_to_string(img, config=config)
    return text.strip()

