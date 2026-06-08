"""CLI entry point for the trading engine."""

import asyncio
from pathlib import Path
from typing import List, Optional

import typer
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from typing_extensions import Annotated

import dataclasses

from day_trader.broker.alpaca import AlpacaBroker
from day_trader.broker.simulated import SimulatedBroker
from day_trader.config import RunDefaults, Settings, get_settings
from day_trader.core.base import BrokerInterface
from day_trader.data.cache import DataCache
from day_trader.data.replay import ReplayStream
from day_trader.engine.engine import Engine
from day_trader.logging import get_logger
from day_trader.strategy.loader import StrategyLoader
from day_trader.ui import CLIOutput
from day_trader.utils.helpers import DataFetcher, save_bars_to_csv, load_bars_from_csv, load_bars_from_csv_multi, get_last_n_days  # DataFetcher used by fetch_data command

logger = get_logger(__name__)

app = typer.Typer(
    name="trader",
    help="Lightweight CLI-based trading framework with Alpaca API integration",
)


@app.callback()
def main(
    ctx: typer.Context,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Disable ANSI colors in CLI output"),
    ] = False,
    plain: Annotated[
        bool,
        typer.Option("--plain", help="Use plain, script-safe output formatting"),
    ] = False,
) -> None:
    """Configure CLI output preferences."""
    ctx.obj = {"ui": CLIOutput(no_color=no_color, plain=plain)}


def _get_ui(ctx: typer.Context) -> CLIOutput:
    """Resolve UI settings from Typer context."""
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("ui"), CLIOutput):
        return ctx.obj["ui"]
    return CLIOutput()


def _create_broker(mode: str, settings: Settings) -> BrokerInterface:
    """Factory that maps run mode to the appropriate broker.

    Centralises broker selection so adding a new broker type only requires
    a change here, not in the body of the run() command.

    Args:
        mode: Resolved run mode ('replay' or 'live')
        settings: Application settings

    Returns:
        Configured BrokerInterface implementation
    """
    if mode == "replay":
        return SimulatedBroker()
    # Live mode — confirm before placing real orders
    if settings.paper_trading:
        msg = "This run will place PAPER trade orders on Alpaca. Continue?"
    else:
        msg = "This run will place REAL $$$ trades on Alpaca. Continue?"
    if not typer.confirm(msg):
        raise typer.Exit(code=0)
    return AlpacaBroker(settings)


def _parse_symbols(symbol_text: str) -> List[str]:
    """Parse comma-separated symbols into a deduplicated ordered list."""
    symbols: List[str] = []
    for token in symbol_text.split(","):
        clean = token.strip()
        if not clean:
            raise ValueError(
                "Invalid --symbol value: empty symbol token found. "
                "Example: --symbol SPY,QQQ,IWM"
            )
        if clean not in symbols:
            symbols.append(clean)

    if not symbols:
        raise ValueError("At least one symbol is required")

    return symbols


def _supports_multi_symbol(strategy_instance: object) -> bool:
    """Return True when a strategy explicitly advertises multi-symbol safety."""
    checker = getattr(strategy_instance, "supports_multi_symbol", None)
    if not callable(checker):
        return False
    try:
        return bool(checker())
    except Exception:
        return False


