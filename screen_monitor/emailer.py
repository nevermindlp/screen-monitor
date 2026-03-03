from __future__ import annotations

import queue
import smtplib
import threading
import time
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .utils import env_or_empty, utc_ts_compact


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool
    flush_interval_sec: float
    max_items_per_email: int
    subject_prefix: str
    to_email: str
    from_email: str
    app_password: str
    smtp_server: str
    smtp_port: int
    smtp_ssl: bool
    smtp_starttls: bool
    smtp_timeout_sec: float

    @staticmethod
    def from_config(cfg: dict[str, Any]) -> "EmailConfig":
        ecfg = cfg.get("email") or {}
        app_pw = str(ecfg.get("app_password", "")).strip() or env_or_empty("EMAIL_SMTP_PASSWORD") or env_or_empty(
            "GMAIL_APP_PASSWORD"
        )
        return EmailConfig(
            enabled=bool(ecfg.get("enabled", True)),
            flush_interval_sec=float(ecfg.get("flush_interval_sec", 30)),
            max_items_per_email=int(ecfg.get("max_items_per_email", 10)),
            subject_prefix=str(ecfg.get("subject_prefix", "[screen-monitor]")),
            to_email=str(ecfg.get("to_email", "")),
            from_email=str(ecfg.get("from_email", "")),
            app_password=app_pw,
            smtp_server=str(ecfg.get("smtp_server", "smtp.gmail.com")),
            smtp_port=int(ecfg.get("smtp_port", 587)),
            smtp_ssl=bool(ecfg.get("smtp_ssl", False)),
            smtp_starttls=bool(ecfg.get("smtp_starttls", True)),
            smtp_timeout_sec=float(ecfg.get("smtp_timeout_sec", 30)),
        )


@dataclass(frozen=True)
class EvidenceItem:
    path: Path
    score: float
    created_utc: str


def _send_email(cfg: EmailConfig, items: list[EvidenceItem], *, subject: str, body: str) -> None:
    if not cfg.to_email or not cfg.from_email:
        raise ValueError("Email to_email/from_email is empty. Please set them in config.yaml.")
    if not cfg.app_password:
        raise ValueError(
            "SMTP password/authorization code is empty. Set env EMAIL_SMTP_PASSWORD or email.app_password in config.yaml."
        )

    msg = EmailMessage()
    msg["From"] = cfg.from_email
    msg["To"] = cfg.to_email
    msg["Subject"] = subject
    msg.set_content(body)

    for it in items:
        data = it.path.read_bytes()
        # 简化：按 png/jpg 处理；大多数截图会是 png
        suffix = it.path.suffix.lower().lstrip(".")
        if suffix in ("jpg", "jpeg"):
            maintype, subtype = "image", "jpeg"
        else:
            maintype, subtype = "image", "png"
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=it.path.name)

    timeout = float(cfg.smtp_timeout_sec) if cfg.smtp_timeout_sec else 30.0
    if cfg.smtp_ssl:
        with smtplib.SMTP_SSL(cfg.smtp_server, cfg.smtp_port, timeout=timeout) as s:
            s.ehlo()
            s.login(cfg.from_email, cfg.app_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg.smtp_server, cfg.smtp_port, timeout=timeout) as s:
            s.ehlo()
            if cfg.smtp_starttls:
                s.starttls()
                s.ehlo()
            s.login(cfg.from_email, cfg.app_password)
            s.send_message(msg)


class EmailBatcher:
    def __init__(self, cfg: EmailConfig) -> None:
        self.cfg = cfg
        self._q: "queue.Queue[EvidenceItem]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._buffer: list[EvidenceItem] = []
        self._buffer_first_ts: float | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="EmailBatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        # 停止后尽量把队列里剩余的也发掉（best-effort）
        try:
            self.flush_now()
        except Exception:
            pass

    def enqueue(self, item: EvidenceItem) -> None:
        if not self.cfg.enabled:
            return
        self._q.put(item)

    def flush_now(self) -> None:
        if not self.cfg.enabled:
            return
        # 把队列里尚未被线程消费的证据也 drain 进 buffer
        while True:
            try:
                it = self._q.get_nowait()
            except queue.Empty:
                break
            self._buffer.append(it)
            if self._buffer_first_ts is None:
                self._buffer_first_ts = time.time()
        self._flush(force=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                it = self._q.get(timeout=0.5)
            except queue.Empty:
                self._flush(force=False)
                continue

            self._buffer.append(it)
            if self._buffer_first_ts is None:
                self._buffer_first_ts = time.time()

            self._flush(force=False)

        # best-effort shutdown flush
        try:
            self._flush(force=True)
        except Exception:
            pass

    def _flush(self, *, force: bool) -> None:
        if not self._buffer:
            return

        now = time.time()
        first_ts = self._buffer_first_ts or now
        due_by_time = (self.cfg.flush_interval_sec > 0) and ((now - first_ts) >= self.cfg.flush_interval_sec)
        due_by_count = self.cfg.max_items_per_email > 0 and (len(self._buffer) >= self.cfg.max_items_per_email)

        if not force and not (due_by_time or due_by_count):
            return

        items = self._buffer[:]
        self._buffer.clear()
        self._buffer_first_ts = None

        subject = f"{self.cfg.subject_prefix} hits={len(items)} {utc_ts_compact()}"
        lines = [
            f"合并发送：{len(items)} 次命中",
            "",
        ]
        for i, it in enumerate(items, start=1):
            lines.append(f"{i}. {it.path.name}  score={it.score:.4f}  utc={it.created_utc}")
        body = "\n".join(lines)

        _send_email(self.cfg, items, subject=subject, body=body)


def send_test_email(cfg: EmailConfig) -> None:
    subject = f"{cfg.subject_prefix} test {utc_ts_compact()}"
    body = "这是一封测试邮件（无附件）。"
    _send_email(cfg, [], subject=subject, body=body)

