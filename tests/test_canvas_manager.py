"""Tests for CanvasManager."""

import pytest

from canvas_mcp.canvas_manager import CanvasManager
from canvas_mcp.models import CanvasConfig


@pytest.fixture
def config() -> CanvasConfig:
    """Create test configuration."""
    return CanvasConfig(
        host="localhost",
        port=8080,
        persistence_enabled=False,  # Disable persistence for tests
    )


@pytest.fixture
async def manager(config: CanvasConfig) -> CanvasManager:
    """Create and initialize a CanvasManager."""
    mgr = CanvasManager(config)
    await mgr.initialize()
    return mgr


class TestCanvasManager:
    """Tests for CanvasManager."""

    async def test_create_surface(self, manager: CanvasManager) -> None:
        """Test creating a new surface."""
        surface = await manager.create_surface(name="test-canvas")

        assert surface.surface_id is not None
        assert surface.name == "test-canvas"
        assert "localhost:8080" in surface.local_url
        assert "localhost:8080" in surface.ws_url

    async def test_create_surface_without_name(self, manager: CanvasManager) -> None:
        """Test creating a surface without a name."""
        surface = await manager.create_surface()

        assert surface.surface_id is not None
        assert surface.name is None

    async def test_list_surfaces(self, manager: CanvasManager) -> None:
        """Test listing surfaces."""
        # Initially empty
        surfaces = manager.list_surfaces()
        assert len(surfaces) == 0

        # Create some surfaces
        await manager.create_surface(name="canvas-1")
        await manager.create_surface(name="canvas-2")

        surfaces = manager.list_surfaces()
        assert len(surfaces) == 2

    async def test_update_components(self, manager: CanvasManager) -> None:
        """Test updating components on a surface."""
        surface = await manager.create_surface()

        components = [
            {"id": "root", "component": "Column", "children": ["text1"]},
            {"id": "text1", "component": "Text", "text": "Hello, World!"},
        ]

        result = await manager.update_components(surface.surface_id, components)
        assert result is True

        # Verify state
        state = manager.get_surface(surface.surface_id)
        assert state is not None
        assert len(state.components) == 2
        assert state.components[0]["id"] == "root"

    async def test_update_data_model(self, manager: CanvasManager) -> None:
        """Test updating data model."""
        surface = await manager.create_surface()

        await manager.update_data_model(surface.surface_id, "/user/name", "Alice")
        await manager.update_data_model(surface.surface_id, "/user/age", 30)

        state = manager.get_surface(surface.surface_id)
        assert state is not None
        assert state.data_model["user"]["name"] == "Alice"
        assert state.data_model["user"]["age"] == 30

    async def test_close_surface(self, manager: CanvasManager) -> None:
        """Test closing a surface."""
        surface = await manager.create_surface()
        surface_id = surface.surface_id

        # Verify it exists
        assert manager.get_surface(surface_id) is not None

        # Close it
        result = await manager.close_surface(surface_id)
        assert result is True

        # Verify it's gone
        assert manager.get_surface(surface_id) is None

    async def test_close_nonexistent_surface(self, manager: CanvasManager) -> None:
        """Test closing a surface that doesn't exist."""
        with pytest.raises(ValueError, match="Surface not found"):
            await manager.close_surface("nonexistent")

    async def test_update_nonexistent_surface(self, manager: CanvasManager) -> None:
        """Test updating a surface that doesn't exist."""
        with pytest.raises(ValueError, match="Surface not found"):
            await manager.update_components("nonexistent", [])

    async def test_get_surface_info(self, manager: CanvasManager) -> None:
        """Test getting surface info."""
        surface = await manager.create_surface(name="info-test")

        info = manager.get_surface_info(surface.surface_id)
        assert info is not None
        assert info.surface_id == surface.surface_id
        assert info.name == "info-test"
        assert info.connected_clients == 0

    async def test_get_nonexistent_surface_info(self, manager: CanvasManager) -> None:
        """Test getting info for a nonexistent surface."""
        info = manager.get_surface_info("nonexistent")
        assert info is None
