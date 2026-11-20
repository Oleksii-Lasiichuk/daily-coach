"""Lab marker catalogue for C10: canonical key, names in EN/UA/RU, canonical unit, unit
conversions to it, and a default reference range (used only when the sheet prints none).

Names are matched after `key()` (lower case, no spaces, dots or brackets). Conversions are
factors: value_in_canonical = value * factor.
"""

import re

# key: (EN name, UA name, aliases, canonical unit, {other unit: factor}, default (low, high))
MARKERS: dict[str, tuple] = {
    "wbc": ("White blood cells", "Лейкоцити",
            ["WBC", "Leukocytes", "Лейкоцити", "Лейкоциты"], "10^9/L",
            {"10^3/µL": 1, "тис/мкл": 1}, (4.0, 9.0)),
    "rbc": ("Red blood cells", "Еритроцити",
            ["RBC", "Erythrocytes", "Еритроцити", "Эритроциты"], "10^12/L",
            {"10^6/µL": 1, "млн/мкл": 1}, (4.0, 5.5)),
    "hgb": ("Haemoglobin", "Гемоглобін",
            ["HGB", "Hb", "Hemoglobin", "Haemoglobin", "Гемоглобін", "Гемоглобин"], "g/L",
            {"g/dL": 10}, (120, 170)),
    "hct": ("Haematocrit", "Гематокрит",
            ["HCT", "Hematocrit", "Haematocrit", "Гематокрит"], "%", {}, (36, 50)),
    "mcv": ("MCV", "Середній об'єм еритроцита",
            ["MCV", "Середній об'єм еритроцита", "Средний объем эритроцита"], "fL", {"фл": 1},
            (80, 100)),
    "mch": ("MCH", "Середній вміст гемоглобіну",
            ["MCH", "Середній вміст гемоглобіну в еритроциті", "Середній вміст гемоглобіну",
             "Среднее содержание гемоглобина"], "pg", {"пг": 1}, (27, 34)),
    "mchc": ("MCHC", "Середня концентрація гемоглобіну",
             ["MCHC", "Середня концентрація гемоглобіну в еритроциті",
              "Середня концентрація гемоглобіну"], "g/L", {"g/dL": 10}, (320, 360)),
    "plt": ("Platelets", "Тромбоцити",
            ["PLT", "Platelets", "Тромбоцити", "Тромбоциты"], "10^9/L",
            {"10^3/µL": 1, "тис/мкл": 1}, (150, 400)),
    "neut": ("Neutrophils", "Нейтрофіли",
             ["NEUT", "Neutrophils", "Нейтрофіли", "Нейтрофилы", "NEU%"], "%", {}, (47, 72)),
    "lymph": ("Lymphocytes", "Лімфоцити",
              ["LYMPH", "LYM", "Lymphocytes", "Лімфоцити", "Лимфоциты", "LYM%"], "%", {},
              (19, 37)),
    "mono": ("Monocytes", "Моноцити",
             ["MONO", "MON", "Monocytes", "Моноцити", "Моноциты", "MON%"], "%", {}, (3, 11)),
    "eos": ("Eosinophils", "Еозинофіли",
            ["EOS", "Eosinophils", "Еозинофіли", "Эозинофилы", "EOS%"], "%", {}, (0.5, 5)),
    "baso": ("Basophils", "Базофіли",
             ["BASO", "BAS", "Basophils", "Базофіли", "Базофилы", "BAS%"], "%", {}, (0, 1)),
    "esr": ("ESR", "ШОЕ", ["ESR", "ШОЕ", "ШОЭ", "СОЕ"], "mm/h", {"мм/год": 1, "мм/ч": 1},
            (2, 15)),
    "ferritin": ("Ferritin", "Феритин", ["Ferritin", "Феритин", "Ферритин"], "µg/L",
                 {"ng/mL": 1, "нг/мл": 1, "мкг/л": 1}, (30, 400)),
    "iron": ("Iron", "Залізо", ["Iron", "Serum iron", "Залізо", "Залізо сироватки",
                                "Железо", "Fe"], "µmol/L", {"µg/dL": 0.179, "мкмоль/л": 1},
             (10.7, 32.2)),
    "transferrin_sat": ("Transferrin saturation", "Насичення трансферину",
                        ["Transferrin saturation", "TSAT", "Насичення трансферину",
                         "Насыщение трансферрина"], "%", {}, (20, 50)),
    "vitamin_d": ("Vitamin D (25-OH)", "Вітамін D (25-OH)",
                  ["Vitamin D", "25-OH Vitamin D", "Vitamin D 25-OH", "25(OH)D",
                   "Вітамін D", "Вітамін D (25-OH)", "25-ОН вітамін D", "Витамин D"],
                  "nmol/L", {"ng/mL": 2.496, "нг/мл": 2.496, "нмоль/л": 1}, (75, 250)),
    "b12": ("Vitamin B12", "Вітамін B12", ["Vitamin B12", "B12", "Cobalamin", "Вітамін B12",
                                          "Вітамін В12", "Витамин B12", "Кобаламін"],
            "pmol/L", {"pg/mL": 0.738, "пг/мл": 0.738, "пмоль/л": 1}, (145, 569)),
    "folate": ("Folate", "Фолієва кислота", ["Folate", "Folic acid", "Фолієва кислота",
                                             "Фолати", "Фолиевая кислота"], "nmol/L",
               {"ng/mL": 2.266, "нг/мл": 2.266, "нмоль/л": 1}, (10.4, 42.4)),
    "tsh": ("TSH", "ТТГ", ["TSH", "ТТГ", "Тиреотропний гормон", "Тиреотропный гормон"],
            "mIU/L", {"µIU/mL": 1, "мкМО/мл": 1, "мМО/л": 1}, (0.4, 4.0)),
    "ft4": ("Free T4", "Т4 вільний", ["Free T4", "FT4", "fT4", "Т4 вільний", "Т4 свободный",
                                      "Вільний тироксин"], "pmol/L", {"ng/dL": 12.87,
                                                                      "пмоль/л": 1},
            (12, 22)),
    "cortisol": ("Cortisol", "Кортизол", ["Cortisol", "Кортизол"], "nmol/L",
                 {"µg/dL": 27.59, "нмоль/л": 1}, (138, 635)),
    "testosterone": ("Testosterone", "Тестостерон", ["Testosterone", "Total testosterone",
                                                     "Тестостерон", "Тестостерон загальний"],
                     "nmol/L", {"ng/dL": 1 / 28.84, "ng/mL": 3.467, "нмоль/л": 1},
                     (8.6, 29)),
    "crp": ("C-reactive protein", "С-реактивний білок",
            ["CRP", "hs-CRP", "C-reactive protein", "С-реактивний білок", "СРБ",
             "С-реактивный белок"], "mg/L", {"мг/л": 1, "mg/dL": 10}, (0, 5)),
    "alt": ("ALT", "АЛТ", ["ALT", "ALAT", "АЛТ", "Аланінамінотрансфераза"], "U/L",
            {"Од/л": 1, "Ед/л": 1, "IU/L": 1}, (0, 41)),
    "ast": ("AST", "АСТ", ["AST", "ASAT", "АСТ", "Аспартатамінотрансфераза"], "U/L",
            {"Од/л": 1, "Ед/л": 1, "IU/L": 1}, (0, 40)),
    "ck": ("Creatine kinase", "Креатинкіназа", ["CK", "CPK", "Creatine kinase",
                                                "Креатинкіназа", "Креатинкиназа", "КФК"],
           "U/L", {"Од/л": 1, "Ед/л": 1, "IU/L": 1}, (0, 190)),
    "creatinine": ("Creatinine", "Креатинін", ["Creatinine", "Креатинін", "Креатинин"],
                   "µmol/L", {"mg/dL": 88.4, "мкмоль/л": 1}, (62, 106)),
    "glucose": ("Glucose", "Глюкоза", ["Glucose", "Fasting glucose", "Глюкоза",
                                       "Глюкоза натще"], "mmol/L",
                {"mg/dL": 1 / 18, "ммоль/л": 1}, (3.9, 5.6)),
    "hba1c": ("HbA1c", "Глікований гемоглобін", ["HbA1c", "Glycated haemoglobin",
                                                 "Глікований гемоглобін",
                                                 "Гликированный гемоглобин"], "%", {},
              (4.0, 5.7)),
    "chol_total": ("Total cholesterol", "Холестерин загальний",
                   ["Total cholesterol", "Cholesterol", "Холестерин загальний", "Холестерин",
                    "Холестерин общий"], "mmol/L", {"mg/dL": 1 / 38.67, "ммоль/л": 1},
                   (0, 5.2)),
    "ldl": ("LDL cholesterol", "ЛПНЩ", ["LDL", "LDL cholesterol", "ЛПНЩ", "ЛПНП",
                                        "Холестерин ЛПНЩ"], "mmol/L",
            {"mg/dL": 1 / 38.67, "ммоль/л": 1}, (0, 3.0)),
    "hdl": ("HDL cholesterol", "ЛПВЩ", ["HDL", "HDL cholesterol", "ЛПВЩ", "ЛПВП",
                                        "Холестерин ЛПВЩ"], "mmol/L",
            {"mg/dL": 1 / 38.67, "ммоль/л": 1}, (1.0, 3.0)),
    "triglycerides": ("Triglycerides", "Тригліцериди", ["Triglycerides", "TG", "Тригліцериди",
                                                        "Триглицериды"], "mmol/L",
                      {"mg/dL": 1 / 88.57, "ммоль/л": 1}, (0, 1.7)),
    "magnesium": ("Magnesium", "Магній", ["Magnesium", "Mg", "Магній", "Магний"], "mmol/L",
                  {"mg/dL": 0.4114, "ммоль/л": 1}, (0.66, 1.07)),
    "calcium": ("Calcium", "Кальцій", ["Calcium", "Ca", "Кальцій", "Кальций",
                                       "Кальцій загальний"], "mmol/L",
                {"mg/dL": 0.2495, "ммоль/л": 1}, (2.15, 2.55)),
    "sodium": ("Sodium", "Натрій", ["Sodium", "Na", "Натрій", "Натрий"], "mmol/L",
               {"ммоль/л": 1, "mEq/L": 1}, (136, 145)),
    "potassium": ("Potassium", "Калій", ["Potassium", "K", "Калій", "Калий"], "mmol/L",
                  {"ммоль/л": 1, "mEq/L": 1}, (3.5, 5.1)),
}

