from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple


def _ensure_log_dir() -> Path:
    log_dir = Path("DEBUG/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_logger() -> logging.Logger:
    logger = logging.getLogger("nyu_hq_daily_publisher")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)

    log_dir = _ensure_log_dir()
    fh = logging.FileHandler(log_dir / "nyu_hq_daily_publisher.log", encoding="utf-8")
    ch = logging.StreamHandler()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def summarize_results(records: List[dict]) -> Tuple[str, bool]:
    total = 0
    success = 0
    failed = 0
    lines = ["Publish Summary:"]
    for rec in records:
        name = rec.get("name")
        attempted = rec.get("attempted")
        status = rec.get("status")
        http_status = rec.get("http_status")
        msg = rec.get("message")
        if attempted:
            total += 1
            if status == "success":
                success += 1
            elif status == "failed":
                failed += 1
        lines.append(f" - {name}: {status} (http={http_status}) {msg}")
    lines.append(f"Overall: attempted={total}, succeeded={success}, failed={failed}")
    return "\n".join(lines), failed > 0


