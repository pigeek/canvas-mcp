"""Canvas MCP Server - A2UI rendering for AI agents."""

__version__ = "0.1.0"

from canvas_mcp.canvas_manager import CanvasManager
from canvas_mcp.models import Surface, SurfaceState
from canvas_mcp.server import CanvasMCPServer

__all__ = [
    "CanvasManager",
    "CanvasMCPServer",
    "Surface",
    "SurfaceState",
]
