"""Spend category rules (code, plan 11 B4). Run before C11; whatever they place never reaches an
LLM.

Order: sign/type (income, transfers, cash) → merchant name rules → MCC table → None (C11).
Merchant names are normalised (lowercase, Cyrillic look-alikes folded, punctuation dropped) so
"СІЛЬПО", "Silpo" and "silpo.ua" all match. Receipt lines use `product_category` (keywords).
"""

import re

CATEGORIES = ["groceries", "eating_out", "delivery", "coffee", "sports_nutrition",
              "race_entries", "sport_gear", "gym_classes", "medical", "pharmacy", "transport",
              "taxi", "fuel", "home_bills", "subscriptions", "shopping", "entertainment",
              "travel", "transfers", "cash", "income", "other"]
FOOD = {"groceries", "eating_out", "delivery", "coffee", "sports_nutrition"}
TRANSFER_MCC = {4829, 6538, 6012}
CASH_MCC = {6011}

# Latin transliteration of Ukrainian letters, so one rule matches both spellings.
_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie", "ж": "zh",
    "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ь": "", "ю": "iu", "я": "ia", "ё": "e", "ы": "y",
    "э": "e", "ъ": "", "'": "", "’": "", "ʼ": ""})


def normalise(description: str | None) -> str:
    """'СІЛЬПО Київ' → 'silpo kyiv'. Used for rules and as the merchant key."""
    s = (description or "").lower().translate(_TRANSLIT)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()[:80]


# (category, name fragments after normalise). Checked in this order, first hit wins, so the
# more specific names (Bolt Food) come before the general ones (Bolt).
MERCHANTS: list[tuple[str, list[str]]] = [
    ("delivery", ["glovo", "bolt food", "boltfood", "rocket", "uklon delivery", "uber eats",
                  "wolt", "raketa", "zakaz ua", "silpo delivery", "deliveroo"]),
    ("transport", ["metro kyiv", "kyiv metro", "kyivpastrans", "ukrzaliznytsia", "uz gov",
                   "easypay transport", "bilet", "transport"]),
    ("groceries", ["silpo", "atb", "novus", "fora", "varus", "metro", "ashan", "auchan",
                   "eko market", "lidl", "biedronka", "billa", "spar", "tavria", "velmart",
                   "megamarket", "rost"]),
    ("taxi", ["bolt", "uklon", "uber", "ontaxi", "838"]),
    ("sport_gear", ["decathlon", "intersport", "megasport", "sportmaster", "runnersclub",
                    "runners club", "nike", "adidas", "asics", "garmin", "salomon",
                    "sport life shop", "4f"]),
    ("sports_nutrition", ["myprotein", "maurten", "sis ", "science in sport", "powerbar",
                          "sportpit", "sport pit", "protein ua", "nutrend", "sporter",
                          "bombbar", "enervit"]),
    ("race_entries", ["ahotu", "registration", "reiestratsiia", "my run", "myrun", "run ukraine",
                      "runukraine", "wizz marathon", "nova poshta marathon", "ultra trail",
                      "utmb", "race id", "raceid", "athlinks", "njuko", "marathon", "trail run",
                      "triathlon", "ironman"]),
    ("gym_classes", ["sport life", "sportlife", "apollo", "fitness", "gym", "crossfit",
                     "yoga", "basein", "pool", "basseyn"]),
    ("pharmacy", ["apteka", "pharmacy", "podorozhnyk", "anc ", "3i", "bazhaiemo zdorovia",
                  "dobroho dnia apteka"]),
    ("medical", ["synevo", "dila", "medlab", "dobrobut", "into sana", "boris", "oxford medical",
                 "klinika", "clinic", "stomatolog", "dental", "esculab", "laboratoriia"]),
    ("coffee", ["aroma kava", "lviv croissants", "starbucks", "coffee", "kava", "costa",
                "one love", "black honey", "takava", "white rabbit"]),
    ("eating_out", ["mcdonald", "kfc", "puzata khata", "domino", "sushi", "pizza", "restoran",
                    "restaurant", "kafe", "cafe", "bistro", "burger", "pyvnytsia", "bar "]),
    ("fuel", ["wog", "okko", "socar", "upg", "shell", "brsm", "klo", "amic"]),
    ("subscriptions", ["netflix", "spotify", "youtube", "google one", "apple com bill",
                       "icloud", "megogo", "sweet tv", "openai", "chatgpt", "strava",
                       "intervals icu", "trainingpeaks", "zwift", "komoot"]),
    ("home_bills", ["kyivstar", "vodafone", "lifecell", "kyivteploenerho", "yasno", "naftogaz",
                    "vodokanal", "kyivvodokanal", "volia", "triolan", "osbb", "komunalni"]),
    ("travel", ["booking com", "airbnb", "ryanair", "wizz air", "wizzair", "lot ", "hotel",
                "hostel", "flixbus", "skyup"]),
    ("entertainment", ["multiplex", "planeta kino", "kino", "concert", "karabas", "steam",
                       "playstation", "teatr", "theatre"]),
    ("shopping", ["rozetka", "prom ua", "allo", "foxtrot", "comfy", "epicentr", "zara",
                  "h m", "aliexpress", "amazon", "makeup", "eva ", "watsons"]),
]

