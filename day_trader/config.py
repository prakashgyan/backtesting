"""Configuration management for the trading system."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class RunDefaults:
    """Single source of truth for default run parameters.

    Both the CLI and Strategy base class import this to avoid duplication.
    """

    symbol: str = "AAPL"
    mode: str = "replay"
    days: int = 30
    speed: float = 1.0
    timeframe: str = "1h"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file.

    Attributes:
        alpaca_api_key: Alpaca API key
        alpaca_secret_key: Alpaca secret key
        paper_trading: Enable paper trading mode (default: True)
        log_level: Logging level (default: INFO)
        data_dir: Directory for storing historical data
        logs_dir: Directory for storing logs
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    alpaca_api_key: str
    alpaca_secret_key: str
    paper_trading: bool = True
    log_level: str = "INFO"
    data_dir: Path = Path("./data")
    logs_dir: Path = Path("./logs")
    cache_ttl_hours: float = 24.0

    @field_validator("alpaca_api_key", "alpaca_secret_key")
    @classmethod
    def validate_api_keys(cls, v: str) -> str:
        """Ensure API keys are not empty."""
        if not v or not v.strip():
            raise ValueError("API keys cannot be empty")
        return v.strip()

    @field_validator("data_dir", "logs_dir", mode="before")
    @classmethod
    def validate_and_create_dirs(cls, v: Path) -> Path:
        """Ensure directories exist and are accessible."""
        path = Path(v)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Ensure log level is valid."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        level = v.upper()
        if level not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return level


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings instance with loaded configuration

    Raises:
        ValueError: If required settings are missing or invalid
    """
    return Settings()
