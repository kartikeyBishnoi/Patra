"""Getting a typed or spoken sentence into one comparable shape.

Everything downstream matches phrases against positions in a string, so there
has to be exactly one string. Normalising once and keeping the offsets means
the evidence shown back to the person ("we read this from: 62 saal ki hain") is
a real slice of what they actually wrote rather than a reconstruction.

Case folding is done with `lower` rather than `casefold` wherever folding would
change the length, because a shifted offset points the evidence at the wrong
words, and wrong evidence is worse than none.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Indic digits are what a phone keyboard in a Devanagari layout produces, and
# what speech-to-text returns for spoken numerals in these languages.
DIGIT_SCRIPTS = (
    "०१२३४५६७८९",      # Devanagari
    "০১২৩৪৫৬৭৮৯",      # Bengali
    "௦௧௨௩௪௫௬௭௮௯",      # Tamil
    "૦૧૨૩૪૫૬૭૮૯",      # Gujarati
    "੦੧੨੩੪੫੬੭੮੯",      # Gurmukhi
    "౦౧౨౩౪౫౬౭౮౯",      # Telugu
    "೦೧೨೩೪೫೬೭೮೯",      # Kannada
)

_DIGITS = str.maketrans({d: str(i) for script in DIGIT_SCRIPTS
                         for i, d in enumerate(script)})

# A comma inside a number is a thousands mark, not a clause break. Removing it
# here keeps "72,000" one token instead of two unrelated numbers.
_GROUPED = re.compile(r"(?<=\d),(?=\d\d\d)")

# `\w` is the wrong tool for Indic text. A Devanagari vowel sign is a
# combining mark, which is not alphanumeric, so `[^\W_]+` splits "उत्पन्न" into
# three pieces and no cue phrase ever matches again. Tokens are therefore
# defined by what separates them rather than by what they contain.
# Characters that separate tokens rather than belong to one. The dashes are
# here to be recognised in what somebody types, not to be written by us.
_PUNCT = ",;:?!…·()[]{}<>\"'`/\\|@#$%^&*+=~\u2014\u2013-_" + "।॥“”‘’₹"
_TOKEN = re.compile("[^" + re.escape(_PUNCT) + r"\s]+")


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class Reading:
    """One sentence, normalised, with its tokens and the original beside it."""

    raw: str
    text: str
    """Normalised and folded. All offsets refer to this."""

    tokens: tuple[Token, ...]

    def slice(self, start: int, end: int) -> str:
        return self.text[start:end].strip()

    def token_at(self, index: int) -> Token | None:
        return self.tokens[index] if 0 <= index < len(self.tokens) else None

    def between(self, start: int, end: int) -> tuple[Token, ...]:
        return tuple(tk for tk in self.tokens if tk.start >= start and tk.end <= end)


def fold(text: str) -> str:
    """Normalise, strip digit scripts, and lower without moving any offset."""
    canon = unicodedata.normalize("NFKC", text)
    canon = canon.translate(_DIGITS)
    canon = _GROUPED.sub("", canon)
    lowered = canon.casefold()
    # Turkish dotless i and the German sharp s both change length under
    # casefold. Nothing here needs either, and a length change would desync
    # every offset, so fall back to the length-preserving fold.
    if len(lowered) != len(canon):
        lowered = canon.lower()
    if len(lowered) != len(canon):
        lowered = canon
    return lowered


def read(text: str) -> Reading:
    folded = fold(text)
    tokens = []
    for m in _TOKEN.finditer(folded):
        # A full stop is kept inside the token class so "1.5" survives, which
        # leaves it stuck to the end of a sentence's last word.
        word = m.group(0).strip(".")
        if not word:
            continue
        start = m.start() + m.group(0).index(word)
        tokens.append(Token(text=word, start=start, end=start + len(word)))
    return Reading(raw=text, text=folded, tokens=tuple(tokens))


# A cue this long or longer may be followed by an inflectional ending.
STEM = 3


def phrase_hits(reading: Reading, phrase: str) -> list[tuple[int, int]]:
    """Every place a cue phrase occurs, on word boundaries.

    The left boundary is strict, which is what stops "no" matching inside
    "nobody" and "das" inside "dastavez".

    The right boundary is not, and deliberately. Hindi, Marathi, Bengali and
    Tamil mark case with suffixes, so "गाव" (village) appears as "गावात" (in
    the village) and demanding a clean break would miss it. A cue may therefore
    run into a following vowel sign, but only if it is long enough to be a stem
    rather than a syllable, so a two-letter cue stays strict.
    """
    needle = fold(phrase).strip()
    if not needle:
        return []

    out: list[tuple[int, int]] = []
    start = reading.text.find(needle)
    while start != -1:
        end = start + len(needle)
        before = reading.text[start - 1] if start else " "
        after = reading.text[end] if end < len(reading.text) else " "
        if not _wordish(before) and _right_ok(after, needle):
            out.append((start, end))
        start = reading.text.find(needle, start + 1)
    return out


def _right_ok(after: str, needle: str) -> bool:
    if not _wordish(after):
        return True
    return len(needle) >= STEM and _mark(after)


def _mark(ch: str) -> bool:
    return unicodedata.category(ch) in ("Mn", "Mc")


def _wordish(ch: str) -> bool:
    return ch.isalnum() or ch == "_" or _mark(ch)
