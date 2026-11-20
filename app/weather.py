"""Weather and air quality for planning, from Open-Meteo (free, no key; CC BY 4.0), and place
names from OpenStreetMap Nominatim. Only rounded coordinates (2 decimals, ~1 km) leave the
server. Forecasts are cached for an hour per rounded point, place names for the process life."""

import time
from datetime import UTC, date, datetime, timedelta

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
    lat, lon = rounded(hit["latitude"], hit["longitude"])
    return {"name": hit["name"], "country": hit.get("country", ""), "lat": lat, "lon": lon,
            "source": "city", "at": datetime.now(UTC).isoformat(timespec="seconds")}


def air_label(aqi: float | None) -> str | None:
    """European AQI bands."""
    if aqi is None:
        return None
    for limit, label in [(20, "good"), (40, "fair"), (60, "moderate"), (80, "poor"),
                         (100, "very poor")]:
        if aqi <= limit:
            return label
    return "extremely poor"


HOURLY = ("temperature_2m,apparent_temperature,dew_point_2m,relative_humidity_2m,precipitation,"
          "precipitation_probability,weather_code,wind_speed_10m,wind_gusts_10m,uv_index,is_day")
DAILY = ("temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,"
         "sunrise,sunset,daylight_duration,uv_index_max")
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
# Nominatim policy: identifying User-Agent, max 1 request/s, cache results. No personal email.
USER_AGENT = "DailyCoach/1.0 (+https://daily-coach-af64d.web.app)"
_names: dict[tuple, str] = {}


def rounded(lat: float, lon: float) -> tuple[float, float]:
    return round(float(lat), 2), round(float(lon), 2)


def reverse_name(lat: float, lon: float, lang: str = "en") -> str:
    """Place name for a rounded point ("Kyiv", "Bucha"); "My location" if Nominatim fails."""
    key = (*rounded(lat, lon), lang)
    if key in _names:
        return _names[key]
    try:
        r = httpx.get(NOMINATIM, timeout=8, headers={"User-Agent": USER_AGENT,
                                                 "Accept-Language": lang}, params={
            "format": "jsonv2", "zoom": 10, "lat": key[0], "lon": key[1]})
        a = r.json().get("address") or {}
        name = next((a[k] for k in ("city", "town", "village", "municipality", "county",
                                    "state") if a.get(k)), None)
    except (httpx.HTTPError, ValueError, AttributeError):
        name = None
    if not name:
        return "My location"
    _names[key] = name
    return name


def forecast(lat: float, lon: float) -> dict:
    """{"tz", "hours": {"YYYY-MM-DDTHH:00": {...}}, "days": {"YYYY-MM-DD": {...}}} for 7 days,
    in the place's local time. {} when Open-Meteo fails (the page says "Weather unavailable")."""
    key = rounded(lat, lon)
    if key in _cache and time.time() - _cache[key][0] < 3600:
        return _cache[key][1]
    try:
        f = httpx.get(FORECAST, timeout=8, params={
            "latitude": key[0], "longitude": key[1], "timezone": "auto", "forecast_days": 7,
            "hourly": HOURLY, "daily": DAILY}).json()
        a = httpx.get(AIR, timeout=8, params={
            "latitude": key[0], "longitude": key[1], "timezone": "auto", "forecast_days": 5,
            "hourly": "european_aqi,pm2_5,birch_pollen,grass_pollen"}).json()
        out = {"tz": f.get("timezone"), "hours": _columns(f["hourly"]),
               "days": _columns(f["daily"])}
        for t, row in _columns(a["hourly"]).items():
            if t in out["hours"]:
                out["hours"][t] |= row
    except (httpx.HTTPError, KeyError, ValueError, TypeError, AttributeError):
        return {}
    for d, day in out["days"].items():
        day["aqi_max"] = max((h["european_aqi"] for t, h in out["hours"].items()
                              if t.startswith(d) and 6 <= int(t[11:13]) <= 21
                              and h.get("european_aqi") is not None), default=None)
    _cache[key] = (time.time(), out)
    return out


def _columns(block: dict) -> dict[str, dict]:
    """Open-Meteo's column arrays -> {time: {variable: value}}."""
    times = block["time"]
    return {t: {k: v[i] for k, v in block.items() if k != "time" and i < len(v)}
            for i, t in enumerate(times)}


