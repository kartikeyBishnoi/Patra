"""Answers given as a range, and verdicts that admit it.

Somebody who says "about a lakh" has not told us a lakh. Until now the app
noticed the hedge, asked them to pin it down, and then reasoned on whatever
number came back as though it were measured. That manufactures a certainty
nobody has, and it does it at exactly the place where it matters: income is
the most common reason for refusal and the figure people are least sure of.

So a hedged answer is carried as the interval it really is, and the verdict
gets a third value. Two questions to the solver instead of one:

    possible    the clauses can hold for some value in the range
    certain     they hold for every value in it

Both true is a yes somebody can rely on. Both false is a no. Possible without
certain is the honest third answer, and it is the useful one, because the app
can then say which side of which number the whole thing turns on: "if your
income is really under 46,080 you qualify, and if it is over, you do not."
That is a sentence somebody can check against a pay slip.

It is interval constraint reasoning rather than probability. Nothing here
needs a prior, which is the point: we have no data from which to form one, and
inventing one would put a number on a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import z3

from ..model.attributes import Kind, Schema


class Standing(Enum):
    CERTAIN = "certain"
    """Eligible whatever the true value turns out to be."""

    IMPOSSIBLE = "impossible"
    """Eligible for no value in the range."""

    DEPENDS = "depends"
    """Eligible for some values and not others. The honest third answer."""


@dataclass(frozen=True)
class Range:
    """A fact somebody could only give within bounds."""

    attribute: str
    low: int
    high: int
    said: int | None = None
    """The figure they actually offered, which the range was built around."""

    def __post_init__(self):
        if self.low > self.high:
            raise ValueError(f"{self.attribute}: empty range")

    @property
    def width(self) -> int:
        return self.high - self.low


@dataclass(frozen=True)
class Hinge:
    """The value the whole answer turns on."""

    attribute: str
    at: int
    keeps: str
    """'le' when staying at or below `at` keeps it, 'ge' when at or above."""


@dataclass
class Judgement:
    scheme_id: str
    standing: Standing
    hinge: Hinge | None = None
    ranges: tuple[Range, ...] = ()
    unknown: tuple[str, ...] = field(default_factory=tuple)
    """Facts the scheme reads that nobody has given at all."""

    @property
    def settled(self) -> bool:
        return self.standing is not Standing.DEPENDS


def _pin(opt, encoder, schema, facts, ranges):
    """Exact answers as equalities, uncertain ones as bounds."""
    ranged = {r.attribute: r for r in ranges}
    for name, value in facts.items():
        if name in ranged or name not in schema:
            continue
        opt.add(encoder.const(name) == encoder.encode_value(name, value))
    for r in ranges.__iter__() if not isinstance(ranges, dict) else ():
        if schema[r.attribute].kind is not Kind.INT:
            continue
        const = encoder.const(r.attribute)
        opt.add(const >= r.low, const <= r.high)


def judge(engine, schema: Schema, scheme, facts: dict,
          ranges=()) -> Judgement:
    """Where a scheme stands when some answers are only known within bounds."""
    ranges = tuple(r for r in ranges if r.attribute in schema
                   and schema[r.attribute].kind is Kind.INT)
    known = set(facts) | {r.attribute for r in ranges}
    missing = tuple(sorted(scheme.attributes_used - known))

    encoder = engine.encoder
    clauses = [encoder.compile(c.formula) for c in scheme.criteria]

    def solver():
        s = z3.Solver()
        for expr in encoder.background():
            s.add(expr)
        _pin(s, encoder, schema, facts, ranges)
        return s

    possible = solver()
    for expr in clauses:
        possible.add(expr)
    can = possible.check() == z3.sat

    if not can:
        return Judgement(scheme.id, Standing.IMPOSSIBLE, ranges=ranges,
                         unknown=missing)

    # Certain means no counterexample inside the range, which is the same
    # question with the clauses negated.
    against = solver()
    against.add(z3.Not(z3.And(clauses)))
    must = against.check() == z3.unsat

    if must:
        return Judgement(scheme.id, Standing.CERTAIN, ranges=ranges,
                         unknown=missing)

    return Judgement(scheme.id, Standing.DEPENDS, ranges=ranges,
                     unknown=missing,
                     hinge=_hinge(engine, schema, clauses, facts, ranges))


def _hinge(engine, schema, clauses, facts, ranges) -> Hinge | None:
    """Which side of which number the answer turns on.

    Only reported when a single uncertain fact is in play. With two, the
    boundary is a line rather than a number and there is no honest way to say
    it in one sentence, so nothing is claimed.
    """
    if len(ranges) != 1:
        return None
    r = ranges[0]
    encoder = engine.encoder
    const = encoder.const(r.attribute)

    def edge(sense):
        opt = z3.Optimize()
        for expr in encoder.background():
            opt.add(expr)
        for expr in clauses:
            opt.add(expr)
        _pin(opt, encoder, schema, facts, ranges)
        goal = opt.maximize(const) if sense == "max" else opt.minimize(const)
        if opt.check() != z3.sat:
            return None
        bound = opt.upper(goal) if sense == "max" else opt.lower(goal)
        try:
            return bound.as_long()
        except AttributeError:
            return None

    top, bottom = edge("max"), edge("min")
    if top is not None and top < r.high:
        return Hinge(r.attribute, top, "le")
    if bottom is not None and bottom > r.low:
        return Hinge(r.attribute, bottom, "ge")
    return None


def screen(engine, schema: Schema, schemes, facts: dict, ranges=()):
    """Every scheme, split three ways instead of two."""
    out = []
    for scheme in schemes:
        found = judge(engine, schema, scheme, facts, ranges)
        if found.unknown:
            continue
        out.append(found)
    return out