# Printed unit spellings → one spelling (before conversion).
UNIT_ALIASES = {
    "ug/l": "µg/L", "мкг/л": "µg/L", "μg/l": "µg/L", "ng/ml": "ng/mL", "нг/мл": "ng/mL",
    "g/l": "g/L", "г/л": "g/L", "g/dl": "g/dL", "г/дл": "g/dL", "%": "%",
    "fl": "fL", "фл": "fL", "pg": "pg", "пг": "pg", "pg/ml": "pg/mL", "пг/мл": "pg/mL",
    "pmol/l": "pmol/L", "пмоль/л": "pmol/L", "nmol/l": "nmol/L", "нмоль/л": "nmol/L",
    "umol/l": "µmol/L", "μmol/l": "µmol/L", "мкмоль/л": "µmol/L", "mmol/l": "mmol/L",
    "ммоль/л": "mmol/L", "mg/dl": "mg/dL", "мг/дл": "mg/dL", "mg/l": "mg/L", "мг/л": "mg/L",
    "ug/dl": "µg/dL", "μg/dl": "µg/dL", "мкг/дл": "µg/dL", "ng/dl": "ng/dL", "нг/дл": "ng/dL",
    "u/l": "U/L", "iu/l": "U/L", "од/л": "U/L", "ед/л": "U/L", "мо/л": "U/L",
    "miu/l": "mIU/L", "мод/л": "mIU/L", "ммо/л": "mIU/L", "uiu/ml": "mIU/L", "μiu/ml": "mIU/L",
    "мкмо/мл": "mIU/L", "мкод/мл": "mIU/L",
    "10^9/l": "10^9/L", "10*9/l": "10^9/L", "x10^9/l": "10^9/L", "тис/мкл": "10^9/L",
    "10^3/ul": "10^9/L", "10^12/l": "10^12/L", "10*12/l": "10^12/L", "x10^12/l": "10^12/L",
    "млн/мкл": "10^12/L", "10^6/ul": "10^12/L",
    "mm/h": "mm/h", "мм/год": "mm/h", "мм/ч": "mm/h", "mm/hr": "mm/h",
}


