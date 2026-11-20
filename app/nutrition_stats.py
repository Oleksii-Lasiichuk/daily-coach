"""Nutrition numbers computed in code (no LLM): daily totals, targets by day type, the foods you
eat most, gaps and excesses. The coach and the Nutrition page both use these."""

from collections import Counter
from datetime import date, timedelta

from app import store
from app.pipeline.nutrition import NUTRIENTS

# Reference daily values for an adult man (EFSA/NIH, rounded). Limits are "at most".
REFERENCE = {"fiber_g": 30, "iron_mg": 8, "calcium_mg": 1000, "potassium_mg": 3500,
             "magnesium_mg": 400, "vit_c_mg": 90, "vit_d_ug": 15}
LIMITS = {"sugar_g": 50, "salt_g": 5, "caffeine_mg": 400, "alcohol_g": 20}
CARBS_PER_KG = {"recover": 3.0, "easy": 4.0, "normal": 5.0, "push": 6.5}
ACTIVITY = {"recover": 1.4, "easy": 1.55, "normal": 1.7, "push": 1.85}
LABELS = {"kcal": "Energy", "protein_g": "Protein", "carbs_g": "Carbs", "sugar_g": "Sugar",
          "fiber_g": "Fibre", "fat_g": "Fat", "sat_fat_g": "Saturated fat", "salt_g": "Salt",
          "caffeine_mg": "Caffeine", "alcohol_g": "Alcohol", "iron_mg": "Iron",
          "calcium_mg": "Calcium", "potassium_mg": "Potassium", "magnesium_mg": "Magnesium",
          "vit_c_mg": "Vitamin C", "vit_d_ug": "Vitamin D"}
UNITS = {k: k.rsplit("_", 1)[-1] if "_" in k else "kcal" for k in NUTRIENTS}
UNITS["kcal"] = "kcal"


def meal_totals(data: dict) -> dict[str, float]:
    n = data.get("nutrition") or {}
    t = n.get("totals")
    if t:
        return t
    return {k: n.get(k, 0) for k in ("kcal", "protein_g", "carbs_g", "fat_g")}  # older logs


def day_totals(logs: list[dict]) -> dict[str, float]:
    total = dict.fromkeys(NUTRIENTS, 0.0)
    for lg in logs:
        for k, v in meal_totals(lg["data"]).items():
            if k in total and isinstance(v, (int, float)):
                total[k] += v
    return {k: round(v, 1) for k, v in total.items()}


def _num(profile: dict, key: str, default: float) -> float:
    try:
        raw = str((profile.get(key) or {}).get("value", default))
        return float(raw.split()[0].replace(",", "."))
    except (ValueError, AttributeError):
        return default


def targets(user_id: str, day_type: str | None, session_min: float = 0) -> dict[str, float]:
    """Energy and macros for the day type (Mifflin-St Jeor x activity; carbs g/kg by day type,
    at least 7 g/kg on a day with a session of 90 min or more; protein 1.8 g/kg), plus
    micronutrient references and limits."""
    p = store.get_profile(user_id)
    w = _num(p, "weight_kg", 75)
    h = _num(p, "height_cm", 178)
    age = date.today().year - int(_num(p, "birth_year", 1995))
    sex = str((p.get("sex") or {}).get("value") or "").strip().upper()[:1]
    # Mifflin-St Jeor: +5 for men, -161 for women; unknown sex uses the midpoint
    bmr = 10 * w + 6.25 * h - 5 * age + {"M": 5, "F": -161}.get(sex, -78)
    dt = day_type or "normal"
    kcal = bmr * ACTIVITY[dt]
    protein, carbs = 1.8 * w, CARBS_PER_KG[dt] * w
    if session_min >= 90:
        carbs = max(carbs, 7 * w)
        kcal = max(kcal, 4 * protein + 4 * carbs + 9 * 0.8 * w)
    fat = max(0.8 * w, (kcal - 4 * protein - 4 * carbs) / 9)
    return {"kcal": round(kcal), "protein_g": round(protein), "carbs_g": round(carbs),
            "fat_g": round(fat), "sat_fat_g": round(kcal * 0.1 / 9), **REFERENCE, **LIMITS}


def foods(logs: list[dict]) -> Counter:
    c: Counter = Counter()
    for lg in logs:
        for item in (lg["data"].get("nutrition") or {}).get("items", []):
            name = (item.get("food") or item.get("name") or "").strip().lower()
            if name:
                c[name] += 1
    return c


