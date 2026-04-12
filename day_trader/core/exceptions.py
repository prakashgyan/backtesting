"""Custom exceptions for the trading system."""


class DayTraderException(Exception):
    """Base exception for all day trader errors."""

    pass


class ConfigError(DayTraderException):
    """Raised when configuration is invalid."""

    pass


class DataStreamError(DayTraderException):
    """Raised when data stream encounters an error."""

    pass


class BrokerError(DayTraderException):
    """Raised when broker API call fails."""

    pass


class StrategyError(DayTraderException):
    """Raised when strategy execution fails."""

    pass


class EngineError(DayTraderException):
    """Raised when engine encounters an error."""

    pass


class OrderError(BrokerError):
    """Raised when order execution fails."""

    pass


class AuthenticationError(BrokerError):
    """Raised when API authentication fails."""

    pass


class StreamConnectionError(DataStreamError):
    """Raised when connection to data source fails."""

    pass
