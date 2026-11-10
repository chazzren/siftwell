"""Regenerate the raster brand assets in assets/brand/ from the funnel mark (same geometry as siftwell-mark.svg).

    python scripts/build_icons.py

Needs Pillow (a build-time tool only; the app itself never imports it). Draws at 2048 px, then downsamples.
Outputs: favicon-16/32/48.png, apple-touch-icon.png (180), icon-192/512/1024.png, siftwell.ico, siftwell.icns,
social-preview.png (1280x640).
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "brand")
TEAL, GOLD, WHITE, INK, MUTED = "#0F6E56", "#FAC775", "#FFFFFF", "#152033", "#5B6678"
BASE = 2048


def mark(size=BASE, background=True):
    """The mark on an 112-unit grid, scaled to size x size, RGBA."""
    k = size / 112.0
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if background:
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=28 * k, fill=TEAL)
    for cx in (38, 56, 74):
        d.ellipse([(cx - 4) * k, 16 * k, (cx + 4) * k, 24 * k], fill=WHITE)
    pts = [(22, 32), (90, 32), (64, 62), (64, 78), (48, 78), (48, 62)]
    for i, a in enumerate(pts):                      # stroke 7 with round joins: thick segments + a disc per vertex
        b = pts[(i + 1) % len(pts)]
        d.line([(a[0] * k, a[1] * k), (b[0] * k, b[1] * k)], fill=WHITE, width=round(7 * k))
        d.ellipse([(a[0] - 3.5) * k, (a[1] - 3.5) * k, (a[0] + 3.5) * k, (a[1] + 3.5) * k], fill=WHITE)
    d.ellipse([50 * k, 88 * k, 62 * k, 100 * k], fill=GOLD)
    return im


def font(size, bold=True):
    names = (["segoeuib.ttf", "arialbd.ttf", "SFNS.ttf", "Helvetica.ttc", "DejaVuSans-Bold.ttf"] if bold
             else ["segoeui.ttf", "arial.ttf", "SFNS.ttf", "Helvetica.ttc", "DejaVuSans.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def save_png(im, name, size):
    im.resize((size, size), Image.LANCZOS).save(os.path.join(OUT, name))


def social():
    W, H = 1280, 640
    im = Image.new("RGB", (W, H), "#F5F6F8")
    m = mark().resize((200, 200), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    f1, f2 = font(120), font(34, False)
    word, tag = "Siftwell", "Your own job search assistant"
    tw = d.textlength(word, font=f1)
    total = 200 + 40 + tw
    x0 = (W - total) / 2
    im.paste(m, (round(x0), 150), m)
    d.text((x0 + 240, 150 + 100), word, font=f1, fill=INK, anchor="lm")
    d.text((W / 2, 440), tag, font=f2, fill=MUTED, anchor="mm")
    d.text((W / 2, 490), "that runs on your computer", font=f2, fill=MUTED, anchor="mm")
    im.save(os.path.join(OUT, "social-preview.png"))


def main():
    os.makedirs(OUT, exist_ok=True)
    big = mark()
    for s in (16, 32, 48):
        save_png(big, f"favicon-{s}.png", s)
    save_png(big, "apple-touch-icon.png", 180)
    for s in (192, 512, 1024):
        save_png(big, f"icon-{s}.png", s)
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "siftwell.ico"),
                                              sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    big.resize((1024, 1024), Image.LANCZOS).save(os.path.join(OUT, "siftwell.icns"))
    social()
    print("wrote", sorted(os.listdir(OUT)))


if __name__ == "__main__":
    main()
