"""intervals.icu API client (https://intervals.icu/api/v1, basic auth "API_KEY:<key>").

Field names checked against real responses on 2026-11-14 (see docs/plans/03-build.md).
Errors become IntervalsError with a message a user can act on. The key is never logged.
"""

import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from app import crypto, store

BASE = "https://intervals.icu/api/v1"
log = logging.getLogger("intervals")


class IntervalsError(Exception):
    pass


class NotConnected(IntervalsError):
    pass


@dataclass
class Conn:
    athlete_id: str
    api_key: str


def connection_for(user_id: str) -> Conn:
    row = store.get_secret(user_id, "intervals")
    if not row:
        raise NotConnected("intervals.icu is not connected. Connect it in Settings.")
    return Conn(athlete_id=row["external_id"], api_key=crypto.decrypt(row["ciphertext"]))


def _request(conn: Conn, method: str, path: str, **kwargs) -> httpx.Response:
    url = f"{BASE}{path}"
    for attempt in range(3):
        try:
            r = httpx.request(method, url, auth=("API_KEY", conn.api_key), timeout=15, **kwargs)
        except httpx.TimeoutException as e:
            if attempt == 2:
                raise IntervalsError(
                    "intervals.icu is not responding. Try again in a minute.") from e
            continue
        except httpx.HTTPError as e:
            raise IntervalsError("Could not reach intervals.icu. Check your connection.") from e
        if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code in (401, 403):
            raise IntervalsError(
                "intervals.icu refused the key or athlete ID. Check them in Settings.")
        if r.status_code == 404:
            raise IntervalsError("intervals.icu could not find that athlete or item.")
        if r.status_code >= 400:
            log.warning("intervals %s %s -> %s", method, path, r.status_code)
            raise IntervalsError(f"intervals.icu returned an error ({r.status_code}). Try again.")
        return r
    raise IntervalsError("intervals.icu is busy. Try again in a minute.")


def get_athlete(conn: Conn) -> dict:
    return _request(conn, "GET", f"/athlete/{conn.athlete_id}").json()


def get_wellness(conn: Conn, oldest: date, newest: date) -> list[dict]:
    return _request(conn, "GET", f"/athlete/{conn.athlete_id}/wellness",
                    params={"oldest": oldest.isoformat(), "newest": newest.isoformat()}).json()


def get_activities(conn: Conn, oldest: date, newest: date) -> list[dict]:
    return _request(conn, "GET", f"/athlete/{conn.athlete_id}/activities",
                    params={"oldest": oldest.isoformat(), "newest": newest.isoformat()}).json()


def get_events(conn: Conn, oldest: date, newest: date) -> list[dict]:
    return _request(conn, "GET", f"/athlete/{conn.athlete_id}/events",
                    params={"oldest": oldest.isoformat(), "newest": newest.isoformat()}).json()


def create_workout(conn: Conn, day: date, sport: str, name: str, description: str) -> dict:
    """Planned workout on the calendar. intervals.icu parses `description` (workout text) into
    steps and, with Garmin upload on, sends it to the watch."""
    body = {"category": "WORKOUT", "start_date_local": f"{day.isoformat()}T00:00:00",
            "type": sport, "name": name, "description": description}
    return _request(conn, "POST", f"/athlete/{conn.athlete_id}/events", json=body).json()


def delete_event(conn: Conn, event_id: str | int) -> None:
    _request(conn, "DELETE", f"/athlete/{conn.athlete_id}/events/{event_id}")


def connect_user(user_id: str, api_key: str, athlete_id: str) -> dict:
    """Checks the key with a real call, stores it encrypted and prefills the profile.
    Returns the athlete; raises IntervalsError with a message for the user."""
    api_key, athlete_id = api_key.strip(), athlete_id.strip()
    if not api_key or not athlete_id:
        raise IntervalsError("Enter both the API key and the athlete ID.")
    athlete = get_athlete(Conn(athlete_id, api_key))
    store.save_secret(user_id, "intervals", crypto.encrypt(api_key), crypto.last4(api_key),
                      athlete_id)
    for key, value in profile_from_athlete(athlete).items():
        store.set_profile_field(user_id, key, value, "intervals", overwrite_user=False)
    if athlete.get("timezone"):
        store.set_time_zone(user_id, athlete["timezone"].replace("Europe/Kiev", "Europe/Kyiv"))
    return athlete


def athlete_summary(profile: dict) -> str:
    """'Run, Swim and Ride zones · weight 74 kg · resting HR 45' from prefilled fields."""
    parts = []
    sports = list((profile.get("sport_settings") or {}).keys())
    if sports:
        parts.append(", ".join(sports[:-1]) + (" and " if len(sports) > 1 else "") + sports[-1]
                     + " zones")
    if profile.get("weight_kg"):
        parts.append(f"weight {profile['weight_kg']} kg")
    if profile.get("resting_hr"):
        parts.append(f"resting HR {profile['resting_hr']}")
    return " · ".join(parts)


# --- profile prefill ---------------------------------------------------------------------

