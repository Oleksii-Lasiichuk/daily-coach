"""Builds the C4 eval set: a synthetic "ChatGPT project export" with planted facts.

Each planted fact has a sentence the person says verbatim (the gold location), a gold fact and a
question. The LLM only writes the surrounding dialogue (assistant advice, small talk) — the
facts and questions are fixed here, so the gold does not depend on the model.
Run once: uv run python -m evals.make_c4_export
"""

import json
from pathlib import Path

from app import llm

D = Path(__file__).parent / "data"

# (id, category, user's verbatim sentence, gold fact, question)
PLANTED = [
    ("f01", "injury", "У жовтні 2026 почало боліти ліве коліно після пробіжок довше 15 км.", "Left knee pain after runs over 15 km since Oct 2026", "When did my left knee start hurting?"),
    ("f02", "health", "Лікар сказав, що в мене залізодефіцитна анемія, феритин був 12.", "Iron-deficiency anaemia, ferritin 12", "What did the doctor find in my blood?"),
    ("f03", "medication", "I take ferrous sulfate 100 mg every morning since September 2026.", "Ferrous sulfate 100 mg daily since Sep 2026", "Which iron supplement do I take?"),
    ("f04", "race", "Я зареєструвався на Lviv Half Marathon 12 квітня 2027.", "Lviv Half Marathon on 12 Apr 2027", "Which race am I registered for in April?"),
    ("f05", "goal", "My goal for the half is 1:45, my current PB is 1:52 from Kyiv 2026.", "Half marathon goal 1:45; PB 1:52 (Kyiv 2026)", "What is my half marathon PB?"),
    ("f06", "health", "У мене алергія на ібупрофен, висипає після нього.", "Allergic to ibuprofen (rash)", "Am I allergic to any painkiller?"),
    ("f07", "gear", "Бігаю в Nike Pegasus 41, вони вже пройшли приблизно 650 км.", "Nike Pegasus 41, ~650 km", "How many km are on my running shoes?"),
    ("f08", "preference", "I hate treadmills, I'd rather run in the rain than indoors.", "Dislikes treadmills, prefers running outside", "Do I like running on a treadmill?"),
    ("f09", "life", "Працюю з 9 до 18, тому тренуватись можу тільки зранку до 8:00.", "Works 9-18; trains only before 8:00", "When can I train on weekdays?"),
    ("f10", "health", "My sleep is bad when I drink coffee after 2 pm, I wake up at 3 am.", "Coffee after 2 pm ruins sleep", "What ruins my sleep?"),
    ("f11", "injury", "Минулого року в мене був стресовий перелом правої плесневої кістки, 6 тижнів без бігу.", "Stress fracture right metatarsal last year, 6 weeks off", "Have I had a stress fracture?"),
    ("f12", "goal", "Хочу схуднути з 78 до 74 кг до весни.", "Wants to lose weight from 78 to 74 kg by spring", "What is my weight goal?"),
    ("f13", "health", "I have mild asthma, I use a Ventolin inhaler before hard intervals in cold weather.", "Mild asthma; Ventolin before hard intervals in cold", "Do I need an inhaler for training?"),
    ("f14", "preference", "Я вегетаріанець вже три роки, але їм яйця і молочне.", "Vegetarian (eats eggs and dairy) for 3 years", "Do I eat meat?"),
    ("f15", "gear", "My bike is a Canyon Endurace CF 7, I bought it in August 2026.", "Bike: Canyon Endurace CF 7 (Aug 2026)", "What bike do I have?"),
    ("f16", "race", "Planning my first Olympic triathlon in Kyiv in July 2027.", "First Olympic triathlon, Kyiv, Jul 2027", "Which triathlon am I planning?"),
    ("f17", "health", "Тиск у мене зазвичай 135/85, лікар радив стежити.", "Blood pressure usually 135/85; doctor advised monitoring", "What is my usual blood pressure?"),
    ("f18", "medication", "Після COVID у березні 2026 пив антибіотики амоксицилін 7 днів.", "Amoxicillin 7 days after COVID in Mar 2026", "What antibiotics did I take after COVID?"),
    ("f19", "life", "We have a newborn daughter since August, so my sleep is often broken.", "Newborn daughter since Aug; broken sleep", "Why is my sleep often broken?"),
    ("f20", "preference", "Плавати люблю тільки в басейні 50 м, у відкритій воді панікую.", "Swims only in 50 m pool; panics in open water", "Am I comfortable swimming in open water?"),
    ("f21", "injury", "My lower back gets tight after long rides over 3 hours.", "Lower back tightness after rides over 3 h", "What happens to my back on long rides?"),
    ("f22", "health", "Мій максимальний пульс на тесті був 198.", "Max heart rate 198 (test)", "What max heart rate did I reach on the test?"),
    ("f23", "goal", "I want to swim 1500 m freestyle without stopping by June.", "Swim 1500 m freestyle non-stop by June", "What is my swimming goal?"),
    ("f24", "medication", "Приймаю вітамін D 2000 МО щодня взимку.", "Vitamin D 2000 IU daily in winter", "How much vitamin D do I take?"),
]

PROMPT = """Write one exported ChatGPT conversation in Markdown, about 2500-3500 characters, between
a person ("**You:**") and an assistant ("**ChatGPT:**") about training, health or nutrition.
Mix Ukrainian and English like the person does. The assistant gives long general advice.
Include EVERY sentence below VERBATIM inside the person's messages (do not change a character),
spread naturally across the conversation. Do not add any other personal facts about the person
(no other injuries, medications, races or numbers about them). Start with a heading "## <topic>".
Sentences:
{sentences}"""


def main():
    groups = [PLANTED[i:i + 3] for i in range(0, len(PLANTED), 3)]
    parts = []
    for g in groups:
        sentences = "\n".join(f"- {s}" for _, _, s, _, _ in g)
        r = llm.complete(name="make-c4-export", model=llm.SMART_MODEL, max_tokens=2500,
                         temperature=0.7, messages=[{"role": "user",
                                                     "content": PROMPT.format(sentences=sentences)}])
        text = r.text.strip()
        missing = [s for _, _, s, _, _ in g if s not in text]
        if missing:  # the model changed a sentence: append it verbatim so the gold stays exact
            text += "\n\n**You:** " + " ".join(missing)
        parts.append(text)
    export = "# ChatGPT export — project “Health and sport”\n\n" + "\n\n---\n\n".join(parts)
    (D / "c4_export.md").write_text(export)
    rows = [{"id": i, "category": c, "sentence": s, "fact": f, "question": q}
            for i, c, s, f, q in PLANTED]
    (D / "c4_planted.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(len(export), "chars,", len(rows), "planted facts")


if __name__ == "__main__":
    main()
