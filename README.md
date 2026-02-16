# Canvas MCP Server

MCP (Model Context Protocol) server that provides A2UI canvas rendering capabilities for AI agents.

## Overview

Canvas MCP Server enables AI agents to create rich, real-time visualizations using the [A2UI](https://github.com/google/A2UI) protocol. It provides:

- **MCP Tools** for creating and managing canvas surfaces
- **HTTP Server** serving the A2UI renderer
- **WebSocket Server** for real-time updates
- **State Persistence** for canvas recall

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Canvas MCP Server                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────────┐    ┌────────────────┐  │
│  │ MCP Server  │    │ Canvas Manager  │    │ Web Server     │  │
│  │             │───▶│                 │───▶│ (HTTP + WS)    │  │
│  │ - Tools     │    │ - Surfaces      │    │                │  │
│  │ - Resources │    │ - Persistence   │    │ /canvas/{id}   │  │
│  └─────────────┘    └─────────────────┘    │ /ws/{id}       │  │
│                                             └────────────────┘  │
│                                                     │           │
│                                                     ▼           │
│                                            ┌────────────────┐   │
│                                            │ Browser / TV   │   │
│                                            │ (A2UI Renderer)│   │
│                                            └────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Installation

```bash
pip install canvas-mcp
```

Or install from source:

```bash
git clone https://github.com/pigeek/canvas-mcp.git
cd canvas-mcp
pip install -e ".[dev]"
```

## Usage

### As MCP Server (stdio)

```bash
canvas-mcp --port 8080 --host 0.0.0.0
```

### With nanobot

Add to `~/.nanobot/config.json`:

```json
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
```

### CLI Options

```
Usage: canvas-mcp [OPTIONS]

Options:
  --host TEXT               Host to bind the web server to [default: 0.0.0.0]
  --port INTEGER            Port for the web server [default: 8080]
  --persistence-path TEXT   Path to store canvas state [default: ~/.canvas-mcp/surfaces/]
  --no-persistence          Disable state persistence
  --default-size TEXT       Default canvas size preset [default: tv_1080p]
                            Options: tv_1080p, tv_4k, phone, tablet, square, auto
  --receiver-url TEXT       URL of the external Chromecast receiver app
  --cast-app-id TEXT        Google Cast application ID
  -v, --verbose             Enable verbose logging
  --help                    Show this message and exit
```

## MCP Tools

### `canvas_create`

Create a new canvas surface.

**Parameters:**
- `name` (optional): Friendly name for the canvas
- `size` (optional): Canvas size preset or custom dimensions

**Size Presets:**
| Preset | Dimensions | Use Case |
|--------|------------|----------|
| `tv_1080p` | 1920×1080 | Full HD TV (default) |
| `tv_4k` | 3840×2160 | 4K TV |
| `phone` | 390×844 | Mobile portrait |
| `tablet` | 1024×768 | Tablet |
| `square` | 1080×1080 | Social media |
| `auto` | viewport | Fill browser window |

**Returns:**
```json
{
  "success": true,
  "surface_id": "abc123def456",
  "name": "my-canvas",
  "size": {"width": 1920, "height": 1080, "preset": "tv_1080p"},
  "local_url": "http://localhost:8080/canvas/abc123def456",
  "ws_url": "ws://localhost:8080/ws/abc123def456"
}
```

### `canvas_update`

Update components on a canvas using A2UI format.

**Parameters:**
- `surface_id`: The surface ID to update
- `components`: Array of A2UI component definitions

**Example:**
```json
{
  "surface_id": "abc123def456",
  "components": [
    {"id": "root", "component": "Column", "children": ["header", "content"]},
    {"id": "header", "component": "Text", "text": "Hello!", "style": {"fontSize": 48}},
    {"id": "content", "component": "Card", "children": ["message"]},
    {"id": "message", "component": "Text", "text": "Welcome to Canvas"}
  ]
}
```

### `canvas_data`

Update data model without re-rendering components.

**Parameters:**
- `surface_id`: The surface ID to update
- `path`: JSON Pointer path (e.g., `/user/name`)
- `value`: Value to set at the path

### `canvas_close`

Close and delete a canvas surface.

**Parameters:**
- `surface_id`: The surface ID to close

### `canvas_list`

List all canvas surfaces.

**Returns:**
```json
{
  "success": true,
  "count": 2,
  "surfaces": [
    {
      "surface_id": "abc123",
      "name": "dashboard",
      "local_url": "http://localhost:8080/canvas/abc123",
      "ws_url": "ws://localhost:8080/ws/abc123",
      "created_at": "2024-02-16T10:00:00",
      "connected_clients": 1
    }
  ]
}
```

### `canvas_get`

Get the full state of a canvas.

**Parameters:**
- `surface_id`: The surface ID to retrieve

**Returns:**
```json
{
  "success": true,
  "surface_id": "abc123",
  "name": "dashboard",
  "components": [...],
  "data_model": {...},
  "created_at": "2024-02-16T10:00:00",
  "updated_at": "2024-02-16T10:05:00"
}
```

## MCP Resources

- `canvas://{surface_id}/state` - Full canvas state (components + data model)
- `canvas://{surface_id}/url` - Canvas URLs for access

## A2UI Components

The built-in renderer supports these A2UI components:

| Component | Description |
|-----------|-------------|
| `Column` | Vertical flex container |
| `Row` | Horizontal flex container |
| `Card` | Styled card container |
| `Text` | Text display |
| `Image` | Image display |
| `List` | List container |
| `Divider` | Visual separator |

### Styling

Components support a `style` property with CSS-like properties:

```json
{
  "id": "header",
  "component": "Text",
  "text": "Dashboard",
  "style": {
    "fontSize": 48,
    "fontWeight": "bold",
    "color": "#ffffff",
    "padding": 24
  }
}
```

### Data Binding

Use `{{/path/to/data}}` syntax for data binding:

```json
{
  "id": "greeting",
  "component": "Text",
  "text": "Hello, {{/user/name}}!"
}
```

Then update via `canvas_data`:

```json
{
  "surface_id": "abc123",
  "path": "/user/name",
  "value": "Alice"
}
```

## Development

```bash
# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .

# Format
ruff format .

# Type check
mypy src/
```

## Integration with Chromecast

Canvas MCP Server is designed to work with Chromecast/Google TV devices for casting visualizations. The typical workflow:

1. Create a canvas surface with `canvas_create`
2. Update components with `canvas_update`
3. Open the canvas URL on a Chromecast device or cast-enabled browser

For advanced TV integration with device discovery and pairing, see the [AndroidTV MCP Server](https://github.com/pigeek/androidtvmcp).

## License

MIT
