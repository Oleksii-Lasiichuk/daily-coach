"""Writes evals/data/c9_day_review.jsonl: 15 synthetic days for the C9 day review, each with
what a good review must notice (`expect`, checked by the judge). Hand-designed situations;
numbers are made up. Run: uv run python -m evals.make_c9_days"""

import json
from pathlib import Path

OUT = Path(__file__).parent / "data" / "c9_day_review.jsonl"
T_NORMAL = {"kcal": 2700, "protein_g": 135, "carbs_g": 375, "fat_g": 75, "fiber_g": 30,
            "sugar_g": 50, "salt_g": 5}
T_PUSH = T_NORMAL | {"kcal": 3100, "carbs_g": 490}
T_RECOVER = T_NORMAL | {"kcal": 2200, "carbs_g": 225}


def meal(time, what, kcal, p, c):
    return {"time": time, "what": what, "kcal": kcal, "protein_g": p, "carbs_g": c}


def day(i, lang, dtype, targets, eaten, meals, training=(), drinks=None, over=True):
    return {"id": f"d{i:02d}", "input": {
        "day": f"2026-11-{i:02d}", "lang": lang, "day_is_over": over, "day_type": dtype,
        "targets": targets, "eaten": eaten, "meals_logged": len(meals), "meals": meals,
        "drinks": drinks or {"water_l": 1.5, "caffeine_mg": 95, "alcohol_g": 0},
        "training": list(training)}}


