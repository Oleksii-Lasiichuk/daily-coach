"""Writes the C6, C0 and C8 eval sets (hand-written cases, kept as code so they are reviewable)."""

import json
from pathlib import Path

D = Path(__file__).parent / "data"
sports_r = ["Run", "TrailRun", "Swim", "WeightTraining", "Walk"]
sports_b = ["Ride", "Run", "WeightTraining", "Walk"]
prof = {"sport_settings": {"Run": {"lthr": 185, "max_hr": 204, "threshold_pace_per_km": "4:07"},
                           "Swim": {"threshold_pace_per_100m": "2:00"}},
        "main_goal": "Half marathon under 1:45 in April",
        "weekly_availability": "Mon, Wed, Fri mornings 1 h; Sat long 2 h"}
acts = [{"date": "2026-11-12", "type": "Run", "km": 10, "minutes": 55, "load": 60},
        {"date": "2026-11-10", "type": "Swim", "km": 2, "minutes": 45, "load": 35},
        {"date": "2026-11-09", "type": "Run", "km": 16, "minutes": 90, "load": 95}]


def P(d):
    return [{"day": "2026-11-14", "kind": "planned_workout", "description": d}]


def c(day_type, reasons, planned="nothing stated", facts=(), request="What should I do today?",
      sports=sports_r, red=False, expect=""):
    return {"inputs": {"date": "2026-11-14", "day_type": day_type, "reasons": reasons,
                       "athlete_sports": sports, "planned_today": planned,
                       "recent_activities": acts, "profile": prof, "facts": list(facts),
                       "red_flag_today": red, "request": request}, "expect": expect}


c6 = [
    c("recover", ["Slept 4 h", "4 beers last night"], P("6x800 m at 4:00/km"),
      expect="rest or <=40 min Z1-2; replace the intervals"),
    c("easy", ["Slept 6 h"], P("6x800 m at 4:00/km"), expect="modify to an easy Z1-2 run"),
    c("normal", ["No negative signals"], P("6x800 m at 4:00/km"), expect="keep the intervals"),
    c("push", ["HRV above baseline", "Slept 8 h", "Legs fresh"], P("Easy 40 min run"),
      request="I feel great, can I do more?", expect="keep or add moderate quality"),
    c("easy", ["Left knee pain 3/10"], P("Tempo run 8 km"),
      facts=["injury: Left knee pain since Monday"],
      expect="no running quality; swim or easy non-impact Z1-2"),
    c("recover", ["Fever 38.1"], P("Long run 18 km"), facts=["health: Flu since yesterday"],
      red=True, expect="rest"),
    c("normal", ["All good"], request="Make me a swim workout for today",
      expect="structured swim session"),
    c("easy", ["HRV 10% below baseline"], request="Something short, I only have 30 minutes",
      expect="<=30 min easy"),
    c("normal", ["No negative signals"], P("Strength 45 min"), expect="keep strength"),
    c("push", ["Everything good"], facts=["race: Half marathon in 3 weeks"],
      expect="quality run (threshold), specific to the half marathon"),
    c("recover", ["Sleep 3.5 h", "Exhausted"], request="Can I at least do something?",
      expect="rest or <=40 min Z1 walk/easy"),
    c("easy", ["2 glasses of wine"], P("Hill repeats 8x60 s"), expect="easy run Z1-2 instead"),
    c("normal", ["OK"], P("Long run 20 km"), facts=["goal: Half marathon in April"],
      expect="keep the long run, <=180 min"),
    c("easy", ["Stressful day"], sports=sports_b, request="I want to ride today",
      expect="easy ride Z1-2"),
    c("normal", ["No negative signals"], P("Sweet spot 3x12 min"), sports=sports_b,
      expect="keep bike intervals (Ride)"),
    c("recover", ["Calf strain 6/10, hurts walking"], P("Easy run 40 min"),
      facts=["injury: Right calf strain"], expect="rest, no running"),
    c("easy", ["Mild runny nose, no fever"], P("Intervals 5x1 km"), expect="easy Z1-2, shorter"),
    c("normal", ["Fine"], P("Easy run 45 min"),
      request="Replace today's run with a swim, the pool is closer",
      expect="swim about 45 min easy-moderate"),
    c("push", ["HRV high", "Fresh"], request="I want a hard workout",
      facts=["preference: Prefers track intervals"],
      expect="interval session with warmup and cooldown"),
    c("easy", ["Form -24, high fatigue"], P("Tempo 10 km"), expect="easy, shorter run"),
]