def key(name: str) -> str:
    return re.sub(r"[\s.,()\-'’ʼ]", "", (name or "").lower()).replace("в12", "b12")


_ALIAS = {key(a): k for k, m in MARKERS.items() for a in [m[0], m[1], *m[2]]}


def find(name: str) -> str | None:
    """Canonical marker key for a printed name, or None (unknown marker)."""
    k = key(name)
    if k in _ALIAS:
        return _ALIAS[k]
    for alias, marker in sorted(_ALIAS.items(), key=lambda x: -len(x[0])):
        if len(alias) >= 5 and (k.startswith(alias) or alias in k):
            return marker
    return None


def unit(printed: str) -> str:
    u = (printed or "").strip().lower().replace("μ", "u").replace("µ", "u").replace("×", "x")
    u = u.replace(" ", "")
    return UNIT_ALIASES.get(u, UNIT_ALIASES.get(u.replace("u", "μ"), (printed or "").strip()))


def factor(marker: str, printed_unit: str) -> float | None:
    """Multiply by this to get the canonical unit; None when the unit is unknown for it."""
    canon, conv = MARKERS[marker][3], MARKERS[marker][4]
    u = unit(printed_unit)
    if not u or u == canon:
        return 1.0
    for other, f in conv.items():
        if unit(other) == u:
            return f
    return None


def name(marker: str, lang: str = "en") -> str:
    return MARKERS[marker][1 if lang == "uk" else 0]
