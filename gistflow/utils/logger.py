"""
Logging configuration using Loguru.
Provides a centralized logging setup for the entire application.
"""

import sys
from pathlib import Path
from typing import Optional

from loguru import logger


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

    # Console handler with colored output
    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>",
        colorize=True,
    )

    # File handler (if log_dir is specified)
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "gistflow_{time:YYYY-MM-DD}.log"

        logger.add(
            str(log_file),
            level=log_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            rotation=rotation,
            retention=retention,
            compression="zip",
            encoding="utf-8",
        )

        # Separate error log file
        error_log_file = log_dir / "gistflow_errors_{time:YYYY-MM-DD}.log"
        logger.add(
            str(error_log_file),
            level="ERROR",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            rotation=rotation,
            retention=retention,
            compression="zip",
            encoding="utf-8",
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