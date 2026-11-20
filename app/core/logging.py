import os
import sys
from pathlib import Path

from loguru import logger

from app.core.config import ROOT, LoggingConfig

FMT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"


def setup_logger(settings: LoggingConfig) -> None:
    log_file = Path(settings.file)
    if not log_file.is_absolute():
        log_file = ROOT / log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)

    process_log_file = log_file.with_name(
        f"{log_file.stem}.{os.getpid()}{log_file.suffix}"
    )

    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.level,
        format=FMT,
        colorize=False,
    )
    logger.add(
        process_log_file,
        level=settings.level,
        format=FMT,
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        enqueue=True,
    )


__all__ = ["setup_logger", "logger"]