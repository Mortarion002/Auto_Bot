from __future__ import annotations

import logging
import sys
from datetime import datetime

from config import Settings


def setup_logger(settings: Settings) -> logging.Logger:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("elvan_x_agent")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    log_date = datetime.now(settings.zoneinfo()).strftime("%Y-%m-%d")
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(
        settings.logs_dir / f"agent_{log_date}.log",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger
