"""Getting text off a photograph, on this machine.

Tesseract is a local binary, so a photographed income certificate is read in
the same process boundary as everything else and no image leaves the device.
That matters more here than the accuracy would: the alternative is uploading a
picture of somebody's caste certificate to a cloud vision API, which no promise
in a privacy policy makes acceptable.

It is called over a pipe rather than through a Python wrapper because the
wrapper is another dependency for one subprocess call, and the standard library
already does subprocesses.

Indic scripts need their own trained data, which is packaged separately from
tesseract itself. What is installed is detected rather than assumed, and a
missing pack is reported as a missing pack instead of coming back as an empty
read that looks like a bad photograph.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

BINARY = "tesseract"

# Our language codes to tesseract's. Tesseract uses ISO 639-2/T.
TESSERACT_LANG = {
    "en": "eng",
    "hi": "hin",
    "mr": "mar",
    "bn": "ben",
    "ta": "tam",
}

# Every Indian document worth reading here is bilingual, so the local script
# and English are always requested together.
TIMEOUT = 40


@dataclass(frozen=True)
class Capability:
    available: bool
    installed: tuple[str, ...] = ()
    """Tesseract language packs present on this machine."""

    missing: tuple[str, ...] = ()
    """Our languages with no pack, named so the message can say which."""

    note: str | None = None


@dataclass(frozen=True)
class Scan:
    text: str
    used: tuple[str, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text.strip())

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(l.strip() for l in self.text.splitlines() if l.strip())


def capability() -> Capability:
    """What this machine can actually read, asked rather than assumed."""
    if shutil.which(BINARY) is None:
        return Capability(False, note="tesseract is not installed")
    try:
        done = subprocess.run([BINARY, "--list-langs"],
                              capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return Capability(False, note=str(exc))

    found = {
        line.strip() for line in done.stdout.decode("utf-8", "replace").splitlines()
        if line.strip() and " " not in line.strip()
    }
    installed = tuple(sorted(found))
    missing = tuple(
        code for code, pack in TESSERACT_LANG.items() if pack not in found
    )
    note = None
    if missing:
        note = f"install {', '.join(packs_for(missing))} to read these scripts"
    return Capability(True, installed=installed, missing=missing, note=note)


def packs_for(codes) -> list[str]:
    """The package names to install, so the message can be said in any
    language with only the names left in Latin, which is what you type."""
    return [f"tesseract-ocr-{TESSERACT_LANG[c]}" for c in codes
            if c in TESSERACT_LANG]


def scan(image: bytes, lang: str = "en", cap: Capability | None = None) -> Scan:
    """Read one image. The language is a hint; English is always included."""
    cap = cap or capability()
    if not cap.available:
        return Scan("", error=cap.note or "no text reader on this machine")

    wanted = []
    pack = TESSERACT_LANG.get(lang)
    if pack and pack in cap.installed:
        wanted.append(pack)
    if "eng" in cap.installed and "eng" not in wanted:
        wanted.append("eng")
    if not wanted:
        return Scan("", error=cap.note or "no language pack installed")

    try:
        done = subprocess.run(
            # psm 4 treats the page as columns of text, which is what a card
            # or a certificate is. psm 3 splits them into unrelated blocks.
            [BINARY, "-", "stdout", "-l", "+".join(wanted), "--psm", "4"],
            input=image, capture_output=True, timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return Scan("", error="reading the picture took too long")
    except (OSError, subprocess.SubprocessError) as exc:
        return Scan("", error=str(exc))

    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip().splitlines()
        return Scan("", used=tuple(wanted),
                    error=detail[-1] if detail else "could not read the picture")
    return Scan(done.stdout.decode("utf-8", "replace"), used=tuple(wanted))
