"""Synthetic C11 eval set (plan 11 B4). No real bank data: merchant names are public brands or
made-up local places, MCC codes are typical (some misleading on purpose), labels by hand.

- evals/data/c11_spend.jsonl: 150 card payments {id, description, mcc, amount_minor, label}.
- evals/data/c11_receipts/*.png + c11_receipts.jsonl: 15 receipts drawn with PIL in a
  Ukrainian fiscal-receipt layout (fake shops), with line labels, the expected total, whether
  a meal/fuel offer is expected, and a matching synthetic card payment for the split check.
Run: uv run python -m evals.make_c11_spend
"""

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

DATA = Path(__file__).parent / "data"
FONT = "/System/Library/Fonts/Supplemental/Courier New.ttf"

# (description, mcc, label). Groups: known chains (UA/Latin spellings), misleading MCC,
# unknown local places, race sites, sports nutrition, pharmacies/medical, transfers, income.
TX = [
    # groceries
    ("СІЛЬПО", 5411, "groceries"), ("Silpo Kyiv", 5411, "groceries"), ("ATB-Market", 5411, "groceries"),
    ("АТБ 1123", 5411, "groceries"), ("NOVUS", 5411, "groceries"), ("Фора", 5411, "groceries"),
    ("VARUS", 5411, "groceries"), ("METRO Cash&Carry", 5411, "groceries"), ("Ашан Петрівка", 5411, "groceries"),
    ("Lidl Krakow", 5411, "groceries"), ("Овочева лавка Марти", 5499, "groceries"),
    ("Пекарня Хлібна Хата", 5462, "groceries"), ("М'ясна крамниця", 5422, "groceries"),
    ("Biedronka", 5411, "groceries"), ("Еко маркет", 5411, "groceries"), ("Таврія В", 5411, "groceries"),
    ("Сирна лавка на Подолі", 5451, "groceries"), ("Market Bazar Lviv", 5499, "groceries"),
    # eating out
    ("McDonald's", 5814, "eating_out"), ("Пузата Хата", 5812, "eating_out"), ("KFC Ocean Plaza", 5814, "eating_out"),
    ("Domino's Pizza", 5814, "eating_out"), ("Sushi Master", 5812, "eating_out"), ("Ресторан Кримська", 5812, "eating_out"),
    ("Бістро Зелений Кіт", 5812, "eating_out"), ("Burger Club", 5814, "eating_out"), ("Pivnytsia 3 Bochky", 5813, "eating_out"),
    ("Їдальня Студентська", 5812, "eating_out"), ("Varenychna Katerynka", 5812, "eating_out"),
    ("Шаурма Кінг", 5814, "eating_out"), ("Mafia Pizza", 5812, "eating_out"), ("Cafe Gorgany", 5812, "eating_out"),
    ("Хінкальня", 5812, "eating_out"), ("LIQPAY*Ресторан Острів", 7399, "eating_out"),
    # delivery
    ("Glovo", 5814, "delivery"), ("GLOVO*Kyiv", 4215, "delivery"), ("Bolt Food", 5814, "delivery"),
    ("Wolt", 5814, "delivery"), ("Rocket Delivery", 5814, "delivery"), ("Uklon Delivery", 4121, "delivery"),
    ("Uber Eats", 5814, "delivery"), ("Zakaz.ua", 5411, "delivery"), ("Silpo Delivery", 5411, "delivery"),
    ("Raketa", 5814, "delivery"),
    # coffee
    ("Aroma Kava", 5814, "coffee"), ("Lviv Croissants", 5814, "coffee"), ("Starbucks Warsaw", 5814, "coffee"),
    ("One Love Coffee", 5814, "coffee"), ("Кав'ярня Ранок", 5814, "coffee"), ("Black Honey", 5812, "coffee"),
    ("Takava", 5814, "coffee"), ("Coffee Point Vokzal", 5499, "coffee"), ("White Rabbit Coffee", 5812, "coffee"),
    ("Kavovyi kiosk Arsenalna", 5999, "coffee"),
    # sports nutrition
    ("MyProtein", 5499, "sports_nutrition"), ("Maurten AB", 5499, "sports_nutrition"),
    ("SportPit Shop", 5499, "sports_nutrition"), ("Powerbar Online", 5969, "sports_nutrition"),
    ("Nutrend UA", 5499, "sports_nutrition"), ("Science in Sport", 5969, "sports_nutrition"),
    ("Енергетичні гелі Біг", 5499, "sports_nutrition"), ("Ізотонік маркет", 5999, "sports_nutrition"),
    # race entries
    ("Wizz Marathon Kyiv", 7941, "race_entries"), ("Nova Poshta Marathon", 7999, "race_entries"),
    ("Ahotu Events", 7999, "race_entries"), ("Run Ukraine Реєстрація", 8699, "race_entries"),
    ("UTMB World Series", 7941, "race_entries"), ("Gorgany Race Registration", 7999, "race_entries"),
    ("Ironman Europe", 7941, "race_entries"), ("Трейл Карпати забіг", 7999, "race_entries"),
    ("Harpia Ultra Trail", 7999, "race_entries"), ("Lviv Half Marathon", 7941, "race_entries"),
    # sport gear
    ("Decathlon", 5941, "sport_gear"), ("Intersport", 5655, "sport_gear"), ("MEGASPORT", 5941, "sport_gear"),
    ("Runners Club Kyiv", 5941, "sport_gear"), ("Garmin Store", 5732, "sport_gear"), ("Salomon Store", 5661, "sport_gear"),
    ("ASICS Outlet", 5661, "sport_gear"), ("Велосклад", 5940, "sport_gear"),
    # gym and classes
    ("Sport Life", 7997, "gym_classes"), ("Apollo Fitness", 7997, "gym_classes"), ("CrossFit Box Lviv", 7997, "gym_classes"),
    ("Yoga Studio Lotus", 7997, "gym_classes"), ("Басейн Олімпійський", 7997, "gym_classes"),
    ("Climbing Wall Bigwall", 7941, "gym_classes"), ("Танцювальна студія Ритм", 7911, "gym_classes"),
    # medical / pharmacy
    ("Synevo", 8071, "medical"), ("Діла лабораторія", 8071, "medical"), ("Dobrobut Clinic", 8062, "medical"),
    ("Стоматологія Посмішка", 8021, "medical"), ("Into-Sana", 8011, "medical"), ("Esculab", 8071, "medical"),
    ("Аптека Доброго Дня", 5912, "pharmacy"), ("Подорожник", 5912, "pharmacy"), ("АНЦ аптека", 5912, "pharmacy"),
    ("Apteka 3i", 5912, "pharmacy"), ("Бажаємо здоров'я", 5912, "pharmacy"), ("Pharmacy Warsaw", 5912, "pharmacy"),
    # transport / taxi / fuel
    ("Kyiv Metro", 4111, "transport"), ("Ukrzaliznytsia", 4112, "transport"), ("Kyivpastrans", 4131, "transport"),
    ("FlixBus", 4131, "travel"), ("Bolt", 4121, "taxi"), ("Uklon", 4121, "taxi"), ("Uber Trip", 4121, "taxi"),
    ("838 Taxi", 4121, "taxi"), ("WOG", 5541, "fuel"), ("OKKO", 5542, "fuel"), ("SOCAR", 5541, "fuel"), ("UPG", 5541, "fuel"),
    # home bills / subscriptions
    ("Kyivstar", 4814, "home_bills"), ("Vodafone UA", 4814, "home_bills"), ("lifecell", 4814, "home_bills"),
    ("YASNO", 4900, "home_bills"), ("Нафтогаз", 4900, "home_bills"), ("Triolan", 4899, "home_bills"),
    ("Netflix.com", 4899, "subscriptions"), ("Spotify", 5815, "subscriptions"), ("YouTube Premium", 5815, "subscriptions"),
    ("Google One", 5818, "subscriptions"), ("Strava", 5818, "subscriptions"), ("Apple.com/bill", 5818, "subscriptions"),
    ("MEGOGO", 4899, "subscriptions"), ("Zwift", 5816, "subscriptions"),
    # shopping / entertainment / travel
    ("Rozetka", 5732, "shopping"), ("Prom.ua", 5399, "shopping"), ("Comfy", 5732, "shopping"),
    ("Епіцентр", 5200, "shopping"), ("ZARA", 5651, "shopping"), ("AliExpress", 5999, "shopping"),
    ("EVA", 5977, "shopping"), ("Multiplex", 7832, "entertainment"), ("Планета Кіно", 7832, "entertainment"),
    ("Karabas.com", 7922, "entertainment"), ("Steam", 5816, "entertainment"), ("Театр Франка", 7922, "entertainment"),
    ("Booking.com", 4722, "travel"), ("Airbnb", 7011, "travel"), ("Ryanair", 3246, "travel"), ("Hotel Dnipro", 7011, "travel"),
    ("SkyUp", 4511, "travel"),
    # misleading MCC (the name should win)
    ("Glovo", 5411, "delivery"), ("Decathlon", 5411, "sport_gear"), ("Аптека Доброго Дня", 5411, "pharmacy"),
    ("Aroma Kava", 5411, "coffee"), ("Wizz Marathon Kyiv", 7997, "race_entries"),
    # unknown local places (C11's job)
    ("ФОП Коваленко О.В.", 5812, "eating_out"), ("Пельменна на Валах", 5812, "eating_out"),
    ("Смаколик", 5411, "groceries"), ("Лавка Бабусі", 5499, "groceries"),
    ("Кавовий куточок", 5814, "coffee"), ("Piazza Italia trattoria", 5812, "eating_out"),
    ("Кіоск Преса", 5994, "other"), ("ФОП Шевчук ремонт взуття", 7251, "other"),
]
TRANSFERS = [("Transfer", 4829, -50000, "transfers"), ("Transfer", 4829, -12000, "transfers"),
             ("Transfer", 6538, -30000, "transfers"), ("Банкомат ПриватБанк", 6011, -100000, "cash"),
             ("Transfer", 4829, 250000, "income"), ("Кешбек", 0, 4500, "income")]