CASES = [
    (day(1, "en", "normal", T_NORMAL, {"kcal": 2650, "protein_g": 95, "carbs_g": 380, "fat_g": 70,
         "fiber_g": 31, "sugar_g": 45, "salt_g": 4},
         [meal("08:00", "Oatmeal with banana", 480, 14, 86), meal("13:00", "Pasta bolognese", 850,
          35, 110), meal("19:30", "Rice with vegetables", 700, 15, 130), meal("16:00",
          "Apple and crackers", 300, 4, 60)]), "protein about 40 g under target"),
    (day(2, "uk", "push", T_PUSH, {"kcal": 1900, "protein_g": 120, "carbs_g": 210, "fat_g": 60,
         "fiber_g": 25, "sugar_g": 30, "salt_g": 4},
         [meal("07:00", "Яйця з тостом", 450, 25, 35), meal("13:00", "Гречка з куркою", 690, 46,
          72), meal("20:00", "Сир кисломолочний", 300, 36, 10)],
         [{"type": "Run", "minutes": 95, "km": 18, "kcal": 1300}]),
     "carbs far under target on a hard day with a long run"),
    (day(3, "en", "easy", T_NORMAL | {"kcal": 2400, "carbs_g": 300}, {"kcal": 2450, "protein_g":
         140, "carbs_g": 290, "fat_g": 80, "fiber_g": 12, "sugar_g": 40, "salt_g": 5},
         [meal("09:00", "Eggs and bacon", 600, 35, 5), meal("13:00", "Burger and fries", 1100, 45,
          110), meal("19:00", "Steak with potatoes", 750, 60, 70)]), "fibre very low (12 of 30)"),
    (day(4, "uk", "normal", T_NORMAL, {"kcal": 2800, "protein_g": 130, "carbs_g": 360, "fat_g":
         80, "fiber_g": 28, "sugar_g": 95, "salt_g": 5},
         [meal("08:00", "Каша з медом", 520, 12, 100), meal("12:30", "Борщ і хліб", 600, 20, 80),
          meal("16:00", "Тістечко і кола", 650, 5, 110), meal("19:30", "Курка з рисом", 750, 50,
          80)]), "sugar almost double the limit (cake and cola)"),
    (day(5, "en", "normal", T_NORMAL, {"kcal": 520, "protein_g": 20, "carbs_g": 70, "fat_g": 15,
         "fiber_g": 6, "sugar_g": 20, "salt_g": 1},
         [meal("08:30", "Coffee with milk and a croissant", 520, 20, 70)]),
     "only one meal logged: says the log may be incomplete"),
    (day(6, "uk", "recover", T_RECOVER, {"kcal": 2300, "protein_g": 110, "carbs_g": 240,
         "fat_g": 85, "fiber_g": 22, "sugar_g": 35, "salt_g": 6},
         [meal("09:00", "Омлет", 400, 25, 5), meal("14:00", "Піца", 900, 35, 100),
          meal("20:00", "Салат з тунцем", 450, 35, 20)],
         drinks={"water_l": 0.8, "caffeine_mg": 190, "alcohol_g": 60}),
     "alcohol 60 g on a recovery day"),
    (day(7, "en", "push", T_PUSH, {"kcal": 3150, "protein_g": 150, "carbs_g": 500, "fat_g": 80,
         "fiber_g": 35, "sugar_g": 55, "salt_g": 6},
         [meal("06:30", "Bagel with honey and banana", 600, 15, 120), meal("10:30",
          "Recovery shake", 350, 30, 50), meal("13:30", "Rice bowl with salmon", 900, 45, 120),
          meal("19:30", "Pasta with chicken", 950, 55, 130)],
         [{"type": "Ride", "minutes": 150, "km": 70, "kcal": 1800}]),
     "a good hard day: energy and carbs close to target"),
    (day(8, "uk", "normal", T_NORMAL, {"kcal": 3600, "protein_g": 140, "carbs_g": 420, "fat_g":
         140, "fiber_g": 24, "sugar_g": 60, "salt_g": 9},
         [meal("09:00", "Сирники зі сметаною", 700, 30, 60), meal("13:00", "Шаурма", 900, 40, 80),
          meal("19:00", "Вареники з картоплею і шкварками", 1200, 30, 150), meal("22:30",
          "Чипси і пиво", 800, 8, 80)]), "energy or fat well over target"),
    (day(9, "en", "easy", T_NORMAL | {"kcal": 2400, "carbs_g": 300}, {"kcal": 2380, "protein_g":
         132, "carbs_g": 305, "fat_g": 72, "fiber_g": 33, "sugar_g": 38, "salt_g": 4},
         [meal("08:00", "Greek yogurt with berries and oats", 500, 30, 60), meal("12:30",
          "Lentil soup and bread", 650, 32, 95), meal("16:00", "Apple and nuts", 300, 8, 25),
          meal("19:30", "Chicken with buckwheat and salad", 930, 62, 125)]),
     "a well balanced day close to all targets; nothing big to fix"),
    (day(10, "uk", "normal", T_NORMAL, {"kcal": 2500, "protein_g": 150, "carbs_g": 330,
          "fat_g": 70, "fiber_g": 30, "sugar_g": 40, "salt_g": 4},
          [meal("08:00", "Вівсянка", 450, 15, 75), meal("13:00", "Курка з рисом", 750, 55, 90),
           meal("19:00", "Риба з овочами", 600, 45, 40), meal("21:00", "Протеїновий батончик",
           250, 20, 25)], over=False), "the day is not over: speaks about so far today, tip for the rest of today"),
    (day(11, "en", "push", T_PUSH, {"kcal": 2900, "protein_g": 140, "carbs_g": 420, "fat_g": 85,
          "fiber_g": 30, "sugar_g": 50, "salt_g": 5},
          [meal("12:00", "Big lunch: rice, chicken, salad", 1100, 60, 140), meal("19:00",
           "Pasta", 900, 35, 150), meal("21:30", "Oatmeal", 500, 20, 80)],
          [{"type": "Run", "minutes": 70, "km": 14, "kcal": 900}]),
     "no breakfast: first meal at 12:00 on a hard training day"),
    (day(12, "uk", "easy", T_NORMAL | {"kcal": 2400, "carbs_g": 300}, {"kcal": 2350,
          "protein_g": 70, "carbs_g": 380, "fat_g": 60, "fiber_g": 27, "sugar_g": 48,
          "salt_g": 4}, [meal("08:00", "Млинці з варенням", 600, 12, 100), meal("13:00",
           "Овочевий суп і хліб", 500, 12, 80), meal("19:00", "Макарони з томатним соусом", 800,
           25, 140), meal("16:00", "Банан", 110, 1, 27)]), "protein half the target (70 of 135)"),
    (day(13, "en", "recover", T_RECOVER, {"kcal": 2150, "protein_g": 128, "carbs_g": 230,
          "fat_g": 70, "fiber_g": 29, "sugar_g": 35, "salt_g": 4},
          [meal("08:30", "Cottage cheese with fruit", 400, 30, 40), meal("13:00",
           "Chicken soup", 550, 40, 50), meal("19:00", "Salmon, potatoes, broccoli", 800, 48,
           70)], drinks={"water_l": 2.4, "caffeine_mg": 95, "alcohol_g": 0}),
     "a good recovery day: targets close, nothing big to fix"),
    (day(14, "uk", "normal", T_NORMAL, {"kcal": 2650, "protein_g": 135, "carbs_g": 350,
          "fat_g": 80, "fiber_g": 30, "sugar_g": 45, "salt_g": 5},
          [meal("08:00", "Кава", 5, 0, 1), meal("08:05", "Кава", 5, 0, 1), meal("10:00", "Кава",
           5, 0, 1), meal("13:00", "Борщ, котлета, пюре", 1200, 60, 120), meal("19:00",
           "Курка з булгуром", 1435, 75, 228)],
          drinks={"water_l": 0.5, "caffeine_mg": 480, "alcohol_g": 0}),
     "caffeine 480 mg over the 400 mg limit"),
    (day(15, "en", "normal", T_NORMAL, {"kcal": 2700, "protein_g": 135, "carbs_g": 375,
          "fat_g": 75, "fiber_g": 30, "sugar_g": 50, "salt_g": 11},
          [meal("08:00", "Ham and cheese sandwich", 500, 25, 45), meal("13:00",
           "Instant noodles and sausages", 900, 30, 100), meal("19:00",
           "Pizza with salami", 1300, 80, 230)]), "salt about double the limit (11 g of 5)"),
]


if __name__ == "__main__":
    with OUT.open("w") as f:
        for case, expect in CASES:
            f.write(json.dumps(case | {"expect": expect}, ensure_ascii=False) + "\n")
    print(OUT, len(CASES))
