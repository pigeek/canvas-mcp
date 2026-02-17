"""Data models for Canvas MCP Server."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CanvasSizePreset(str, Enum):
    """Predefined canvas size presets."""
    TV_1080P = "tv_1080p"      # 1920x1080 (16:9) - Full HD TV
    TV_4K = "tv_4k"            # 3840x2160 (16:9) - 4K TV
    PHONE_PORTRAIT = "phone"   # 390x844 (9:19.5) - iPhone-like
    TABLET = "tablet"          # 1024x768 (4:3) - Tablet
    SQUARE = "square"          # 1080x1080 (1:1) - Square
    AUTO = "auto"              # Fit to viewport
    CUSTOM = "custom"          # Custom dimensions


class CanvasSize(BaseModel):
    """Canvas size configuration."""
    width: int | None = None   # Width in pixels (None = auto)
    height: int | None = None  # Height in pixels (None = auto)
    preset: CanvasSizePreset = CanvasSizePreset.AUTO
    scale_mode: str = "fit"    # fit, fill, stretch, none

    @classmethod
    def from_preset(cls, preset: CanvasSizePreset | str) -> "CanvasSize":
        """Create CanvasSize from a preset name."""
        if isinstance(preset, str):
            preset = CanvasSizePreset(preset)

        presets = {
            CanvasSizePreset.TV_1080P: (1920, 1080),
            CanvasSizePreset.TV_4K: (3840, 2160),
            CanvasSizePreset.PHONE_PORTRAIT: (390, 844),
            CanvasSizePreset.TABLET: (1024, 768),
            CanvasSizePreset.SQUARE: (1080, 1080),
            CanvasSizePreset.AUTO: (None, None),
            CanvasSizePreset.CUSTOM: (None, None),
        }
        width, height = presets.get(preset, (None, None))
        return cls(width=width, height=height, preset=preset)

    @property
    def aspect_ratio(self) -> float | None:
        """Return aspect ratio (width/height) or None if auto."""
        if self.width and self.height:
            return self.width / self.height
        return None

    @property
    def css_width(self) -> str:
        """Return CSS width value."""
        return f"{self.width}px" if self.width else "100%"

    @property
    def css_height(self) -> str:
        """Return CSS height value."""
        return f"{self.height}px" if self.height else "100%"


class A2UIMessageType(str, Enum):
    """A2UI message types (server to client)."""
    CREATE_SURFACE = "createSurface"
    UPDATE_COMPONENTS = "updateComponents"
    UPDATE_DATA_MODEL = "updateDataModel"
    DELETE_SURFACE = "deleteSurface"


class A2UIComponent(BaseModel):
    """A single A2UI component."""
    id: str
    component: str
    children: list[str] | None = None
    text: str | None = None
    style: dict[str, Any] | None = None
    # Allow additional properties for component-specific attributes
    model_config = {"extra": "allow"}


class A2UIMessage(BaseModel):
    """A2UI protocol message."""
    type: A2UIMessageType
    surface_id: str | None = Field(None, alias="surfaceId")
    catalog_id: str | None = Field(None, alias="catalogId")
    components: list[A2UIComponent] | None = None
    path: str | None = None  # JSON Pointer for updateDataModel
    value: Any | None = None  # Value for updateDataModel

    model_config = {"populate_by_name": True}


class SurfaceState(BaseModel):
    """Persisted state of a canvas surface."""
    surface_id: str
    name: str | None = None
    device_id: str | None = None  # Associated device (TV) for this surface
    size: CanvasSize = Field(default_factory=lambda: CanvasSize.from_preset(CanvasSizePreset.AUTO))
    components: list[dict[str, Any]] = Field(default_factory=list)
    data_model: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def to_create_message(self) -> dict[str, Any]:
        """Generate createSurface A2UI message."""
        return {
            "type": "createSurface",
            "surfaceId": self.surface_id,
            "catalogId": "standard",
        }

    def to_components_message(self) -> dict[str, Any]:
        """Generate updateComponents A2UI message."""
        return {
            "type": "updateComponents",
            "components": self.components,
        }


class Surface(BaseModel):
    """A canvas surface with connection info."""
    surface_id: str
    name: str | None = None
    device_id: str | None = None  # Associated device (TV) for this surface
    size: CanvasSize = Field(default_factory=lambda: CanvasSize.from_preset(CanvasSizePreset.AUTO))
    local_url: str  # URL to access the canvas locally (HTTP)
    ws_url: str  # WebSocket URL for real-time updates
    created_at: datetime = Field(default_factory=datetime.now)

    # Runtime state (not persisted)
    connected_clients: int = 0


class CanvasConfig(BaseModel):
    """Configuration for Canvas MCP Server."""
    host: str = "0.0.0.0"
    port: int = 8080
    persistence_enabled: bool = True
    persistence_path: str = "~/.canvas-mcp/surfaces/"

    # External host for URLs - if None, auto-detect network IP
    # This is the IP/hostname that external clients (like Chromecast) will use
    external_host: str | None = None

    # Default canvas size (TV 1080p for casting use case)
    default_size: CanvasSize = Field(
        default_factory=lambda: CanvasSize.from_preset(CanvasSizePreset.TV_1080P)
    )

    # Cast receiver configuration
    receiver_url: str | None = None
    cast_app_id: str | None = None
