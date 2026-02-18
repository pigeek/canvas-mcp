"""Web Server - HTTP and WebSocket server for canvas rendering."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import WSMsgType, web
from loguru import logger

if TYPE_CHECKING:
    from canvas_mcp.canvas_manager import CanvasManager
    from canvas_mcp.models import CanvasConfig, Surface


# Path to static files (A2UI renderer)
STATIC_PATH = Path(__file__).parent / "static"


WEBSOCKET_PING_INTERVAL = 30  # seconds between pings


class CanvasWebServer:
    """
    HTTP and WebSocket server for canvas rendering.

    Serves:
    - /canvas/{surface_id} - HTML page with A2UI renderer
    - /ws/{surface_id} - WebSocket endpoint for real-time updates
    - /static/* - Static files (A2UI renderer assets)
    - /health - Health check endpoint
    """

    def __init__(self, config: "CanvasConfig", canvas_manager: "CanvasManager"):
        self.config = config
        self.canvas_manager = canvas_manager
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._ping_task: asyncio.Task | None = None
        self._ws_clients: set[web.WebSocketResponse] = set()

    def _create_app(self) -> web.Application:
        """Create the aiohttp application."""
        app = web.Application()

        # Routes
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/canvas/{surface_id}", self._handle_canvas_page)
        app.router.add_get("/ws/{surface_id}", self._handle_websocket)

        # Static files
        if STATIC_PATH.exists():
            app.router.add_static("/static", STATIC_PATH, name="static")

        return app

    async def start(self) -> None:
        """Start the web server.

        If the port is already in use (another canvas-mcp instance is running),
        the web server will not start but the MCP server will continue to work.
        """
        self._app = self._create_app()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(
            self._runner,
            self.config.host,
            self.config.port,
        )

        try:
            await self._site.start()
            # Start WebSocket ping task for keep-alive
            self._ping_task = asyncio.create_task(self._ping_websockets())
            logger.info(f"Canvas Web Server started on http://{self.config.host}:{self.config.port}")
        except OSError as e:
            if e.errno == 98:  # Address already in use
                logger.warning(
                    f"Port {self.config.port} already in use - another canvas-mcp instance is running. "
                    f"Continuing without web server (will use existing instance)."
                )
                # Clean up the failed runner
                await self._runner.cleanup()
                self._runner = None
                self._site = None
            else:
                raise

    async def stop(self) -> None:
        """Stop the web server (if it was started)."""
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            self._ping_task = None
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            logger.info("Canvas Web Server stopped")

    async def _ping_websockets(self) -> None:
        """Periodically ping all connected WebSocket clients to keep connections alive."""
        while True:
            try:
                await asyncio.sleep(WEBSOCKET_PING_INTERVAL)
                if self._ws_clients:
                    logger.debug(f"Pinging {len(self._ws_clients)} WebSocket clients")
                    dead_clients = []
                    for ws in self._ws_clients:
                        try:
                            if not ws.closed:
                                await ws.ping()
                            else:
                                dead_clients.append(ws)
                        except Exception as e:
                            logger.debug(f"Failed to ping client: {e}")
                            dead_clients.append(ws)
                    # Remove dead clients
                    for ws in dead_clients:
                        self._ws_clients.discard(ws)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in ping task: {e}")

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({"status": "ok"})

    async def _handle_canvas_page(self, request: web.Request) -> web.Response:
        """Serve the canvas HTML page with A2UI renderer."""
        surface_id = request.match_info["surface_id"]

        # Check if surface exists
        surface = self.canvas_manager.get_surface_info(surface_id)
        if not surface:
            return web.Response(status=404, text=f"Surface not found: {surface_id}")

        # Generate HTML page with embedded A2UI renderer
        html = self._generate_canvas_html(surface)
        return web.Response(text=html, content_type="text/html")

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connections for real-time updates."""
        surface_id = request.match_info["surface_id"]

        ws = web.WebSocketResponse(heartbeat=WEBSOCKET_PING_INTERVAL)
        await ws.prepare(request)

        # Register client
        if not self.canvas_manager.register_ws_client(surface_id, ws):
            await ws.close(code=4004, message=b"Surface not found")
            return ws

        # Track client for keep-alive pings
        self._ws_clients.add(ws)
        logger.info(f"WebSocket connected to surface {surface_id}")

        try:
            # Send initial state
            await self.canvas_manager.send_initial_state(surface_id, ws)

            # Keep connection alive and handle incoming messages
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    # Client messages (e.g., user interactions) - currently not used
                    logger.debug(f"Received message from client: {msg.data}")
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            self._ws_clients.discard(ws)
            self.canvas_manager.unregister_ws_client(surface_id, ws)
            logger.info(f"WebSocket disconnected from surface {surface_id}")

        return ws

    def _generate_canvas_html(self, surface: "Surface") -> str:
        """Generate HTML page for canvas rendering.

        This is a thin shell: WebSocket connection + innerHTML updates.
        All rendering is done server-side by renderer.py.
        """
        from canvas_mcp.models import CanvasSizePreset
        from canvas_mcp.renderer import render_components_to_html

        surface_id = surface.surface_id
        size = surface.size

        # Determine canvas container styles based on size configuration
        if size.preset == CanvasSizePreset.AUTO or (size.width is None and size.height is None):
            canvas_width = "100%"
            canvas_height = "100%"
            canvas_max_width = "none"
            canvas_max_height = "none"
            body_display = "block"
        else:
            canvas_width = f"{size.width}px"
            canvas_height = f"{size.height}px"
            canvas_max_width = "100vw"
            canvas_max_height = "100vh"
            body_display = "flex"

        # Pre-render current content for initial page load (no flash of empty content)
        state = self.canvas_manager.get_surface(surface_id)
        initial_html = ""
        if state and state.components:
            initial_html = render_components_to_html(state.components, state.data_model)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Canvas - {surface_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{
            width: 100%; height: 100%;
            background: #0d0d1a; color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            overflow: hidden;
            display: {body_display}; justify-content: center; align-items: center;
        }}
        #canvas-container {{
            width: {canvas_width}; height: {canvas_height};
            max-width: {canvas_max_width}; max-height: {canvas_max_height};
            background: #1a1a2e; position: relative; overflow: hidden;
        }}
        #canvas-root {{ width: 100%; height: 100%; overflow: hidden; }}
        #status {{
            position: absolute; top: 16px; right: 16px;
            padding: 8px 16px; border-radius: 4px; font-size: 12px;
            background: rgba(0,0,0,0.5); z-index: 1000;
        }}
        #status.connected {{ color: #4ade80; }}
        #status.disconnected {{ color: #f87171; }}
        #status.connecting {{ color: #fbbf24; }}
        #size-info {{
            position: absolute; bottom: 16px; left: 16px;
            padding: 4px 8px; border-radius: 4px; font-size: 10px;
            background: rgba(0,0,0,0.5); color: #666; z-index: 1000;
        }}
    </style>
</head>
<body>
    <div id="canvas-container">
        <div id="status" class="connecting">Connecting...</div>
        <div id="size-info">{size.width or 'auto'}x{size.height or 'auto'} ({size.preset.value})</div>
        <div id="canvas-root">{initial_html}</div>
    </div>
    <script>
    (function() {{
        const wsUrl = (location.protocol === 'https:' ? 'wss:' : 'ws:')
            + '//' + location.host + '/ws/{surface_id}';
        const statusEl = document.getElementById('status');
        const rootEl = document.getElementById('canvas-root');
        let ws, reconnects = 0;

        function connect() {{
            statusEl.className = 'connecting';
            statusEl.textContent = 'Connecting...';
            ws = new WebSocket(wsUrl);
            ws.onopen = () => {{
                statusEl.className = 'connected';
                statusEl.textContent = 'Connected';
                reconnects = 0;
            }};
            ws.onmessage = (e) => {{
                try {{
                    const msg = JSON.parse(e.data);
                    if (msg.type === 'html') {{
                        rootEl.innerHTML = msg.html;
                    }} else if (msg.type === 'deleteSurface') {{
                        rootEl.innerHTML = '<div style="text-align:center;padding:48px"><h2>Canvas Closed</h2></div>';
                    }}
                }} catch (err) {{
                    console.error('Parse error:', err);
                }}
            }};
            ws.onclose = () => {{
                statusEl.className = 'disconnected';
                statusEl.textContent = 'Disconnected';
                if (reconnects < 10) {{ reconnects++; setTimeout(connect, 2000); }}
            }};
            ws.onerror = (err) => console.error('WS error:', err);
        }}
        connect();
    }})();
    </script>
</body>
</html>"""