athletes = [
    {"id": "a1", "prefilled": {"height_cm": "182"}, "lang": "uk", "hidden": {
        "main_goal": "Half marathon under 1:45", "races": "Lviv Half Marathon on 12 April 2027",
        "sports": "Run 3x/week, Swim 1x/week, sometimes strength",
        "weekly_availability": "Mon, Wed, Fri mornings 1 h, Saturday long 2 h",
        "injuries_health": "Left knee pain sometimes after long runs", "medications": "none",
        "sleep_target_h": "8", "birth_year": "1997", "gear": "Nike Pegasus 41, 600 km"}},
    {"id": "a2", "prefilled": {}, "lang": "en", "hidden": {
        "main_goal": "Finish my first sprint triathlon", "races": "Kyiv Sprint Triathlon, June 2027",
        "sports": "Ride 4x/week, Run 2x/week, learning to swim",
        "weekly_availability": "Weekday evenings after 19:00, both weekend mornings",
        "injuries_health": "Asthma, uses an inhaler before hard sessions",
        "medications": "Salbutamol inhaler as needed", "sleep_target_h": "7.5",
        "height_cm": "176", "birth_year": "1993",
        "gear": "Canyon Endurace road bike, Hoka Clifton 9"}},
    {"id": "a3", "prefilled": {"height_cm": "168", "birth_year": "1988"}, "lang": "uk", "hidden": {
        "main_goal": "Lose 5 kg and run 10 km without stopping", "races": "none planned",
        "sports": "Run 2x/week, badminton on Sundays",
        "weekly_availability": "Tue and Thu evenings, Sunday morning",
        "injuries_health": "no injuries", "medications": "none", "sleep_target_h": "7",
        "gear": "Asics Gel-Nimbus 25"}},
    {"id": "a4", "prefilled": {}, "lang": "en", "hidden": {
        "main_goal": "Marathon under 3:30", "races": "Valencia Marathon, December 2027",
        "sports": "Run 5x/week, strength 2x/week",
        "weekly_availability": "Every morning 6:00-7:30, long run Sunday 3 h",
        "injuries_health": "Plantar fasciitis last year, now ok", "medications": "Vitamin D daily",
        "sleep_target_h": "8", "height_cm": "180", "birth_year": "1990",
        "gear": "Saucony Endorphin Speed, Garmin HRM"}},
    {"id": "a5", "prefilled": {"height_cm": "175"}, "lang": "uk", "hidden": {
        "main_goal": "Swim 3 km in open water", "races": "Dnipro open water swim, August 2027",
        "sports": "Swim 3x/week, Run 1x/week",
        "weekly_availability": "Pool Mon/Wed/Fri 7:00, run Saturday",
        "injuries_health": "Right shoulder impingement", "medications": "none",
        "sleep_target_h": "7.5", "birth_year": "1999", "gear": "Orca wetsuit, paddles"}},
]

c8_context = {
    "date": "2026-11-14",
    "profile": {"main_goal": "Half marathon under 1:45 in April", "height_cm": "182",
                "sport_settings": {"Run": {"lthr": 185, "max_hr": 204,
                                           "hr_zones_bpm": {"Z1": "up to 123", "Z2": "124-143",
                                                            "Z3": "144-164", "Z4": "165-184",
                                                            "Z5": "185-204"},
                                           "threshold_pace_per_km": "4:07"}},
                "weekly_availability": "Mon, Wed, Fri 1 h; Sat 2 h"},
    "facts": ["injury: Left knee pain since Monday", "gear: Nike Pegasus 41, 600 km",
              "race: Lviv Half Marathon on 12 April 2027"],
    "logs_yesterday_today": [
        {"day": "2026-11-13", "kind": "alcohol", "description": "4 пива", "alcohol_drinks": 6},
        {"day": "2026-11-14", "kind": "sleep", "description": "5 годин", "sleep_hours": 5},
        {"day": "2026-11-14", "kind": "meal", "description": "вівсянка з бананом",
         "nutrition": {"kcal": 320}}]}
