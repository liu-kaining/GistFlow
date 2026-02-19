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
    # Ensure extra dict exists
    if "extra" not in record:
        record["extra"] = {}
    record["extra"]["beijing_time"] = beijing_time.strftime("%Y-%m-%d %H:%M:%S")
    return record


# Custom format function for Beijing time
def format_beijing_time(record):
    """Format time in Beijing timezone for loguru format string"""
    tz_beijing = timezone(timedelta(hours=8))
    beijing_time = record["time"].astimezone(tz_beijing)
    return beijing_time.strftime("%Y-%m-%d %H:%M:%S")


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
    global logger
    
    # Remove default handler
    logger.remove()
    
    # Patch logger to use Beijing timezone (must be done before adding handlers)
    # This ensures all log records have beijing_time in extra
    logger = logger.patch(beijing_time_formatter)

    # Console handler with colored output (using Beijing timezone)
    # Use a format function that directly formats time in Beijing timezone
    def console_format(record):
        """Format function for console output with Beijing timezone"""
        tz_beijing = timezone(timedelta(hours=8))
        beijing_time = record["time"].astimezone(tz_beijing).strftime("%Y-%m-%d %H:%M:%S")
        level_name = record["level"].name
        name = record["name"]
        function = record["function"]
        line = record["line"]
        message = record["message"]
        # Return formatted string (loguru will handle colorization if colorize=True)
        return f"{beijing_time} | {level_name: <8} | {name}:{function}:{line} - {message}"
    
    logger.add(
        sys.stdout,
        level=log_level,
        format=console_format,
        colorize=False,  # Disable colorize when using custom format function
        enqueue=True,  # Enable async logging for thread safety
    )

    # File handler (if log_dir is specified)
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        # Use beijing_time for filename as well (format it manually)
        from datetime import datetime
        tz_beijing = timezone(timedelta(hours=8))
        beijing_now = datetime.now(tz_beijing)
        date_str = beijing_now.strftime("%Y-%m-%d")
        log_file = log_dir / f"gistflow_{date_str}.log"

        def file_format(record):
            """Format function for file handlers with Beijing timezone"""
            tz_beijing = timezone(timedelta(hours=8))
            beijing_time = record["time"].astimezone(tz_beijing).strftime("%Y-%m-%d %H:%M:%S")
            return f"{beijing_time} | {record['level'].name: <8} | {record['name']}:{record['function']}:{record['line']} - {record['message']}"
        
        logger.add(
            str(log_file),
            level=log_level,
            format=file_format,
            rotation=rotation,
            retention=retention,
            compression="zip",
            encoding="utf-8",
            enqueue=True,  # Enable async logging for thread safety
        )

        # Separate error log file
        error_log_file = log_dir / f"gistflow_errors_{date_str}.log"
        logger.add(
            str(error_log_file),
            level="ERROR",
            format=file_format,
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