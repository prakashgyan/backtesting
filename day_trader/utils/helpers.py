"""Utility functions and helpers."""

from datetime import datetime, timedelta, date, timezone
from pathlib import Path
from typing import List, Optional
import csv

from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient

from day_trader.config import Settings
from day_trader.logging import get_logger
from day_trader.models import Bar

logger = get_logger(__name__)


class DataFetcher:
    """Utility class for fetching historical data from Alpaca."""

    def __init__(self, settings: Settings):
        """Initialize data fetcher.

        Args:
            settings: Configuration settings with API credentials (required)
        """
        self.settings = settings
        self._stock_client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        self._crypto_client = CryptoHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )

    def fetch_stock_bars(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timeframe: str = "1h",
    ) -> List[Bar]:
        """Fetch historical stock bars from Alpaca.

        Args:
            symbol: Stock ticker symbol
            start_date: Start date
            end_date: End date
            timeframe: Bar timeframe ('1min', '5min', '1h', '1d', etc.)

        Returns:
            List of Bar objects

        Raises:
            Exception: If data fetch fails
        """
        try:
            logger.info(f"Fetching {symbol} bars from {start_date} to {end_date}")

            # Map timeframe string to TimeFrame enum
            timeframe_map = {
                "1min": TimeFrame.Minute,
                "5min": TimeFrame(5, TimeFrameUnit.Minute),
                "15min": TimeFrame(15, TimeFrameUnit.Minute),
                "1h": TimeFrame.Hour,
                "1d": TimeFrame.Day,
            }

            tf = timeframe_map.get(timeframe, TimeFrame.Hour)

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=datetime.combine(start_date, datetime.min.time()),
            )

            # Fetch data
            bars = self._stock_client.get_stock_bars(request)

            # Convert to internal Bar model
            result = []
            if symbol in bars.data:
                for alpaca_bar in bars.data[symbol]:
                    bar = Bar(
                        symbol=symbol,
                        timestamp=alpaca_bar.timestamp,
                        open=float(alpaca_bar.open),
                        high=float(alpaca_bar.high),
                        low=float(alpaca_bar.low),
                        close=float(alpaca_bar.close),
                        volume=float(alpaca_bar.volume),
                    )
                    result.append(bar)

            logger.info(f"Fetched {len(result)} bars for {symbol}")
            return result
        except Exception as e:
            logger.error(f"Failed to fetch bars: {e}")
            raise

    def fetch_crypto_bars(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timeframe: str = "1h",
    ) -> List[Bar]:
        """Fetch historical crypto bars from Alpaca.

        Args:
            symbol: Crypto symbol (e.g., 'BTC/USD')
            start_date: Start date
            end_date: End date
            timeframe: Bar timeframe

        Returns:
            List of Bar objects
        """
        try:
            logger.info(f"Fetching {symbol} crypto bars from {start_date} to {end_date}")

            timeframe_map = {
                "1min": TimeFrame.Minute,
                "5min": TimeFrame(5, TimeFrameUnit.Minute),
                "15min": TimeFrame(15, TimeFrameUnit.Minute),
                "1h": TimeFrame.Hour,
                "1d": TimeFrame.Day,
            }

            tf = timeframe_map.get(timeframe, TimeFrame.Hour)

            request = CryptoBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=datetime.combine(start_date, datetime.min.time()),
            )

            bars = self._crypto_client.get_crypto_bars(request)

            result = []
            if symbol in bars.data:
                for alpaca_bar in bars.data[symbol]:
                    bar = Bar(
                        symbol=symbol,
                        timestamp=alpaca_bar.timestamp,
                        open=float(alpaca_bar.open),
                        high=float(alpaca_bar.high),
                        low=float(alpaca_bar.low),
                        close=float(alpaca_bar.close),
                        volume=float(alpaca_bar.volume),
                    )
                    result.append(bar)

            logger.info(f"Fetched {len(result)} bars for {symbol}")
            return result
        except Exception as e:
            logger.error(f"Failed to fetch crypto bars: {e}")
            raise


