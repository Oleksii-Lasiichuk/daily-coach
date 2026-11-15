"""C3 Nutrition estimator: meal text → items with grams, energy, macros and key micronutrients."""

from pydantic import BaseModel

from app import llm
from app.pipeline.common import prompt

NUTRIENTS = ["kcal", "protein_g", "carbs_g", "sugar_g", "fiber_g", "fat_g", "sat_fat_g",
             "salt_g", "caffeine_mg", "alcohol_g", "iron_mg", "calcium_mg", "potassium_mg",
             "magnesium_mg", "vit_c_mg", "vit_d_ug"]


class Item(BaseModel):
    name: str
    food: str
    grams: float
    kcal: float
    protein_g: float
    carbs_g: float
    sugar_g: float
    fiber_g: float
    fat_g: float
    sat_fat_g: float
    salt_g: float
    caffeine_mg: float
    alcohol_g: float
    iron_mg: float
    calcium_mg: float
    potassium_mg: float
    magnesium_mg: float
    vit_c_mg: float
    vit_d_ug: float


class Nutrition(BaseModel):
    items: list[Item]
    kcal: float = 0
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0
    totals: dict[str, float] = {}


def estimate(meal: str, user_id: str | None = None) -> Nutrition:
    r = llm.complete(name="estimate-nutrition", schema=Nutrition, user_id=user_id,
                     max_tokens=1600, temperature=0, messages=[
                         {"role": "system", "content": prompt("c3_nutrition")},
                         {"role": "user", "content": meal}])
    return with_totals(r.parsed)


def with_totals(n: Nutrition) -> Nutrition:
    """Totals are always the sum of the items (computed here, not trusted from the model)."""
    n.totals = {k: round(sum(getattr(i, k) for i in n.items), 1) for k in NUTRIENTS}
    n.kcal, n.protein_g = round(n.totals["kcal"]), round(n.totals["protein_g"])
    n.carbs_g, n.fat_g = round(n.totals["carbs_g"]), round(n.totals["fat_g"])
    return n
