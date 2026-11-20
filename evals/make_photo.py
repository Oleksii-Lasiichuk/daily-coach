"""Draws the synthetic meal photo used by the e2e eval (no real photo in git): a plate with
buckwheat, a chicken breast, a tomato-cucumber salad, on a wooden table, seen from above.
Run: uv run python -m evals.make_photo"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).parent / "data" / "meal_photo.jpg"


def draw() -> Image.Image:
    img = Image.new("RGB", (900, 700), (150, 105, 70))
    d = ImageDraw.Draw(img)
    for y in range(0, 700, 38):  # table boards
        d.line([(0, y), (900, y + 6)], fill=(125, 85, 55), width=3)
    d.ellipse([140, 60, 760, 660], fill=(245, 245, 242), outline=(220, 220, 215), width=6)
    d.ellipse([200, 120, 700, 600], fill=(250, 250, 248))
    for i in range(1400):  # buckwheat: many small brown grains, left half
        x, y = 250 + (i * 37) % 210, 200 + (i * 53) % 260
        d.ellipse([x, y, x + 9, y + 6], fill=(120 + i % 30, 75 + i % 20, 40))
    d.rounded_rectangle([470, 190, 650, 330], radius=50, fill=(222, 186, 140))  # chicken
    for k in range(5):
        d.line([(490 + k * 35, 200), (470 + k * 35, 320)], fill=(190, 140, 90), width=6)
    for i in range(9):  # salad: tomato wedges and cucumber slices
        x, y = 470 + (i % 3) * 60, 380 + (i // 3) * 55
        d.ellipse([x, y, x + 50, y + 42], fill=(205, 40, 35) if i % 2 else (120, 175, 90))
        if not i % 2:
            d.ellipse([x + 14, y + 12, x + 36, y + 30], fill=(200, 225, 170))
    return img.filter(ImageFilter.GaussianBlur(1.2))


if __name__ == "__main__":
    draw().save(OUT, quality=85)
    print(OUT)
