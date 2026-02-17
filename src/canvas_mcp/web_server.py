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
        """Start the web server."""
        self._app = self._create_app()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(
            self._runner,
            self.config.host,
            self.config.port,
        )
        await self._site.start()

        # Start WebSocket ping task for keep-alive
        self._ping_task = asyncio.create_task(self._ping_websockets())

        logger.info(f"Canvas Web Server started on http://{self.config.host}:{self.config.port}")

    async def stop(self) -> None:
        """Stop the web server."""
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
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
        """Generate HTML page for canvas rendering."""
        from canvas_mcp.models import CanvasSizePreset

        surface_id = surface.surface_id
        size = surface.size

        # Determine canvas container styles based on size configuration
        if size.preset == CanvasSizePreset.AUTO or (size.width is None and size.height is None):
            # Auto mode: fill viewport
            canvas_width = "100%"
            canvas_height = "100%"
            canvas_max_width = "none"
            canvas_max_height = "none"
            body_display = "block"
        else:
            # Fixed size: center in viewport with aspect ratio preservation
            canvas_width = f"{size.width}px"
            canvas_height = f"{size.height}px"
            canvas_max_width = "100vw"
            canvas_max_height = "100vh"
            body_display = "flex"

        # Note: The JavaScript in the template constructs the WebSocket URL
        # dynamically based on window.location for proper HTTPS/WSS handling
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Canvas - {surface_id}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        html, body {{
            width: 100%;
            height: 100%;
            background: #0d0d1a;
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            overflow: hidden;
            display: {body_display};
            justify-content: center;
            align-items: center;
        }}
        #canvas-container {{
            width: {canvas_width};
            height: {canvas_height};
            max-width: {canvas_max_width};
            max-height: {canvas_max_height};
            background: #1a1a2e;
            position: relative;
            overflow: hidden;
        }}
        #canvas-root {{
            width: 100%;
            height: 100%;
            padding: 32px;
            overflow: auto;
        }}
        #status {{
            position: absolute;
            top: 16px;
            right: 16px;
            padding: 8px 16px;
            border-radius: 4px;
            font-size: 12px;
            background: rgba(0, 0, 0, 0.5);
            z-index: 1000;
        }}
        #status.connected {{
            color: #4ade80;
        }}
        #status.disconnected {{
            color: #f87171;
        }}
        #status.connecting {{
            color: #fbbf24;
        }}
        #size-info {{
            position: absolute;
            bottom: 16px;
            left: 16px;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 10px;
            background: rgba(0, 0, 0, 0.5);
            color: #666;
            z-index: 1000;
        }}

        /* A2UI Component Styles */
        .a2ui-column {{
            display: flex;
            flex-direction: column;
        }}
        .a2ui-row {{
            display: flex;
            flex-direction: row;
        }}
        .a2ui-card {{
            background: #16213e;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        }}
        .a2ui-text {{
            line-height: 1.5;
        }}
        .a2ui-list {{
            list-style: none;
        }}
        .a2ui-list-item {{
            padding: 12px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .a2ui-list-item:last-child {{
            border-bottom: none;
        }}
        .a2ui-image {{
            max-width: 100%;
            border-radius: 8px;
        }}
        .a2ui-divider {{
            height: 1px;
            background: rgba(255, 255, 255, 0.2);
            margin: 16px 0;
        }}
    </style>
</head>
<body>
    <div id="canvas-container">
        <div id="status" class="connecting">Connecting...</div>
        <div id="size-info">{size.width or 'auto'}x{size.height or 'auto'} ({size.preset.value})</div>
        <div id="canvas-root"></div>
    </div>

    <script>
        // Canvas MCP Client-Side Renderer
        (function() {{
            const surfaceId = "{surface_id}";
            const wsUrl = window.location.protocol === 'https:'
                ? `wss://${{window.location.host}}/ws/{surface_id}`
                : `ws://${{window.location.host}}/ws/{surface_id}`;

            let ws = null;
            let components = {{}};
            let dataModel = {{}};
            let reconnectAttempts = 0;
            const maxReconnectAttempts = 10;
            const reconnectDelay = 2000;

            const statusEl = document.getElementById('status');
            const rootEl = document.getElementById('canvas-root');

            function connect() {{
                statusEl.className = 'connecting';
                statusEl.textContent = 'Connecting...';

                ws = new WebSocket(wsUrl);

                ws.onopen = () => {{
                    console.log('WebSocket connected');
                    statusEl.className = 'connected';
                    statusEl.textContent = 'Connected';
                    reconnectAttempts = 0;
                }};

                ws.onmessage = (event) => {{
                    try {{
                        const message = JSON.parse(event.data);
                        handleMessage(message);
                    }} catch (e) {{
                        console.error('Failed to parse message:', e);
                    }}
                }};

                ws.onclose = () => {{
                    console.log('WebSocket disconnected');
                    statusEl.className = 'disconnected';
                    statusEl.textContent = 'Disconnected';

                    // Attempt to reconnect
                    if (reconnectAttempts < maxReconnectAttempts) {{
                        reconnectAttempts++;
                        setTimeout(connect, reconnectDelay);
                    }}
                }};

                ws.onerror = (error) => {{
                    console.error('WebSocket error:', error);
                }};
            }}

            function handleMessage(message) {{
                console.log('Received:', message.type);

                switch (message.type) {{
                    case 'createSurface':
                        // Surface created, ready to receive components
                        components = {{}};
                        dataModel = {{}};
                        break;

                    case 'updateComponents':
                        // Update component definitions
                        if (message.components) {{
                            message.components.forEach(comp => {{
                                components[comp.id] = comp;
                            }});
                            render();
                        }}
                        break;

                    case 'updateDataModel':
                        // Update data at path
                        if (message.path && message.value !== undefined) {{
                            setValueAtPath(dataModel, message.path, message.value);
                            render();
                        }}
                        break;

                    case 'deleteSurface':
                        // Surface deleted
                        rootEl.innerHTML = '<div style="text-align:center;padding:48px;"><h2>Canvas Closed</h2></div>';
                        break;
                }}
            }}

            function setValueAtPath(obj, path, value) {{
                const parts = path.replace(/^\\//, '').split('/');
                let current = obj;

                for (let i = 0; i < parts.length - 1; i++) {{
                    if (!(parts[i] in current)) {{
                        current[parts[i]] = {{}};
                    }}
                    current = current[parts[i]];
                }}

                current[parts[parts.length - 1]] = value;
            }}

            function render() {{
                // Find root component
                const root = components['root'];
                if (!root) {{
                    return;
                }}

                rootEl.innerHTML = '';
                const el = renderComponent(root);
                if (el) {{
                    rootEl.appendChild(el);
                }}
            }}

            function renderComponent(comp) {{
                if (!comp) return null;

                const el = document.createElement('div');
                el.className = `a2ui-${{comp.component.toLowerCase()}}`;
                el.id = `comp-${{comp.id}}`;

                // Apply styles
                if (comp.style) {{
                    Object.entries(comp.style).forEach(([key, value]) => {{
                        // Convert camelCase to kebab-case
                        const cssKey = key.replace(/([A-Z])/g, '-$1').toLowerCase();
                        el.style[key] = typeof value === 'number' ? `${{value}}px` : value;
                    }});
                }}

                // Render based on component type
                switch (comp.component) {{
                    case 'Column':
                    case 'Row':
                    case 'Card':
                        if (comp.children) {{
                            comp.children.forEach(childId => {{
                                const childComp = components[childId];
                                if (childComp) {{
                                    const childEl = renderComponent(childComp);
                                    if (childEl) el.appendChild(childEl);
                                }}
                            }});
                        }}
                        break;

                    case 'Text':
                        el.textContent = resolveValue(comp.text || '');
                        break;

                    case 'Image':
                        const img = document.createElement('img');
                        img.src = resolveValue(comp.src || '');
                        img.alt = comp.alt || '';
                        img.className = 'a2ui-image';
                        el.appendChild(img);
                        break;

                    case 'List':
                        const ul = document.createElement('ul');
                        ul.className = 'a2ui-list';
                        if (comp.children) {{
                            comp.children.forEach(childId => {{
                                const li = document.createElement('li');
                                li.className = 'a2ui-list-item';
                                const childComp = components[childId];
                                if (childComp) {{
                                    const childEl = renderComponent(childComp);
                                    if (childEl) li.appendChild(childEl);
                                }}
                                ul.appendChild(li);
                            }});
                        }}
                        el.appendChild(ul);
                        break;

                    case 'Divider':
                        // Already styled via CSS
                        break;

                    default:
                        // Generic container
                        if (comp.children) {{
                            comp.children.forEach(childId => {{
                                const childComp = components[childId];
                                if (childComp) {{
                                    const childEl = renderComponent(childComp);
                                    if (childEl) el.appendChild(childEl);
                                }}
                            }});
                        }}
                        if (comp.text) {{
                            el.textContent = resolveValue(comp.text);
                        }}
                }}

                return el;
            }}

            function resolveValue(value) {{
                // Data binding: replace all {{/path/to/data}} occurrences in the string
                if (typeof value !== 'string') return value;
                return value.replace(/\\{{\\{{([^}}]+)\\}}\\}}/g, (match, path) => {{
                    const resolved = getValueAtPath(dataModel, path);
                    return resolved !== undefined ? resolved : match;
                }});
            }}

            function getValueAtPath(obj, path) {{
                const parts = path.replace(/^\\//, '').split('/');
                let current = obj;

                for (const part of parts) {{
                    if (current === undefined || current === null) return undefined;
                    current = current[part];
                }}

                return current;
            }}

            // Start connection
            connect();
        }})();
    </script>
</body>
</html>"""
