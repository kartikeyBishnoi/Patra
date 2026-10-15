"""What would change if one answer were different.

"What if we earned eighty thousand instead of sixty?" is the question people
actually have, and it is not the same question as "why was I refused". A
refusal explains one scheme. This re-decides all of them against a household
that does not exist yet and reports the difference both ways, because a change
that gains three schemes while quietly costing two is not an improvement and
somebody about to take a better-paying job deserves to know.

It is the same machinery, run twice. The counting rule is the one the rest of
the app uses: a scheme is eligible only when every fact it reads is known and
the solver finds no conflict. Schemes that cannot be judged are reported as
undecided rather than folded into either total, because a count that quietly
includes guesses is worse than a smaller honest one.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model.household import Profile
from ..model.scheme import Labelled


@dataclass(frozen=True)
class Shift:
    attribute: str
    was: object
    now: object


@dataclass(frozen=True)
class Loss:
    scheme_id: str
    blocked_by: tuple[Labelled, ...] = ()
    """The clause that now refuses it, so the cost has a reason attached."""


@dataclass(frozen=True)
class Simulation:
    shifts: tuple[Shift, ...]
    before: tuple[str, ...]
    after: tuple[str, ...]
    gained: tuple[str, ...]
    lost: tuple[Loss, ...]
    kept: tuple[str, ...]
    undecided: tuple[str, ...] = ()
    """Facts missing, so neither total can claim them."""

    impossible: tuple[tuple[Shift, str], ...] = ()
    """A change that cannot be true of anybody, with the axiom that says so."""

    rejected: tuple[tuple[Shift, str], ...] = ()
    """A change outside what the schema allows."""

    @property
    def ran(self) -> bool:
        return not self.impossible and not self.rejected and bool(self.shifts)


def eligible_now(engine, scheme, profile: Profile) -> bool:
    """Eligible, under the same rule the interview and the result page use.

    Satisfiability alone is not enough. A scheme whose income threshold has
    not been tested yet is satisfiable and not eligible, and treating the two
    as the same is how a count turns into a promise.
    """
    if not scheme.attributes_used <= set(profile.facts):
        return False
    return engine.satisfiable(scheme, profile)


def simulate(engine, schema, schemes, facts: dict, changes: dict) -> Simulation:
    shifts = tuple(
        Shift(attribute=name, was=facts.get(name), now=value)
        for name, value in changes.items()
    )

    rejected = []
    clean = {}
    for shift in shifts:
        if shift.attribute not in schema:
            rejected.append((shift, f"no attribute called {shift.attribute!r}"))
            continue
        try:
            schema[shift.attribute].check(shift.now)
        except ValueError as exc:
            rejected.append((shift, str(exc)))
            continue
        clean[shift.attribute] = shift.now

    if rejected:
        return Simulation(shifts=shifts, before=(), after=(), gained=(),
                          lost=(), kept=(), rejected=tuple(rejected))

    after_facts = {**facts, **clean}
    after_profile = Profile(id="after", facts=after_facts)

    impossible = []
    for clash in engine.inconsistencies(after_profile):
        axiom = "; ".join(a.text for a in clash.axioms)
        for shift in shifts:
            if shift.attribute in clash.attributes:
                impossible.append((shift, axiom))
    if impossible:
        return Simulation(shifts=shifts, before=(), after=(), gained=(),
                          lost=(), kept=(), impossible=tuple(impossible))

    before_profile = Profile(id="before", facts=dict(facts))

    before, after, undecided = [], [], []
    for scheme in schemes:
        known_before = scheme.attributes_used <= set(facts)
        known_after = scheme.attributes_used <= set(after_facts)
        if not (known_before and known_after):
            undecided.append(scheme.id)
            continue
        if eligible_now(engine, scheme, before_profile):
            before.append(scheme.id)
        if eligible_now(engine, scheme, after_profile):
            after.append(scheme.id)

    gained = tuple(s for s in after if s not in before)
    kept = tuple(s for s in after if s in before)

    by_id = {s.id: s for s in schemes}
    lost = []
    for scheme_id in before:
        if scheme_id in after:
            continue
        conflicts = engine.explain(by_id[scheme_id], after_profile, every=False)
        rules = conflicts[0].rules if conflicts else ()
        lost.append(Loss(scheme_id=scheme_id, blocked_by=tuple(rules)))

    return Simulation(
        shifts=shifts,
        before=tuple(before),
        after=tuple(after),
        gained=gained,
        lost=tuple(lost),
        kept=kept,
        undecided=tuple(sorted(undecided)),
    )
