"""Logging configuration for the trading system."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from rich.logging import RichHandler
except Exception:  # pragma: no cover - fallback when rich is unavailable
    RichHandler = None  # type: ignore[assignment]


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def get_logger(
    name: str,
    log_level: str = "INFO",
    logs_dir: Optional[Path] = None,
) -> logging.Logger:
    """Get a configured logger instance.

    Args:
        name: Logger name (typically __name__)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        logs_dir: Directory to write log files to

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    # Console handler
    if RichHandler is not None and sys.stdout.isatty():
        console_handler = RichHandler(
            show_time=True,
            show_level=True,
            show_path=False,
            markup=False,
            rich_tracebacks=False,
        )
        console_handler.setLevel(log_level)
        # RichHandler renders metadata itself; formatter controls message text.
        console_handler.setFormatter(logging.Formatter("%(name)s - %(message)s"))
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler (JSON)
    if logs_dir:
        logs_dir = Path(logs_dir)
        logs_dir.mkdir(parents=True, exist_ok=True)

        log_file = logs_dir / f"{name.replace('.', '_')}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(JSONFormatter())
        logger.addHandler(file_handler)

    return logger


def create_trade_logger(logs_dir: Path) -> logging.Logger:
    """Create a dedicated logger for trade execution.

    Args:
        logs_dir: Directory to write trade logs to

    Returns:
        Configured trade logger
    """
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("day_trader.trades")
    logger.setLevel(logging.INFO)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    # File handler for trades (CSV-like format)
    trade_file = logs_dir / "trades.log"
    file_handler = logging.FileHandler(trade_file)
    file_handler.setLevel(logging.INFO)

    # CSV-like formatter for trades
    formatter = logging.Formatter(
        "%(asctime)s,%(name)s,%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
