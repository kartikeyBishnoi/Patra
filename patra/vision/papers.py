"""Which document this is a photograph of, and what it says.

Two jobs, with very different stakes, and they are kept apart for that reason.

**Which document.** Decided by the phrases an issuing authority prints on every
copy. Getting it wrong costs a wrongly ticked checkbox the person can see and
untick, so the strongest candidate is offered along with the runners-up and the
phrase each one matched on.

**What it says.** A number read off a creased card in bad light is a guess. A
five read as a six moves an income by ten thousand rupees and can move a family
across a threshold, and nobody would ever know which had happened. So a value
read here is never used: it is proposed, shown beside the line of text it came
from, and reaches the solver only after the person confirms it. `patra.guard`
enforces that rather than trusting callers to remember.

Aadhaar and PAN numbers are matched and then thrown away. Their shape is the
best evidence of which card this is, and this app tells people it never asks
for their Aadhaar number, which has to remain true while it is looking at the
card itself.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..model.attributes import Kind, Schema
from ..nlp.extract import Confidence, Mention
from ..nlp.text import fold, phrase_hits, read
from .ocr import Scan

PAPERS = Path(__file__).resolve().parent.parent.parent / "data" / "papers.yaml"

# A year of birth is only an age if it is a year somebody could be born in.
EARLIEST_BIRTH_YEAR = 1900


@dataclass(frozen=True)
class Guess:
    document: str
    score: int
    matched: tuple[str, ...]
    """The printed phrases that produced this guess."""


@dataclass(frozen=True)
class Redacted:
    """A number used to identify the card and then discarded unread."""

    field: str
    shape: str
    """A description of what was found, never the digits."""


@dataclass(frozen=True)
class PaperReading:
    scan: Scan
    guesses: tuple[Guess, ...] = ()
    mentions: tuple[Mention, ...] = ()
    redacted: tuple[Redacted, ...] = ()
    unreadable: tuple[str, ...] = ()
    """Field rules that matched nothing, so the person knows what to type."""

    @property
    def document(self) -> str | None:
        return self.guesses[0].document if self.guesses else None

    @property
    def sure(self) -> bool:
        """One candidate clearly ahead of the next."""
        if not self.guesses:
            return False
        if len(self.guesses) == 1:
            return self.guesses[0].score >= 2
        return self.guesses[0].score >= self.guesses[1].score * 2


class Papers:
    def __init__(self, schema: Schema, signatures: dict | None = None,
                 today: datetime.date | None = None):
        self.schema = schema
        self.spec = (signatures if signatures is not None
                     else yaml.safe_load(PAPERS.read_text(encoding="utf-8")))["papers"]
        self.today = today or datetime.date.today()

    def interpret(self, scan: Scan) -> PaperReading:
        if not scan.ok:
            return PaperReading(scan=scan)

        reading = read(scan.text)
        guesses = []
        for document, spec in self.spec.items():
            matched = tuple(
                phrase for phrase in ((spec or {}).get("signatures") or ())
                if phrase_hits(reading, str(phrase))
            )
            if matched:
                guesses.append(Guess(document=document, score=len(matched),
                                     matched=matched))
        guesses.sort(key=lambda g: (-g.score, g.document))

        mentions, redacted, unreadable = (), (), ()
        if guesses:
            mentions, redacted, unreadable = self._fields(
                guesses[0].document, scan.text)

        return PaperReading(scan=scan, guesses=tuple(guesses),
                            mentions=mentions, redacted=redacted,
                            unreadable=unreadable)

    # ---- reading the fields off one kind of document ----

    def _fields(self, document: str, text: str):
        rules = ((self.spec.get(document) or {}).get("fields") or ())
        mentions, redacted, missed = [], [], []

        for rule in rules:
            name = rule.get("name", "field")
            try:
                found = re.search(str(rule["pattern"]), text,
                                  re.IGNORECASE | re.MULTILINE)
            except re.error:
                continue

            if found is None:
                missed.append(name)
                continue

            if rule.get("redact"):
                whole = found.group(0)
                redacted.append(Redacted(
                    field=name,
                    shape=f"{sum(c.isdigit() for c in whole)} digits"
                    if any(c.isdigit() for c in whole) else "a reference"))
                continue

            attribute = rule.get("attribute")
            if not attribute or attribute not in self.schema:
                continue

            raw = found.group(1) if found.groups() else found.group(0)
            value = self._value(attribute, raw, rule)
            if value is None:
                missed.append(name)
                continue

            mentions.append(Mention(
                attribute=attribute, value=value,
                # Always medium, never high. The guard turns every document
                # reading into a question regardless, and overstating the
                # confidence here would only mislead whoever reads the trace.
                confidence=Confidence.MEDIUM,
                evidence=self._line(text, found.start()),
                start=found.start(), end=found.end()))

        return tuple(mentions), tuple(redacted), tuple(missed)

    def _value(self, attribute: str, raw: str, rule: dict):
        attr = self.schema[attribute]
        reads = rule.get("reads")

        if attr.kind is Kind.ENUM:
            table = {fold(str(k)): v for k, v in (rule.get("map") or {}).items()}
            got = table.get(fold(raw))
            return got if got in attr.options else None

        if attr.kind is Kind.BOOL:
            return True

        digits = re.sub(r"[^\d.]", "", raw)
        if not digits:
            return None
        try:
            number = float(digits)
        except ValueError:
            return None

        if reads == "year":
            year = int(number)
            if not EARLIEST_BIRTH_YEAR <= year <= self.today.year:
                return None
            number = self.today.year - year
        elif reads == "money":
            # A certificate states a year's income. Where it states a month's
            # it says so in words the pattern does not capture, so the value is
            # confirmed rather than guessed at.
            number = int(number)

        # Half up, not Python's half-to-even, which turns 2.5 acres into 2 and
        # looks like a reading error rather than a rounding rule.
        value = int(number + 0.5) if number >= 0 else int(number - 0.5)
        if attr.low is not None and value < attr.low:
            return None
        if attr.high is not None and value > attr.high:
            return None
        return value

    @staticmethod
    def _line(text: str, position: int) -> str:
        start = text.rfind("\n", 0, position) + 1
        end = text.find("\n", position)
        return text[start:end if end != -1 else len(text)].strip()
