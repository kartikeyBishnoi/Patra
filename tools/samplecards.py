"""Specimen documents, so the reading pipeline can be tested and shown.

The document reader cannot be developed against real documents. Nobody should
be asked for a photograph of their Aadhaar card to run a test suite, and a test
that depends on a file somebody has to supply is a test that never runs.

So these are drawn from scratch: the layout and the printed phrases a real
certificate carries, with invented names and numbers, stamped SPECIMEN across
every one. They are good enough to exercise the signatures, the field patterns
and the redaction, and they are not good enough to present to anybody as a
record, which is the point.

    python3 tools/samplecards.py --out /tmp/cards

Devanagari needs a font that has it. Where none is installed the English half
of each bilingual document is drawn on its own, which is also all the English
tesseract pack could read anyway.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)
BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)

# Names and figures are invented. The phrases are the ones really printed on
# these documents, because those are what the signatures match on.
SPECIMENS = {
    "income_certificate": [
        ("title", "OFFICE OF THE TEHSILDAR"),
        ("title", "INCOME CERTIFICATE"),
        ("line", "Certificate No. SPECIMEN/2026/0000"),
        ("line", "This is to certify that Shri/Smt. Radha Devi"),
        ("line", "resident of Village Kherli, District Nuh"),
        ("line", "Annual Income: Rs 72,000"),
        ("line", "Issued on: 14/08/2026"),
        ("line", "Signature of Tehsildar"),
    ],
    "ration_card": [
        ("title", "DEPARTMENT OF FOOD AND PUBLIC DISTRIBUTION"),
        ("title", "RATION CARD"),
        ("line", "National Food Security Act"),
        ("line", "Card Category: ANTYODAYA"),
        ("line", "Head of Family: Radha Devi"),
        ("line", "Card No. SPECIMEN 0000 0000"),
        ("line", "Members: 4"),
    ],
    "aadhaar": [
        ("title", "GOVERNMENT OF INDIA"),
        ("line", "Unique Identification Authority of India"),
        ("title", "AADHAAR"),
        ("line", "Radha Devi"),
        ("line", "Year of Birth: 1964"),
        ("line", "0000 0000 0000"),
        ("line", "Mera Aadhaar, Meri Pehchaan"),
    ],
    "disability_certificate": [
        ("title", "DISTRICT MEDICAL BOARD"),
        ("title", "DISABILITY CERTIFICATE"),
        ("line", "Unique Disability ID: SPECIMEN-0000"),
        ("line", "Name: Bhola Ram"),
        ("line", "Permanent disability assessed at 60 percent"),
        ("line", "Chairperson, Medical Board"),
    ],
    "land_records": [
        ("title", "RECORD OF RIGHTS"),
        ("title", "KHATAUNI"),
        ("line", "Khasra No. SPECIMEN/114"),
        ("line", "Village Kherli, Tehsil Nuh"),
        ("line", "Holder: Ramlal Yadav"),
        ("line", "Area: 2.5 acres"),
    ],
}


def font(paths, size):
    for path in paths:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw(rows, width=900, height=520):
    image = Image.new("RGB", (width, height), "white")
    pen = ImageDraw.Draw(image)
    heavy = font(BOLD, 30)
    light = font(FONTS, 25)

    pen.rectangle([8, 8, width - 9, height - 9], outline="black", width=3)

    y = 46
    for kind, text in rows:
        pen.text((44, y), text, fill="black",
                 font=heavy if kind == "title" else light)
        y += 44 if kind == "title" else 38

    # Said plainly rather than at an angle, because a watermark tesseract
    # cannot read is a watermark a person cannot read either.
    pen.text((44, height - 56), "SPECIMEN  ·  NOT A REAL DOCUMENT",
             fill="black", font=font(BOLD, 26))
    return image


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="samplecards",
        description="Draw specimen documents for testing the reader.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for name, rows in SPECIMENS.items():
        path = args.out / f"{name}.png"
        draw(rows).save(path)
        print(f"  {path}")
    print(f"\n{len(SPECIMENS)} specimens in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
