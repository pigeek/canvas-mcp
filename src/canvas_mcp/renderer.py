"""Server-side HTML renderer for A2UI components.

This is the SINGLE source of truth for rendering A2UI components to HTML.
Used by both the web_server (browser preview) and canvas_manager (Chromecast/WebSocket).
"""

import re
from typing import Any


# CSS properties where numeric values should NOT get 'px' appended
UNITLESS_CSS_PROPERTIES = {
    "opacity", "zIndex", "z-index", "flex", "order",
    "flexGrow", "flex-grow", "flexShrink", "flex-shrink",
    "fontWeight", "font-weight", "lineHeight", "line-height",
}


def render_components_to_html(
    components: list[dict[str, Any]],
    data_model: dict[str, Any] | None = None,
) -> str:
    """Render A2UI components to an HTML string with inline styles.

    Args:
        components: List of A2UI component definitions (flat, with id references).
        data_model: Optional data model for resolving {{/path}} bindings.

    Returns:
        HTML string ready to be inserted as innerHTML.
    """
    if not components:
        return ""

    if data_model is None:
        data_model = {}

    # Build lookup map: id -> component
    comp_map: dict[str, dict[str, Any]] = {}
    for comp in components:
        comp_id = comp.get("id")
        if comp_id:
            comp_map[comp_id] = comp

    # Find root component
    root = comp_map.get("root")
    if not root:
        raise ValueError("No root component found for rendering")

    return _render_component(root, comp_map, data_model)


def _resolve_data_binding(value: Any, data_model: dict[str, Any]) -> Any:
    """Resolve {{/path/to/data}} bindings in a value.

    Handles both full-string bindings (returns the raw value, preserving type)
    and inline bindings within a larger string.
    """
    if not isinstance(value, str):
        return value

    # Full-string binding: {{/path}} -> return raw value (could be list, dict, etc.)
    full_match = re.fullmatch(r"\{\{(.+?)\}\}", value)
    if full_match:
        path = full_match.group(1).strip()
        resolved = _get_value_at_path(data_model, path)
        return resolved if resolved is not None else value

    # Inline bindings: "Hello {{/name}}, you have {{/count}} items"
    def replace_binding(match: re.Match) -> str:
        path = match.group(1).strip()
        resolved = _get_value_at_path(data_model, path)
        return str(resolved) if resolved is not None else match.group(0)

    return re.sub(r"\{\{(.+?)\}\}", replace_binding, value)


def _get_value_at_path(obj: dict[str, Any], path: str) -> Any:
    """Get a value from a nested dict using JSON Pointer-style path (/a/b/c)."""
    parts = path.strip("/").split("/")
    current: Any = obj
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _css_value(key: str, value: Any) -> str:
    """Convert a style value to a CSS value string."""
    if isinstance(value, (int, float)) and key not in UNITLESS_CSS_PROPERTIES:
        return f"{value}px"
    return str(value)


def _build_style_string(style: dict[str, Any] | None) -> str:
    """Build an inline CSS style string from a style dict."""
    if not style:
        return ""

    parts = []
    for key, value in style.items():
        if value is None:
            continue
        # Convert camelCase to kebab-case
        css_key = re.sub(r"([A-Z])", r"-\1", key).lower()
        css_val = _css_value(key, value)
        parts.append(f"{css_key}:{css_val}")

    return ";".join(parts)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_component(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
) -> str:
    """Render a single component and its children to HTML."""
    comp_type = comp.get("component", "")
    style = dict(comp.get("style", {}) or {})

    renderer = _COMPONENT_RENDERERS.get(comp_type)
    if renderer is None:
        raise ValueError(f"Unknown component type: '{comp_type}'")
    return renderer(comp, comp_map, data_model, style)


def _render_children(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
) -> str:
    """Render child components referenced by ID."""
    children_ids = comp.get("children", [])
    if not children_ids:
        return ""

    parts = []
    for child_id in children_ids:
        child_comp = comp_map.get(child_id)
        if child_comp:
            parts.append(_render_component(child_comp, comp_map, data_model))
    return "".join(parts)


# --- Component-specific renderers ---