def transactions() -> list[dict]:
    r = random.Random(11)
    rows = [{"description": d, "mcc": m, "amount_minor": -r.randint(3000, 250000), "label": lab}
            for d, m, lab in TX]
    rows += [{"description": d, "mcc": m, "amount_minor": a, "label": lab}
             for d, m, a, lab in TRANSFERS]
    return [{"id": f"t{i:03d}", **row} for i, row in enumerate(rows)]


# Receipts: (store, kind, date, lines [(name, qty, price, label)], offer)
RECEIPTS = [
    ("КАВ'ЯРНЯ ЗЕРНО", "restaurant", "2026-11-12", [("Капучино 300мл", 1, 75, "coffee"), ("Круасан з сиром", 1, 85, "eating_out")], "meal"),
    ("ПІЦЕРІЯ МАРГО", "restaurant", "2026-11-10", [("Піца Маргарита", 1, 245, "eating_out"), ("Кола 0.5", 1, 55, "eating_out"), ("Салат Цезар", 1, 189, "eating_out")], "meal"),
    ("ЇДАЛЬНЯ СМАЧНО", "restaurant", "2026-11-09", [("Борщ", 1, 65, "eating_out"), ("Котлета по-київськи", 1, 120, "eating_out"), ("Компот", 1, 25, "eating_out")], "meal"),
    ("СУПЕРМАРКЕТ КОЛОСОК", "grocery", "2026-11-08", [("Молоко 2.5% 900г", 2, 84, "groceries"), ("Хліб житній", 1, 38, "groceries"), ("Яйця С1 10шт", 1, 72, "groceries"), ("Гречка 1кг", 1, 69, "groceries"), ("Банани", 1.2, 66, "groceries"), ("Кефір 1%", 1, 44, "groceries"), ("Філе куряче", 0.8, 168, "groceries"), ("Пакет", 1, 3, "shopping")], None),
    ("МАРКЕТ ЛАСУН", "grocery", "2026-11-07", [("Сендвіч з куркою", 1, 89, "eating_out"), ("Вода 0.5", 1, 22, "groceries")], "meal"),
    ("БІГОВИЙ МАГАЗИН ТЕМП", "sport", "2026-11-06", [("Гель енергетичний SiS", 3, 255, "sports_nutrition"), ("Ізотонік порошок", 1, 390, "sports_nutrition")], "fuel"),
    ("АПТЕКА ЗДОРОВА РОДИНА", "pharmacy", "2026-11-05", [("Вітамін D3 2000", 1, 289, "pharmacy"), ("Ібупрофен 200мг", 1, 76, "pharmacy"), ("Пластир", 1, 34, "pharmacy")], None),
    ("ГАСТРОНОМ ЦЕНТР", "grocery", "2026-11-04", [("Сир твердий", 0.3, 135, "groceries"), ("Помідори", 1, 79, "groceries"), ("Огірки", 0.8, 52, "groceries"), ("Шоколад чорний", 2, 110, "groceries"), ("Шампунь", 1, 159, "shopping"), ("Макарони", 2, 78, "groceries")], None),
    ("БУРГЕРНА ДИМ", "restaurant", "2026-11-03", [("Бургер класичний", 2, 398, "eating_out"), ("Картопля фрі", 2, 138, "eating_out"), ("Лимонад", 2, 120, "eating_out")], "meal"),
    ("ЕКО ЛАВКА", "grocery", "2026-11-02", [("Йогурт натуральний", 4, 132, "groceries"), ("Вівсяні пластівці", 1, 58, "groceries"), ("Яблука", 1.5, 45, "groceries"), ("Чай зелений", 1, 89, "groceries")], None),
    # 5 more for the meal-offer check
    ("СУШІ ХАУС", "restaurant", "2026-11-01", [("Рол Філадельфія", 1, 329, "eating_out"), ("Місо суп", 1, 95, "eating_out")], "meal"),
    ("КАВА НА РОГУ", "restaurant", "2026-10-31", [("Американо", 1, 50, "coffee")], "meal"),
    ("СУПЕРМАРКЕТ КОЛОСОК", "grocery", "2026-10-30", [("Рис 1кг", 2, 118, "groceries"), ("Масло вершкове", 1, 89, "groceries"), ("Сметана 15%", 1, 42, "groceries"), ("Картопля", 3, 54, "groceries"), ("Риба хек", 1, 210, "groceries"), ("Печиво", 1, 46, "groceries"), ("Сік яблучний", 2, 96, "groceries")], None),
    ("МАРКЕТ ЛАСУН", "grocery", "2026-10-29", [("Шаурма з куркою", 1, 129, "eating_out"), ("Кава лате", 1, 55, "coffee")], "meal"),
    ("БІГОВИЙ МАГАЗИН ТЕМП", "sport", "2026-10-28", [("Протеїновий батончик", 4, 236, "sports_nutrition")], "fuel"),
]


