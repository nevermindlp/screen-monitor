from __future__ import annotations

import argparse
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
from PIL import Image

from .calibrate import interactive_select_region, run_calibrate
from .capture import CaptureRegion, RegionCapturer
from .clicker import ClickController, ClickPoint
from .config import load_yaml, parse_click_point
from .emailer import EmailBatcher, EmailConfig, EvidenceItem, send_test_email
from .matcher import matcher_from_config
from .utils import ensure_dir, mean_abs_diff, utc_ts_compact


def _log(level: str, msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} [{level}] {msg}", flush=True)


def _wait_until_region_changes(
    capturer: RegionCapturer,
    region: CaptureRegion,
    before_bgr,
    *,
    timeout_sec: float,
    change_threshold: float,
    poll_interval_sec: float = 0.2,
) -> tuple[bool, float, float]:
    if timeout_sec <= 0 or change_threshold <= 0:
        return True, 0.0, 0.0

    before_gray = cv2.cvtColor(before_bgr, cv2.COLOR_BGR2GRAY)
    start = time.time()
    deadline = time.time() + timeout_sec
    max_diff = 0.0
    while time.time() < deadline:
        time.sleep(max(0.05, poll_interval_sec))
        now_bgr = capturer.grab_bgr(region)
        now_gray = cv2.cvtColor(now_bgr, cv2.COLOR_BGR2GRAY)
        diff = mean_abs_diff(before_gray, now_gray)
        if diff > max_diff:
            max_diff = diff
        if diff >= change_threshold:
            return True, max_diff, (time.time() - start)
    return False, max_diff, (time.time() - start)


def _save_evidence(
    evidence_dir: Path,
    img_bgr,
    *,
    score: float,
    box: tuple[int, int, int, int] | None = None,
) -> Path:
    """
    保存命中证据截图：
    - 若提供 box=(x, y, w, h)，则在大图上画出矩形框，并额外保存一张小图裁剪。
    - 返回值为带框大图的路径。
    """

    ts = utc_ts_compact()
    base = f"hit_{ts}_score_{score:.4f}"

    # 大图（带或不带框）
    full_name = base + "_full.png"
    full_path = evidence_dir / full_name

    img_full = img_bgr.copy()
    if box is not None:
        x, y, w, h = box
        x = max(int(x), 0)
        y = max(int(y), 0)
        w = max(int(w), 1)
        h = max(int(h), 1)
        x2 = x + w
        y2 = y + h

        # 在大图上画出命中区域的矩形框（红色，略粗一点）
        cv2.rectangle(img_full, (x, y), (x2, y2), (0, 0, 255), thickness=2)

        # 小图裁剪
        crop = img_bgr[y:y2, x:x2]
        if crop.size > 0:
            crop_name = base + "_crop.png"
            crop_path = evidence_dir / crop_name
            cv2.imwrite(str(crop_path), crop)

    cv2.imwrite(str(full_path), img_full)
    return full_path


def cmd_calibrate(args: argparse.Namespace) -> int:
    # 读取 mss 监视器尺寸用于 macOS Retina 坐标缩放估计
    try:
        import mss  # local import to keep errors localized

        with mss.mss() as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            mw, mh = int(mon.get("width", 0)), int(mon.get("height", 0))
    except Exception:
        mw, mh = None, None

    run_calibrate(args.config, mss_monitor_width=mw, mss_monitor_height=mh)
    return 0


def cmd_test_email(args: argparse.Namespace) -> int:
    cfg: dict[str, Any] = load_yaml(args.config)
    ecfg = EmailConfig.from_config(cfg)
    send_test_email(ecfg)
    _log("INFO", "测试邮件已发送（如未收到请检查授权码/收件箱/垃圾箱）。")
    return 0


def cmd_resize_image(args: argparse.Namespace) -> int:
    src = Path(args.src)
    dst = Path(args.dst)
    if not src.is_file():
        raise SystemExit(f"源图片不存在: {src}")

    img = Image.open(src)
    orig_size = img.size
    img = img.resize((args.width, args.height), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst)
    _log(
        "INFO",
        f"image_resized src={src} orig_size={orig_size} "
        f"-> dst={dst} new_size={img.size}",
    )
    return 0


