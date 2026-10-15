"""Finding the numbers in a sentence, including the ones written as words.

Three things make this more than `int(...)`. People write numerals in their own
script. They say "do lakh" rather than 200000, and "a lakh" with no number in
front of it at all. And they hedge: "around a lakh" is an estimate, and acting
on it as a figure is how somebody gets told they are over a threshold they may
well be under, so a hedged number is carried as hedged all the way through.

The scale words are the part worth being careful with. A bare multiplier with
no count before it means one of them, and a count directly before it multiplies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .text import Reading, phrase_hits

_NUMERIC = re.compile(r"^\d+(?:\.\d+)?$")


@dataclass(frozen=True)
class Number:
    value: int
    start: int
    end: int
    hedged: bool
    """A hedge word sits within a few tokens, so this is an estimate."""

    scaled: bool
    """A scale word (thousand, lakh, crore) was applied."""

    text: str
    scale: int = 1
    """The multiplier that was applied, so additive compounds can be merged."""


class Numbers:
    """Reads the number vocabulary out of data/cues.yaml."""

    def __init__(self, cues: dict):
        spec = cues.get("numbers", {})
        self.words: dict[str, int] = {}
        for value in (spec.get("shared") or {}).items():
            self.words[str(value[0]).casefold()] = int(value[1])
        for table in (spec.get("words") or {}).values():
            for word, value in (table or {}).items():
                self.words[str(word).casefold()] = int(value)
        self.scales = {
            str(word).casefold(): int(value)
            for word, value in (spec.get("scales") or {}).items()
        }
        self.hedges = tuple(cues.get("hedges") or ())

    def find(self, reading: Reading, in_scope=None) -> list[Number]:
        """Every number, with any hedge that applies to it.

        `in_scope` decides whether a hedge reaches a number. The caller
        supplies it because clause boundaries live with the extractor, and a
        character window on its own lets "income around a lakh" mark the age
        in the clause before it as an estimate.
        """
        hedge_spans = [span for h in self.hedges for span in phrase_hits(reading, h)]
        reaches = in_scope or self._near_enough
        out: list[Number] = []

        i = 0
        tokens = reading.tokens
        while i < len(tokens):
            run = self._run(tokens, i)
            if run is None:
                i += 1
                continue
            value, scaled, consumed, scale = run
            start = tokens[i].start
            end = tokens[i + consumed - 1].end
            out.append(
                Number(
                    value=value,
                    start=start,
                    end=end,
                    hedged=any(reaches(start, s) or reaches(start, e)
                               for s, e in hedge_spans),
                    scaled=scaled,
                    text=reading.slice(start, end),
                    scale=scale,
                )
            )
            i += consumed
        return self._merge(reading, out)

    # ---- internals ----

    def _value(self, token: str) -> float | None:
        if _NUMERIC.match(token):
            return float(token)
        word = self.words.get(token)
        return float(word) if word is not None else None

    def _run(self, tokens, i) -> tuple[int, bool, int, int] | None:
        """One number starting at token i, with any scale word applied."""
        first = self._value(tokens[i].text)

        if first is None:
            # "a lakh", with the count left implicit.
            scale = self.scales.get(tokens[i].text)
            if scale is None:
                return None
            return scale, True, 1, scale

        consumed = 1
        total = first

        # "pachas hazaar" and "do lakh": a count then its multiplier.
        if i + 1 < len(tokens):
            scale = self.scales.get(tokens[i + 1].text)
            if scale is not None:
                total = first * scale
                consumed = 2
                return int(round(total)), True, consumed, scale

        return int(round(total)), False, consumed, 1

    @staticmethod
    def _merge(reading: Reading, found: list[Number]) -> list[Number]:
        """Join additive compounds: "do lakh pachas hazaar" is one figure.

        Indian number words stack by addition with strictly falling scale, and
        they are written that way far more often than as 250000. Only a falling
        scale merges, so "2 lakh" followed by an unrelated "5 acres" stays two
        numbers.
        """
        out: list[Number] = []
        for item in found:
            if out:
                last = out[-1]
                adjacent = 0 <= item.start - last.end <= 2
                falling = last.scaled and item.scaled and item.scale < last.scale
                if adjacent and falling:
                    out[-1] = Number(
                        value=last.value + item.value,
                        start=last.start,
                        end=item.end,
                        hedged=last.hedged or item.hedged,
                        scaled=True,
                        text=reading.slice(last.start, item.end),
                        scale=item.scale,
                    )
                    continue
            out.append(item)
        return out

    @staticmethod
    def _near_enough(a: int, b: int) -> bool:
        """The fallback when no clause information is supplied."""
        return abs(a - b) <= 40
