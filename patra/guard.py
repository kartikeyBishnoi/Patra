"""The boundary between what was understood and what is true.

Everything in `patra.nlp` and `patra.vision` guesses. A gazetteer match, an
OCR line, a transcribed sentence: each is a reading of something noisy, and
each is wrong sometimes. Everything in `patra.reason` proves. Between them
there has to be a gate, and this is it.

Two directions, both enforced here rather than left to whoever calls.

**Facts in.** A proposed fact is admitted only if the schema accepts its type
and range, it does not quietly overwrite an answer the person actually gave,
and it does not contradict the domain axioms given everything already known.
A reading that fails goes back with the reason. A reading that is merely unsure
goes back to be confirmed, never through.

**Claims out.** No statement that somebody is entitled to something leaves this
module unless the solver derived it from facts that are all known. If a layer
upstream asserts eligibility and the solver disagrees, the answer is not the
assertion and not the refusal, it is "this could not be verified".

That asymmetry is the whole design. A language layer that mis-hears an income
costs a clarifying question. A language layer allowed to conclude would cost
somebody a day's wages walking to an office for a scheme they cannot have, and
they would have no way to tell which had happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .model.attributes import Schema
from .model.household import Profile
from .nlp.extract import Confidence, Mention, Understanding


class Source(Enum):
    """Where a fact came from. Shown to the person, and kept for the trace."""

    ASKED = "asked"
    """They answered the question directly. The only firm source."""

    SPOKEN = "spoken"
    """Read out of a sentence they typed or said."""

    DOCUMENT = "document"
    """Read off a photographed document."""

    INFERRED = "inferred"
    """Implied by something else, such as a gender by "my mother"."""

    CONFIRMED = "confirmed"
    """Proposed by a perception layer and then confirmed by the person."""

    @property
    def firm(self) -> bool:
        return self in (Source.ASKED, Source.CONFIRMED)


class Doubt(Enum):
    HEDGED = "hedged"
    """They said "around a lakh". That is an estimate, not a figure."""

    UNSURE = "unsure"
    """The phrase only hints at the value."""

    DISAGREEMENT = "disagreement"
    """One sentence said two different things about the same fact."""

    OVERWRITES = "overwrites"
    """It contradicts an answer they gave directly."""


class Refused(Enum):
    UNKNOWN_ATTRIBUTE = "unknown_attribute"
    OUT_OF_RANGE = "out_of_range"
    IMPOSSIBLE = "impossible"
    """It contradicts something that cannot be false of anybody."""


@dataclass(frozen=True)
class Admission:
    attribute: str
    value: object
    source: Source
    evidence: str | None = None
    confidence: Confidence | None = None
    inferred_from: str | None = None


@dataclass(frozen=True)
class Query:
    """A reading that will be used only if the person says yes."""

    attribute: str
    value: object
    doubt: Doubt
    evidence: str | None = None
    alternative: object | None = None
    """The other reading, when the doubt is a disagreement."""


@dataclass(frozen=True)
class Refusal:
    attribute: str
    value: object
    reason: Refused
    detail: str | None = None
    axiom: str | None = None


@dataclass(frozen=True)
class Intake:
    accepted: tuple[Admission, ...] = ()
    confirm: tuple[Query, ...] = ()
    refused: tuple[Refusal, ...] = ()

    @property
    def facts(self) -> dict:
        return {a.attribute: a.value for a in self.accepted}

    @property
    def quiet(self) -> bool:
        return not (self.accepted or self.confirm or self.refused)


@dataclass(frozen=True)
class Verification:
    """Whether a statement about entitlement may be made at all."""

    scheme_id: str
    verified: bool
    eligible: bool | None
    missing: tuple[str, ...] = ()
    contradicted: bool = False
    """An upstream layer said one thing and the solver said the other."""

    @property
    def sayable(self) -> bool:
        return self.verified and self.eligible is not None


class Guard:
    def __init__(self, engine, schema: Schema):
        self.engine = engine
        self.schema = schema

    # ---- facts in ----

    def admit(
        self,
        mentions,
        known: dict,
        source: Source,
        disagreements=(),
        confirm_all: bool = False,
    ) -> Intake:
        """Decide what may enter the profile, what must be asked, what cannot.

        Readings are considered best evidence first, so a certain phrase sets
        the fact and an unsure one later in the same sentence has to argue with
        an established answer rather than the other way round.

        `confirm_all` holds everything back for confirmation however confident
        the reading was. Document photographs always use it: a five read as a
        six moves an income by ten thousand rupees, the person is the only one
        who can see that it has happened, and they are holding the paper.
        """
        accepted: list[Admission] = []
        confirm: list[Query] = []
        refused: list[Refusal] = []

        for pair in disagreements:
            confirm.append(Query(
                attribute=pair[0].attribute, value=pair[0].value,
                doubt=Doubt.DISAGREEMENT, evidence=pair[0].evidence,
                alternative=pair[1].value))
        contested = {pair[0].attribute for pair in disagreements}

        standing = dict(known)
        order = sorted(
            mentions,
            key=lambda m: (-(m.confidence.rank if m.confidence else 3), m.start
                           if hasattr(m, "start") else 0),
        )

        for mention in order:
            name = mention.attribute
            if name in contested:
                continue

            attr = self._attribute(name)
            if attr is None:
                refused.append(Refusal(name, mention.value,
                                       Refused.UNKNOWN_ATTRIBUTE))
                continue

            try:
                attr.check(mention.value)
            except ValueError as exc:
                # An age of 480 is a mis-heard "48", not an age. Saying so
                # beats clamping it to 120 and carrying on.
                refused.append(Refusal(name, mention.value,
                                       Refused.OUT_OF_RANGE, detail=str(exc)))
                continue

            held = standing.get(name)
            if held is not None and held != mention.value:
                confirm.append(Query(name, mention.value, Doubt.OVERWRITES,
                                     evidence=mention.evidence,
                                     alternative=held))
                continue

            clash = self._clash(standing, name, mention.value)
            if clash is not None:
                refused.append(Refusal(name, mention.value, Refused.IMPOSSIBLE,
                                       axiom=clash))
                continue

            doubt = self._doubt(mention)
            if confirm_all and doubt is None:
                doubt = Doubt.UNSURE
            if doubt is not None:
                confirm.append(Query(name, mention.value, doubt,
                                     evidence=mention.evidence))
                continue

            standing[name] = mention.value
            accepted.append(Admission(
                attribute=name, value=mention.value,
                source=Source.INFERRED if getattr(mention, "inferred_from", None)
                else source,
                evidence=mention.evidence,
                confidence=mention.confidence,
                inferred_from=getattr(mention, "inferred_from", None)))

        return Intake(tuple(accepted), tuple(confirm), tuple(refused))

    def admit_understanding(self, understanding: Understanding, known: dict) -> Intake:
        return self.admit(understanding.mentions, known, Source.SPOKEN,
                          understanding.disagreements)

    def admit_document(self, reading, known: dict) -> Intake:
        """A photographed document, every field of which is read back first."""
        return self.admit(reading.mentions, known, Source.DOCUMENT,
                          confirm_all=True)

    def confirm(self, attribute: str, value, known: dict) -> Intake:
        """Take a fact the person has just agreed to, with the same checks.

        Confirmation raises the confidence, not the permission. An age the
        person stands behind can still be impossible beside their marital
        status, and the axioms say so here as readily as they would have before.
        """
        attr = self._attribute(attribute)
        if attr is None:
            return Intake(refused=(Refusal(attribute, value,
                                           Refused.UNKNOWN_ATTRIBUTE),))
        try:
            attr.check(value)
        except ValueError as exc:
            return Intake(refused=(Refusal(attribute, value,
                                           Refused.OUT_OF_RANGE, detail=str(exc)),))
        clash = self._clash(known, attribute, value)
        if clash is not None:
            return Intake(refused=(Refusal(attribute, value, Refused.IMPOSSIBLE,
                                           axiom=clash),))
        return Intake(accepted=(Admission(attribute, value, Source.CONFIRMED),))

    # ---- claims out ----

    def verify(self, scheme, facts: dict, asserted: bool | None = None) -> Verification:
        """Re-derive an entitlement before anybody is told about it.

        `asserted` is what some other layer believes. It is only ever used to
        detect that the two disagree; it never influences the answer.
        """
        missing = tuple(sorted(scheme.attributes_used - set(facts)))
        if missing:
            return Verification(scheme.id, verified=False, eligible=None,
                                missing=missing)

        profile = Profile(id="guard", facts=dict(facts))
        if self.engine.inconsistencies(profile):
            # Contradictory answers make every conclusion drawn from them
            # unsound, including a favourable one.
            return Verification(scheme.id, verified=False, eligible=None)

        verdict = self.engine.adjudicate(scheme, profile)
        if asserted is not None and bool(asserted) != verdict.eligible:
            return Verification(scheme.id, verified=False,
                                eligible=verdict.eligible, contradicted=True)
        return Verification(scheme.id, verified=True, eligible=verdict.eligible)

    def verified_eligible(self, schemes, facts: dict) -> list:
        """The schemes that may be presented as claimable, and nothing else."""
        out = []
        for scheme in schemes:
            check = self.verify(scheme, facts)
            if check.sayable and check.eligible:
                out.append(scheme)
        return out

    # ---- internals ----

    def _attribute(self, name):
        try:
            return self.schema[name]
        except KeyError:
            return None

    def _clash(self, known: dict, name: str, value) -> str | None:
        """The axiom this fact would break, if it breaks one.

        Checked against the facts already standing, so the report names the
        pair that cannot both be true rather than the whole profile.
        """
        trial = Profile(id="guard", facts={**known, name: value})
        for clash in self.engine.inconsistencies(trial):
            if name in clash.attributes:
                return "; ".join(a.text for a in clash.axioms)
        return None

    @staticmethod
    def _doubt(mention) -> Doubt | None:
        if getattr(mention, "hedged", False):
            return Doubt.HEDGED
        confidence = getattr(mention, "confidence", None)
        if confidence is not None and confidence.needs_confirming:
            return Doubt.UNSURE
        return None
