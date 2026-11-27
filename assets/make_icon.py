"""Draws the Valt icons: assets/valt.ico (app) and assets/valt-doc.ico (.valt files).

App icon: a rounded safe with a dial. Document icon: a page with a folded
corner and a small dial. Drawn 4x oversized and downscaled for smooth edges.
Run from the repo root:  .venv\\Scripts\\python assets\\make_icon.py
"""
import os

from PIL import Image, ImageDraw

OUT = os.path.dirname(os.path.abspath(__file__))
SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
S = 4  # supersampling factor


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def dial(draw, cx, cy, r, colors):
    """A safe dial: dark ring, lighter face, tick marks, center dot."""
    ring, face, tick, center = colors
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ring)
    d = int(r * 0.68)
    draw.ellipse([cx - d, cy - d, cx + d, cy + d], fill=face)
    # tick marks around the ring
    import math
    for i in range(8):
        a = math.pi * 2 * i / 8
        x1, y1 = cx + math.cos(a) * r * 0.72, cy + math.sin(a) * r * 0.72
        x2, y2 = cx + math.cos(a) * r * 0.92, cy + math.sin(a) * r * 0.92
        draw.line([x1, y1, x2, y2], fill=tick, width=max(2, int(r * 0.10)))
    d = int(r * 0.16)
    draw.ellipse([cx - d, cy - d, cx + d, cy + d], fill=center)


def make_app_icon():
    """Dark slate safe: steel door, dial, hinge bars."""
    img = Image.new("RGBA", (256 * S, 256 * S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rounded(draw, [8 * S, 8 * S, 248 * S, 248 * S], 48 * S, (44, 56, 72, 255))       # body
    rounded(draw, [24 * S, 24 * S, 232 * S, 232 * S], 36 * S, (142, 158, 176, 255))  # door
    dial(draw, 128 * S, 122 * S, 52 * S,
         ((44, 56, 72, 255), (206, 216, 226, 255), (44, 56, 72, 255), (44, 56, 72, 255)))
    draw.rounded_rectangle([96 * S, 196 * S, 160 * S, 210 * S], 7 * S, (44, 56, 72, 255))  # handle
    for y in (52, 190):                                                              # hinges
        draw.rounded_rectangle([18 * S, y * S, 30 * S, (y + 14) * S], 5 * S, (110, 124, 140, 255))
    return img.resize((256, 256), Image.LANCZOS)


def make_doc_icon():
    """A page with a folded corner and a small dial: the .valt document."""
    img = Image.new("RGBA", (256 * S, 256 * S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rounded(draw, [40 * S, 12 * S, 216 * S, 244 * S], 22 * S, (238, 242, 246, 255), (120, 132, 148, 255), 6 * S)
    draw.polygon([160 * S, 12 * S, 216 * S, 68 * S, 160 * S, 68 * S], fill=(180, 192, 206, 255))  # fold
    dial(draw, 128 * S, 138 * S, 46 * S,
         ((44, 56, 72, 255), (206, 216, 226, 255), (44, 56, 72, 255), (44, 56, 72, 255)))
    draw.rounded_rectangle([92 * S, 202 * S, 164 * S, 214 * S], 6 * S, (120, 132, 148, 255))
    return img.resize((256, 256), Image.LANCZOS)


for name, img in (("valt", make_app_icon()), ("valt-doc", make_doc_icon())):
    img.save(os.path.join(OUT, f"{name}.ico"), sizes=SIZES)
    img.save(os.path.join(OUT, f"{name}.png"))
    print(f"wrote {name}.ico / {name}.png")
