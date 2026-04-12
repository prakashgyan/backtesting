"""Unit tests for configuration."""

import os
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from day_trader.config import Settings, get_settings


class TestSettings:
    """Test cases for Settings configuration."""

    def test_settings_with_env_vars(self) -> None:
        """Test creating settings from environment variables."""
        os.environ["ALPACA_API_KEY"] = "test_key"
        os.environ["ALPACA_SECRET_KEY"] = "test_secret"

        try:
            settings = Settings()
            assert settings.alpaca_api_key == "test_key"
            assert settings.alpaca_secret_key == "test_secret"
        finally:
            del os.environ["ALPACA_API_KEY"]
            del os.environ["ALPACA_SECRET_KEY"]

    def test_settings_default_values(self) -> None:
        """Test default values in settings."""
        os.environ["ALPACA_API_KEY"] = "test_key"
        os.environ["ALPACA_SECRET_KEY"] = "test_secret"

        try:
            settings = Settings()
            assert settings.paper_trading is True
            assert settings.log_level == "INFO"
        finally:
            del os.environ["ALPACA_API_KEY"]
            del os.environ["ALPACA_SECRET_KEY"]

    def test_settings_empty_api_key(self) -> None:
        """Test that empty API key is rejected."""
        os.environ["ALPACA_API_KEY"] = ""
        os.environ["ALPACA_SECRET_KEY"] = "test_secret"

        try:
            with pytest.raises(ValidationError):
                Settings()
        finally:
            del os.environ["ALPACA_API_KEY"]
            del os.environ["ALPACA_SECRET_KEY"]

    def test_settings_invalid_log_level(self) -> None:
        """Test that invalid log level is rejected."""
        os.environ["ALPACA_API_KEY"] = "test_key"
        os.environ["ALPACA_SECRET_KEY"] = "test_secret"
        os.environ["LOG_LEVEL"] = "INVALID"

        try:
            with pytest.raises(ValidationError):
                Settings()
        finally:
            del os.environ["ALPACA_API_KEY"]
            del os.environ["ALPACA_SECRET_KEY"]
            del os.environ["LOG_LEVEL"]

    def test_settings_creates_directories(self) -> None:
        """Test that settings creates required directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["ALPACA_API_KEY"] = "test_key"
            os.environ["ALPACA_SECRET_KEY"] = "test_secret"
            os.environ["DATA_DIR"] = str(Path(tmpdir) / "data")
            os.environ["LOGS_DIR"] = str(Path(tmpdir) / "logs")

            try:
                settings = Settings()
                assert settings.data_dir.exists()
                assert settings.logs_dir.exists()
            finally:
                for key in ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "DATA_DIR", "LOGS_DIR"]:
                    os.environ.pop(key, None)

    def test_get_settings_caching(self) -> None:
        """Test that get_settings caches the instance."""
        os.environ["ALPACA_API_KEY"] = "test_key"
        os.environ["ALPACA_SECRET_KEY"] = "test_secret"

        try:
            settings1 = get_settings()
            settings2 = get_settings()
            assert settings1 is settings2
        finally:
            del os.environ["ALPACA_API_KEY"]
            del os.environ["ALPACA_SECRET_KEY"]
            # Clear cache for other tests
            get_settings.cache_clear()
