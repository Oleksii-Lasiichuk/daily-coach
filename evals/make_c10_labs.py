"""Synthetic lab sheets for the C10 eval (no real report in git): 15 sheets, ~20 rows each,
fake values, three made-up layouts in the style of common UA lab tables (no real forms or
logos), Ukrainian and English, with distractors (patient name, birth date, order number,
doctor, a second date, a comment paragraph).

Kinds: 5 clean PNG, 5 "phone photos" (rotation, blur, shadow, JPEG), 5 text PDFs (matplotlib).
Labels: evals/data/c10_labs.jsonl (canonical marker, value, unit, range, flag per row).
Run: uv run python -m evals.make_c10_labs
"""

import json
import random
import textwrap
from datetime import date, timedelta
from pathlib import Path

import matplotlib
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app import lab_catalog as cat

matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42  # real text in the PDF, so pypdf can read it
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path(__file__).parent / "data" / "c10_labs"
LABELS = Path(__file__).parent / "data" / "c10_labs.jsonl"
FONT = str(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf")
FONT_B = str(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans-Bold.ttf")

PATIENT = {"uk": "Тест Тестенко", "en": "Test Testenko"}
LABS = ["ЛабТест", "Лабораторія Здоров'я", "MedLab Demo", "Діагностика Плюс", "CityLab Demo"]
UA_UNIT = {"g/L": "г/л", "mmol/L": "ммоль/л", "µmol/L": "мкмоль/л", "µg/L": "мкг/л",
           "nmol/L": "нмоль/л", "pmol/L": "пмоль/л", "U/L": "Од/л", "mIU/L": "мМО/л",
           "10^9/L": "10^9/л", "10^12/L": "10^12/л", "mm/h": "мм/год", "fL": "фл", "pg": "пг",
           "%": "%", "mg/L": "мг/л"}
# Other units a lab may print: marker → (EN spelling, UA spelling)
ALT_UNIT = {"vitamin_d": ("ng/mL", "нг/мл"), "ferritin": ("ng/mL", "нг/мл"),
            "hgb": ("g/dL", None), "glucose": ("mg/dL", None), "testosterone": ("ng/dL", None),
            "b12": ("pg/mL", "пг/мл"), "chol_total": ("mg/dL", None)}
UNKNOWN = {"uk": [("Прокальцитонін", "0,03", "нг/мл", "< 0,05"),
                  ("Гомоцистеїн", "11,2", "мкмоль/л", "5 - 15"),
                  ("Антитіла до ТПО", "12", "МО/мл", "< 34")],
           "en": [("Procalcitonin", "0.03", "ng/mL", "< 0.05"),
                  ("Homocysteine", "11.2", "µmol/L", "5 - 15"),
                  ("Anti-TPO antibodies", "12", "IU/mL", "< 34")]}
COMMENT = {"uk": "Коментар: результати слід інтерпретувати разом з лікарем. Повторіть аналіз "
                 "через 3 місяці. Зразок доставлено в контейнері № 55-019.",
           "en": "Comment: results should be interpreted by your doctor together with other "
                 "findings. Repeat in 3 months. Sample delivered in container no. 55-019."}


def fmt(x: float, dec: int, lang: str) -> str:
    s = f"{x:.{dec}f}"
    return s.replace(".", ",") if lang == "uk" else s


def gold_flag(v, q, lo, hi) -> str:
    if lo is not None and v < lo and q != ">":
        return "low"
    if hi is not None and v > hi and q != "<":
        return "high"
    return "in"


def make_row(rnd: random.Random, marker: str, lang: str) -> tuple[dict, dict]:
    en, ua, aliases, canon, conv, (lo, hi) = cat.MARKERS[marker]
    alt = ALT_UNIT.get(marker)
    unit_printed = canon if lang == "en" else UA_UNIT[canon]
    f = 1.0
    if alt and rnd.random() < 0.5 and (alt[0] if lang == "en" else alt[1]):
        unit_printed = alt[0] if lang == "en" else alt[1]
        f = cat.factor(marker, unit_printed)
    # the lab's own range, sometimes a little different from the catalogue default
    shift = rnd.choice([1.0, 1.0, 0.9, 1.1])
    plo, phi = lo * shift / f, hi * shift / f
    span = (phi - plo) or phi
    dec = 0 if phi >= 100 else 1 if phi >= 5 else 2
    roll = rnd.random()
    if plo <= 0:  # "up to X" markers: no "low", and no silly near-zero values
        plo, roll = 0.0, max(roll, 0.15)
    v = (plo - span * rnd.uniform(0.05, 0.3) if roll < 0.15 else
         phi + span * rnd.uniform(0.05, 0.3) if roll < 0.3 else rnd.uniform(max(plo, 0.3 * phi), phi))
    v = max(round(v, dec), 10 ** -dec)
    q = None
    printed = fmt(v, dec, lang)
    if marker == "crp" and rnd.random() < 0.5:
        q, v, printed = "<", 0.5, "<" + fmt(0.5, 1, lang)
    plo_s, phi_s = round(plo, dec), round(phi, dec)
    if plo_s <= 0:
        ref = ("до " if lang == "uk" else "< ") + fmt(phi_s, dec, lang)
        glo, ghi = None, phi_s
    else:
        ref = f"{fmt(plo_s, dec, lang)} - {fmt(phi_s, dec, lang)}"
        glo, ghi = plo_s, phi_s
    flag = gold_flag(v, q, glo, ghi)
    if flag != "in" and rnd.random() < 0.5:
        printed += " ↑" if flag == "high" else " ↓"
    name = ua if lang == "uk" else en
    if rnd.random() < 0.4 and aliases[0] != name and aliases[0].isascii():
        name = f"{name} ({aliases[0]})"
    printed_row = {"name": name, "value": printed, "unit": unit_printed, "ref": ref}
    gold = {"marker": marker, "name_as_printed": name, "value": round(v * f, 3), "qualifier": q,
            "unit": canon, "ref_low": None if glo is None else round(glo * f, 3),
            "ref_high": round(ghi * f, 3), "flag": flag}
    return printed_row, gold


def make_sheet(i: int) -> dict:
    rnd = random.Random(1000 + i)
    lang = "en" if i % 5 in (1, 3) else "uk"
    kind = ["png", "photo", "pdf"][i // 5]
    layout = i % 3
    markers = rnd.sample(sorted(cat.MARKERS), 18)
    printed, gold = [], []
    for m in markers:
        p, g = make_row(rnd, m, lang)
        printed.append(p)
        gold.append(g)
    for name, val, unit, ref in rnd.sample(UNKNOWN[lang], 2):
        printed.insert(rnd.randrange(len(printed)), {"name": name, "value": val, "unit": unit,
                                                      "ref": ref})
        gold.append({"marker": None, "name_as_printed": name,
                     "value": float(val.replace(",", ".")), "qualifier": None, "unit": None,
                     "ref_low": None, "ref_high": None, "flag": "in"})
    taken = date(2026, 1, 10) + timedelta(days=rnd.randrange(300))
    order = f"{rnd.randrange(1000, 9999)}-{rnd.randrange(1000, 9999)}-{rnd.randrange(10, 99)}"
    return {"id": f"lab{i:02d}", "lang": lang, "kind": kind, "layout": layout,
            "lab": rnd.choice(LABS), "taken_on": taken.isoformat(),
            "issued": (taken + timedelta(days=2)).isoformat(), "order": order,
            "patient": PATIENT[lang], "birth": f"{rnd.randrange(1,28):02d}.0{rnd.randrange(1,9)}."
            f"{rnd.randrange(1960, 2005)}", "printed": printed, "rows": gold}


def d(iso: str, lang: str) -> str:
    y, m, dd = iso.split("-")
    return f"{dd}.{m}.{y}" if lang == "uk" else f"{dd}/{m}/{y}"


def lines(s: dict) -> tuple[list[str], list[str], list[list[str]], str]:
    """Header lines, column titles, table rows, comment: the same text for PNG and PDF."""
    uk = s["lang"] == "uk"
    head = [s["lab"] + (" · медична лабораторія" if uk else " · medical laboratory"),
            (f"Пацієнт: {s['patient']}   Дата народження: {s['birth']}" if uk else
             f"Patient: {s['patient']}   Date of birth: {s['birth']}"),
            (f"Замовлення № {s['order']}   Лікар: Іваненко І. І." if uk else
             f"Order no. {s['order']}   Physician: Dr. I. Ivanenko"),
            (f"Дата взяття біоматеріалу: {d(s['taken_on'], 'uk')}   Дата видачі: "
             f"{d(s['issued'], 'uk')}" if uk else
             f"Sample taken: {d(s['taken_on'], 'en')}   Report issued: {d(s['issued'], 'en')}")]
    cols = {0: ["Показник", "Результат", "Од. вим.", "Референтні значення"] if uk else
            ["Test", "Result", "Units", "Reference range"],
            1: ["Дослідження", "Результат", "Норма", "Одиниці"] if uk else
            ["Analyte", "Result", "Reference", "Units"],
            2: ["Назва тесту", "Результат", "Референтний інтервал"] if uk else
            ["Test name", "Result", "Reference interval"]}[s["layout"]]
    rows = []
    for p in s["printed"]:
        if s["layout"] == 0:
            rows.append([p["name"], p["value"], p["unit"], p["ref"]])
        elif s["layout"] == 1:
            rows.append([p["name"], p["value"], p["ref"], p["unit"]])
        else:
            rows.append([p["name"], f"{p['value']} {p['unit']}", f"{p['ref']} {p['unit']}"])
    return head, cols, rows, COMMENT[s["lang"]]


def render_png(s: dict) -> Image.Image:
    head, cols, rows, comment = lines(s)
    W, H = 1500, 300 + 52 * (len(rows) + 1) + 200
    img = Image.new("RGB", (W, H), "white")
    dr = ImageDraw.Draw(img)
    f, fb, fs = (ImageFont.truetype(FONT, 26), ImageFont.truetype(FONT_B, 26),
                 ImageFont.truetype(FONT, 22))
    dr.text((60, 40), head[0], font=ImageFont.truetype(FONT_B, 34), fill="black")
    for k, h in enumerate(head[1:]):
        dr.text((60, 100 + 40 * k), h, font=fs, fill=(60, 60, 60))
    xs = [60, 660, 900, 1150] if len(cols) == 4 else [60, 660, 1000]
    y = 260
    dr.rectangle([50, y - 8, W - 50, y + 40], fill=(225, 232, 240))
    for x, c in zip(xs, cols, strict=True):
        dr.text((x, y), c, font=fb, fill="black")
    for r in rows:
        y += 52
        dr.line([(50, y - 10), (W - 50, y - 10)], fill=(210, 210, 210))
        for x, c in zip(xs, r, strict=True):
            bad = "↑" in c or "↓" in c
            dr.text((x, y), c, font=fb if bad else f, fill="black")
    for k, part in enumerate(textwrap.wrap(comment, 95)):
        y += 36 if k else 70
        dr.text((60, y), part, font=fs, fill=(80, 80, 80))
    return img


def photo(img: Image.Image, rnd: random.Random) -> Image.Image:
    """Like a phone photo of paper on a table: tilt, shadow, slight blur."""
    img = img.rotate(rnd.uniform(-4, 4), expand=True, fillcolor=(120, 100, 80),
                     resample=Image.BICUBIC)
    shade = Image.linear_gradient("L").resize(img.size).point(lambda p: 255 - int(p * 0.35))
    dark = Image.new("RGB", img.size, (0, 0, 0))
    img = Image.composite(img, dark, shade)
    return img.filter(ImageFilter.GaussianBlur(rnd.uniform(0.8, 1.4)))


def render_pdf(s: dict, path: Path) -> None:
    head, cols, rows, comment = lines(s)
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.07, 0.95, head[0], fontsize=13, weight="bold")
    for k, h in enumerate(head[1:]):
        fig.text(0.07, 0.92 - 0.02 * k, h, fontsize=8)
    xs = [0.07, 0.47, 0.62, 0.78] if len(cols) == 4 else [0.07, 0.47, 0.70]
    y = 0.84
    for x, c in zip(xs, cols, strict=True):
        fig.text(x, y, c, fontsize=9, weight="bold")
    for r in rows:
        y -= 0.03
        for x, c in zip(xs, r, strict=True):
            fig.text(x, y, c, fontsize=9)
    fig.text(0.07, y - 0.05, comment, fontsize=7, wrap=True)
    fig.savefig(path)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with open(LABELS, "w") as out:
        for i in range(15):
            s = make_sheet(i)
            rnd = random.Random(i)
            if s["kind"] == "pdf":
                name = f"{s['id']}.pdf"
                render_pdf(s, OUT / name)
            elif s["kind"] == "photo":
                name = f"{s['id']}.jpg"
                photo(render_png(s), rnd).save(OUT / name, quality=80)
            else:
                name = f"{s['id']}.png"
                render_png(s).save(OUT / name)
            out.write(json.dumps({"id": s["id"], "file": name, "kind": s["kind"],
                                  "lang": s["lang"], "layout": s["layout"],
                                  "taken_on": s["taken_on"], "patient": s["patient"],
                                  "order": s["order"], "rows": s["rows"]},
                                 ensure_ascii=False) + "\n")
    print(f"15 sheets → {OUT}")


if __name__ == "__main__":
    main()