@app.command()
def run(
    ctx: typer.Context,
    strategy: Annotated[
        str,
        typer.Argument(help="Strategy module path or file path (e.g., strategies.sma)"),
    ],
    symbol: Annotated[
        Optional[str],
        typer.Option(help="Stock ticker symbol (optional; strategy default preferred)"),
    ] = None,
    mode: Annotated[
        Optional[str],
        typer.Option(help="Trading mode: live or replay (optional; strategy default preferred)"),
    ] = None,
    days: Annotated[
        Optional[int],
        typer.Option(help="Number of days of historical data (optional; replay only)"),
    ] = None,
    speed: Annotated[
        Optional[float],
        typer.Option(help="Playback speed multiplier (optional; replay only)"),
    ] = None,
    timeframe: Annotated[
        Optional[str],
        typer.Option(help="Bar timeframe for --days fetch (optional; strategy default preferred)"),
    ] = None,
    data_file: Annotated[
        Optional[Path],
        typer.Option(help="CSV file with historical data (replay mode)"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose logging"),
    ] = False,
) -> None:
    """Run a trading strategy.

    Examples:
        trader run strategies.sma --symbol AAPL --mode replay --days 30
        trader run /path/to/strategy.py --symbol TSLA --mode live
        trader run strategies.rsi --symbol BTC/USD --mode replay --data-file btc_data.csv
    """
    ui = _get_ui(ctx)
    try:
        if verbose:
            logger.setLevel("DEBUG")

        # Load strategy
        logger.info("Loading strategy: %s", strategy)
        if strategy.endswith(".py"):
            # Load from file
            strategy_instance = StrategyLoader.load_from_file(Path(strategy))
        else:
            # Load from module
            strategy_instance = StrategyLoader.load_from_module(strategy)

        strategy_defaults = strategy_instance.runtime_defaults()
        global_defaults: dict[str, object] = dataclasses.asdict(RunDefaults())

        def _resolve_param(name: str, cli_value: object) -> object:
            strategy_default = strategy_defaults.get(name)

            if cli_value is not None:
                if strategy_default is not None and strategy_default != cli_value:
                    warning_msg = (
                        f"Override: --{name}={cli_value} replaces strategy default {strategy_default}"
                    )
                    logger.warning(warning_msg)
                    ui.print(warning_msg, style="yellow")
                return cli_value

            if strategy_default is not None:
                return strategy_default

            return global_defaults[name]

        resolved_symbol = str(_resolve_param("symbol", symbol))
        resolved_symbols = _parse_symbols(resolved_symbol)
        resolved_mode = str(_resolve_param("mode", mode)).lower()
        resolved_days_value = _resolve_param("days", days)
        resolved_days = int(resolved_days_value) if resolved_days_value is not None else None
        resolved_speed = float(_resolve_param("speed", speed))
        resolved_timeframe = str(_resolve_param("timeframe", timeframe))
        resolved_symbol_display = ",".join(resolved_symbols)

        if resolved_mode not in ("live", "replay"):
            ui.print(f"Invalid mode: {resolved_mode}. Must be live or replay.", err=True)
            raise typer.Exit(code=1)

        if len(resolved_symbols) > 1 and not _supports_multi_symbol(strategy_instance):
            ui.print(
                "Strategy does not support multi-symbol runs. "
                "Use one symbol, or implement supports_multi_symbol() -> True "
                "with per-symbol state isolation.",
                err=True,
            )
            raise typer.Exit(code=1)

        # Get configuration
        settings = get_settings()
        logger.info(
            "Trading engine starting - Mode: %s, Symbols: %s",
            resolved_mode,
            resolved_symbol_display,
        )

        # Create data stream
        logger.info("Creating %s data stream", resolved_mode)
        replay_stream: ReplayStream | None = None
        if resolved_mode == "replay":
            if data_file and Path(data_file).exists():
                logger.info("Loading data from %s", data_file)
                if len(resolved_symbols) > 1:
                    bars = load_bars_from_csv_multi(Path(data_file), symbols=resolved_symbols)
                else:
                    bars = load_bars_from_csv(Path(data_file), resolved_symbols[0])
            elif resolved_days:
                n_days = resolved_days
                start_date, end_date = get_last_n_days(n_days)
                cache = DataCache(settings)
                bars = []
                for current_symbol in resolved_symbols:
                    info = cache.cache_info(
                        current_symbol,
                        resolved_timeframe,
                        start_date,
                        end_date,
                    )
                    if info["fresh"]:
                        ui.print(
                            f"[{current_symbol}] cache hit "
                            f"(age {info['age_hours']:.1f}h < ttl {info['ttl_hours']:.0f}h)",
                            style="cyan",
                        )
                    else:
                        ui.print(f"[{current_symbol}] fetching historical bars...", style="cyan")
                    symbol_bars = cache.fetch_bars(
                        current_symbol,
                        start_date,
                        end_date,
                        resolved_timeframe,
                    )
                    bars.extend(symbol_bars)

                bars.sort(key=lambda b: (b.timestamp, b.symbol))
                if len(resolved_symbols) == 1:
                    ui.print(f"Loaded {len(bars)} bars for replay", style="green")
                else:
                    ui.print(
                        f"Loaded {len(bars)} bars across {len(resolved_symbols)} symbols for replay",
                        style="green",
                    )
            else:
                ui.print(
                    "No data source specified. Use --days or --data-file.", err=True
                )
                raise typer.Exit(code=1)
            replay_stream = ReplayStream(bars, speed=resolved_speed)
            stream = replay_stream
        else:
            bars = []  # No bars for live mode
            # Live mode
            from day_trader.data.live import LiveStream
            stream = LiveStream(settings, symbols=resolved_symbols)

        # Create broker via factory
        broker = _create_broker(resolved_mode, settings)

        # Extract data date range from bars (for replay mode benchmarks)
        data_start_date: str | None = None
        data_end_date: str | None = None
        if bars:
            data_start_date = bars[0].timestamp.date().isoformat()
            data_end_date = bars[-1].timestamp.date().isoformat()

        # Create engine
        run_metrics_csv = settings.logs_dir / "run_metrics.csv"
        run_events_db = settings.logs_dir / "run_history.db"
        engine = Engine(
            stream,
            strategy_instance,
            broker,
            run_metrics_csv_path=run_metrics_csv,
            run_events_db_path=run_events_db,
            run_metadata={
                "symbol": resolved_symbols[0],
                "symbols": resolved_symbols,
                "mode": resolved_mode,
                "strategy": strategy,
                "timeframe": resolved_timeframe,
                "data_start_date": data_start_date,
                "data_end_date": data_end_date,
            },
        )

        # Display banner
        _display_banner(ui, resolved_symbols, resolved_mode, strategy)

        progress: Progress | None = None
        if replay_stream is not None and replay_stream.total_bars > 0 and ui.rich_enabled:
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
            )
            task_id = progress.add_task("Replaying bars", total=replay_stream.total_bars)

            def _update_progress(current: int, total: int) -> None:
                progress.update(task_id, total=total, completed=current)

            replay_stream.set_progress_callback(_update_progress)

        # Run engine
        if progress is not None:
            with progress:
                asyncio.run(engine.run())
            ui.print("")
        else:
            asyncio.run(engine.run())

        # Display stats
        _display_stats(ui, engine)

    except KeyboardInterrupt:
        logger.info("Engine interrupted by user")
        ui.print("\nTrading engine stopped.", style="yellow")
    except typer.Exit:
        raise
    except Exception as e:
        logger.error(f"Error: {e}")
        ui.print(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def fetch_data(
    ctx: typer.Context,
    symbol: Annotated[str, typer.Option(help="Stock ticker symbol (e.g., AAPL)")],
    days: Annotated[int, typer.Option(help="Number of days of historical data")] = 30,
    output: Annotated[
        Path,
        typer.Option(help="Output CSV file path"),
    ] = Path("./data/{symbol}_{days}d.csv"),
    timeframe: Annotated[str, typer.Option(help="Bar timeframe (1min, 5min, 1h, 1d)")] = "1h",
) -> None:
    """Fetch historical data from Alpaca and save to CSV.

    Examples:
        trader fetch-data --symbol AAPL --days 30
        trader fetch-data --symbol TSLA --days 90 --output tsla_data.csv
    """
    ui = _get_ui(ctx)
    try:
        settings = get_settings()
        fetcher = DataFetcher(settings)

        # Get date range
        start_date, end_date = get_last_n_days(days)

        ui.print(f"Fetching {symbol} data from {start_date} to {end_date}...", style="cyan")

        # Determine if crypto or stock
        is_crypto = "/" in symbol

        # Fetch data
        ui.print(f"Fetching {symbol} {timeframe} bars...", style="cyan")
        if is_crypto:
            bars = fetcher.fetch_crypto_bars(symbol, start_date, end_date, timeframe)
        else:
            bars = fetcher.fetch_stock_bars(symbol, start_date, end_date, timeframe)

        ui.print(f"Fetched {len(bars)} bars", style="green")

        # Prepare output path
        output_path = output.with_name(
            output.name.format(symbol=symbol, days=days)
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Save to CSV
        save_bars_to_csv(bars, output_path)
        ui.print(f"Saved to {output_path}", style="green")

    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        ui.print(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def list_strategies(
    ctx: typer.Context,
    directory: Annotated[
        Path,
        typer.Option(help="Directory to scan for strategies"),
    ] = Path("./strategies"),
) -> None:
    """List available strategies in a directory."""
    ui = _get_ui(ctx)
    try:
        if not directory.exists():
            ui.print(f"Directory not found: {directory}", err=True)

        # Also list built-in examples
        from day_trader.strategy import examples
        examples_dir = Path(examples.__file__).parent

        strategies = StrategyLoader.discover_strategies(examples_dir)

        if strategies:
            ui.print(f"Built-in strategies ({len(strategies)}):", style="cyan")
            for i, strategy in enumerate(strategies, 1):
                ui.print(f"  {i}. {strategy}")

        # Check user directory
        if directory.exists():
            user_strategies = StrategyLoader.discover_strategies(directory)
            if user_strategies:
                ui.print(f"\nUser strategies ({len(user_strategies)}):", style="cyan")
                for i, strategy in enumerate(user_strategies, 1):
                    ui.print(f"  {i}. {strategy}")
        else:
            ui.print(f"\nCreate strategies in: {directory}", style="yellow")

    except Exception as e:
        logger.error(f"Error listing strategies: {e}")
        ui.print(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def account(ctx: typer.Context) -> None:
    """Fetch and display account information."""
    ui = _get_ui(ctx)
    try:
        settings = get_settings()
        broker = AlpacaBroker(settings)

        async def _get_account():
            await broker.connect()
            account_data = await broker.get_account()
            await broker.disconnect()
            return account_data

        account_info = asyncio.run(_get_account())

        if ui.rich_enabled:
            margin_usage = account_info.margin_usage_pct()
            margin_style = "red" if margin_usage >= 50 else "yellow" if margin_usage >= 25 else "green"

            table = Table(title="Account Information")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", justify="right")
            table.add_row("Cash", f"${account_info.cash:,.2f}")
            table.add_row("Buying Power", f"${account_info.buying_power:,.2f}")
            table.add_row("Portfolio Value", f"${account_info.portfolio_value:,.2f}")
            table.add_row("Equity", f"${account_info.equity:,.2f}")
            table.add_row("Margin Usage", f"[{margin_style}]{margin_usage:.1f}%[/{margin_style}]")
            ui.console.print(table)
        else:
            ui.print("\n=== Account Information ===")
            ui.print(f"Cash:            ${account_info.cash:,.2f}")
            ui.print(f"Buying Power:    ${account_info.buying_power:,.2f}")
            ui.print(f"Portfolio Value: ${account_info.portfolio_value:,.2f}")
            ui.print(f"Equity:          ${account_info.equity:,.2f}")
            ui.print(f"Margin Usage:    {account_info.margin_usage_pct():.1f}%\n")
    except Exception as e:
        logger.error(f"Error fetching account: {e}")
        ui.print(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


def _display_banner(ui: CLIOutput, symbols: list[str], mode: str, strategy: str) -> None:
    """Display trading engine banner."""
    symbol_label = "Symbols" if len(symbols) > 1 else "Symbol"
    symbol_value = ",".join(symbols)
    if ui.rich_enabled:
        ui.print("\n" + "=" * 50, style="cyan bold")
        ui.print("Day Trader - Trading Engine", style="cyan bold")
        ui.print("=" * 50, style="cyan bold")
        ui.print(f"Mode:     {mode.upper()}", style="white")
        ui.print(f"{symbol_label}:   {symbol_value}", style="yellow")
        ui.print(f"Strategy: {strategy}", style="white")
        ui.print("=" * 50 + "\n", style="cyan bold")
        return

    ui.print("\n" + "=" * 50)
    ui.print("Day Trader - Trading Engine")
    ui.print("=" * 50)
    ui.print(f"Mode:     {mode.upper()}")
    ui.print(f"{symbol_label}:   {symbol_value}")
    ui.print(f"Strategy: {strategy}")
    ui.print("=" * 50 + "\n")


def _display_stats(ui: CLIOutput, engine: Engine) -> None:
    """Display engine statistics."""
    stats = engine.stats
    if ui.rich_enabled:
        table = Table(title="Engine Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Bars Processed", str(stats["bars_processed"]))
        table.add_row("Trades Executed", str(stats["trades_executed"]))
        error_style = "red" if stats["errors"] else "green"
        table.add_row("Errors", f"[{error_style}]{stats['errors']}[/{error_style}]")
        table.add_row("Duration", f"{stats['elapsed_seconds']:.2f}s")
        ui.console.print(table)
        return

    ui.print("\n" + "=" * 50)
    ui.print("Engine Statistics")
    ui.print("=" * 50)
    ui.print(f"Bars Processed: {stats['bars_processed']}")
    ui.print(f"Trades Executed: {stats['trades_executed']}")
    ui.print(f"Errors: {stats['errors']}")
    ui.print(f"Duration: {stats['elapsed_seconds']:.2f}s")
    ui.print("=" * 50 + "\n")


@app.command()
def dashboard(
    ctx: typer.Context,
    port: Annotated[
        int,
        typer.Option("--port", help="Port to bind the dashboard server"),
    ] = 8080,
    db: Annotated[
        Path,
        typer.Option("--db", help="Path to run_history.db SQLite database"),
    ] = Path("./logs/run_history.db"),
    no_browser: Annotated[
        bool,
        typer.Option("--no-browser", help="Do not open browser automatically"),
    ] = False,
) -> None:
    """Launch the trading dashboard web UI.

    Examples:

        trader dashboard

        trader dashboard --port 9000

        trader dashboard --db /path/to/run_history.db --no-browser
    """
    import threading
    import webbrowser

    import uvicorn

    from day_trader.dashboard.server import app as dashboard_app
    from day_trader.dashboard.server import configure

    ui = _get_ui(ctx)

    try:
        settings = get_settings()
        logs_dir = settings.logs_dir
    except Exception:
        logs_dir = Path("./logs")

    db_path = db.resolve()
    csv_path = (logs_dir / "run_metrics.csv").resolve()
    html_path = Path(__file__).parent / "dashboard" / "static" / "index.html"

    if not db_path.exists():
        ui.print(
            f"[yellow]Database not found at {db_path}. Dashboard will show empty state.[/yellow]"
            if ui.rich_enabled
            else f"Database not found at {db_path}. Dashboard will show empty state."
        )

    configure(db_path=db_path, csv_path=csv_path, html_path=html_path)

    url = f"http://localhost:{port}"
    if ui.rich_enabled:
        ui.print(
            f"Dashboard running at [link={url}]{url}[/link]  (Ctrl+C to stop)",
            style="cyan",
        )
    else:
        ui.print(f"Dashboard running at {url}  (Ctrl+C to stop)")

    if not no_browser:
        def _open_browser() -> None:
            import time
            time.sleep(1.2)
            webbrowser.open(url)

        threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(
        dashboard_app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
    )


if __name__ == "__main__":
    app()

