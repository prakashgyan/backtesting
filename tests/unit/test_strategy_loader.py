"""Unit tests for strategy loader."""

import pytest
import tempfile
from pathlib import Path

from day_trader.strategy.loader import StrategyLoader, load_strategy, load_strategy_from_file
from day_trader.strategy.examples.simple_sma import SimpleSMAStrategy
from day_trader.core.exceptions import StrategyError


class TestStrategyLoader:
    """Test cases for StrategyLoader."""

    def test_load_from_module(self) -> None:
        """Test loading strategy from module."""
        strategy = StrategyLoader.load_from_module(
            "day_trader.strategy.examples.simple_sma",
            "SimpleSMAStrategy",
        )
        assert isinstance(strategy, SimpleSMAStrategy)

    def test_load_invalid_module(self) -> None:
        """Test loading from non-existent module."""
        with pytest.raises(StrategyError):
            StrategyLoader.load_from_module("nonexistent.module", "Strategy")

    def test_load_missing_class(self) -> None:
        """Test loading missing class from module."""
        with pytest.raises(StrategyError):
            StrategyLoader.load_from_module(
                "day_trader.strategy.examples.simple_sma",
                "NonExistentStrategy",
            )

    def test_load_non_strategy_class(self) -> None:
        """Test loading non-Strategy class."""
        with pytest.raises(StrategyError):
            StrategyLoader.load_from_module("os", "path")

    def test_load_from_file(self) -> None:
        """Test loading strategy from file."""
        file_path = Path(
            "/home/prakashgyan/zprojects/day-trader/day_trader/strategy/examples/simple_sma.py"
        )

        strategy = StrategyLoader.load_from_file(file_path, "SimpleSMAStrategy")
        assert type(strategy).__name__ == "SimpleSMAStrategy"

    def test_load_from_nonexistent_file(self) -> None:
        """Test loading from non-existent file."""
        file_path = Path("/tmp/nonexistent_strategy.py")

        with pytest.raises(StrategyError):
            StrategyLoader.load_from_file(file_path)

    def test_discover_strategies(self) -> None:
        """Test discovering strategies in directory."""
        directory = Path(
            "/home/prakashgyan/zprojects/day-trader/day_trader/strategy/examples"
        )

        strategies = StrategyLoader.discover_strategies(directory)
        assert len(strategies) > 0
        assert any("SimpleSMAStrategy" in s for s in strategies)

    def test_discover_nonexistent_directory(self) -> None:
        """Test discovering strategies in non-existent directory."""
        directory = Path("/tmp/nonexistent_directory")

        with pytest.raises(StrategyError):
            StrategyLoader.discover_strategies(directory)

    def test_load_strategy_convenience_function(self) -> None:
        """Test convenience load_strategy function."""
        strategy = load_strategy(
            "day_trader.strategy.examples.simple_sma",
            "SimpleSMAStrategy",
        )
        assert isinstance(strategy, SimpleSMAStrategy)

    def test_load_strategy_from_file_convenience(self) -> None:
        """Test convenience load_strategy_from_file function."""
        file_path = Path(
            "/home/prakashgyan/zprojects/day-trader/day_trader/strategy/examples/simple_sma.py"
        )

        strategy = load_strategy_from_file(file_path, "SimpleSMAStrategy")
        assert type(strategy).__name__ == "SimpleSMAStrategy"
