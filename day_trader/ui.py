"""CLI output helpers with Rich and plain-output fallbacks."""

from contextlib import nullcontext
from typing import Any, ContextManager

import typer
from rich.console import Console


class CLIOutput:
    """Handle styled and plain-safe terminal output for CLI commands."""

    def __init__(self, no_color: bool = False, plain: bool = False) -> None:
        # Use Click's stream TTY check to avoid ANSI output in non-interactive contexts.
        import click

        is_interactive = click.get_text_stream("stdout").isatty()
        self.rich_enabled = is_interactive and not plain
        self.no_color = no_color or plain or not is_interactive
        self.plain = plain
        self.console = Console(
            no_color=self.no_color,
            force_terminal=self.rich_enabled,
            highlight=False,
        )

    def print(self, message: str, style: str | None = None, err: bool = False) -> None:
        """Print a message with optional style when Rich output is enabled."""
        if err:
            typer.echo(message, err=True)
            return

        if self.rich_enabled and style:
            self.console.print(message, style=style)
            return

        typer.echo(message)

    def status(self, message: str) -> ContextManager[Any]:
        """Return a status context manager for long-running operations."""
        if self.rich_enabled:
            return self.console.status(message)
        return nullcontext()
