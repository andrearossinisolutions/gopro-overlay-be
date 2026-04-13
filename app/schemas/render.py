from typing import Literal

from pydantic import BaseModel


class RenderConfig(BaseModel):
    theme: Literal["minimal-dark", "minimal-light"] = "minimal-dark"
    units: Literal["metric", "imperial"] = "metric"
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "bottom-left"

    # showSpeed = GS per compatibilità con il FE già esistente
    showSpeed: bool = True
    showIAS: bool = True

    showAltitude: bool = True
    showCoordinates: bool = False
    showMiniMap: bool = False
    showTimestamp: bool = True
    showHeading: bool = True

    fontScale: float = 1.0
    margin: int = 24