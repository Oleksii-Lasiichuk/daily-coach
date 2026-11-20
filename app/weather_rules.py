"""C12 Weather advice: rule tables in code (no LLM), unit-tested in tests/test_weather_rules.py.

Input: the forecast hours of the session (from weather.forecast), the hours before it (for ice),
the day's sunrise/sunset. Output: pace slowdown band, clothing, flags, best hour and short facts
the coach and the morning report read. Thresholds are heuristics (documented in the report),
not a study; Oleksii tunes them.
"""

# 1. Heat -> pace: (upper bound of air temp + dew point in °F, slowdown % [lo, hi]).
HEAT_BANDS = [(100, (0.0, 0.0)), (110, (0.0, 0.5)), (120, (0.5, 1.0)), (130, (1.0, 2.0)),
              (140, (2.0, 3.0)), (150, (3.0, 4.5)), (160, (4.5, 6.0)), (170, (6.0, 8.0)),
              (180, (8.0, 10.0))]
# 2. Clothing by feels-like °C: (lower bound, items).
CLOTHING = [(20, ["singlet", "shorts", "cap"]), (12, ["T-shirt", "shorts"]),
            (5, ["long sleeve", "shorts or tights"]),
            (0, ["long sleeve", "light jacket", "tights", "gloves"]),
            (-5, ["thermal layer", "jacket", "hat", "gloves"]),
            (float("-inf"), ["two layers", "windproof jacket", "tights", "hat", "gloves", "buff"])]
STORM_CODES = {95, 96, 99}
FREEZING_CODES = {56, 57, 66, 67}
WET_CODES = set(range(51, 68)) | set(range(80, 83))  # drizzle, rain, freezing rain, showers
POLLEN_HIGH = {"birch_pollen": 100, "grass_pollen": 50}  # grains/m³, CAMS "high" band (approx.)
RIDE = ("Ride", "MountainBikeRide", "VirtualRide", "GravelRide")
FLAG_FACTS = {
    "indoors_aqi": "Air is very poor (European AQI above 80): intense sessions indoors, or easy only.",
    "storm": "Thunderstorm forecast: train indoors or move the session.",
    "rain": "Heavy rain (4 mm/h or more): indoors or another time.",
    "ice": "Ice is likely: trail or track, careful footing, no intervals on the road.",
    "dark": "It is dark at this time: headlamp and a reflective vest.",
    "uv_high": "UV index 6 or higher: avoid 11:00–16:00, use sunscreen.",
    "wind": "Gusts of 50 km/h or more: no cycling outdoors.",
    "pollen": "Pollen is high: take it into account if you are allergic.",
}


def heat_sum_f(temp_c: float, dew_c: float) -> float:
    return round(temp_c * 9 / 5 + 32 + dew_c * 9 / 5 + 32, 1)


def pace_band(sum_f: float | None) -> tuple[list[float] | None, str]:
    """(slowdown % [lo, hi], heat level). None band above 180: hard running not advised."""
    if sum_f is None:
        return [0.0, 0.0], "unknown"
    for upper, band in HEAT_BANDS:
        if sum_f <= upper:
            level = "none" if upper <= 100 else "mild" if upper <= 130 else \
                "moderate" if upper <= 150 else "high"
            return list(band), level
    return None, "extreme"


def clothing(feels_c: float | None, gusts_kmh: float | None = None,
             rain_prob: float | None = None, uv: float | None = None) -> list[str]:
    if feels_c is None:
        return []
    items = list(next(items for lower, items in CLOTHING if feels_c >= lower))
    if feels_c >= 20 and (uv or 0) >= 6:
        items.append("sunscreen")
    if (gusts_kmh or 0) >= 30 and "windproof jacket" not in items:
        items.append("windproof layer")
    if (rain_prob or 0) >= 60:
        items.append("rain jacket or cap")
    return items


def _end(start: str, minutes: float) -> str:
    total = min(int(start[:2]) * 60 + int(start[3:5]) + int(minutes), 24 * 60 - 1)
    return f"{total // 60:02d}:{total % 60:02d}"


def _vals(hours: list[dict], key: str) -> list[float]:
    return [h[key] for h in hours if h.get(key) is not None]


