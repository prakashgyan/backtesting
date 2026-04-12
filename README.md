# Day Trader CLI

A lightweight, async-first CLI-based trading framework with Alpaca API integration.

## Features

✨ **Async Architecture** - Built on asyncio for low-latency, concurrent operations
🔌 **Pluggable Strategies** - Define custom trading strategies declaratively
📊 **Live & Replay Modes** - Trade live or replay historical data
🛡️ **Paper Trading** - Test strategies safely with paper accounts
🏗️ **Minimal Dependencies** - Lean codebase with essential packages only
📝 **Audit Logging** - Comprehensive trade execution logs
🗃️ **Run History Database** - SQLite run + order-event tracking for dashboard visualization

## Quick Start

### Installation

```bash
pip install -e ".[dev]"  # Install with dev dependencies
# or
pip install -r requirements.txt
```

### Basic Usage

```bash
# Replay historical data with SMA strategy
trader run day_trader.strategy.examples.simple_sma --symbol AAPL --mode replay --days 30

# Trade live with custom strategy
trader run /path/to/my_strategy.py --symbol TSLA --mode live

# List available strategies
trader list-strategies --directory ./strategies

# Check account information
trader account
```

## Run Command Reference

Yes. Replay speed is configurable with `--speed`.

### Command syntax

```bash
trader run [OPTIONS] STRATEGY
```

### Required argument

- `STRATEGY` (required): Strategy module path or Python file path.

Examples:

```bash
trader run day_trader.strategy.examples.simple_sma --symbol AAPL --mode replay --days 30
trader run /path/to/my_strategy.py --symbol TSLA --mode live
```

### Run options

- `--symbol TEXT` (default: `AAPL`): Symbol to trade or replay.
- `--mode TEXT` (default: `replay`): `replay` or `live`.
- `--days INTEGER`: Number of historical days to fetch for replay.
- `--speed FLOAT` (default: `1.0`): Replay playback multiplier. Example: `2.0` means 2x speed, `10.0` means 10x speed.
- `--data-file PATH`: Use a local CSV file as replay source.
- `--verbose, -v`: Enable verbose logging.

### Global output options

These options can be used before any command, including `run`:

- `--no-color`: Disable ANSI color output.
- `--plain`: Use script-safe plain formatting.

Examples:

```bash
trader --plain run day_trader.strategy.examples.simple_sma --symbol AAPL --mode replay --days 30
trader --no-color run day_trader.strategy.examples.simple_sma --symbol AAPL --mode replay --days 30 --speed 5
```

### Replay mode data source behavior

- If `--data-file` is provided and exists, replay uses that CSV file.
- Else if `--days` is provided, replay fetches historical bars from Alpaca.
- If neither is provided in replay mode, the command exits with an error.

### Replay speed examples

```bash
# Real-time equivalent replay
trader run day_trader.strategy.examples.simple_sma --symbol AAPL --mode replay --days 30 --speed 1

# Faster backtest-style replay
trader run day_trader.strategy.examples.simple_sma --symbol AAPL --mode replay --days 30 --speed 10

# Very fast replay from local CSV
trader run day_trader.strategy.examples.simple_sma --symbol AAPL --mode replay --data-file ./data/aapl.csv --speed 50
```

## Architecture

```
CLI Layer (typer)
    ↓
Engine (orchestrator)
    ├── DataStream (live or replay)
    ├── Strategy (user-defined)
    └── Broker (Alpaca API)
```

### Key Components

#### DataStream
Data source for market bars:
- **ReplayStream**: Load historical OHLCV data from CSV, emit at configurable speed
- **LiveStream**: Connect to Alpaca WebSocket for real-time bars

#### Strategy
Trading strategy logic:
- Override `on_bar(bar)` to implement trading logic
- Call `self.buy()` or `self.sell()` to place orders
- Optional `reason` and `details` can be passed for richer run-event tracking
- Example: `SimpleSMAStrategy` implements SMA crossover

#### Broker
Order execution and account management:
- **AlpacaBroker**: Execute orders via Alpaca API
- Methods: `buy()`, `sell()`, `get_account()`, `get_positions()`

#### Engine
Main orchestrator:
- Routes bars from stream to strategy
- Executes orders via broker
- Handles lifecycle (initialize → process → finalize)

## Creating a Custom Strategy

Create a new Python file with a strategy class extending `Strategy`:

```python
from day_trader.strategy.base import Strategy
from day_trader.models import Bar

class MyStrategy(Strategy):
    async def initialize(self, broker):
        """Called once at startup."""
        await super().initialize(broker)
        # Set up indicators, state, etc.

    async def on_bar(self, bar: Bar):
        """Called for each bar."""
        if bar.close > 150:
            await self.buy(
                "AAPL",
                qty=10,
                limit_price=bar.close,
                reason="Price broke resistance",
                details={"resistance": 150},
            )
        elif bar.close < 140:
            await self.sell(
                "AAPL",
                qty=10,
                limit_price=bar.close,
                reason="Price lost support",
                details={"support": 140},
            )

    async def finalize(self):
        """Called at shutdown."""
        await super().finalize()
```

Run with:
```bash
trader run /path/to/my_strategy.py --symbol AAPL --mode replay
```

Or place in `strategies/` directory and run:
```bash
trader run strategies.my_strategy --symbol AAPL
```

## Configuration

Settings are loaded from `.env` file. Copy `.env.example`:

```bash
cp .env.example .env
```

Edit with your Alpaca credentials:

```env
ALPACA_API_KEY=your_api_key
ALPACA_SECRET_KEY=your_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets  # Paper trading
PAPER_TRADING=true
LOG_LEVEL=INFO
```

## Data Sources

### Historical Data (Replay Mode)

