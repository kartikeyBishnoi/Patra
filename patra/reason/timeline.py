"""When, rather than whether.

Every answer the app gives is about today. A fifty-seven year old asking about
the old age pension is told no, which is true and not the useful thing to say.
The useful thing is that the answer becomes yes in three years.

The other direction matters more and nobody ever hears it. Several schemes
close with age rather than open with it. The Atal Pension Yojana takes nobody
over forty, so somebody who is thirty-eight has two years to join something
they will never be offered again, and a system that only answers today's
question lets that pass in silence.

The question has to be asked carefully to be worth anything. Asking "when does
this open if nothing at all changes" is almost always answered never, because
some unlinked bank account is also in the way and no birthday fixes that. So
only the facts that *cannot* change are pinned: age, gender, caste, a spouse's
death. The paperwork is left free, and the answer becomes "once the paperwork
is done, this opens at sixty", which is the sentence somebody can act on.

Two calls to the optimiser, not a loop. The smallest age at which the clauses
can hold, and the largest, which is the window this household's fixed
circumstances leave open.
"""

from __future__ import annotations

from dataclasses import dataclass

import z3

from ..model.attributes import Kind, Mutability
from ..model.household import Profile

AGE = "age"

# A closing more than this far off is true and not actionable. Nobody plans
# around an insurance scheme that stops taking them in thirty-four years, and
# printing it buries the one that closes in two.
SOON = 10

# Crossing sixty makes a household one with somebody over sixty. It is the only
# derived fact that follows from one member's age, and leaving it stale would
# let the projection contradict itself.
IMPLIED_AT = {"has_member_over_60": (60, True)}


@dataclass(frozen=True)
class Horizon:
    scheme_id: str
    eligible_now: bool

    opens_at: int | None = None
    """The youngest future age at which the clauses can hold."""

    closes_at: int | None = None
    """The first age at which they can no longer hold, whatever else is done."""

    only_age: bool = False
    """Age is the sole obstacle, so waiting on its own is enough."""

    def years_from(self, age: int):
        return (self.opens_at - age if self.opens_at is not None else None,
                self.closes_at - age if self.closes_at is not None else None)

    @property
    def worth_saying(self) -> bool:
        return self.opens_at is not None or self.closes_at is not None


def _base(engine, scheme, facts, schema, pin_everything=False):
    """The clauses, plus the facts that are not up for negotiation."""
    opt = z3.Optimize()
    encoder = engine.encoder
    for expr in encoder.background():
        opt.add(expr)
    for criterion in scheme.criteria:
        opt.add(encoder.compile(criterion.formula))

    age_var = encoder.const(AGE)
    for name, value in facts.items():
        if name == AGE or name not in schema:
            continue
        fixed = schema[name].mutability is Mutability.FIXED
        if not (pin_everything or fixed):
            continue
        threshold = IMPLIED_AT.get(name)
        if threshold is not None and value is not threshold[1]:
            # True early is possible, because somebody else may already be
            # over sixty. False late is not.
            opt.add(z3.Implies(age_var >= threshold[0],
                               encoder.const(name) == threshold[1]))
            opt.add(z3.Implies(age_var < threshold[0],
                               encoder.const(name) == encoder.encode_value(name, value)))
            continue
        opt.add(encoder.const(name) == encoder.encode_value(name, value))
    return opt, age_var


def horizon(engine, schema, scheme, facts: dict) -> Horizon | None:
    """The age window this scheme leaves open, or None if age does not decide
    it."""
    if AGE not in facts or AGE not in schema or schema[AGE].kind is not Kind.INT:
        return None
    if AGE not in scheme.attributes_used:
        return None

    age_now = facts[AGE]
    ceiling = schema[AGE].high if schema[AGE].high is not None else 120
    eligible = engine.satisfiable(scheme, Profile(id="now", facts=dict(facts)))

    opens = closes = None
    only_age = False

    if not eligible:
        opt, age_var = _base(engine, scheme, facts, schema)
        # From today, not from tomorrow. Asking for a strictly greater age
        # answers "next year" for somebody already inside the window, which
        # reads as a wait they do not have.
        opt.add(age_var >= age_now, age_var <= ceiling)
        goal = opt.minimize(age_var)
        if opt.check() == z3.sat:
            found_age = opt.lower(goal).as_long()
            opens = found_age if found_age > age_now else None

        if opens is not None:
            # Would waiting alone do it, or is there paperwork as well? The
            # difference is "come back at sixty" against "come back at sixty,
            # with your account linked".
            strict, strict_age = _base(engine, scheme, facts, schema,
                                       pin_everything=True)
            strict.add(strict_age == opens)
            only_age = strict.check() == z3.sat

    opt, age_var = _base(engine, scheme, facts, schema)
    opt.add(age_var >= age_now, age_var <= ceiling)
    goal = opt.maximize(age_var)
    if opt.check() == z3.sat:
        last = opt.upper(goal).as_long()
        # Reaching the schema's own ceiling is the end of the scale rather
        # than a rule about the scheme, and announcing it would be noise.
        if last < ceiling and last + 1 - age_now <= SOON:
            closes = last + 1

    found = Horizon(scheme_id=scheme.id, eligible_now=eligible, opens_at=opens,
                    closes_at=closes, only_age=only_age)
    return found if found.worth_saying else None


def horizons(engine, schema, schemes, facts: dict) -> list[Horizon]:
    """Every scheme whose answer changes with a birthday, soonest first."""
    out = []
    for scheme in schemes:
        if not scheme.attributes_used <= set(facts):
            continue
        found = horizon(engine, schema, scheme, facts)
        if found is not None:
            out.append(found)

    age = facts.get(AGE, 0)

    def soonest(h):
        marks = [m for m in (h.opens_at, h.closes_at) if m is not None]
        return min(marks) - age if marks else 999

    out.sort(key=soonest)
    return out
