"""Builds evals/data/c13_calendar.jsonl: 15 synthetic calendar days for C13 + C6.
Each case = the athlete context of C6 case 2 (a normal day) + that day's busy blocks (local
Europe/Kyiv times) + tomorrow's blocks. `expect.sleep_warning`: the case was built so the calendar
leaves too little sleep; `expect.no_slot`: no free window long enough for a normal session.
Run: uv run python -m evals.make_c13_days"""

import json

from evals.common import DATA, load

DAYS = [  # (id, date, label, today blocks, tomorrow blocks, sleep_warning, no_slot)
    ("office", "2026-11-18", "office day 09-18 with lunch", [["09:00", "12:30"], ["13:30", "18:00"]],
     [["09:00", "18:00"]], False, False),
    ("office_evening", "2026-11-19", "office day + evening dinner", [["09:00", "17:30"], ["19:30", "21:30"]],
     [["10:00", "11:00"]], False, False),
    ("shift_night", "2026-11-17", "night shift worker 20:00-06:00", [["14:00", "15:00"], ["20:00", "23:59"]],
     [["00:00", "06:00"]], True, False),
    ("shift_early", "2026-11-16", "early shift 06:00-14:00", [["06:00", "14:00"]],
     [["06:00", "14:00"]], True, False),
    ("b2b_lunch45", "2026-11-18", "back-to-back meetings, 45-min lunch gap",
     [["08:30", "12:00"], ["12:45", "18:30"]], [], False, False),
    ("b2b_short_gaps", "2026-11-20", "meetings with only 20-min gaps",
     [["08:00", "10:00"], ["10:20", "12:00"], ["12:20", "15:00"], ["15:20", "18:00"], ["18:20", "22:30"]],
     [], False, True),
    ("travel_flight", "2026-11-20", "late call, 07:00 flight tomorrow",
     [["10:00", "12:00"], ["13:15", "15:30"], ["16:00", "18:30"], ["22:00", "23:00"]],
     [["07:00", "09:30"]], True, False),
    ("weekend_morning", "2026-11-21", "weekend, long free morning", [["13:00", "16:00"]],
     [], False, False),
    ("weekend_empty", "2026-11-22", "empty Sunday", [], [], False, False),
    ("no_window", "2026-11-18", "conference all day 07:00-22:30",
     [["07:00", "12:15"], ["12:45", "17:00"], ["17:30", "22:30"]], [], False, True),
    ("standups_dst", "2026-10-26", "recurring standups the day after the DST switch",
     [["09:30", "09:45"], ["10:00", "17:00"]], [["09:30", "09:45"]], False, False),
    ("evening_only", "2026-11-19", "busy 07:00-19:00, free evening", [["07:00", "19:00"]],
     [["09:00", "10:00"]], False, False),
    ("midday_gap", "2026-11-17", "free only 11:30-14:30", [["07:00", "11:00"], ["15:00", "22:30"]],
     [], False, False),
    ("late_party", "2026-11-21", "party until 01:00, brunch 08:00", [["20:00", "23:59"]],
     [["00:00", "01:00"], ["08:00", "10:00"]], True, False),
    ("doctor_morning", "2026-11-16", "doctor 08:00-09:00 then office", [["08:00", "09:00"], ["10:00", "18:00"]],
     [], False, False),
]


def main():
    base = load("c6_planner.jsonl")[2]["inputs"]
    with open(DATA / "c13_calendar.jsonl", "w") as f:
        for cid, day, label, today, tomorrow, warn, no_slot in DAYS:
            inputs = base | {"date": day, "day_type": "normal", "reasons": ["Normal recovery"],
                             "planned_today": "nothing stated",
                             "request": "What should I do today?"}
            f.write(json.dumps({"id": cid, "label": label, "inputs": inputs, "blocks": today,
                                "tomorrow": tomorrow, "expect": {"sleep_warning": warn,
                                                                 "no_slot": no_slot}},
                               ensure_ascii=False) + "\n")
    print(f"wrote {len(DAYS)} days")


if __name__ == "__main__":
    main()
