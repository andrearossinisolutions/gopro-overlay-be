from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, List, Dict

import requests


class WeatherServiceError(RuntimeError):
    pass


OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"


def _parse_iso(dt: str) -> datetime:
    return datetime.fromisoformat(dt.replace("Z", "+00:00"))


def fetch_weather_timeseries(
    lat: float,
    lon: float,
    start: datetime,
    end: datetime,
) -> List[Dict[str, Any]]:
    """
    Recupera vento storico orario da Open-Meteo
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "hourly": "wind_speed_10m,wind_direction_10m",
        "timezone": "UTC",
    }

    resp = requests.get(OPEN_METEO_URL, params=params, timeout=10)

    if resp.status_code != 200:
        raise WeatherServiceError(f"Errore Open-Meteo: {resp.text}")

    data = resp.json()

    hourly = data.get("hourly")
    if not hourly:
        raise WeatherServiceError("Nessun dato meteo disponibile")

    times = hourly["time"]
    speeds = hourly["wind_speed_10m"]
    directions = hourly["wind_direction_10m"]

    result = []

    for i in range(len(times)):
        result.append({
            "time": _parse_iso(times[i]),
            "wind_speed_kmh": float(speeds[i]),
            "wind_dir_deg": float(directions[i]),
        })

    return result


def _interpolate(a: float, b: float, ratio: float) -> float:
    return a + (b - a) * ratio


def interpolate_weather(
    weather_series: List[Dict[str, Any]],
    target_time: datetime,
) -> Dict[str, float]:
    """
    Interpola vento su timestamp preciso
    """
    if not weather_series:
        raise WeatherServiceError("Serie meteo vuota")

    for i in range(len(weather_series) - 1):
        t0 = weather_series[i]["time"]
        t1 = weather_series[i + 1]["time"]

        if t0 <= target_time <= t1:
            total = (t1 - t0).total_seconds()
            if total == 0:
                return weather_series[i]

            ratio = (target_time - t0).total_seconds() / total

            speed = _interpolate(
                weather_series[i]["wind_speed_kmh"],
                weather_series[i + 1]["wind_speed_kmh"],
                ratio,
            )

            direction = _interpolate(
                weather_series[i]["wind_dir_deg"],
                weather_series[i + 1]["wind_dir_deg"],
                ratio,
            )

            return {
                "wind_speed_kmh": speed,
                "wind_dir_deg": direction,
            }

    return weather_series[-1]


def compute_headwind(
    wind_speed_kmh: float,
    wind_dir_deg: float,
    heading_deg: float,
) -> float:
    """
    Calcola componente vento lungo direzione volo
    + = headwind
    - = tailwind
    """
    angle = math.radians(wind_dir_deg - heading_deg)
    return wind_speed_kmh * math.cos(angle)


def estimate_ias(
    ground_speed_kmh: float,
    altitude_m: float,
    headwind_kmh: float,
) -> float:
    """
    GS -> TAS -> IAS (stimata)
    """
    import math

    tas = ground_speed_kmh - headwind_kmh

    # densità aria semplificata
    rho_ratio = (1 - 0.0000225577 * altitude_m) ** 4.256

    ias = tas * math.sqrt(rho_ratio)

    return max(0.0, ias)