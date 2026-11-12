"""Genera l'icona dell'app (assets/icon.png 1024x1024 e assets/icon.ico multi-risoluzione).

Disegno originale: quadrato arrotondato con sfumatura viola-blu, barre bianche
di forma d'onda e una nota musicale. Nessuna immagine di terzi.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

SS = 4  # supersampling per bordi morbidi
N = 1024 * SS
OUT = Path(__file__).parent / "assets"


def gradient(size):
    top_left, bottom_right = (139, 92, 246), (37, 99, 235)  # viola -> blu
    g = Image.new("RGB", (size, size))
    px = g.load()
    for y in range(0, size, SS):
        for x in range(0, size, SS):
            t = (x + y) / (2 * size)
            c = tuple(round(a + (b - a) * t) for a, b in zip(top_left, bottom_right))
            for dy in range(SS):
                for dx in range(SS):
                    px[x + dx, y + dy] = c
    return g


def main():
    OUT.mkdir(exist_ok=True)
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    mask = Image.new("L", (N, N), 0)
    margin = 40 * SS
    ImageDraw.Draw(mask).rounded_rectangle(
        (margin, margin, N - margin, N - margin), radius=210 * SS, fill=255
    )
    img.paste(gradient(N), (0, 0), mask)

    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)

    # Barre della forma d'onda, centrate in verticale su y=600
    heights = [120, 230, 360, 470, 330, 200, 280, 150]
    bar_w, gap, cy = 62 * SS, 34 * SS, 610 * SS
    total = len(heights) * bar_w + (len(heights) - 1) * gap
    x = (N - total) // 2
    for h in heights:
        h *= SS
        d.rounded_rectangle((x, cy - h // 2, x + bar_w, cy + h // 2), radius=bar_w // 2, fill=white)
        x += bar_w + gap

    # Nota musicale (croma) in alto a destra, sopra le barre
    head_cx, head_cy, rx, ry = 640 * SS, 330 * SS, 72 * SS, 52 * SS
    ang = math.radians(-25)
    pts = [
        (
            head_cx + rx * math.cos(t) * math.cos(ang) - ry * math.sin(t) * math.sin(ang),
            head_cy + rx * math.cos(t) * math.sin(ang) + ry * math.sin(t) * math.cos(ang),
        )
        for t in (i * 2 * math.pi / 120 for i in range(120))
    ]
    d.polygon(pts, fill=white)
    stem_x = head_cx + 40 * SS
    stem_top = 120 * SS
    d.rectangle((stem_x, stem_top, stem_x + 26 * SS, head_cy), fill=white)
    d.polygon(
        [
            (stem_x, stem_top),
            (stem_x + 26 * SS, stem_top),
            (stem_x + 150 * SS, stem_top + 110 * SS),
            (stem_x + 120 * SS, stem_top + 200 * SS),
            (stem_x + 26 * SS, stem_top + 105 * SS),
        ],
        fill=white,
    )

    final = img.resize((1024, 1024), Image.LANCZOS)
    final.save(OUT / "icon.png")
    final.save(OUT / "icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])

    # autocontrollo: l'ico contiene tutte le risoluzioni richieste
    with Image.open(OUT / "icon.ico") as ico:
        got = sorted(s[0] for s in ico.info["sizes"])
    assert got == [16, 24, 32, 48, 64, 128, 256], got
    print("Icona creata:", OUT / "icon.png", OUT / "icon.ico", got)


if __name__ == "__main__":
    main()