c8 = [
    ("What is my zone 2 heart rate?", "Zone 2 is 124-143 bpm.", "answer"),
    ("Який у мене пороговий темп?", "4:07 на км.", "answer"),
    ("When is my race?", "Lviv Half Marathon, 12 April 2027.", "answer"),
    ("Скільки кілометрів на моїх кросівках?", "Nike Pegasus 41, 600 км.", "answer"),
    ("How much did I sleep last night?", "5 hours.", "answer"),
    ("Скільки я сьогодні з'їв калорій?", "Близько 320 ккал (вівсянка з бананом).", "answer"),
    ("What's my VO2max?", "Not in the context; must say it is missing.", "missing"),
    ("Скільки я важу?", "Ваги немає; має сказати, що даних немає.", "missing"),
    ("Did I drink yesterday?", "Yes, 4 beers (about 6 standard drinks).", "answer"),
    ("What is my FTP on the bike?", "No bike FTP in context; must say it is missing.", "missing"),
    ("Чи болить у мене щось?", "Ліве коліно з понеділка.", "answer"),
    ("How many days a week do I train?", "Mon, Wed, Fri and Sat: 4 days.", "answer"),
    ("What is my main goal?", "Half marathon under 1:45 in April.", "answer"),
    ("Який у мене пульс у спокої?", "Немає в контексті; має сказати, що даних немає.", "missing"),
    ("What's my max heart rate?", "204 bpm.", "answer"),
]


def write(name, rows):
    with open(D / name, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# B1: three weather cases (C12 advice in the input) on a normal running day.
_normal = next(x for x in c6 if x["inputs"]["day_type"] == "normal")


def _wx(flags, facts, heat, band):
    return {"day": {"t_max": 31 if heat != "none" else 8, "t_min": 18 if heat != "none" else 2,
                    "sunrise": "05:10", "sunset": "21:00", "air": "very poor" if
                    "indoors_aqi" in flags else "fair", "place": "Kyiv"},
            "session_hours": "18:00–19:00",
            "advice": {"pace_slower_pct": band, "heat_level": heat, "flags": flags,
                       "clothing": ["singlet", "shorts", "cap"], "best_hour": None,
                       "facts": facts}}


for _flags, _facts, _heat, _band, _expect in [
        (["indoors_aqi"], ["Air is very poor (European AQI above 80): intense sessions indoors, "
                           "or easy only."], "none", [0.0, 0.0],
         "indoor (treadmill/strength) or easy only; says the air is very poor"),
        (["storm"], ["Thunderstorm forecast: train indoors or move the session."], "none",
         [0.0, 0.0], "indoor option or moved session; mentions the thunderstorm"),
        ([], ["Heat and humidity slow running pace by about 4.5–6 %.", "Wear: singlet, shorts, "
              "cap."], "high", [4.5, 6.0],
         "easier or shorter, by HR not pace; mentions heat and the slower pace")]:
    c6.append({"inputs": _normal["inputs"] | {"weather": _wx(_flags, _facts, _heat, _band),
                                               "request": "What should I do today?"},
               "expect": _expect})
write("c6_planner.jsonl", [{"id": i, **x} for i, x in enumerate(c6)])
write("c0_interview.jsonl", athletes)
write("c8_reply.jsonl", [{"question": q, "expected": a, "type": t} for q, a, t in c8])
(D / "c8_context.json").write_text(json.dumps(c8_context, ensure_ascii=False, indent=1))
print(len(c6), len(athletes), len(c8))