def save_bars_to_csv(bars: List[Bar], output_path: Path) -> None:
    """Save bars to CSV file.

    Args:
        bars: List of Bar objects
        output_path: Path to output CSV file
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            writer.writeheader()

            for bar in bars:
                writer.writerow({
                    'timestamp': bar.timestamp.isoformat(),
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume,
                })

        logger.info(f"Saved {len(bars)} bars to {output_path}")
    except Exception as e:
        logger.error(f"Failed to save bars to CSV: {e}")
        raise


def load_bars_from_csv(file_path: Path, symbol: str) -> List[Bar]:
    """Load bars from CSV file.

    Args:
        file_path: Path to CSV file
        symbol: Symbol to assign to all bars

    Returns:
        List of Bar objects
    """
    try:
        bars = []
        failed_rows = 0
        with open(file_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ts = datetime.fromisoformat(row['timestamp'])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    bar = Bar(
                        symbol=symbol,
                        timestamp=ts,
                        open=float(row['open']),
                        high=float(row['high']),
                        low=float(row['low']),
                        close=float(row['close']),
                        volume=float(row['volume']),
                    )
                    bars.append(bar)
                except (ValueError, KeyError) as e:
                    logger.warning(f"Skipping invalid row: {e}")
                    failed_rows += 1

        total_rows = len(bars) + failed_rows
        if failed_rows > 0 and len(bars) == 0:
            raise ValueError(
                f"All {failed_rows} rows failed to parse from {file_path}"
            )
        if total_rows > 0 and failed_rows / total_rows > 0.5:
            raise ValueError(
                f"Majority of rows failed to parse ({failed_rows}/{total_rows}) "
                f"from {file_path} — check file format"
            )

        logger.info(f"Loaded {len(bars)} bars from {file_path}")
        return bars
    except Exception as e:
        logger.error(f"Failed to load bars from CSV: {e}")
        raise


def load_bars_from_csv_multi(file_path: Path, symbols: Optional[List[str]] = None) -> List[Bar]:
    """Load bars from CSV file with optional multi-symbol filtering.

    Expected CSV columns:
    - Legacy single-symbol: timestamp,open,high,low,close,volume
    - Multi-symbol: timestamp,symbol,open,high,low,close,volume

    Args:
        file_path: Path to CSV file.
        symbols: Optional symbol allowlist. When provided, only rows for these
            symbols are returned.

    Returns:
        List of Bar objects.

    Raises:
        ValueError: If symbols are required but CSV lacks a symbol column.
    """
    try:
        bars: List[Bar] = []
        failed_rows = 0
        requested = set(symbols) if symbols else None

        with open(file_path, "r") as f:
            reader = csv.DictReader(f)
            has_symbol_col = bool(reader.fieldnames and "symbol" in reader.fieldnames)

            if requested and len(requested) > 1 and not has_symbol_col:
                raise ValueError(
                    "CSV does not contain a 'symbol' column; cannot load multiple symbols"
                )

            single_fallback_symbol = next(iter(requested)) if requested and len(requested) == 1 else None

            for row in reader:
                try:
                    ts = datetime.fromisoformat(row["timestamp"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)

                    row_symbol = row.get("symbol", "").strip() if has_symbol_col else ""
                    symbol = row_symbol or single_fallback_symbol
                    if not symbol:
                        failed_rows += 1
                        continue

                    if requested and symbol not in requested:
                        continue

                    bar = Bar(
                        symbol=symbol,
                        timestamp=ts,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                    bars.append(bar)
                except (ValueError, KeyError):
                    logger.warning("Skipping invalid row in multi-symbol CSV")
                    failed_rows += 1

        total_rows = len(bars) + failed_rows
        if failed_rows > 0 and len(bars) == 0:
            raise ValueError(f"All {failed_rows} rows failed to parse from {file_path}")
        if total_rows > 0 and failed_rows / total_rows > 0.5:
            raise ValueError(
                f"Majority of rows failed to parse ({failed_rows}/{total_rows}) "
                f"from {file_path} — check file format"
            )

        logger.info(f"Loaded {len(bars)} bars from {file_path} (multi-symbol)")
        return bars
    except Exception as e:
        logger.error(f"Failed to load bars from CSV (multi-symbol): {e}")
        raise


def get_last_n_days(n_days: int) -> tuple[date, date]:
    """Get date range for last N days.

    Args:
        n_days: Number of days

    Returns:
        Tuple of (start_date, end_date)
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=n_days)
    return start_date, end_date