def summary(user: store.User, today: date, days: int) -> dict:
    first = today - timedelta(days=days - 1)
    logs = [lg for lg in store.logs_between(user.id, first, today) if lg["data"].get("nutrition")]
    by_day: dict[date, list] = {}
    for lg in logs:
        by_day.setdefault(lg["day"], []).append(lg)
    a = store.get_assessment(user.id, today)
    tgt = targets(user.id, a["day_type"] if a else None)
    n_days = max(1, len(by_day))
    total = day_totals(logs)
    avg = {k: round(v / n_days, 1) for k, v in total.items()}
    out = {"period_days": days, "days_with_meals": len(by_day), "average_per_day": avg,
           "targets_today": tgt, "top_foods": foods(logs).most_common(15)}
    if days == 1:
        out["remaining_today"] = {k: round(tgt[k] - avg.get(k, 0)) for k in
                                  ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g")}
    out["too_much"] = [LABELS[k] for k, lim in LIMITS.items() if avg.get(k, 0) > lim]
    out["too_little"] = [LABELS[k] for k, ref in REFERENCE.items() if 0 < len(logs)
                         and avg.get(k, 0) < 0.7 * ref]
    recent = [d for d in sorted(by_day) if d >= today - timedelta(days=2)]
    if len(recent) >= 3:
        common = set.intersection(*[set(foods(by_day[d])) for d in recent])
        out["eaten_each_of_last_3_days"] = sorted(common)
    return out


def bars(user: store.User, today: date, days: int) -> list[dict]:
    """Rows for the Nutrition page: label, value (per day), target, % and status."""
    s = summary(user, today, days)
    avg, tgt = s["average_per_day"], s["targets_today"]
    rows = []
    for k in NUTRIENTS:
        target = tgt.get(k)
        val = avg.get(k, 0)
        pct = round(100 * val / target) if target else None
        status = "limit" if k in LIMITS or k == "sat_fat_g" else "goal"
        over = status == "limit" and target and val > target
        under = (days > 1 and status == "goal" and target and pct is not None and pct < 70
                 and s["days_with_meals"])
        rows.append({"key": k, "label": LABELS[k], "value": val, "unit": UNITS[k],
                     "target": target, "pct": pct, "kind": status,
                     "flag": "over" if over else "low" if under else ""})
    return rows


def weight_of(user_id: str) -> float:
    return _num(store.get_profile(user_id), "weight_kg", 75)


def water_l(logs: list[dict]) -> float:
    return round(sum(lg["data"].get("water_ml", 0) for lg in logs) / 1000, 2)


def session_fuel(workout: dict, weight: float) -> dict | None:
    """What to eat before, during and after a planned session (sports-nutrition rules of thumb:
    carbs in g per kg before and after, g per hour during long sessions). Each value is
    (text with {placeholders}, numbers), so the page can translate the text."""
    if not workout or workout.get("action") == "rest":
        return None
    minutes = workout.get("minutes") or 0
    hard = any((s.get("zone_high") or 0) >= 4 for b in workout.get("blocks", [])
               for s in b.get("steps", []))
    w = {"lo": round(1 * weight), "hi": round(2 * weight), "p": round(0.3 * weight)}
    if minutes >= 90:
        before = "Carb-rich meal 2–3 h before: {lo}–{hi} g carbs (oatmeal with honey, rice, " \
                 "bread with jam)."
    elif hard or minutes >= 60:
        before = "A light carb snack 60–90 min before: 30–60 g carbs (banana, toast with honey)."
    else:
        before = "Nothing special. A small snack if you're hungry; water."
    if minutes >= 150:
        during = "60–90 g carbs per hour (gels, drink, bars) and 500–750 ml fluid with salt " \
                 "per hour."
    elif minutes >= 75:
        during = "30–60 g carbs per hour (a gel or sports drink) and 400–750 ml fluid per hour."
    else:
        during = "Water if it's warm."
    if hard or minutes >= 75:
        after = "Within 1–2 h: about {lo} g carbs and {p} g protein."
    else:
        after = "Your next normal meal, with about {p} g protein."
    return {"before": before, "during": during, "after": after, "n": w}


QUICK = {  # one-tap logs; values per serving (USDA, rounded)
    "water": ("drink", "Water 250 ml", {"water_ml": 250}, {}),
    "coffee": ("drink", "Coffee, 1 cup", {}, {"kcal": 2, "caffeine_mg": 95,
                                              "potassium_mg": 115, "magnesium_mg": 7}),
    "tea": ("drink", "Black tea, 1 cup", {}, {"kcal": 2, "caffeine_mg": 45,
                                              "potassium_mg": 90}),
    "beer": ("alcohol", "Beer 0.5 L", {"alcohol_drinks": 1},
             {"kcal": 215, "protein_g": 2.3, "carbs_g": 18, "alcohol_g": 20,
              "potassium_mg": 135, "magnesium_mg": 30}),
}


def quick_data(key: str) -> tuple[str, dict]:
    kind, text, extra, n = QUICK[key]
    totals = dict.fromkeys(NUTRIENTS, 0.0) | n
    item = {"name": text, "food": key, "grams": 250 if key != "beer" else 500} | totals
    return kind, {"description": text, "quick": key, **extra,
                  "nutrition": {"items": [item] if n else [], "totals": totals,
                                "kcal": totals["kcal"]}}


def scale_nutrition(data: dict, factor: float) -> dict:
    """A meal eaten ×factor (half portion, two portions, or a kcal you know)."""
    n = dict(data.get("nutrition") or {})
    if not n:
        return data
    n["items"] = [{k: (round(v * factor, 1) if isinstance(v, (int, float)) and k != "name"
                       else v) for k, v in it.items()} for it in n.get("items", [])]
    n["totals"] = {k: round(v * factor, 1) for k, v in (n.get("totals") or {}).items()}
    for k in ("kcal", "protein_g", "carbs_g", "fat_g"):
        if k in n:
            n[k] = round(n[k] * factor)
    return data | {"nutrition": n}


# --- one day, Garmin-style (Nutrition page, day view) ------------------------------------

MEAL_PARTS = [("Breakfast", 4, 11), ("Lunch", 11, 16), ("Dinner", 16, 22)]


def meal_part(lg: dict, tz) -> str:
    """Breakfast / Lunch / Dinner by the local time it was eaten; drinks apart; else Snacks."""
    if lg["kind"] in ("drink", "alcohol"):
        return "Drinks"
    if not lg.get("occurred_at"):
        return "Snacks"
    h = lg["occurred_at"].astimezone(tz).hour
    return next((name for name, a, b in MEAL_PARTS if a <= h < b), "Snacks")


def day_view(user: store.User, day: date, today: date) -> dict:
    """Everything the day page shows, computed in code; `review_input` feeds C9."""
    from zoneinfo import ZoneInfo

    from app import health
    tz = ZoneInfo(user.time_zone)
    logs = [lg for lg in store.logs_between(user.id, day, day)
            if lg["data"].get("nutrition") or lg["kind"] in ("meal", "drink", "alcohol")]
    totals = day_totals(logs)
    a = store.get_assessment(user.id, day)
    session_min = max([p["workout"].get("minutes") or 0 for p in store.proposals_for_day(
        user.id, day) if p["status"] != "undone"], default=0)
    tgt = targets(user.id, a["day_type"] if a else None, session_min)
    training = health.activities(user.id, day, day)
    over = day < today  # a finished day: "low" is a real gap, not "not eaten yet"
    rows = []
    for k in NUTRIENTS:
        target, val = tgt.get(k), totals.get(k, 0)
        pct = round(100 * val / target) if target else None
        limit = k in LIMITS or k == "sat_fat_g"
        flag = "over" if limit and target and val > target else (
            "low" if over and not limit and pct is not None and pct < 70 and logs else "")
        rows.append({"key": k, "label": LABELS[k], "value": val, "unit": UNITS[k],
                     "target": target, "pct": pct, "kind": "limit" if limit else "goal",
                     "flag": flag})
    parts: dict[str, list] = {}
    for lg in logs:
        parts.setdefault(meal_part(lg, tz), []).append(lg)
    order = [p for p, *_ in MEAL_PARTS] + ["Snacks", "Drinks"]
    meals = [{"time": lg["occurred_at"].astimezone(tz).strftime("%H:%M")
              if lg.get("occurred_at") else None, "what": lg["data"].get("description", ""),
              **{k: round(meal_totals(lg["data"]).get(k) or 0)
                 for k in ("kcal", "protein_g", "carbs_g")}} for lg in logs]
    drinks = {"water_l": water_l(logs), "caffeine_mg": round(totals.get("caffeine_mg", 0)),
              "alcohol_g": round(totals.get("alcohol_g", 0))}
    burned = round(sum(t.get("kcal") or 0 for t in training))
    review_input = {
        "day": day.isoformat(), "lang": store.user_lang(user.id), "day_is_over": over,
        "day_type": a["day_type"] if a else None,
        "targets": {k: tgt[k] for k in ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g",
                                        "sugar_g", "salt_g")},
        "eaten": {k: round(totals.get(k, 0)) for k in ("kcal", "protein_g", "carbs_g", "fat_g",
                                                       "fiber_g", "sugar_g", "salt_g")},
        "meals_logged": len(logs), "meals": meals, "drinks": drinks,
        "training": [{"type": t.get("type"), "minutes": t.get("minutes"), "km": t.get("km"),
                      "kcal": t.get("kcal")} for t in training]}
    from app.pipeline import labs  # B3: low ferritin / haemoglobin → iron-rich food tip
    if flags := labs.low_flags(user.id, day):
        review_input["lab_flags"] = flags
    return {"day": day, "logs": logs, "totals": totals, "targets": tgt, "rows": rows,
            "byk": {r["key"]: r for r in rows}, "day_type": a["day_type"] if a else None,
            "parts": [(p, parts[p], day_totals(parts[p])) for p in order if p in parts],
            "drinks": drinks, "training": training, "burned": burned,
            "review_input": review_input}
