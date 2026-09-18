"""Catching answers that contradict each other.

Nobody is sitting beside the household to notice a misheard question. Without
that check the system reasons perfectly from a false premise and produces a
verdict that looks traceable, cites a real clause, and is wrong.

Axioms describe what cannot be true of anyone. When answers break one, the same
minimal-conflict machinery used for refusals names exactly which two answers
disagree, so we re-ask those instead of starting over.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..encode.z3enc import Z3Encoder
from ..model.attributes import Schema
from ..model.household import Profile
from ..model.scheme import Axiom, Labelled, Origin, facts_as_labelled
from .oracle import Oracle
from .quickxplain import NoConflict, quickxplain


@dataclass(frozen=True)
class Clash:
    axioms: tuple[Labelled, ...]
    facts: tuple[Labelled, ...]

    @property
    def attributes(self) -> list[str]:
        return [f.attribute for f in self.facts if f.attribute]


def check(
    encoder: Z3Encoder, schema: Schema, profile: Profile, axioms: list[Axiom]
) -> list[Clash]:
    if not axioms:
        return []

    labelled_axioms = [
        Labelled(a.id, Origin.AXIOM, a.formula, a.text) for a in axioms
    ]
    facts = facts_as_labelled(profile, schema)

    oracle = Oracle(encoder, labelled_axioms + facts)
    if oracle.is_sat(oracle.ids):
        return []

    found: list[Clash] = []
    remaining = list(oracle.ids)

    # Peel conflicts one at a time. Households rarely trip more than one axiom,
    # so we stop as soon as the rest is consistent rather than enumerating.
    while True:
        try:
            core = quickxplain(oracle, remaining)
        except NoConflict:
            break

        labels = [oracle.label(c) for c in core]
        found.append(
            Clash(
                axioms=tuple(l for l in labels if l.origin is Origin.AXIOM),
                facts=tuple(l for l in labels if l.origin is Origin.FACT),
            )
        )

        broken = next((l.id for l in labels if l.origin is Origin.AXIOM), None)
        if broken is None:
            break
        remaining = [c for c in remaining if c != broken]
        if oracle.is_sat(remaining):
            break

    return found