def _font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def draw_receipt(store, date, lines, total, seed) -> Image.Image:
    r = random.Random(seed)
    w, h = 520, 440 + 56 * len(lines)
    img = Image.new("RGB", (w, h), (250, 248, 240))
    d = ImageDraw.Draw(img)
    f, fb = _font(20), _font(24)
    y = 20

    def put(text, font=f, center=False):
        nonlocal y
        x = (w - d.textlength(text, font=font)) / 2 if center else 24
        d.text((x, y), text, fill=(30, 30, 35), font=font)
        y += font.size + 8

    put(f'ТОВ "{store.title()}"', fb, center=True)
    put(store, fb, center=True)
    put("м. Київ, вул. Вигадана, " + str(r.randint(1, 99)), center=True)
    put("ПН 12345678901234  ФН 30010" + str(r.randint(10000, 99999)), center=True)
    put("-" * 38)
    for name, qty, price, _ in lines:
        put(name)
        unit = price / qty
        q = f"{qty:g}".replace(".", ",")
        tail = f"{price:.2f} А".replace(".", ",")
        line = f"  {q} x {unit:.2f}".replace(".", ",")
        d.text((w - 24 - d.textlength(tail, font=f), y), tail, fill=(30, 30, 35), font=f)
        put(line)
    put("-" * 38)
    tot = f"{total:.2f}".replace(".", ",")
    d.text((w - 24 - d.textlength(tot + " грн", font=fb), y), tot + " грн", fill=(0, 0, 0), font=fb)
    put("СУМА", fb)
    put(f"ПДВ А 20%      {total / 6:.2f}".replace(".", ","))
    put("КАРТКА  ****" + str(r.randint(1000, 9999)))
    put(f"{date[8:10]}.{date[5:7]}.{date[:4]}  {r.randint(8, 21):02d}:{r.randint(0, 59):02d}", center=True)
    put("ФІСКАЛЬНИЙ ЧЕК", center=True)
    img = img.rotate(r.uniform(-2.5, 2.5), expand=True, fillcolor=(90, 90, 95))
    return img.filter(ImageFilter.GaussianBlur(0.6))


def main():
    rows = transactions()
    (DATA / "c11_spend.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n")
    out = DATA / "c11_receipts"
    out.mkdir(exist_ok=True)
    recs = []
    for i, (store, kind, date, lines, offer) in enumerate(RECEIPTS):
        total = round(sum(p for _, _, p, _ in lines), 2)
        path = out / f"r{i:02d}.png"
        draw_receipt(store, date, lines, total, i).save(path)
        recs.append({"id": f"r{i:02d}", "image": f"c11_receipts/{path.name}", "store": store,
                     "kind": kind, "date": date, "total": total, "offer": offer,
                     "lines": [{"name": n, "qty": q, "price": p, "label": lab}
                               for n, q, p, lab in lines], "accuracy_set": i < 10})
    (DATA / "c11_receipts.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in recs) + "\n")
    print(len(rows), "transactions,", len(recs), "receipts")


if __name__ == "__main__":
    main()
