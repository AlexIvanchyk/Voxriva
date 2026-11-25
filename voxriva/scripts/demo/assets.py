"""Author original fictional brand assets; requires Pillow. No remote media."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "assets"


def font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    return ImageFont.truetype(next(p for p in candidates if Path(p).exists()), size)


def main():
    OUT.mkdir(exist_ok=True)
    logo = Image.new("RGB", (640, 120), "#ffffff")
    d = ImageDraw.Draw(logo)
    d.rounded_rectangle((0, 0, 112, 112), 28, fill="#133f3a")
    d.polygon(
        [
            (56, 18),
            (65, 45),
            (94, 56),
            (65, 66),
            (56, 94),
            (46, 66),
            (18, 56),
            (46, 45),
        ],
        fill="#bde897",
    )
    d.text((135, 10), "NORTHSTAR", font=font(47, True), fill="#133f3a")
    d.text((137, 70), "M A R K E T", font=font(24), fill="#697971")
    logo.save(OUT / "northstar-logo.png", optimize=True)
    for name, title, subtitle, bg, accent in [
        (
            "welcome",
            "Good things, closer.",
            "Thoughtful essentials for everyday living",
            "#e8f1df",
            "#91b66d",
        ),
        (
            "seasonal",
            "A little fresh perspective.",
            "Your next chapter starts here",
            "#f7e9dc",
            "#d49c70",
        ),
    ]:
        im = Image.new("RGB", (1120, 480), bg)
        d = ImageDraw.Draw(im)
        d.ellipse((800, -110, 1220, 310), fill=accent)
        d.rounded_rectangle((785, 185, 985, 425), 25, fill="#133f3a")
        d.ellipse((825, 165, 945, 285), fill="#f6f3e7")
        d.rounded_rectangle((960, 300, 1090, 465), 20, fill="#f6f3e7")
        d.line([(1025, 300), (1030, 220), (1085, 185)], fill="#133f3a", width=9)
        d.ellipse((1030, 220, 1090, 250), fill="#133f3a")
        d.ellipse((1000, 235, 1045, 265), fill="#133f3a")
        d.text((55, 70), "NORTHSTAR NOTES / 01", font=font(23, True), fill="#376052")
        words = title.split()
        lines = (
            [" ".join(words[:2]), " ".join(words[2:])]
            if name == "welcome"
            else ["A little fresh", "perspective."]
        )
        for i, line in enumerate(lines):
            d.text((50, 145 + 70 * i), line, font=font(60, True), fill="#133f3a")
        d.text((55, 345), subtitle, font=font(24), fill="#376052")
        im.save(OUT / f"northstar-{name}.png", optimize=True)
    print("Created three original fictional Northstar assets.")


if __name__ == "__main__":
    main()