For CSV format, use columns: `timestamp,open,high,low,close,volume`

```csv
2024-01-01T10:00:00,150.00,151.00,149.00,150.50,1000000
2024-01-01T10:01:00,150.50,151.50,149.50,151.00,1000000
```

Load with:
```python
from day_trader.data.replay import ReplayStream

stream = ReplayStream.from_csv("path/to/data.csv", symbol="AAPL")
```

### Live Data

The engine connects to Alpaca's WebSocket stream automatically in live mode.

## Testing

Run all tests:
```bash
pytest
```

Run with coverage:
```bash
pytest --cov=day_trader --cov-report=html
```

Test types:
- **Unit tests** (`tests/unit/`): Individual components with mocks
- **Integration tests** (`tests/integration/`): Full workflows

## Run History Database

Every `trader run` now records run metadata and detailed order events to:

- `logs/run_history.db` (SQLite)

Schema overview:

- `runs`: one row per engine run (status, duration, bars, trades, errors, metadata)
- `run_events`: timeline events (`RUN_STARTED`, `ORDER_REQUESTED`, `ORDER_RESULT`, `ORDER_FAILED`, `RUN_COMPLETED`)

This is intended for building timeline and diagnostics dashboards that explain what happened during a run and why.

## Project Structure

```
day-trader/
├── day_trader/
│   ├── cli.py              # CLI entry point (typer)
│   ├── config.py           # Configuration & settings
│   ├── models.py           # Data models (Bar, Position, Order, AccountInfo)
│   ├── logging.py          # Structured logging
│   ├── core/
│   │   ├── base.py         # Abstract base classes
│   │   └── exceptions.py   # Custom exceptions
│   ├── engine/
│   │   └── engine.py       # Main orchestrator
│   ├── data/
│   │   ├── stream.py       # DataStream base class
│   │   ├── replay.py       # Historical replay implementation
│   │   └── live.py         # Live WebSocket implementation
│   ├── broker/
│   │   ├── base.py         # Broker base class
│   │   └── alpaca.py       # Alpaca API implementation
│   └── strategy/
│       ├── base.py         # Strategy base class
│       ├── loader.py       # Dynamic strategy loader
│       └── examples/
│           └── simple_sma.py  # Example SMA strategy
├── tests/
│   ├── conftest.py         # Pytest fixtures
│   ├── unit/               # Unit tests
│   └── integration/        # Integration tests
├── .env.example            # Example configuration
└── requirements.txt        # Dependencies
```

## Log Output

Logs are written to:
- **Console**: Real-time events and errors
- **`logs/day_trader.log`**: JSON formatted detailed logs
- **`logs/trades.log`**: Trade execution audit trail

Example trade log:
```
2024-01-01 10:05:30,day_trader.strategy,BUY order: AAPL x10 @ 150.00
2024-01-01 10:06:45,day_trader.strategy,SELL order: AAPL x10 @ 151.50
```

## Models

### Bar
OHLCV candlestick data:
- `symbol`: Stock ticker
- `timestamp`: Bar time
- `open, high, low, close`: Prices
- `volume`: Trading volume

### Position
Open trading position:
- `symbol`: Stock ticker
- `qty`: Shares held
- `avg_fill_price`: Average entry price
- `current_price`: Current market price

### Order
Executed order:
- `symbol, qty, side`: Order details
- `status`: PENDING, FILLED, CANCELLED, REJECTED
- `filled_qty, avg_fill_price`: Fill details

### AccountInfo
Account state:
- `cash`: Available cash
- `buying_power`: Available margin
- `portfolio_value`: Total account value
- `equity`: Account equity

## Examples

### SMA Crossover Strategy

```python
from day_trader.strategy.examples.simple_sma import SimpleSMAStrategy

# 5-bar SMA crosses above/below 20-bar SMA
trader run day_trader.strategy.examples.simple_sma --symbol AAPL --mode replay
```

### Custom Momentum Strategy

```python
from day_trader.strategy.base import Strategy
from day_trader.models import Bar

class MomentumStrategy(Strategy):
    async def on_bar(self, bar: Bar):
        pct_change = bar.price_change_pct()

        if pct_change > 1.0:  # Up more than 1%
            await self.buy("AAPL", qty=5, limit_price=bar.close)
        elif pct_change < -1.0:  # Down more than 1%
            await self.sell("AAPL", qty=5, limit_price=bar.close)
```

## Performance Notes

- **Live mode**: Designed for sub-second latency
- **Replay mode**: Can process 1000+ bars/second at 100x speed
- Use async operations only; blocking calls will slow the event loop
- Avoid heavy computation in `on_bar()`; use executor pool if needed

## Troubleshooting

**Authentication Error**
- Check `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` in `.env`
- Verify you're using correct credentials for paper/live trading

**No bars received in replay**
- Check CSV file format and path
- Ensure bars are sorted chronologically

**Strategy not triggered**
- Add logging to verify `on_bar()` is called
- Check signal generation logic

**High latency**
- Minimize work in `on_bar()`
- Check network connection for live mode
- Consider increasing batch size if available

## Contributing

Contributions welcome! Areas for enhancement:
- Multi-symbol support
- Risk management layer
- Advanced backtesting metrics
- More example strategies
- Additional data sources

## Roadmap

- [ ] WebSocket reconnection with exponential backoff
- [ ] Order type support (stop, trailing stop, OCO)
- [ ] Portfolio analytics dashboard
- [ ] Multi-broker support
- [ ] Machine learning integration

## License

MIT License - See LICENSE file for details

## Support

- 📖 See [Design Document](DESIGN.md) for architecture details
- 🐛 Report issues on GitHub
- 💬 Discuss in discussions

---

Built with ❤️ for traders and developers.
