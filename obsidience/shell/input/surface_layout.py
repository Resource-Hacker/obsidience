"""Validated geometry and edge routing for physical Obsidience Surfaces."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path


SURFACE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
EDGES = ("left", "right", "top", "bottom")
OPPOSITE_EDGE = {
    "left": "right",
    "right": "left",
    "top": "bottom",
    "bottom": "top",
}


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def _positive_int(value: object, field: str) -> int:
    number = _number(value, field)
    if number <= 0 or not number.is_integer():
        raise ValueError(f"{field} must be a positive integer")
    return int(number)


def _nonnegative_int(value: object, field: str) -> int:
    number = _number(value, field)
    if number < 0 or not number.is_integer():
        raise ValueError(f"{field} must be a nonnegative integer")
    return int(number)


@dataclass(frozen=True)
class MapRect:
    x: float
    y: float
    width: float
    height: float

    @classmethod
    def from_dict(cls, value: object, field: str) -> MapRect:
        if not isinstance(value, dict):
            raise ValueError(f"{field} must be an object")
        rect = cls(
            x=_number(value.get("x"), f"{field}.x"),
            y=_number(value.get("y"), f"{field}.y"),
            width=_number(value.get("width"), f"{field}.width"),
            height=_number(value.get("height"), f"{field}.height"),
        )
        if rect.width <= 0 or rect.height <= 0:
            raise ValueError(f"{field} width and height must be positive")
        return rect


@dataclass(frozen=True)
class Surface:
    id: str
    label: str
    backend: str
    display: str
    output: str
    x_screen: int | None
    pixel_width: int
    pixel_height: int
    logical_width: int
    logical_height: int
    device_scale: float
    map_rect: MapRect

    @classmethod
    def from_dict(cls, value: object, index: int) -> Surface:
        if not isinstance(value, dict):
            raise ValueError(f"surfaces[{index}] must be an object")
        surface_id = value.get("id")
        if not isinstance(surface_id, str) or not SURFACE_ID.fullmatch(surface_id):
            raise ValueError(f"surfaces[{index}].id is invalid")
        x_screen_value = value.get("x_screen")
        if x_screen_value is not None:
            x_screen_value = _nonnegative_int(x_screen_value, f"surfaces[{index}].x_screen")
        scale = _number(value.get("device_scale"), f"surfaces[{index}].device_scale")
        if scale <= 0:
            raise ValueError(f"surfaces[{index}].device_scale must be positive")
        return cls(
            id=surface_id,
            label=str(value.get("label") or surface_id),
            backend=str(value.get("backend") or ""),
            display=str(value.get("display") or ""),
            output=str(value.get("output") or ""),
            x_screen=x_screen_value,
            pixel_width=_positive_int(value.get("pixel_width"), f"surfaces[{index}].pixel_width"),
            pixel_height=_positive_int(value.get("pixel_height"), f"surfaces[{index}].pixel_height"),
            logical_width=_positive_int(value.get("logical_width"), f"surfaces[{index}].logical_width"),
            logical_height=_positive_int(value.get("logical_height"), f"surfaces[{index}].logical_height"),
            device_scale=scale,
            map_rect=MapRect.from_dict(value.get("map_rect"), f"surfaces[{index}].map_rect"),
        )


@dataclass(frozen=True)
class Route:
    destination_id: str
    destination_edge: str
    x: int
    y: int


class SurfaceLayout:
    """One validated layout whose touching rectangles define every edge route."""

    schema = "obsidience.surface-layout.v1"

    def __init__(self, revision: int, surfaces: tuple[Surface, ...]):
        self.revision = revision
        self.surfaces = surfaces
        self._by_id = {surface.id: surface for surface in surfaces}

    @classmethod
    def from_dict(cls, value: object) -> SurfaceLayout:
        if not isinstance(value, dict) or value.get("schema") != cls.schema:
            raise ValueError(f"surface layout schema must be {cls.schema}")
        revision = _nonnegative_int(value.get("revision", 0), "revision")
        raw_surfaces = value.get("surfaces")
        if not isinstance(raw_surfaces, list) or not raw_surfaces:
            raise ValueError("surfaces must be a non-empty list")
        surfaces = tuple(Surface.from_dict(item, index) for index, item in enumerate(raw_surfaces))
        ids = [surface.id for surface in surfaces]
        if len(set(ids)) != len(ids):
            raise ValueError("surface ids must be unique")
        return cls(revision=revision, surfaces=surfaces)

    @classmethod
    def from_file(cls, path: Path) -> SurfaceLayout:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def surface(self, surface_id: str) -> Surface:
        try:
            return self._by_id[surface_id]
        except KeyError as exc:
            raise ValueError(f"unknown surface: {surface_id}") from exc

    def route(
        self,
        source_id: str,
        edge: str,
        local_x: float,
        local_y: float,
        *,
        inset: int = 12,
    ) -> Route | None:
        if edge not in EDGES:
            raise ValueError(f"unknown edge: {edge}")
        source = self.surface(source_id)
        source_rect = source.map_rect
        horizontal = edge in ("top", "bottom")
        if horizontal:
            local_axis = max(0.0, min(float(local_x), source.pixel_width - 1))
            source_span = max(1, source.pixel_width)
            global_axis = source_rect.x + (local_axis / source_span) * source_rect.width
            boundary = source_rect.y if edge == "top" else source_rect.y + source_rect.height
        else:
            local_axis = max(0.0, min(float(local_y), source.pixel_height - 1))
            source_span = max(1, source.pixel_height)
            global_axis = source_rect.y + (local_axis / source_span) * source_rect.height
            boundary = source_rect.x if edge == "left" else source_rect.x + source_rect.width

        destination_edge = OPPOSITE_EDGE[edge]
        for destination in self.surfaces:
            if destination.id == source_id:
                continue
            rect = destination.map_rect
            destination_boundary = (
                rect.y + rect.height
                if destination_edge == "bottom"
                else rect.y
                if destination_edge == "top"
                else rect.x + rect.width
                if destination_edge == "right"
                else rect.x
            )
            if not math.isclose(boundary, destination_boundary, abs_tol=0.001):
                continue
            destination_start = rect.x if horizontal else rect.y
            destination_length = rect.width if horizontal else rect.height
            source_start = source_rect.x if horizontal else source_rect.y
            source_length = source_rect.width if horizontal else source_rect.height
            overlap_start = max(source_start, destination_start)
            overlap_end = min(source_start + source_length, destination_start + destination_length)
            if overlap_end <= overlap_start or not overlap_start <= global_axis < overlap_end:
                continue

            ratio = max(0.0, min(1.0, (global_axis - destination_start) / destination_length))
            mapped_x = round(ratio * (destination.pixel_width - 1)) if horizontal else 0
            mapped_y = round(ratio * (destination.pixel_height - 1)) if not horizontal else 0
            bounded_inset_x = min(inset, max(0, destination.pixel_width - 1))
            bounded_inset_y = min(inset, max(0, destination.pixel_height - 1))
            if destination_edge == "left":
                mapped_x = bounded_inset_x
            elif destination_edge == "right":
                mapped_x = destination.pixel_width - 1 - bounded_inset_x
            elif destination_edge == "top":
                mapped_y = bounded_inset_y
            else:
                mapped_y = destination.pixel_height - 1 - bounded_inset_y
            return Route(
                destination_id=destination.id,
                destination_edge=destination_edge,
                x=mapped_x,
                y=mapped_y,
            )
        return None
