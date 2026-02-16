"""CLI for Canvas MCP Server."""

import asyncio
import sys

import click
from loguru import logger

from canvas_mcp.models import CanvasConfig, CanvasSize, CanvasSizePreset
from canvas_mcp.server import run_server

# Available size presets for CLI help
SIZE_PRESETS = [p.value for p in CanvasSizePreset]


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    logger.remove()  # Remove default handler

    level = "DEBUG" if verbose else "INFO"
    format_str = (
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
        "<level>{message}</level>"
    )

    logger.add(sys.stderr, format=format_str, level=level, colorize=True)


@click.command()
@click.option(
    "--host",
    default="0.0.0.0",
    help="Host to bind the web server to",
)
@click.option(
    "--port",
    default=8080,
    type=int,
    help="Port for the web server",
)
@click.option(
    "--persistence-path",
    default="~/.canvas-mcp/surfaces/",
    help="Path to store canvas state",
)
@click.option(
    "--no-persistence",
    is_flag=True,
    help="Disable state persistence",
)
@click.option(
    "--receiver-url",
    default=None,
    help="URL of the external Chromecast receiver app",
)
@click.option(
    "--cast-app-id",
    default=None,
    help="Google Cast application ID",
)
@click.option(
    "--default-size",
    default="tv_1080p",
    type=click.Choice(SIZE_PRESETS, case_sensitive=False),
    help="Default canvas size preset for new surfaces",
)
@click.option(
    "-v", "--verbose",
    is_flag=True,
    help="Enable verbose logging",
)
def main(
    host: str,
    port: int,
    persistence_path: str,
    no_persistence: bool,
    receiver_url: str | None,
    cast_app_id: str | None,
    default_size: str,
    verbose: bool,
) -> None:
    """Canvas MCP Server - A2UI rendering for AI agents.

    This server provides MCP tools for creating and managing A2UI canvas
    surfaces that can be displayed in browsers or cast to Chromecast devices.

    Example usage with nanobot:

        Add to ~/.nanobot/config.json:

        {
          "tools": {
            "mcpServers": {
              "canvas": {
                "command": "canvas-mcp",
                "args": ["--port", "8080"]
              }
            }
          }
        }
    """
    setup_logging(verbose)

    config = CanvasConfig(
        host=host,
        port=port,
        persistence_enabled=not no_persistence,
        persistence_path=persistence_path,
        default_size=CanvasSize.from_preset(default_size),
        receiver_url=receiver_url,
        cast_app_id=cast_app_id,
    )

    logger.info(f"Starting Canvas MCP Server on {host}:{port} (default size: {default_size})")

    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