# ISO 18245 merchant category codes our categories need (greggles/mcc-codes, Unlicense).
MCC: dict[int, str] = {
    **{m: "groceries" for m in (5411, 5422, 5441, 5451, 5462, 5499)},
    5812: "eating_out", 5813: "eating_out", 5814: "eating_out",
    5912: "pharmacy",
    **{m: "medical" for m in (8011, 8021, 8031, 8041, 8042, 8043, 8049, 8062, 8071, 8099)},
    5941: "sport_gear", 5655: "sport_gear",
    7997: "gym_classes", 7941: "gym_classes", 7911: "gym_classes",
    4121: "taxi",
    4111: "transport", 4112: "transport", 4131: "transport",
    5541: "fuel", 5542: "fuel",
    4814: "home_bills", 4899: "home_bills", 4900: "home_bills",
    **{m: "subscriptions" for m in (5815, 5816, 5817, 5818, 4816)},
    7832: "entertainment", 7922: "entertainment", 7996: "entertainment",
    4511: "travel", 7011: "travel", 4722: "travel",
}


def mcc_category(mcc: int | None) -> str | None:
    if mcc is None:
        return None
    if 3000 <= mcc <= 3299:  # airlines
        return "travel"
    return MCC.get(mcc)


def merchant_category(name: str) -> str | None:
    padded = f" {name} "
    for cat, frags in MERCHANTS:
        for f in frags:
            # whole-word match for short fragments ("atb", "wog"), substring for longer ones
            if (f" {f.strip()} " in padded) if len(f.strip()) <= 4 else (f in padded):
                return cat
    return None


def is_transfer(mcc: int | None, original_mcc: int | None = None) -> bool:
    return mcc in TRANSFER_MCC or original_mcc in TRANSFER_MCC


def categorise(description: str | None, mcc: int | None, amount_minor: int,
               original_mcc: int | None = None, user_rules: dict[str, str] | None = None
               ) -> str | None:
    """The category from rules, or None (then C11 decides). A person's own rule wins over
    everything except income/transfers/cash."""
    if amount_minor > 0:
        return "income"
    if is_transfer(mcc, original_mcc):
        return "transfers"
    if mcc in CASH_MCC or original_mcc in CASH_MCC:
        return "cash"
    name = normalise(description)
    if user_rules and name in user_rules:
        return user_rules[name]
    by_name = merchant_category(name)
    if by_name:
        return by_name
    return mcc_category(mcc) or mcc_category(original_mcc)


# Receipt lines: product keywords (normalised). First hit wins.
PRODUCTS: list[tuple[str, list[str]]] = [
    ("sports_nutrition", ["gel", "hel", "izotonik", "isotonic", "protein", "batonchyk protein",
                          "energy bar", "electrolyt", "elektrolit", "bcaa", "maurten",
                          "sis go", "kreatyn", "creatine"]),
    ("pharmacy", ["tabl", "vitamin", "ibuprof", "paracetamol", "plastyr", "bynt", "mazʹ",
                  "kapsuly", "syrop"]),
    ("coffee", ["kava", "coffee", "kapuchyno", "cappuccino", "latte", "lat te", "espresso",
                "espreso", "amerykano", "americano", "flat white", "raf"]),
    ("eating_out", ["burger", "pitsa", "pizza", "sendvich", "sandwich", "shaurma", "shawarma",
                    "khot doh", "hot dog", "salat bowl", "boul", "bowl", "sup dnia", "kruasan",
                    "croissant", "biznes lanch", "lanch", "obid", "wrap", "rol ", "sushi"]),
    ("shopping", ["paket", "bag", "shampun", "shampoo", "zubna", "toothpaste", "porosh",
                  "detergent", "servetky"]),
    ("groceries", ["khlib", "bread", "moloko", "milk", "kefir", "syr", "cheese", "iaitsia",
                   "eggs", "banan", "banana", "iabluk", "apple", "kartoplia", "potato",
                   "hrechka", "buckwheat", "rys", "rice", "kuriache", "chicken", "file",
                   "ovochi", "pomidor", "tomato", "ohirok", "cucumber", "makarony", "pasta",
                   "iohurt", "yogurt", "voda", "water", "sik", "juice", "maslo", "butter",
                   "kovbasa", "riba", "fish", "tvoroh", "smetana", "vivsiani", "oats",
                   "shokolad", "chocolate", "pechyvo", "cookies", "chai", "tea", "kola",
                   "cola", "napii"]),
]


def product_category(line: str) -> str | None:
    name = f" {normalise(line)} "
    for cat, frags in PRODUCTS:
        for f in frags:
            if (f" {f.strip()} " in name) if len(f.strip()) <= 3 else (f in name):
                return cat
    return None
