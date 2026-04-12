"""Dynamic strategy loader."""

import importlib
import inspect
from pathlib import Path
from typing import List, Type

from day_trader.core.exceptions import StrategyError
from day_trader.logging import get_logger
from day_trader.strategy.base import Strategy

logger = get_logger(__name__)


class StrategyLoader:
    """Dynamically loads and instantiates strategy classes."""

    @staticmethod
    def _find_strategy_class(module, class_name: str = None) -> type:
        """Find a concrete Strategy subclass in a module.

        If class_name is given and is a concrete subclass, use it directly.
        Otherwise, auto-discover the first concrete Strategy subclass defined
        in the module (skipping the abstract base class itself).

        Args:
            module: Imported Python module
            class_name: Optional explicit class name to look for

        Returns:
            Strategy subclass (not instantiated)

        Raises:
            StrategyError: If no suitable class is found
        """
        # If an explicit class name was given, it must exist and be a valid Strategy
        if class_name:
            if not hasattr(module, class_name):
                raise StrategyError(
                    f"Class '{class_name}' not found in {module.__name__}"
                )
            cls = getattr(module, class_name)
            if (
                inspect.isclass(cls)
                and issubclass(cls, Strategy)
                and cls is not Strategy
                and not inspect.isabstract(cls)
            ):
                return cls
            raise StrategyError(
                f"'{class_name}' in {module.__name__} is not a concrete Strategy subclass"
            )

        # Auto-discover: find concrete Strategy subclasses defined in this module
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Strategy)
                and obj is not Strategy
                and not inspect.isabstract(obj)
                and obj.__module__ == module.__name__
            ):
                return obj

        raise StrategyError(
            f"No concrete Strategy subclass found in {module.__name__}"
        )

    @staticmethod
    def load_from_module(module_path: str, class_name: str = None) -> Strategy:
        """Load a strategy from a Python module.

        Args:
            module_path: Dotted module path (e.g., 'strategies.sma')
            class_name: Name of strategy class (auto-detected if None)

        Returns:
            Instantiated strategy

        Raises:
            StrategyError: If loading or instantiation fails
        """
        try:
            # Import module
            logger.debug(f"Loading strategy from {module_path}")
            module = importlib.import_module(module_path)

            # Find strategy class
            strategy_class = StrategyLoader._find_strategy_class(module, class_name)

            # Instantiate
            strategy = strategy_class()
            logger.info(f"Strategy loaded: {strategy_class.__name__}")
            return strategy
        except StrategyError:
            raise
        except ImportError as e:
            raise StrategyError(f"Could not import {module_path}: {e}")
        except Exception as e:
            raise StrategyError(f"Failed to load strategy: {e}")

    @staticmethod
    def load_from_file(file_path: Path, class_name: str = None) -> Strategy:
        """Load a strategy from a file path.

        Args:
            file_path: Path to Python file containing strategy
            class_name: Name of strategy class (auto-detected if None)

        Returns:
            Instantiated strategy

        Raises:
            StrategyError: If loading fails
        """
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                raise StrategyError(f"File not found: {file_path}")

            # Create module name from file path
            module_name = file_path.stem

            # Load module using importlib
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if not spec or not spec.loader:
                raise StrategyError(f"Could not load module spec from {file_path}")

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find strategy class
            strategy_class = StrategyLoader._find_strategy_class(module, class_name)

            strategy = strategy_class()
            logger.info(f"Strategy loaded from {file_path}: {strategy_class.__name__}")
            return strategy
        except StrategyError:
            raise
        except Exception as e:
            raise StrategyError(f"Failed to load strategy from file: {e}")

    @staticmethod
    def discover_strategies(directory: Path) -> List[str]:
        """Discover all strategy files in a directory.

        Args:
            directory: Directory to search for strategy files

        Returns:
            List of strategy class names found

        Raises:
            StrategyError: If directory doesn't exist
        """
        directory = Path(directory)
        if not directory.exists():
            raise StrategyError(f"Directory not found: {directory}")

        strategies = []
        for file_path in directory.glob("*.py"):
            if file_path.name.startswith("_"):
                continue

            try:
                module_name = file_path.stem
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                if not spec or not spec.loader:
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Find Strategy subclasses
                for name, obj in inspect.getmembers(module):
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, Strategy)
                        and obj is not Strategy
                    ):
                        strategies.append(f"{module_name}.{name}")
            except Exception as e:
                logger.warning(f"Could not scan {file_path}: {e}")

        logger.info(f"Discovered {len(strategies)} strategies")
        return strategies


# Convenience functions
def load_strategy(module_path: str, class_name: str = None) -> Strategy:
    """Load a strategy by module path.

    Args:
        module_path: Dotted module path (e.g., 'strategies.sma')
        class_name: Strategy class name (auto-detected if None)

    Returns:
        Instantiated strategy
    """
    return StrategyLoader.load_from_module(module_path, class_name)


def load_strategy_from_file(file_path: Path, class_name: str = None) -> Strategy:
    """Load a strategy from a file.

    Args:
        file_path: Path to strategy file
        class_name: Strategy class name (auto-detected if None)

    Returns:
        Instantiated strategy
    """
    return StrategyLoader.load_from_file(file_path, class_name)
