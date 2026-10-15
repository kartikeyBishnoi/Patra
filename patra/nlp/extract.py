"""Turning a sentence into proposed facts.

    "Meri maa 62 saal ki hain aur unka husband nahi hai"

        relation          mother          (so gender is female)
        age               62              from "62 saal"
        marital_status    widowed         from "husband nahi", unsure

What it is not is a classifier. It is a gazetteer and a set of positional
rules, which matters for three reasons. It can point at the exact words that
produced each fact, so a wrong reading is visible instead of mysterious. It
degrades into "I did not catch that" rather than into a confident invention.
And its vocabulary is a YAML file a Marathi speaker can fix.

Nothing here decides anything. Every fact comes out as a proposal with a
confidence attached; `patra.guard` checks it against the schema and the domain
axioms, the unsure ones are read back to the person, and only then does the
solver see them.

Three rules do most of the work.

**Negation is scoped to the clause.** Hindi and Marathi put the negation after
the phrase, English puts it before, so both directions are searched, but only
as far as the nearest punctuation. "I have a bank account, no gas connection"
must not come out as having no bank account.

**A number needs an anchor and has to be plausible.** A bare "62" could be an
age, an income or a house number, so a number with no anchoring word near it is
discarded. Where two anchors compete, the schema's own range settles it: 72000
is not an age, so "72000 saal ki kamai" is income.

**A monthly figure is rescaled.** People state what they earn in a month far
more often than in a year, and reading 6000 a month as 6000 a year clears every
income threshold in the rulebook.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from ..model.attributes import Kind, Schema
from .numbers import Number, Numbers
from .text import Reading, phrase_hits, read

CUES = Path(__file__).resolve().parent.parent.parent / "data" / "cues.yaml"

_CLAUSE = re.compile(r"[।.;:,?!\n]|\baur\b|\band\b|\bbut\b|\blekin\b|\bपर\b|\bऔर\b")

# How near an anchoring word has to be before a number is believed to be the
# thing that word names. Two clauses of slack reads worse than it sounds: the
# clause boundary is checked separately, and this only ranks competitors.
NEAR = 44


def _tier(name) -> "Confidence | None":
    """A tier name from the cue file, or None for a key that is not one."""
    try:
        return Confidence(str(name))
    except ValueError:
        return None


def _strings(values) -> tuple[str, ...]:
    """Cue phrases, whatever YAML made of them.

    A bare `no` or `yes` in a cue list parses as a boolean under YAML 1.1. The
    lists are quoted for that reason, but a contributor adding a phrase should
    get a working app rather than a stack trace, so the type is forced here too.
    """
    if not values:
        return ()
    return tuple(str(v) for v in values if v is not None and str(v).strip())


class Confidence(Enum):
    HIGH = "high"
    """The phrase means this and nothing else. Used without asking."""

    MEDIUM = "medium"
    """The phrase usually means this. Used, and shown with its evidence."""

    LOW = "low"
    """The phrase hints at it. Never used until the person confirms."""

    @property
    def rank(self) -> int:
        return {"high": 3, "medium": 2, "low": 1}[self.value]

    @property
    def needs_confirming(self) -> bool:
        return self is Confidence.LOW


@dataclass(frozen=True)
class Mention:
    attribute: str
    value: object
    confidence: Confidence
    evidence: str
    """The words that produced it, so a wrong reading can be seen."""

    start: int
    end: int
    hedged: bool = False
    negated: bool = False
    inferred_from: str | None = None
    """Set when the fact came from something else said, not from its own words.

    "My mother" gives a gender nobody stated. Worth having and worth labelling.
    """


@dataclass(frozen=True)
class Understanding:
    reading: Reading
    mentions: tuple[Mention, ...]
    relation: str | None = None
    relation_evidence: str | None = None
    disagreements: tuple[tuple[Mention, Mention], ...] = ()
    """One attribute read two ways. Neither is used without asking."""

    numbers_unused: tuple[Number, ...] = ()
    """Numbers with nothing to attach them to, reported so the person can see
    that "62" was noticed and not understood."""

    @property
    def understood_anything(self) -> bool:
        return bool(self.mentions)

    def by_attribute(self) -> dict:
        return {m.attribute: m for m in self.mentions}


class Extractor:
    def __init__(self, schema: Schema, cues: dict | None = None):
        self.schema = schema
        self.cues = cues if cues is not None else yaml.safe_load(
            CUES.read_text(encoding="utf-8"))
        self.numbers = Numbers(self.cues)
        self.negations = _strings(self.cues.get("negations"))
        self.first_person = _strings(self.cues.get("first_person"))
        self.inquiries = _strings(self.cues.get("inquiries"))
        self.relations = self.cues.get("relations") or {}
        self.blocks = {
            name: spec
            for name, spec in (self.cues.get("attributes") or {}).items()
            if name in schema
        }

    # ---- the whole job ----

    def understand(self, text: str) -> Understanding:
        reading = read(text or "")
        if not reading.tokens:
            return Understanding(reading=reading, mentions=())

        negations = self._spans(reading, self.negations)
        asking = self._spans(reading, self.inquiries)
        clauses = self._clauses(reading)

        relation, relation_span = self._relation(reading, negations, clauses)

        found: list[Mention] = []
        found += self._categorical(reading, negations, clauses, asking)
        numeric, unused = self._numeric(reading, clauses, relation_span)
        found += numeric

        if relation:
            found += self._implied(relation, relation_span, reading)

        kept, clashes = self._settle(found)
        return Understanding(
            reading=reading,
            mentions=tuple(kept),
            relation=relation,
            relation_evidence=(reading.slice(*relation_span) if relation_span else None),
            disagreements=tuple(clashes),
            numbers_unused=tuple(unused),
        )

    # ---- booleans and enums ----

    def _categorical(self, reading, negations, clauses, asking=()) -> list[Mention]:
        out: list[Mention] = []
        for name, block in self.blocks.items():
            attr = self.schema[name]
            if attr.kind is Kind.INT:
                continue
            for value, tiers in self._value_tiers(attr, block):
                for tier, phrases in tiers.items():
                    confidence = _tier(tier)
                    if confidence is None:
                        continue
                    for phrase in _strings(phrases):
                        for start, end in phrase_hits(reading, phrase):
                            if self._in_scope(start, end, asking, clauses):
                                # Asking about a thing is not having it.
                                continue
                            mention = self._categorical_hit(
                                reading, attr, value, confidence,
                                start, end, negations, clauses)
                            if mention is not None:
                                out.append(mention)
        return out

    @staticmethod
    def _value_tiers(attr, block):
        """The (value, {tier: phrases}) pairs declared for one attribute."""
        if attr.kind is Kind.BOOL:
            for key, value in (("true", True), ("false", False)):
                tiers = block.get(key)
                if isinstance(tiers, dict):
                    yield value, tiers
            return
        for option, tiers in (block.get("options") or {}).items():
            if option in attr.options and isinstance(tiers, dict):
                yield option, tiers

    def _categorical_hit(self, reading, attr, value, confidence,
                         start, end, negations, clauses):
        negated = self._negated(start, end, negations, clauses)

        if not negated:
            return Mention(attribute=attr.name, value=value,
                           confidence=confidence, evidence=reading.slice(start, end),
                           start=start, end=end)

        if attr.kind is Kind.BOOL:
            # "khata nahi hai" is a fact about having no account, and just as
            # usable as the positive.
            return Mention(attribute=attr.name, value=not value,
                           confidence=confidence, evidence=reading.slice(start, end),
                           start=start, end=end, negated=True)

        # "not a farmer" names seven other occupations and settles none of
        # them, so there is no fact here to propose.
        return None

    # ---- numbers ----

    def _numeric(self, reading, clauses, relation_span=None):
        anchors: dict[str, list[tuple[int, int]]] = {}
        monthly: dict[str, list[tuple[int, int]]] = {}
        for name, block in self.blocks.items():
            if self.schema[name].kind is not Kind.INT:
                continue
            anchors[name] = [
                span for cue in _strings(block.get("anchors"))
                for span in phrase_hits(reading, cue)
            ]
            monthly[name] = [
                span for cue in _strings(block.get("per_month"))
                for span in phrase_hits(reading, cue)
            ]

        # "My daughter is 9" and "meri maa 62" name a person and then a bare
        # number, and the number is their age. Nothing else is said that way,
        # so the relation word earns its place as an age anchor.
        if relation_span and "age" in anchors:
            anchors["age"] = anchors["age"] + [relation_span]

        out: list[Mention] = []
        unused: list[Number] = []
        in_clause = lambda a, b: self._same_clause(a, b, clauses)
        for number in self.numbers.find(reading, in_clause):
            best = self._bind(number, anchors, clauses)
            if best is None:
                unused.append(number)
                continue
            name, distance, anchor = best
            value = number.value
            block = self.blocks[name]

            if any(self._same_clause(number.start, s, clauses)
                   for s, _ in monthly.get(name, ())):
                value *= 12

            confidence = Confidence.HIGH
            if number.hedged:
                confidence = Confidence.LOW
            elif distance > NEAR // 2:
                confidence = Confidence.MEDIUM

            low = min(number.start, anchor[0])
            high = max(number.end, anchor[1])
            out.append(Mention(
                attribute=name, value=int(value), confidence=confidence,
                evidence=reading.slice(low, high), start=low, end=high,
                hedged=number.hedged))
        return out, unused

    def _bind(self, number: Number, anchors, clauses):
        """Which attribute this number belongs to, if any.

        Where two anchors compete, the schema's own range breaks the tie:
        "72000 saal ki kamai" has both an age word and an income word beside
        it, and 72000 is not an age, so it is income.

        A number that fits nothing is still bound to its nearest anchor rather
        than dropped. "My age is 480" is a mis-heard answer about an age, and
        the person should be told it was not usable instead of watching it
        vanish, so the range check belongs in the guard where it has a voice.
        """
        candidates = []
        for name, spans in anchors.items():
            fits = (self._plausible(self.blocks[name], number.value)
                    or self._plausible_after_scaling(name, number.value))
            for span in spans:
                if not self._same_clause(number.start, span[0], clauses):
                    continue
                distance = min(abs(number.start - span[1]), abs(span[0] - number.end))
                if distance > NEAR:
                    continue
                candidates.append((0 if fits else 1, distance, name, span))
        if not candidates:
            return None
        _, distance, name, span = min(candidates)
        return name, distance, span

    def _plausible_after_scaling(self, name, value) -> bool:
        """A monthly income is plausible once multiplied out."""
        block = self.blocks.get(name) or {}
        return bool(block.get("per_month")) and self._plausible(block, value * 12)

    @staticmethod
    def _plausible(block, value) -> bool:
        window = block.get("plausible")
        if not window:
            return True
        return window[0] <= value <= window[1]

    # ---- relation ----

    def _relation(self, reading, negations=(), clauses=()):
        """Whose answers these are.

        A sentence can name two relatives: "meri maa ka husband nahi hai" is
        about the mother, not the husband. The one introduced by a first-person
        possessive wins, and where neither is, the one said first wins, because
        a second relative is almost always mentioned to describe the first.

        A relative mentioned to say they are gone is not the subject. "Unka
        pati nahi hai" is about a widow, and treating the husband as the person
        being asked about would read his gender onto her.
        """
        owned = [span for word in self.first_person
                 for span in phrase_hits(reading, word)]

        candidates = []
        for name, spec in self.relations.items():
            if name == "self":
                continue
            for phrase in _strings(spec.get("phrases")):
                for span in phrase_hits(reading, phrase):
                    if self._negated(span[0], span[1], negations, clauses):
                        continue
                    mine = any(0 <= span[0] - end <= 16 for _, end in owned)
                    candidates.append((0 if mine else 1, span[0],
                                       -(span[1] - span[0]), name, span))
        if candidates:
            chosen = min(candidates)
            return chosen[3], chosen[4]

        for phrase in _strings((self.relations.get("self") or {}).get("phrases")):
            hits = phrase_hits(reading, phrase)
            if hits:
                return "self", hits[0]
        return None, None

    def _implied(self, relation, span, reading) -> list[Mention]:
        implied = (self.relations.get(relation) or {}).get("implies") or {}
        out = []
        for name, value in implied.items():
            if name not in self.schema:
                continue
            attr = self.schema[name]
            if attr.kind is Kind.ENUM and value not in attr.options:
                continue
            out.append(Mention(
                attribute=name, value=value, confidence=Confidence.HIGH,
                evidence=reading.slice(*span), start=span[0], end=span[1],
                inferred_from=relation))
        return out

    # ---- settling disagreements ----

    def _settle(self, found):
        """One value per attribute, and a flag where the sentence said two.

        The best evidence wins when two phrases agree. When they disagree the
        attribute is held back entirely, because picking the higher confidence
        would quietly discard half of what was said.
        """
        grouped: dict[str, list[Mention]] = {}
        for m in found:
            grouped.setdefault(m.attribute, []).append(m)

        kept: list[Mention] = []
        clashes: list[tuple[Mention, Mention]] = []
        for mentions in grouped.values():
            mentions.sort(key=lambda m: (-m.confidence.rank, len(m.evidence) * -1))
            winner = mentions[0]
            other = next((m for m in mentions if m.value != winner.value), None)
            if other is None:
                kept.append(winner)
                continue
            if winner.confidence.rank > other.confidence.rank:
                # A definite phrase beats a hint. "I am a widow, my husband is
                # not here" is not a contradiction.
                kept.append(winner)
                continue
            clashes.append((winner, other))
        kept.sort(key=lambda m: m.start)
        return kept, clashes

    # ---- scope helpers ----

    @staticmethod
    def _spans(reading, words):
        return [span for word in words for span in phrase_hits(reading, word)]

    @staticmethod
    def _clauses(reading: Reading):
        """Character ranges between punctuation and conjunctions."""
        bounds = [0]
        for m in _CLAUSE.finditer(reading.text):
            bounds.append(m.start())
        bounds.append(len(reading.text))
        return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]

    @staticmethod
    def _same_clause(a: int, b: int, clauses) -> bool:
        return any(lo <= a <= hi and lo <= b <= hi for lo, hi in clauses)

    def _in_scope(self, start, end, markers, clauses) -> bool:
        """Is a marker in this cue's clause, without being part of the cue.

        The overlap test is what makes both negation and inquiry safe. A cue
        that contains its own marker is already the statement: "pati nahi" is
        the negative, and "kaam chahiye" is a wish that is itself the fact.
        Counting the marker twice would invert one and suppress the other.
        """
        for ms, me in markers:
            if ms < end and start < me:
                continue
            if self._same_clause(start, ms, clauses):
                return True
        return False

    def _negated(self, start, end, negations, clauses) -> bool:
        return self._in_scope(start, end, negations, clauses)
