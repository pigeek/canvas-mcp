"""Canvas Manager - Surface lifecycle management."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles
from loguru import logger

from canvas_mcp.models import CanvasConfig, CanvasSize, CanvasSizePreset, Surface, SurfaceState


class CanvasManager:
    """
    Manages canvas surfaces and their state.

    Responsibilities:
    - Create/delete surfaces
    - Track surface state (components, data model)
    - Persist state to disk
    - Notify connected WebSocket clients of updates
    """

    def __init__(self, config: CanvasConfig):
        self.config = config
        self._surfaces: dict[str, SurfaceState] = {}
        self._ws_clients: dict[str, set[Any]] = {}  # surface_id -> set of websocket connections
        self._persistence_path = Path(config.persistence_path).expanduser()

        if config.persistence_enabled:
            self._persistence_path.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """Initialize manager, load persisted surfaces."""
        if self.config.persistence_enabled:
            await self._load_persisted_surfaces()
        logger.info(f"Canvas Manager initialized with {len(self._surfaces)} surfaces")

    async def _load_persisted_surfaces(self) -> None:
        """Load surfaces from persistence directory."""
        if not self._persistence_path.exists():
            return

        for file_path in self._persistence_path.glob("*.json"):
            try:
                async with aiofiles.open(file_path, "r") as f:
                    data = json.loads(await f.read())
                    state = SurfaceState(**data)
                    self._surfaces[state.surface_id] = state
                    logger.debug(f"Loaded surface: {state.surface_id}")
            except Exception as e:
                logger.error(f"Failed to load surface from {file_path}: {e}")

    async def _persist_surface(self, surface_id: str) -> None:
        """Persist a surface to disk."""
        if not self.config.persistence_enabled:
            return

        state = self._surfaces.get(surface_id)
        if not state:
            return

        file_path = self._persistence_path / f"{surface_id}.json"
        try:
            async with aiofiles.open(file_path, "w") as f:
                await f.write(state.model_dump_json(indent=2))
            logger.debug(f"Persisted surface: {surface_id}")
        except Exception as e:
            logger.error(f"Failed to persist surface {surface_id}: {e}")

    async def _delete_persisted_surface(self, surface_id: str) -> None:
        """Delete a persisted surface file."""
        if not self.config.persistence_enabled:
            return

        file_path = self._persistence_path / f"{surface_id}.json"
        try:
            if file_path.exists():
                file_path.unlink()
                logger.debug(f"Deleted persisted surface: {surface_id}")
        except Exception as e:
            logger.error(f"Failed to delete persisted surface {surface_id}: {e}")

    def _generate_surface_id(self) -> str:
        """Generate a unique surface ID."""
        return uuid.uuid4().hex[:12]

    def _get_surface_urls(self, surface_id: str) -> tuple[str, str]:
        """Get the local HTTP and WebSocket URLs for a surface."""
        # Use 0.0.0.0 -> localhost for local access, but keep original for network
        display_host = "localhost" if self.config.host == "0.0.0.0" else self.config.host
        display_base = f"{display_host}:{self.config.port}"

        local_url = f"http://{display_base}/canvas/{surface_id}"
        ws_url = f"ws://{display_base}/ws/{surface_id}"
        return local_url, ws_url

    async def create_surface(
        self,
        name: str | None = None,
        size: CanvasSize | CanvasSizePreset | str | None = None,
    ) -> Surface:
        """
        Create a new canvas surface.

        Args:
            name: Optional friendly name for the surface
            size: Canvas size - can be a CanvasSize object, a preset name (e.g., "tv_1080p"),
                  or None to use the default from config

        Returns:
            Surface object with URLs for access
        """
        surface_id = self._generate_surface_id()
        local_url, ws_url = self._get_surface_urls(surface_id)

        # Resolve size
        if size is None:
            canvas_size = self.config.default_size
        elif isinstance(size, CanvasSize):
            canvas_size = size
        elif isinstance(size, (CanvasSizePreset, str)):
            canvas_size = CanvasSize.from_preset(size)
        else:
            canvas_size = self.config.default_size

        state = SurfaceState(
            surface_id=surface_id,
            name=name,
            size=canvas_size,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self._surfaces[surface_id] = state
        self._ws_clients[surface_id] = set()

        await self._persist_surface(surface_id)

        logger.info(f"Created surface: {surface_id} (name={name}, size={canvas_size.preset.value})")
        return Surface(
            surface_id=surface_id,
            name=name,
            size=canvas_size,
            local_url=local_url,
            ws_url=ws_url,
        )

    async def update_components(
        self, surface_id: str, components: list[dict[str, Any]]
    ) -> bool:
        """
        Update components on a surface.

        Args:
            surface_id: Target surface ID
            components: List of A2UI component definitions

        Returns:
            True if successful
        """
        state = self._surfaces.get(surface_id)
        if not state:
            raise ValueError(f"Surface not found: {surface_id}")

        state.components = components
        state.updated_at = datetime.now()

        await self._persist_surface(surface_id)

        # Notify connected clients
        message = {
            "type": "updateComponents",
            "components": components,
        }
        await self._broadcast_to_surface(surface_id, message)

        logger.debug(f"Updated components on surface {surface_id}: {len(components)} components")
        return True

    async def update_data_model(
        self, surface_id: str, path: str, value: Any
    ) -> bool:
        """
        Update data model at a specific path.

        Args:
            surface_id: Target surface ID
            path: JSON Pointer path (e.g., "/user/name")
            value: Value to set at path

        Returns:
            True if successful
        """
        state = self._surfaces.get(surface_id)
        if not state:
            raise ValueError(f"Surface not found: {surface_id}")

        # Update data model using JSON Pointer path
        self._set_json_pointer(state.data_model, path, value)
        state.updated_at = datetime.now()

        await self._persist_surface(surface_id)

        # Notify connected clients
        message = {
            "type": "updateDataModel",
            "path": path,
            "value": value,
        }
        await self._broadcast_to_surface(surface_id, message)

        logger.debug(f"Updated data model on surface {surface_id}: {path}")
        return True

    def _set_json_pointer(self, obj: dict, path: str, value: Any) -> None:
        """Set a value in a dict using JSON Pointer syntax."""
        if not path or path == "/":
            # Root path - replace entire object (not supported in this simple impl)
            raise ValueError("Cannot replace root object")

        parts = path.strip("/").split("/")
        current = obj

        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        current[parts[-1]] = value

    async def close_surface(self, surface_id: str) -> bool:
        """
        Close and delete a surface.

        Args:
            surface_id: Surface to close

        Returns:
            True if successful
        """
        if surface_id not in self._surfaces:
            raise ValueError(f"Surface not found: {surface_id}")

        # Notify clients of deletion
        message = {"type": "deleteSurface", "surfaceId": surface_id}
        await self._broadcast_to_surface(surface_id, message)

        # Close all WebSocket connections
        clients = self._ws_clients.pop(surface_id, set())
        for client in clients:
            try:
                await client.close()
            except Exception:
                pass

        # Remove from memory and persistence
        del self._surfaces[surface_id]
        await self._delete_persisted_surface(surface_id)

        logger.info(f"Closed surface: {surface_id}")
        return True

    def list_surfaces(self) -> list[Surface]:
        """List all surfaces."""
        surfaces = []
        for state in self._surfaces.values():
            local_url, ws_url = self._get_surface_urls(state.surface_id)
            surfaces.append(Surface(
                surface_id=state.surface_id,
                name=state.name,
                size=state.size,
                local_url=local_url,
                ws_url=ws_url,
                created_at=state.created_at,
                connected_clients=len(self._ws_clients.get(state.surface_id, set())),
            ))
        return surfaces

    def get_surface(self, surface_id: str) -> SurfaceState | None:
        """Get a surface's full state."""
        return self._surfaces.get(surface_id)

    def get_surface_info(self, surface_id: str) -> Surface | None:
        """Get surface info (without full state)."""
        state = self._surfaces.get(surface_id)
        if not state:
            return None

        local_url, ws_url = self._get_surface_urls(surface_id)
        return Surface(
            surface_id=state.surface_id,
            name=state.name,
            size=state.size,
            local_url=local_url,
            ws_url=ws_url,
            created_at=state.created_at,
            connected_clients=len(self._ws_clients.get(surface_id, set())),
        )

    # WebSocket client management

    def register_ws_client(self, surface_id: str, ws: Any) -> bool:
        """Register a WebSocket client for a surface."""
        if surface_id not in self._surfaces:
            return False

        if surface_id not in self._ws_clients:
            self._ws_clients[surface_id] = set()

        self._ws_clients[surface_id].add(ws)
        logger.debug(f"WebSocket client connected to surface {surface_id}")
        return True

    def unregister_ws_client(self, surface_id: str, ws: Any) -> None:
        """Unregister a WebSocket client."""
        if surface_id in self._ws_clients:
            self._ws_clients[surface_id].discard(ws)
            logger.debug(f"WebSocket client disconnected from surface {surface_id}")

    async def _broadcast_to_surface(self, surface_id: str, message: dict) -> None:
        """Broadcast a message to all WebSocket clients of a surface."""
        clients = self._ws_clients.get(surface_id, set())
        if not clients:
            return

        message_json = json.dumps(message)
        disconnected = []

        for client in clients:
            try:
                await client.send_str(message_json)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket client: {e}")
                disconnected.append(client)

        # Clean up disconnected clients
        for client in disconnected:
            self._ws_clients[surface_id].discard(client)

    async def send_initial_state(self, surface_id: str, ws: Any) -> None:
        """Send initial state to a newly connected WebSocket client."""
        state = self._surfaces.get(surface_id)
        if not state:
            return

        # Send createSurface message
        await ws.send_str(json.dumps(state.to_create_message()))

        # Send current components if any
        if state.components:
            await ws.send_str(json.dumps(state.to_components_message()))

        # Send data model updates
        if state.data_model:
            for path, value in self._flatten_data_model(state.data_model):
                await ws.send_str(json.dumps({
                    "type": "updateDataModel",
                    "path": path,
                    "value": value,
                }))

    def _flatten_data_model(
        self, obj: dict, prefix: str = ""
    ) -> list[tuple[str, Any]]:
        """Flatten a nested dict into JSON Pointer paths and values."""
        result = []
        for key, value in obj.items():
            path = f"{prefix}/{key}"
            if isinstance(value, dict):
                result.extend(self._flatten_data_model(value, path))
            else:
                result.append((path, value))
        return result
