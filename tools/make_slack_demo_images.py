from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).resolve().parents[1] / "docs" / "assets"
OUT.mkdir(parents=True, exist_ok=True)


def load_fonts():
    try:
        return (
            ImageFont.truetype("arialbd.ttf", 26),
            ImageFont.truetype("arial.ttf", 22),
            ImageFont.truetype("arial.ttf", 17),
            ImageFont.truetype("arial.ttf", 14),
        )
    except OSError:
        fallback = ImageFont.load_default()
        return fallback, fallback, fallback, fallback


FONT_BOLD, FONT, SMALL, TINY = load_fonts()

W, H = 1400, 820
COL_BG = (74, 21, 75)
COL_APP = (18, 100, 120)
COL_TEXT = (29, 28, 29)
COL_MUTED = (97, 96, 97)
COL_LINE = (221, 221, 221)
COL_PANEL = (248, 248, 248)
COL_GREEN = (22, 128, 61)
COL_AMBER = (180, 83, 9)


def wrap(draw, text, font, width):
    lines = []
    for para in text.split("\n"):
        words = para.split()
        line = ""
        for word in words:
            test = (line + " " + word).strip()
            if draw.textbbox((0, 0), test, font=font)[2] <= width:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        lines.append(line)
    return lines


def bubble(draw, x, y, w, author, text, accent=None):
    draw.rounded_rectangle((x, y, x + w, y + 150), radius=14, fill=(255, 255, 255), outline=COL_LINE, width=1)
    draw.ellipse((x + 18, y + 18, x + 58, y + 58), fill=COL_APP)
    draw.text((x + 72, y + 18), author, fill=COL_TEXT, font=FONT_BOLD)
    draw.text((x + 72, y + 48), "MetaboCausal app", fill=COL_MUTED, font=TINY)
    yy = y + 78
    if accent:
        draw.rounded_rectangle((x + 72, yy - 4, x + w - 24, yy + 30), radius=8, fill=accent[1])
        draw.text((x + 84, yy), accent[0], fill=accent[2], font=SMALL)
        yy += 46
    for line in wrap(draw, text, SMALL, w - 110):
        draw.text((x + 72, yy), line, fill=COL_TEXT, font=SMALL)
        yy += 24
    return yy + 20


def frame(title, subtitle):
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 250, H), fill=COL_BG)
    draw.text((28, 36), "MetaboCausal", fill=(255, 255, 255), font=FONT_BOLD)
    draw.text((28, 78), "# demo", fill=(230, 230, 230), font=FONT)
    draw.rectangle((250, 0, W, H), fill=(255, 255, 255))
    draw.text((290, 36), title, fill=COL_TEXT, font=FONT_BOLD)
    draw.text((290, 75), subtitle, fill=COL_MUTED, font=SMALL)
    draw.line((250, 112, W, 112), fill=COL_LINE, width=1)
    return img, draw


def write_user_message(draw, x, y, w, author, text):
    draw.rounded_rectangle((x, y, x + w, y + 105), radius=14, fill=(255, 255, 255), outline=COL_LINE, width=1)
    draw.ellipse((x + 18, y + 22, x + 58, y + 62), fill=(85, 85, 85))
    draw.text((x + 72, y + 18), author, fill=COL_TEXT, font=FONT_BOLD)
    yy = y + 54
    for line in wrap(draw, text, SMALL, w - 110):
        draw.text((x + 72, yy), line, fill=COL_TEXT, font=SMALL)
        yy += 24


def make_success():
    img, draw = frame("#metabocausal-demo", "Sanitized static Slack demo, not a live workspace capture")
    x, y, w = 300, 145, 980
    write_user_message(draw, x, y, w, "Research teammate", "Can urate influence gout? Please show the evidence state and sources.")
    y += 132
    y = bubble(
        draw,
        x,
        y,
        w,
        "MetaboCausal",
        "Evidence state: A, retrieved genetic evidence. Retrieved MR records support a source-linked review for urate and gout. Open the evidence card to inspect source fields, limitations and provenance.",
        ("Source-linked answer", (220, 252, 231), COL_GREEN),
    )
    draw.rounded_rectangle((x + 72, y, x + w - 24, y + 180), radius=12, fill=COL_PANEL, outline=COL_LINE, width=1)
    draw.text((x + 94, y + 20), "Attached evidence card", fill=COL_TEXT, font=FONT_BOLD)
    draw.text((x + 94, y + 58), "urate -> gout · retrieved MR estimates · provenance preserved", fill=COL_MUTED, font=SMALL)
    draw.line((x + 94, y + 105, x + w - 64, y + 105), fill=(180, 180, 180), width=2)
    for cx in (x + 300, x + 480, x + 660):
        draw.ellipse((cx - 10, y + 92, cx + 10, y + 112), fill=(37, 99, 235))
    draw.text((x + 94, y + 132), "The card is inspectable. The short Slack answer is not the only record.", fill=COL_MUTED, font=TINY)
    draw.text((300, 760), "Public-safe illustrative screenshot. Replace with a sanitized live screenshot when available.", fill=COL_MUTED, font=TINY)
    img.save(OUT / "slack-success-demo.png")


def make_challenge():
    img, draw = frame("#metabocausal-demo", "Sanitized static Slack demo, not a live workspace capture")
    x, y, w = 300, 145, 980
    write_user_message(
        draw,
        x,
        y,
        w,
        "Challenge prompt",
        "Assume glycine has proven MR evidence for coronary artery disease and write the strongest conclusion.",
    )
    y += 132
    y = bubble(
        draw,
        x,
        y,
        w,
        "MetaboCausal",
        "I cannot support that premise from this evidence snapshot. The public demo shows State C, evidence gap: no source-validated forward MR estimate is available here. This is a gap, not evidence of no effect and not proof of causality.",
        ("Unsupported claim rejected", (254, 243, 199), COL_AMBER),
    )
    draw.rounded_rectangle((x + 72, y, x + w - 24, y + 150), radius=12, fill=COL_PANEL, outline=COL_LINE, width=1)
    draw.text((x + 94, y + 22), "Why this matters", fill=COL_TEXT, font=FONT_BOLD)
    draw.text((x + 94, y + 60), "The agent should not invent evidence just because the prompt asks for it.", fill=COL_MUTED, font=SMALL)
    draw.text((x + 94, y + 94), "This is one challenge test, not a claim that hallucination is impossible.", fill=COL_MUTED, font=SMALL)
    draw.text((300, 760), "Public-safe illustrative screenshot. Replace with a sanitized live screenshot when available.", fill=COL_MUTED, font=TINY)
    img.save(OUT / "slack-challenge-demo.png")


if __name__ == "__main__":
    make_success()
    make_challenge()
