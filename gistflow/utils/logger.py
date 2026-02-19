"""
Logging configuration using Loguru.
Provides a centralized logging setup for the entire application.
"""

import sys
from datetime import timezone, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger


# Custom time formatter for Beijing timezone (UTC+8)
def beijing_time_formatter(record):
    """Format time in Beijing timezone (UTC+8)"""
    tz_beijing = timezone(timedelta(hours=8))
    beijing_time = record["time"].astimezone(tz_beijing)
    record["extra"]["beijing_time"] = beijing_time.strftime("%Y-%m-%d %H:%M:%S")
    return record


# Patch logger globally to use Beijing timezone
logger = logger.patch(beijing_time_formatter)


def setup_logger(
    log_level: str = "INFO",
    log_dir: Optional[Path] = None,
    rotation: str = "10 MB",
    retention: str = "7 days",
) -> None:
    """
    Configure the application logger with file and console outputs.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_dir: Directory for log files. If None, only console logging is used.
        rotation: Log rotation size/time (e.g., "10 MB", "1 day").
        retention: How long to keep old log files.
    """
    # Remove default handler
    logger.remove()

    # Console handler with colored output (using Beijing timezone)
    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{extra[beijing_time]}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>",
        colorize=True,
        enqueue=True,  # Enable async logging for thread safety
    )

    # File handler (if log_dir is specified)
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "gistflow_{time:YYYY-MM-DD}.log"

        logger.add(
            str(log_file),
            level=log_level,
            format="{extra[beijing_time]} | {level: <8} | {name}:{function}:{line} - {message}",
            rotation=rotation,
            retention=retention,
            compression="zip",
            encoding="utf-8",
            enqueue=True,  # Enable async logging for thread safety
        )

        # Separate error log file
        error_log_file = log_dir / "gistflow_errors_{time:YYYY-MM-DD}.log"
        logger.add(
            str(error_log_file),
            level="ERROR",
            format="{extra[beijing_time]} | {level: <8} | {name}:{function}:{line} - {message}",
            rotation=rotation,
            retention=retention,
            compression="zip",
            encoding="utf-8",
            enqueue=True,  # Enable async logging for thread safety
        )

    logger.info(f"Logger initialized with level: {log_level}")


def get_logger(name: str = "gistflow"):
    """
    Get a logger instance with contextual information.

    Args:
        name: Logger name (usually module name).

    Returns:
        Logger instance with bound name context.
    """
    return logger.bind(name=name)


# Initialize logger on import (can be reconfigured with setup_logger)
setup_logger(log_level="INFO")