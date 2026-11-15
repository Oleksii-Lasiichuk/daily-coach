"""Weather and air quality for planning, from Open-Meteo (free, no key). Only the city's
coordinates that the athlete chose in Settings are sent. Cached for an hour."""

import time
from datetime import date

import httpx

GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
_cache: dict[tuple, tuple[float, dict]] = {}


def geocode(name: str) -> dict | None:
    try:
        r = httpx.get(GEO, params={"name": name[:80], "count": 1, "format": "json"}, timeout=8)
        hit = (r.json().get("results") or [None])[0]
    except (httpx.HTTPError, ValueError):
        return None
    if not hit:
        return None
    return {"name": hit["name"], "country": hit.get("country", ""), "lat": hit["latitude"],
            "lon": hit["longitude"]}


def air_label(aqi: float | None) -> str | None:
    """European AQI bands."""
    if aqi is None:
        return None
    for limit, label in [(20, "good"), (40, "fair"), (60, "moderate"), (80, "poor"),
                         (100, "very poor")]:
        if aqi <= limit:
            return label
    return "extremely poor"


def _week(lat: float, lon: float) -> dict:
    key = (round(lat, 2), round(lon, 2))
    if key in _cache and time.time() - _cache[key][0] < 3600:
        return _cache[key][1]
    out: dict = {}
    try:
        f = httpx.get(FORECAST, timeout=8, params={
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 7,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                     "wind_speed_10m_max"}).json()["daily"]
        for i, d in enumerate(f["time"]):
            out[d] = {"t_max": f["temperature_2m_max"][i], "t_min": f["temperature_2m_min"][i],
                      "rain_mm": f["precipitation_sum"][i],
                      "wind_kmh": f["wind_speed_10m_max"][i]}
        a = httpx.get(AIR, timeout=8, params={"latitude": lat, "longitude": lon,
                                              "timezone": "auto", "forecast_days": 5,
                                              "hourly": "european_aqi"}).json()["hourly"]
        for t, v in zip(a["time"], a["european_aqi"], strict=False):
            day = out.get(t[:10])
            if day is not None and v is not None and 6 <= int(t[11:13]) <= 21:
                day["aqi_max"] = max(day.get("aqi_max", 0), v)
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return {}
    for d in out.values():
        d["air"] = air_label(d.get("aqi_max"))
    _cache[key] = (time.time(), out)
    return out


def for_day(location: dict | None, day: date) -> dict | None:
    if not location or "lat" not in location:
        return None
    w = _week(location["lat"], location["lon"]).get(day.isoformat())
    return w | {"place": location.get("name")} if w else None