def cmd_ocr_image(args: argparse.Namespace) -> int:
    from .ocr_tool import ocr_image

    text = ocr_image(args.path, whitelist=args.whitelist, psm=args.psm)
    _log(
        "INFO",
        f"ocr path={args.path} whitelist={args.whitelist!r} psm={args.psm} text={text!r}",
    )
    # 同时直接打印纯文本，便于管道或手动查看
    print(text)
    return 0


def cmd_capture_image(args: argparse.Namespace) -> int:
    """截取指定区域或全屏为高清 PNG，支持 macOS 原生分辨率（high_dpi）。"""
    cfg: dict[str, Any] = load_yaml(args.config) if Path(args.config).is_file() else {}

    # 区域：交互式选择 > 命令行 > 全屏 > 配置
    if args.interactive:
        try:
            import mss
            with mss.mss() as sct:
                mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                mw = int(mon.get("width", 0))
                mh = int(mon.get("height", 0))
        except Exception:
            mw, mh = None, None
        x, y, w, h = interactive_select_region(mss_monitor_width=mw, mss_monitor_height=mh)
        region = CaptureRegion(x=x, y=y, w=w, h=h)
        _log("INFO", f"selected_region ({region.x},{region.y},{region.w},{region.h})")
    elif args.full_screen:
        try:
            import mss
            with mss.mss() as sct:
                # 主显示器：monitors[1]；monitors[0] 为“全部”
                mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                region = CaptureRegion(
                    x=int(mon["left"]),
                    y=int(mon["top"]),
                    w=int(mon["width"]),
                    h=int(mon["height"]),
                )
        except Exception as e:
            raise SystemExit(f"获取主显示器区域失败: {e}")
    elif args.region:
        parts = args.region.strip().split()
        if len(parts) != 4:
            raise SystemExit("--region 格式应为四个整数: x y w h")
        try:
            x, y, w, h = (int(p) for p in parts)
        except ValueError:
            raise SystemExit("--region 必须为整数: x y w h")
        region = CaptureRegion(x=x, y=y, w=w, h=h)
    else:
        region = CaptureRegion.from_config(cfg)
        if region.w <= 0 or region.h <= 0:
            raise SystemExit(
                "未指定区域。请使用 -i/--interactive、--region x y w h、--full-screen，或先在 config 中配置 monitor_region（如运行 calibrate）"
            )

    cap_cfg = cfg.get("capture") or {}
    high_dpi = bool(cap_cfg.get("high_dpi", False))
    if args.no_high_dpi:
        high_dpi = False
    elif args.high_dpi:
        high_dpi = True
    capture_scale = args.scale if args.scale is not None else float(cap_cfg.get("capture_scale", 1.0))

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    capturer = RegionCapturer(high_dpi=high_dpi, capture_scale=capture_scale)
    try:
        img = capturer.grab_bgr(region)
        cv2.imwrite(str(out_path), img)
        h, w = img.shape[:2]
        _log(
            "INFO",
            f"capture_image saved path={out_path} size={w}x{h} high_dpi={high_dpi} scale={capture_scale}",
        )
    finally:
        capturer.close()

    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg: dict[str, Any] = load_yaml(args.config)

    region = CaptureRegion.from_config(cfg)
    if region.w <= 0 or region.h <= 0:
        raise SystemExit("monitor_region 无效，请先运行 calibrate 或修改 config.yaml")

    cp = parse_click_point(cfg)
    click_point = ClickPoint(x=cp.x, y=cp.y)

    matcher, threshold, multiscale = matcher_from_config(cfg)

    loop_cfg = cfg.get("loop") or {}
    poll_interval_sec = float(loop_cfg.get("poll_interval_sec", 0.2))
    wait_change_timeout_sec = float(loop_cfg.get("wait_change_timeout_sec", 6.0))
    change_threshold = float(loop_cfg.get("change_threshold", 6.0))
    # 无变化时下一轮点击前的延迟，避免疯狂连点
    no_change_click_delay_sec = float(
        loop_cfg.get("no_change_click_delay_sec", loop_cfg.get("click_interval_sec", 0.5))
    )

    evidence_cfg = cfg.get("evidence") or {}
    evidence_dir = ensure_dir(evidence_cfg.get("dir", "evidence"))
    save_on_hit = bool(evidence_cfg.get("save_on_hit", True))

    cap_cfg = cfg.get("capture") or {}
    high_dpi = bool(cap_cfg.get("high_dpi", False))
    capture_scale = float(cap_cfg.get("capture_scale", 1.0))

    email_cfg = EmailConfig.from_config(cfg)
    email_enabled = bool(email_cfg.enabled) and (not args.dry_run)
    batcher = EmailBatcher(email_cfg)
    if email_enabled:
        batcher.start()

    clicker = ClickController(click_point)
    capturer = RegionCapturer(high_dpi=high_dpi, capture_scale=capture_scale)

    try:
        last_log_ts = 0.0
        start_ts = time.time()
        loops = 0
        hits = 0

        if args.once:
            # --once：仅对 config 监控区域做一次高清截图并识别，不包含点击
            _log(
                "INFO",
                "run --once: 对监控区域做一次高清截图并识别（不点击） "
                f"region=({region.x},{region.y},{region.w},{region.h}) "
                f"high_dpi={high_dpi} threshold={threshold:.4f}",
            )
            frame = capturer.grab_bgr(region)
            res = matcher.match(
                frame,
                multiscale_enabled=bool(multiscale.get("enabled", False)),
                scales=multiscale.get("scales", [1.0]),
            )
            hit = res.score >= threshold
            _log(
                "INFO",
                f"score={res.score:.4f}/{threshold:.4f} hit={hit}",
            )
            if hit:
                _log(
                    "HIT",
                    f"score={res.score:.4f} loc={res.top_left} tmpl={res.template_size} scale={res.scale:.3f}",
                )
                path = None
                if save_on_hit:
                    x, y = res.top_left
                    w, h = res.template_size
                    path = _save_evidence(
                        Path(evidence_dir),
                        frame,
                        score=res.score,
                        box=(x, y, w, h),
                    )
                    _log("INFO", f"evidence_saved path={path}")
                if email_enabled and path is not None:
                    batcher.enqueue(
                        EvidenceItem(path=Path(path), score=float(res.score), created_utc=utc_ts_compact())
                    )
                    _log("INFO", "email_enqueued (batch)")
            # --once 不进入循环，直接结束
        else:
            _log(
                "INFO",
                "监控启动（先点击→判变化→有变化才检测） "
                f"region=({region.x},{region.y},{region.w},{region.h}) "
                f"click=({click_point.x},{click_point.y}) "
                f"threshold={threshold:.4f} no_change_click_delay={no_change_click_delay_sec:.2f}s "
                f"high_dpi={high_dpi} capture_scale={capture_scale} "
                f"email_enabled={email_enabled} dry_run={args.dry_run}",
            )
            while True:
                loops += 1
                # 1. 记录点击前帧
                pre_click_frame = capturer.grab_bgr(region)
                # 2. 在指定点触发点击
                _log("ACTION", f"click at=({click_point.x},{click_point.y})")
                clicker.click_now()
                # 3. 判断点击后图片是否变化
                changed, max_diff, elapsed = _wait_until_region_changes(
                    capturer,
                    region,
                    pre_click_frame,
                    timeout_sec=wait_change_timeout_sec,
                    change_threshold=change_threshold,
                    poll_interval_sec=poll_interval_sec,
                )
                _log(
                    "INFO",
                    f"wait_change changed={changed} elapsed={elapsed:.2f}s max_diff={max_diff:.2f} "
                    f"threshold={change_threshold:.2f}",
                )
                if changed:
                    # 4a. 有变化：抓当前帧并做目标检测
                    frame = capturer.grab_bgr(region)
                    res = matcher.match(
                        frame,
                        multiscale_enabled=bool(multiscale.get("enabled", False)),
                        scales=multiscale.get("scales", [1.0]),
                    )
                    now = time.time()
                    if now - last_log_ts >= 1.0:
                        up = now - start_ts
                        _log(
                            "INFO",
                            f"loop={loops} up={up:.1f}s score={res.score:.4f}/{threshold:.4f} hits={hits}",
                        )
                        last_log_ts = now
                    hit = res.score >= threshold
                    if hit:
                        hits += 1
                        _log(
                            "HIT",
                            f"score={res.score:.4f} loc={res.top_left} tmpl={res.template_size} scale={res.scale:.3f}",
                        )
                        path = None
                        if save_on_hit:
                            x, y = res.top_left
                            w, h = res.template_size
                            path = _save_evidence(
                                Path(evidence_dir),
                                frame,
                                score=res.score,
                                box=(x, y, w, h),
                            )
                            _log("INFO", f"evidence_saved path={path}")
                        if email_enabled and path is not None:
                            batcher.enqueue(
                                EvidenceItem(path=Path(path), score=float(res.score), created_utc=utc_ts_compact())
                            )
                            _log("INFO", "email_enqueued (batch)")
                        _log("INFO", "已命中目标，按回车继续监控...")
                        input()
                else:
                    # 4b. 无变化：直接进入下一轮
                    now = time.time()
                    if now - last_log_ts >= 1.0:
                        up = now - start_ts
                        _log("DEBUG", f"loop={loops} up={up:.1f}s no_change, delay then next click")
                        last_log_ts = now

                # 两次点击间保持 0.5～1s 随机间隔
                delay = random.uniform(0.5, 1.0)
                _log("DEBUG", f"next_click_in {delay:.2f}s")
                time.sleep(delay)

    except KeyboardInterrupt:
        _log("INFO", "收到中断，准备退出...")
    finally:
        try:
            if email_enabled:
                batcher.flush_now()
        except Exception as e:
            _log("WARN", f"邮件 flush 失败：{e}")
        try:
            if email_enabled:
                batcher.stop()
        except Exception:
            pass
        capturer.close()
        _log("INFO", "监控已退出")

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="screen-monitor")

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("calibrate", help="交互式校准：监控区域 + 点击点")
    sp.add_argument("--config", default="config.yaml", help="配置文件路径（默认 config.yaml）")
    sp.set_defaults(func=cmd_calibrate)

    sp = sub.add_parser("run", help="运行监控")
    sp.add_argument("--config", default="config.yaml", help="配置文件路径（默认 config.yaml）")
    sp.add_argument("--dry-run", action="store_true", help="只保存截图不发邮件")
    sp.add_argument("--once", action="store_true", help="仅一次：对监控区域高清截图并识别，不点击，然后退出")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("test-email", help="发送测试邮件（无附件）")
    sp.add_argument("--config", default="config.yaml", help="配置文件路径（默认 config.yaml）")
    sp.set_defaults(func=cmd_test_email)

    sp = sub.add_parser("resize-image", help="按指定尺寸缩放图片并另存")
    sp.add_argument("--src", required=True, help="源图片路径")
    sp.add_argument("--dst", required=True, help="目标图片路径")
    sp.add_argument("--width", type=int, required=True, help="目标宽度（像素）")
    sp.add_argument("--height", type=int, required=True, help="目标高度（像素）")
    sp.set_defaults(func=cmd_resize_image)

    sp = sub.add_parser("ocr-image", help="对图片做一次 OCR 识别并输出结果")
    sp.add_argument("--path", required=True, help="图片路径")
    sp.add_argument(
        "--whitelist",
        default=None,
        help="可选：限定字符集，例如 '0123456789+'",
    )
    sp.add_argument(
        "--psm",
        type=int,
        default=7,
        help="Tesseract PSM 模式，默认 7（单行文本）",
    )
    sp.set_defaults(func=cmd_ocr_image)

    sp = sub.add_parser(
        "capture-image",
        help="截取指定区域或全屏为高清 PNG（支持 macOS 原生分辨率）",
    )
    sp.add_argument("--config", default="config.yaml", help="配置文件路径（用于区域与 capture 设置）")
    sp.add_argument("-o", "--output", required=True, help="输出 PNG 路径")
    sp.add_argument(
        "--region",
        metavar="X Y W H",
        default=None,
        help="覆盖区域：四个整数，如 '100 200 800 600'",
    )
    sp.add_argument(
        "--full-screen",
        action="store_true",
        help="截取主显示器全屏",
    )
    sp.add_argument(
        "--high-dpi",
        action="store_true",
        default=None,
        help="启用高清截屏（macOS 下为原生分辨率）",
    )
    sp.add_argument(
        "--no-high-dpi",
        action="store_true",
        help="禁用高清截屏（覆盖 config）",
    )
    sp.add_argument(
        "--scale",
        type=float,
        default=None,
        help="抓图后缩放倍数，如 2.0（默认从 config 读取）",
    )
    sp.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="交互式选择区域：按提示移动鼠标到左上角、右下角各按回车",
    )
    sp.set_defaults(func=cmd_capture_image)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