def _week(lat: float, lon: float) -> dict:
    out = {}
    for d, x in forecast(lat, lon).get("days", {}).items():
        out[d] = {"t_max": x.get("temperature_2m_max"), "t_min": x.get("temperature_2m_min"),
                  "rain_mm": x.get("precipitation_sum"), "wind_kmh": x.get("wind_speed_10m_max"),
                  "sunrise": (x.get("sunrise") or "")[11:16] or None,
                  "sunset": (x.get("sunset") or "")[11:16] or None,
                  "uv_max": x.get("uv_index_max"), "aqi_max": x.get("aqi_max")}
        out[d]["air"] = air_label(out[d]["aqi_max"])
    return out


def for_day(location: dict | None, day: date) -> dict | None:
    if not location or "lat" not in location:
        return None
    w = _week(location["lat"], location["lon"]).get(day.isoformat())
    return w | {"place": location.get("name")} if w else None


def allergic(fact_texts: list[str]) -> bool:
    """Pollen notes only for people with an allergy in their profile facts."""
    return any(w in t.lower() for t in fact_texts for w in ("allerg", "алерг", "hay fever",
                                                             "поліноз"))


def session(location: dict | None, day: date, start: str = "07:00", minutes: float = 60,
            sport: str = "Run", is_allergic: bool = False) -> dict | None:
    """Weather at the session hours plus the C12 advice. None without a location; {"error"}
    when the forecast is unavailable."""
    from app import weather_rules
    if not location or "lat" not in location:
        return None
    f = forecast(location["lat"], location["lon"])
    w_day = for_day(location, day)
    if not f or not w_day:
        return {"error": "Weather unavailable", "place": location.get("name")}
    t0 = datetime.combine(day, datetime.strptime(start, "%H:%M").time()).replace(minute=0)
    span = max(1, -(-int(minutes) // 60))
    at = [t0 + timedelta(hours=i) for i in range(span)]
    hours = [f["hours"][k] for k in (t.strftime("%Y-%m-%dT%H:00") for t in at
                                     if t.date() == day) if k in f["hours"]]
    before = [f["hours"][k] for k in ((t0 - timedelta(hours=i)).strftime("%Y-%m-%dT%H:00")
                                      for i in range(12, 0, -1)) if k in f["hours"]]
    d = day.isoformat()
    day_hours = {t[11:16]: h for t, h in f["hours"].items() if t.startswith(d)}
    advice = weather_rules.advise(hours, sport, start, minutes, w_day["sunrise"], w_day["sunset"],
                                  before, day_hours, is_allergic)
    first = hours[0] if hours else {}
    return {"day": w_day, "tz": f.get("tz"), "start": start, "minutes": minutes,
            "at": {"feels": first.get("apparent_temperature"),
                   "rain_pct": first.get("precipitation_probability"),
                   "wind_kmh": first.get("wind_speed_10m"), "aqi": first.get("european_aqi"),
                   "air": air_label(first.get("european_aqi"))},
            "advice": advice,
            "strip": [{"hour": t[11:16], "feels": h.get("apparent_temperature"),
                       "rain_pct": h.get("precipitation_probability"),
                       "aqi": h.get("european_aqi"), "air": air_label(h.get("european_aqi")),
                       "day": bool(h.get("is_day"))}
                      for t, h in f["hours"].items() if t.startswith(d) and 5 <= int(t[11:13])]}


def for_planner(s: dict | None) -> dict | None:
    """What the planner and the coach see: the day, session hours and advice (no coordinates)."""
    if not s or "advice" not in s:
        return None
    end = (datetime.strptime(s["start"], "%H:%M") + timedelta(minutes=s["minutes"]))
    return {"day": s["day"], "session_hours": f"{s['start']}–{end:%H:%M}", "advice": s["advice"]}


def for_user(user_id: str, day: date, sport: str | None = None,
             minutes: float | None = None) -> dict | None:
    """session() at the person's usual training time, with their place, sport and allergy."""
    from app import store
    from app.pipeline.turn import athlete_sports
    profile = {k: v["value"] for k, v in store.get_profile(user_id).items()}
    sports = athlete_sports(profile)
    return session(profile.get("location"), day, store.day_times(user_id)["usual_training_time"],
                   minutes or 60, sport or (sports[0] if sports else "Run"),
                   allergic([f["text"] for f in store.list_facts(user_id)]))
