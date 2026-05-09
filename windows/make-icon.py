"""Generate windows/docvault.ico — the colorful icon shown next to the
right-click context-menu verbs.

Re-run this whenever you want to refresh the design:
    .\\.venv\\Scripts\\python.exe windows\\make-icon.py

The resulting file (windows/docvault.ico) is checked in. Pillow ships
transitively via pypdfium2, so no extra install step is needed.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent / "docvault.ico"

# Render at 256x256, then let Pillow downscale to the standard ICO sizes.
SIZE = 256


def _gradient(w: int, h: int, top: tuple[int, int, int], bot: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (w, h), top)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def build() -> Image.Image:
    s = SIZE
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # 1. Rounded-rect background with vibrant indigo→teal gradient.
    bg = _gradient(s, s, top=(99, 102, 241), bot=(20, 184, 166))  # indigo → teal
    mask = Image.new("L", (s, s), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((6, 6, s - 7, s - 7), radius=44, fill=255)
    canvas.paste(bg, (0, 0), mask)

    # 2. Soft inner highlight to give the tile a glossy feel.
    gloss = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gloss)
    gd.rounded_rectangle((14, 14, s - 15, int(s * 0.55)), radius=36, fill=(255, 255, 255, 38))
    canvas.alpha_composite(gloss.filter(ImageFilter.GaussianBlur(6)))

    # 3. Document silhouette: cream page with a folded corner, sitting
    #    slightly off-center so it feels designed, not stamped.
    page = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    pd = ImageDraw.Draw(page)
    page_rect = (60, 56, 196, 220)
    pd.rounded_rectangle(page_rect, radius=14, fill=(252, 248, 235, 255), outline=(255, 255, 255, 220), width=3)
    # Folded corner triangle (top-right).
    fold = [(196, 56), (196, 92), (160, 56)]
    pd.polygon(fold, fill=(231, 225, 205, 255))
    pd.line([(196, 92), (160, 56)], fill=(180, 175, 155, 255), width=2)

    # 4. Bright accent bar (amber) to break the green/blue palette and read
    #    "tagged document" at small sizes.
    pd.rounded_rectangle((78, 110, 178, 124), radius=6, fill=(245, 158, 11, 255))
    # Two ghost text lines beneath.
    pd.rounded_rectangle((78, 138, 178, 150), radius=5, fill=(160, 160, 150, 200))
    pd.rounded_rectangle((78, 162, 150, 174), radius=5, fill=(160, 160, 150, 200))
    pd.rounded_rectangle((78, 186, 168, 198), radius=5, fill=(160, 160, 150, 200))

    # Drop shadow for the page.
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((page_rect[0] + 4, page_rect[1] + 8, page_rect[2] + 4, page_rect[3] + 8),
                         radius=14, fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(page)

    # 5. Magenta dot in the bottom-right — a "marked / archived" bullet that
    #    keeps the icon recognisable even at 16x16.
    dot = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dot)
    dd.ellipse((170, 158, 220, 208), fill=(236, 72, 153, 255), outline=(255, 255, 255, 255), width=4)
    canvas.alpha_composite(dot)

    return canvas


def main() -> None:
    img = build()
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(OUT, format="ICO", sizes=sizes)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