def flags(hours: list[dict], start: str | None = None, minutes: float = 60,
          sunrise: str | None = None, sunset: str | None = None,
          before: list[dict] | None = None, allergic: bool = False) -> list[str]:
    """Flags for the session hours. `before` = the 12 hours before the session (ice)."""
    out = []
    aqi = _vals(hours, "european_aqi")
    codes = {int(c) for c in _vals(hours, "weather_code")}
    if aqi and max(aqi) > 80:
        out.append("indoors_aqi")
    if codes & STORM_CODES:
        out.append("storm")
    if any(p >= 4 for p in _vals(hours, "precipitation")):
        out.append("rain")
    window = (before or []) + hours
    temps = _vals(hours, "temperature_2m")
    all_temps = _vals(window, "temperature_2m")
    wet = any(p > 0 for p in _vals(window, "precipitation")) or \
        bool({int(c) for c in _vals(window, "weather_code")} & WET_CODES)
    freezing = bool({int(c) for c in _vals(window, "weather_code")} & FREEZING_CODES)
    crossing = bool(all_temps) and min(all_temps) <= 0 < max(all_temps)
    if temps and min(temps) <= 0.5 and (freezing or (wet and crossing)):
        out.append("ice")
    if start and sunrise and sunset and (start < sunrise or _end(start, minutes) > sunset):
        out.append("dark")
    if any(u >= 6 for u in _vals(hours, "uv_index")):
        out.append("uv_high")
    if any(g >= 50 for g in _vals(hours, "wind_gusts_10m")):
        out.append("wind")
    if allergic and any(any(v >= limit for v in _vals(hours, k)) for k, limit in
                        POLLEN_HIGH.items()):
        out.append("pollen")
    return out


def best_hour(day_hours: dict[str, dict], minutes: float, sunrise: str | None,
              sunset: str | None) -> str | None:
    """Start hour ("HH:00") in daylight with no flags and the lowest heat sum, or None.
    day_hours: {"HH:00": hour} for one day."""
    n = max(1, -(-int(minutes) // 60))
    best = None
    for h in range(24):
        start = f"{h:02d}:00"
        span = [day_hours.get(f"{h + i:02d}:00") for i in range(n)]
        if h + n > 24 or not all(span) or not (sunrise and sunset):
            continue
        if flags(span, start, minutes, sunrise, sunset):
            continue
        heat = max((heat_sum_f(x["temperature_2m"], x["dew_point_2m"]) for x in span
                    if x.get("temperature_2m") is not None and x.get("dew_point_2m")
                    is not None), default=0)
        if best is None or heat < best[0]:
            best = (heat, start)
    return best[1] if best else None


def advise(hours: list[dict], sport: str = "Run", start: str | None = None,
           minutes: float = 60, sunrise: str | None = None, sunset: str | None = None,
           before: list[dict] | None = None, day_hours: dict[str, dict] | None = None,
           allergic: bool = False) -> dict:
    """C12 output for one session. Empty hours -> {} (no forecast)."""
    if not hours:
        return {}
    pairs = [(h["temperature_2m"], h["dew_point_2m"]) for h in hours
             if h.get("temperature_2m") is not None and h.get("dew_point_2m") is not None]
    heat = max((heat_sum_f(t, d) for t, d in pairs), default=None)
    band, level = pace_band(heat)
    feels = _vals(hours, "apparent_temperature")
    wear = clothing(min(feels) if feels else None, max(_vals(hours, "wind_gusts_10m") or [0]),
                    max(_vals(hours, "precipitation_probability") or [0]),
                    max(_vals(hours, "uv_index") or [0]))
    fl = flags(hours, start, minutes, sunrise, sunset, before, allergic)
    best = best_hour(day_hours, minutes, sunrise, sunset) if day_hours else None
    facts = []
    if feels:
        facts.append(f"Feels like {round(min(feels))}…{round(max(feels))} °C at the session time"
                     + (f" ({start})." if start else "."))
    riding = sport in RIDE
    if level in ("mild", "moderate", "high") and not riding:
        facts.append(f"Heat and humidity slow running pace by about {band[0]:g}–{band[1]:g} %.")
    elif level == "extreme" and not riding:
        facts.append("Too hot and humid for hard running: easy or indoors.")
    if riding and level not in ("none", "unknown"):
        facts.append("Warm and humid: drink more, ride by heart rate, not power.")
    if wear:
        facts.append("Wear: " + ", ".join(wear) + ".")
    aqi = _vals(hours, "european_aqi")
    if aqi and 60 < max(aqi) <= 80:
        facts.append("Air is poor (AQI 60–80): shorten the intervals.")
    facts += [FLAG_FACTS[f] for f in fl]
    if best and best != start and fl:
        facts.append(f"Better time today: {best}.")
    return {"pace_slower_pct": band, "heat_level": level, "heat_sum_f": heat,
            "clothing": wear, "flags": fl, "best_hour": best, "facts": facts[:6]}