def _render_column(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    style.setdefault("display", "flex")
    style.setdefault("flexDirection", "column")
    children_html = _render_children(comp, comp_map, data_model)
    return f'<div style="{_build_style_string(style)}">{children_html}</div>'


def _render_row(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    style.setdefault("display", "flex")
    style.setdefault("flexDirection", "row")
    children_html = _render_children(comp, comp_map, data_model)
    return f'<div style="{_build_style_string(style)}">{children_html}</div>'


def _render_grid(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    style.setdefault("display", "grid")
    columns = comp.get("columns")
    if columns is not None:
        if isinstance(columns, int):
            style.setdefault("gridTemplateColumns", f"repeat({columns}, 1fr)")
        else:
            style.setdefault("gridTemplateColumns", str(columns))
    rows = comp.get("rows")
    if rows is not None:
        if isinstance(rows, int):
            style.setdefault("gridTemplateRows", f"repeat({rows}, 1fr)")
        else:
            style.setdefault("gridTemplateRows", str(rows))
    children_html = _render_children(comp, comp_map, data_model)
    return f'<div style="{_build_style_string(style)}">{children_html}</div>'


def _render_box(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    children_html = _render_children(comp, comp_map, data_model)
    return f'<div style="{_build_style_string(style)}">{children_html}</div>'


def _render_card(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    style.setdefault("background", "rgba(255, 255, 255, 0.05)")
    style.setdefault("border", "1px solid rgba(255, 255, 255, 0.1)")
    style.setdefault("borderRadius", 16)
    style.setdefault("padding", 24)
    children_html = _render_children(comp, comp_map, data_model)
    return f'<div style="{_build_style_string(style)}">{children_html}</div>'


def _render_spacer(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    flex = comp.get("flex", 1)
    style.setdefault("flex", flex)
    return f'<div style="{_build_style_string(style)}"></div>'


def _render_divider(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    orientation = comp.get("orientation", "horizontal")
    thickness = comp.get("thickness")
    style.setdefault("background", "rgba(255, 255, 255, 0.2)")
    if orientation == "horizontal":
        style.setdefault("height", thickness if thickness else 1)
        style.setdefault("width", "100%")
    else:
        style.setdefault("width", thickness if thickness else 1)
        style.setdefault("height", "100%")
    return f'<div style="{_build_style_string(style)}"></div>'


def _render_text(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    text = str(_resolve_data_binding(comp.get("text", ""), data_model))
    if "\n" in text:
        style.setdefault("whiteSpace", "pre-line")
    style.setdefault("color", "#ffffff")
    style.setdefault("lineHeight", 1.5)
    escaped = _escape_html(text)
    return f'<div style="{_build_style_string(style)}">{escaped}</div>'


def _render_image(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    src = str(_resolve_data_binding(comp.get("src", ""), data_model))
    alt = _escape_html(comp.get("alt", ""))
    img_style: dict[str, Any] = {"maxWidth": "100%", "borderRadius": 8}
    if "width" in style:
        img_style["width"] = style.pop("width")
    if "height" in style:
        img_style["height"] = style.pop("height")
    img_tag = f'<img src="{_escape_html(src)}" alt="{alt}" style="{_build_style_string(img_style)}">'
    return f'<div style="{_build_style_string(style)}">{img_tag}</div>'


def _render_icon(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    icon = comp.get("icon") or comp.get("emoji") or ""
    size = comp.get("size")
    style.setdefault("display", "flex")
    style.setdefault("alignItems", "center")
    style.setdefault("justifyContent", "center")
    if size:
        style.setdefault("fontSize", size)
    return f'<div style="{_build_style_string(style)}">{_escape_html(str(icon))}</div>'


def _render_avatar(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    size = comp.get("size", 48)
    style.setdefault("display", "flex")
    style.setdefault("alignItems", "center")
    style.setdefault("justifyContent", "center")
    style.setdefault("borderRadius", "50%")
    style.setdefault("background", "linear-gradient(135deg, #e94560, #ff6b6b)")
    style.setdefault("color", "white")
    style.setdefault("fontWeight", 600)
    style.setdefault("overflow", "hidden")
    style.setdefault("width", size)
    style.setdefault("height", size)

    src = comp.get("src")
    if src:
        src = str(_resolve_data_binding(src, data_model))
        alt = _escape_html(comp.get("alt", ""))
        inner = f'<img src="{_escape_html(src)}" alt="{alt}" style="width:100%;height:100%;object-fit:cover">'
    elif comp.get("initials"):
        inner = _escape_html(comp["initials"][:2].upper())
        style.setdefault("fontSize", int(size * 0.4) if isinstance(size, (int, float)) else size)
    elif comp.get("name"):
        parts = comp["name"].split()
        initials = "".join(p[0] for p in parts if p)[:2].upper()
        inner = _escape_html(initials)
        style.setdefault("fontSize", int(size * 0.4) if isinstance(size, (int, float)) else size)
    else:
        inner = ""

    return f'<div style="{_build_style_string(style)}">{inner}</div>'


def _render_list(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    # List can have children (component-based) or items (data-based)
    children_ids = comp.get("children", [])
    if children_ids:
        # Component-based list
        li_style = "padding:12px 0;border-bottom:1px solid rgba(255,255,255,0.1)"
        items_html = []
        for child_id in children_ids:
            child_comp = comp_map.get(child_id)
            if child_comp:
                child_html = _render_component(child_comp, comp_map, data_model)
                items_html.append(f'<li style="{li_style}">{child_html}</li>')
        # Remove border from last item
        if items_html:
            items_html[-1] = items_html[-1].replace(li_style, li_style.replace("border-bottom:1px solid rgba(255,255,255,0.1)", "border-bottom:none"))
        ul_html = f'<ul style="list-style:none;padding:0;margin:0">{"".join(items_html)}</ul>'
    else:
        # Data-based list
        items = _resolve_data_binding(comp.get("items", []), data_model)
        if not isinstance(items, list):
            items = []
        li_style = "padding:12px 0;border-bottom:1px solid rgba(255,255,255,0.1)"
        items_html = []
        for item in items:
            text = str(item) if not isinstance(item, dict) else str(item)
            items_html.append(f'<li style="{li_style}">{_escape_html(text)}</li>')
        if items_html:
            items_html[-1] = items_html[-1].replace(li_style, li_style.replace("border-bottom:1px solid rgba(255,255,255,0.1)", "border-bottom:none"))
        ul_html = f'<ul style="list-style:none;padding:0;margin:0">{"".join(items_html)}</ul>'

    return f'<div style="{_build_style_string(style)}">{ul_html}</div>'


def _render_table(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    table_style = "width:100%;border-collapse:collapse"
    th_style = "padding:12px 16px;text-align:left;border-bottom:1px solid rgba(255,255,255,0.1);font-weight:600;color:#a0a0c0;background:rgba(255,255,255,0.05)"
    td_style = "padding:12px 16px;text-align:left;border-bottom:1px solid rgba(255,255,255,0.1)"

    # Header
    headers = comp.get("headers", [])
    thead = ""
    if headers:
        ths = "".join(f'<th style="{th_style}">{_escape_html(str(h))}</th>' for h in headers)
        thead = f"<thead><tr>{ths}</tr></thead>"

    # Data rows
    data = _resolve_data_binding(comp.get("data"), data_model) or comp.get("rows", [])
    if not isinstance(data, list):
        data = []
    rows_html = []
    for row in data:
        cells = row if isinstance(row, list) else (list(row.values()) if isinstance(row, dict) else [row])
        tds = "".join(f'<td style="{td_style}">{_escape_html(str(c))}</td>' for c in cells)
        rows_html.append(f"<tr>{tds}</tr>")
    tbody = f"<tbody>{''.join(rows_html)}</tbody>" if rows_html else ""

    return f'<div style="{_build_style_string(style)}"><table style="{table_style}">{thead}{tbody}</table></div>'


def _render_progress(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    value = _resolve_data_binding(comp.get("value", 0), data_model)
    try:
        progress = max(0, min(100, float(value)))
    except (TypeError, ValueError):
        progress = 0
    color = comp.get("color", "linear-gradient(90deg, #e94560, #ff6b6b)")

    style.setdefault("background", "rgba(255, 255, 255, 0.1)")
    style.setdefault("borderRadius", 8)
    style.setdefault("overflow", "hidden")
    style.setdefault("height", 8)

    fill_bg = color if color.startswith("linear") else color
    fill_html = f'<div style="height:100%;width:{progress}%;background:{fill_bg};transition:width 0.3s ease"></div>'
    return f'<div style="{_build_style_string(style)}">{fill_html}</div>'


def _render_badge(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    text = str(_resolve_data_binding(comp.get("text") or comp.get("value", ""), data_model))
    color = comp.get("color", "#e94560")

    style.setdefault("display", "inline-flex")
    style.setdefault("alignItems", "center")
    style.setdefault("justifyContent", "center")
    style.setdefault("padding", "4px 12px")
    style.setdefault("borderRadius", 12)
    style.setdefault("background", color)
    style.setdefault("color", "white")
    style.setdefault("fontSize", 14)
    style.setdefault("fontWeight", 600)

    return f'<div style="{_build_style_string(style)}">{_escape_html(text)}</div>'


def _render_spinner(
    comp: dict[str, Any],
    comp_map: dict[str, dict[str, Any]],
    data_model: dict[str, Any],
    style: dict[str, Any],
) -> str:
    size = comp.get("size", 32)
    color = comp.get("color", "#e94560")

    style.setdefault("display", "inline-block")
    style.setdefault("width", size)
    style.setdefault("height", size)
    style.setdefault("border", "3px solid rgba(255, 255, 255, 0.2)")
    style.setdefault("borderTopColor", color)
    style.setdefault("borderRadius", "50%")
    # Animation needs a keyframes definition — inject it via a wrapper
    anim_id = f"spin-{id(comp)}"
    keyframes = f"@keyframes {anim_id}{{to{{transform:rotate(360deg)}}}}"
    style["animation"] = f"{anim_id} 1s linear infinite"

    return f'<style>{keyframes}</style><div style="{_build_style_string(style)}"></div>'


# Component type -> renderer function mapping
_COMPONENT_RENDERERS = {
    "Column": _render_column,
    "Row": _render_row,
    "Grid": _render_grid,
    "Box": _render_box,
    "Card": _render_card,
    "Spacer": _render_spacer,
    "Divider": _render_divider,
    "Text": _render_text,
    "Image": _render_image,
    "Icon": _render_icon,
    "Avatar": _render_avatar,
    "List": _render_list,
    "Table": _render_table,
    "Progress": _render_progress,
    "ProgressBar": _render_progress,
    "Badge": _render_badge,
    "Spinner": _render_spinner,
}
