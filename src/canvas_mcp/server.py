"""MCP Server - Model Context Protocol server for Canvas."""

import json
from typing import Any, Sequence

from loguru import logger
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    ResourceTemplate,
    TextContent,
    Tool,
)

from canvas_mcp.canvas_manager import CanvasManager
from canvas_mcp.models import CanvasConfig
from canvas_mcp.web_server import CanvasWebServer


class CanvasMCPServer:
    """
    MCP Server for Canvas operations.

    Exposes tools for:
    - Creating/closing canvas surfaces
    - Updating components (A2UI)
    - Updating data model
    - Listing and retrieving canvas state
    """

    def __init__(self, config: CanvasConfig):
        self.config = config
        self.server = Server("canvas-mcp")
        self.canvas_manager = CanvasManager(config)
        self.web_server = CanvasWebServer(config, self.canvas_manager)

        self._register_tools()
        self._register_resources()

    def _register_tools(self) -> None:
        """Register MCP tools."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="canvas_create",
                    description="Create a new canvas surface for A2UI visualization",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Optional friendly name for the canvas",
                            },
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="canvas_update",
                    description="Update components on a canvas surface using A2UI format",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "surface_id": {
                                "type": "string",
                                "description": "The surface ID to update",
                            },
                            "components": {
                                "type": "array",
                                "description": "Array of A2UI component definitions",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "component": {"type": "string"},
                                        "children": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "text": {"type": "string"},
                                        "style": {"type": "object"},
                                    },
                                    "required": ["id", "component"],
                                },
                            },
                        },
                        "required": ["surface_id", "components"],
                    },
                ),
                Tool(
                    name="canvas_data",
                    description="Update data model on a canvas without re-rendering components",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "surface_id": {
                                "type": "string",
                                "description": "The surface ID to update",
                            },
                            "path": {
                                "type": "string",
                                "description": "JSON Pointer path (e.g., '/user/name')",
                            },
                            "value": {
                                "description": "Value to set at the path",
                            },
                        },
                        "required": ["surface_id", "path", "value"],
                    },
                ),
                Tool(
                    name="canvas_close",
                    description="Close and delete a canvas surface",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "surface_id": {
                                "type": "string",
                                "description": "The surface ID to close",
                            },
                        },
                        "required": ["surface_id"],
                    },
                ),
                Tool(
                    name="canvas_list",
                    description="List all canvas surfaces",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                ),
                Tool(
                    name="canvas_get",
                    description="Get the full state of a canvas (components and data model)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "surface_id": {
                                "type": "string",
                                "description": "The surface ID to retrieve",
                            },
                        },
                        "required": ["surface_id"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent]:
            try:
                result = await self._handle_tool_call(name, arguments)
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
            except Exception as e:
                logger.error(f"Tool call failed: {name} - {e}")
                return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    async def _handle_tool_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle a tool call and return result."""

        if name == "canvas_create":
            surface = await self.canvas_manager.create_surface(
                name=arguments.get("name")
            )
            return {
                "success": True,
                "surface_id": surface.surface_id,
                "name": surface.name,
                "local_url": surface.local_url,
                "ws_url": surface.ws_url,
            }

        elif name == "canvas_update":
            surface_id = arguments["surface_id"]
            components = arguments["components"]
            await self.canvas_manager.update_components(surface_id, components)
            return {
                "success": True,
                "surface_id": surface_id,
                "components_count": len(components),
            }

        elif name == "canvas_data":
            surface_id = arguments["surface_id"]
            path = arguments["path"]
            value = arguments["value"]
            await self.canvas_manager.update_data_model(surface_id, path, value)
            return {
                "success": True,
                "surface_id": surface_id,
                "path": path,
            }

        elif name == "canvas_close":
            surface_id = arguments["surface_id"]
            await self.canvas_manager.close_surface(surface_id)
            return {
                "success": True,
                "surface_id": surface_id,
            }

        elif name == "canvas_list":
            surfaces = self.canvas_manager.list_surfaces()
            return {
                "success": True,
                "count": len(surfaces),
                "surfaces": [
                    {
                        "surface_id": s.surface_id,
                        "name": s.name,
                        "local_url": s.local_url,
                        "ws_url": s.ws_url,
                        "created_at": s.created_at.isoformat(),
                        "connected_clients": s.connected_clients,
                    }
                    for s in surfaces
                ],
            }

        elif name == "canvas_get":
            surface_id = arguments["surface_id"]
            state = self.canvas_manager.get_surface(surface_id)
            if not state:
                raise ValueError(f"Surface not found: {surface_id}")

            return {
                "success": True,
                "surface_id": state.surface_id,
                "name": state.name,
                "components": state.components,
                "data_model": state.data_model,
                "created_at": state.created_at.isoformat(),
                "updated_at": state.updated_at.isoformat(),
            }

        else:
            raise ValueError(f"Unknown tool: {name}")

    def _register_resources(self) -> None:
        """Register MCP resources."""

        @self.server.list_resources()
        async def list_resources() -> list[Resource]:
            resources = []

            # List all surfaces as resources
            for surface in self.canvas_manager.list_surfaces():
                resources.append(Resource(
                    uri=f"canvas://{surface.surface_id}/state",
                    name=f"Canvas: {surface.name or surface.surface_id}",
                    description=f"Current state of canvas surface {surface.surface_id}",
                    mimeType="application/json",
                ))

            return resources

        @self.server.list_resource_templates()
        async def list_resource_templates() -> list[ResourceTemplate]:
            return [
                ResourceTemplate(
                    uriTemplate="canvas://{surface_id}/state",
                    name="Canvas State",
                    description="Get the current state of a canvas surface",
                    mimeType="application/json",
                ),
                ResourceTemplate(
                    uriTemplate="canvas://{surface_id}/url",
                    name="Canvas URLs",
                    description="Get the URLs for accessing a canvas",
                    mimeType="application/json",
                ),
            ]

        @self.server.read_resource()
        async def read_resource(uri: str) -> str:
            # Parse URI: canvas://{surface_id}/{type}
            if not uri.startswith("canvas://"):
                raise ValueError(f"Invalid resource URI: {uri}")

            path = uri[len("canvas://"):]
            parts = path.split("/")

            if len(parts) != 2:
                raise ValueError(f"Invalid resource path: {path}")

            surface_id, resource_type = parts

            if resource_type == "state":
                state = self.canvas_manager.get_surface(surface_id)
                if not state:
                    raise ValueError(f"Surface not found: {surface_id}")

                return json.dumps({
                    "surface_id": state.surface_id,
                    "name": state.name,
                    "components": state.components,
                    "data_model": state.data_model,
                    "created_at": state.created_at.isoformat(),
                    "updated_at": state.updated_at.isoformat(),
                }, indent=2)

            elif resource_type == "url":
                info = self.canvas_manager.get_surface_info(surface_id)
                if not info:
                    raise ValueError(f"Surface not found: {surface_id}")

                return json.dumps({
                    "surface_id": info.surface_id,
                    "local_url": info.local_url,
                    "ws_url": info.ws_url,
                }, indent=2)

            else:
                raise ValueError(f"Unknown resource type: {resource_type}")

    async def run_stdio(self) -> None:
        """Run the MCP server using stdio transport."""
        # Initialize canvas manager
        await self.canvas_manager.initialize()

        # Start web server in background
        await self.web_server.start()

        logger.info("Canvas MCP Server starting...")

        try:
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    self.server.create_initialization_options(),
                )
        finally:
            await self.web_server.stop()
            logger.info("Canvas MCP Server stopped")


async def run_server(config: CanvasConfig) -> None:
    """Run the Canvas MCP Server."""
    server = CanvasMCPServer(config)
    await server.run_stdio()