def profile_from_athlete(a: dict) -> dict:
    """The athlete fields we keep, as profile_fields (key -> value). Missing values are skipped."""
    out: dict = {}
    if a.get("name"):
        out["name"] = a["name"]
    if a.get("sex"):
        out["sex"] = a["sex"]
    if a.get("icu_date_of_birth"):
        out["birth_year"] = int(str(a["icu_date_of_birth"])[:4])
    if a.get("height"):
        h = float(a["height"])
        out["height_cm"] = round(h * 100 if h < 3 else h)  # API gives metres
    weight = a.get("icu_weight") or a.get("weight")
    if weight:
        out["weight_kg"] = round(float(weight), 1)
    if a.get("icu_resting_hr"):
        out["resting_hr"] = a["icu_resting_hr"]
    if a.get("timezone"):
        out["time_zone"] = a["timezone"].replace("Europe/Kiev", "Europe/Kyiv")
    sports = {}
    for s in a.get("sportSettings") or []:
        types = s.get("types") or []
        if not types or types == ["Other"]:
            continue
        entry = {k: s[k] for k in ("lthr", "max_hr", "ftp") if s.get(k)}
        if s.get("hr_zones"):
            entry["hr_zones_bpm"] = hr_zone_ranges(s["hr_zones"])
        if s.get("threshold_pace"):
            if "Swim" in types:
                entry["threshold_pace_per_100m"] = pace_per(s["threshold_pace"], 100)
            else:
                entry["threshold_pace_per_km"] = pace_per(s["threshold_pace"], 1000)
        sports[types[0]] = {"types": types, **entry}
    if sports:
        out["sport_settings"] = sports
    return out


def hr_zone_ranges(upper_limits: list[int]) -> dict[str, str]:
    """intervals.icu gives each zone's upper limit; spell the ranges out so nobody misreads them.
    [123, 143, 164] -> {"Z1": "up to 123", "Z2": "124-143", "Z3": "144-164"}"""
    ranges, low = {}, None
    for i, high in enumerate(upper_limits, start=1):
        ranges[f"Z{i}"] = f"up to {high}" if low is None else f"{low}-{high}"
        low = high + 1
    return ranges


def pace_per(meters_per_second: float, meters: int) -> str:
    """m/s -> "m:ss" per `meters` (1000 for run, 100 for swim)."""
    seconds = meters / meters_per_second
    return f"{int(seconds // 60)}:{int(round(seconds % 60)):02d}"


# --- day snapshot (cached) ---------------------------------------------------------------

_cache: dict[tuple[str, date], tuple[float, dict]] = {}
CACHE_SECONDS = 300


def day_snapshot(user_id: str, day: date, fresh: bool = False) -> dict:
    """Wellness (8 days) + activities (14 days) for one day, with simple baselines.
    Cached per user and day for 5 minutes."""
    key = (user_id, day)
    if not fresh and key in _cache and time.time() - _cache[key][0] < CACHE_SECONDS:
        return _cache[key][1]
    conn = connection_for(user_id)
    wellness = get_wellness(conn, day - timedelta(days=7), day)
    activities = get_activities(conn, day - timedelta(days=14), day)
    snap = summarize(wellness, activities, day)
    _cache[key] = (time.time(), snap)
    return snap


def _mean(values: list) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def summarize(wellness: list[dict], activities: list[dict], day: date) -> dict:
    by_day = {w.get("id"): w for w in wellness}
    today = by_day.get(day.isoformat(), {})
    prior = [w for d, w in by_day.items() if d and d < day.isoformat()]
    sleep_h = (today.get("sleepSecs") or 0) / 3600 or None
    snap = {
        "date": day.isoformat(),
        "today": {
            "hrv": today.get("hrv"),
            "resting_hr": today.get("restingHR"),
            "sleep_h": round(sleep_h, 1) if sleep_h else None,
            "sleep_score": today.get("sleepScore"),
            "ctl_fitness": round(today["ctl"], 1) if today.get("ctl") is not None else None,
            "atl_fatigue": round(today["atl"], 1) if today.get("atl") is not None else None,
        },
        "baseline_7d": {
            "hrv": _mean([w.get("hrv") for w in prior]),
            "resting_hr": _mean([w.get("restingHR") for w in prior]),
            "sleep_h": _mean([(w.get("sleepSecs") or 0) / 3600 or None for w in prior]),
        },
        "activities_14d": [
            {"date": (a.get("start_date_local") or "")[:10], "type": a.get("type"),
             "name": a.get("name"), "km": round((a.get("distance") or 0) / 1000, 1),
             "minutes": round((a.get("moving_time") or 0) / 60),
             "load": a.get("icu_training_load"), "avg_hr": a.get("average_heartrate")}
            for a in sorted(activities, key=lambda a: a.get("start_date_local") or "")
        ],
    }
    t = snap["today"]
    if t["ctl_fitness"] is not None and t["atl_fatigue"] is not None:
        t["form"] = round(t["ctl_fitness"] - t["atl_fatigue"], 1)
    return snap
