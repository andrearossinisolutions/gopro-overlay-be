from typing import Literal

from pydantic import BaseModel


class RenderConfig(BaseModel):
    theme: Literal["minimal-dark", "minimal-light"] = "minimal-dark"
    units: Literal["metric", "imperial"] = "metric"
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "bottom-left"
    showSpeed: bool = True
    showAltitude: bool = True
    showCoordinates: bool = False
    showMiniMap: bool = False
    showTimestamp: bool = True
    fontScale: float = 1.0
    margin: int = 24
