"""Questions asked backwards: who would qualify, and who would get nothing.

Everything else in this project runs the rulebook forwards. Here is a
household, here is what they can claim. Run it backwards and three different
questions become answerable, none of which needs a single applicant.

**Who would qualify?** Give the solver a scheme's clauses and the domain
axioms and ask for a model. What comes back is a complete, internally
consistent household that would satisfy it. That is abduction: reasoning from
a conclusion to a case that would produce it. It is the fastest way to check
that an encoded rule means what its author thought, because a rule that is
subtly wrong usually produces a witness that is obviously odd.

**Would anybody get nothing?** Harder, and the one worth asking out loud. Add
the negation of every scheme at once and ask whether a household exists that
satisfies none of them. If the answer is yes, the solver hands back a family
this entire welfare system has no answer for, and the interesting version
constrains them to be poor first. A rulebook nobody can fall through is a
claim; this is a way to test it.

**What might the clerk have seen?** Somebody says they were refused at the
office although the app says they qualify. For each clause, find the smallest
change to their answers that would violate it. That is single-fault diagnosis,
and it turns "the office was wrong" into "the office may have recorded your
income as 52,000 rather than 42,000, and here is the paper that settles it".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import z3

from ..model.attributes import Kind, Schema


@dataclass(frozen=True)
class Shown:
    attribute: str
    value: object


@dataclass
class Witness:
    """A household the solver invented, and what it was asked to satisfy."""

    facts: dict = field(default_factory=dict)
    about: tuple[Shown, ...] = ()
    """The facts worth showing, which is not all thirty-three of them."""

    found: bool = True


@dataclass(frozen=True)
class Fault:
    """A single answer that, if the office had it differently, explains a
    refusal."""

    criterion: str
    attribute: str
    ours: object
    theirs: object


# Reading a household back from a model means reading everything, and most of
# it is noise. These are the facts that make a witness recognisable.
TELLING = ("age", "gender", "marital_status", "annual_income",
           "ration_card_type", "area_type", "land_acres", "occupation",
           "disability_percent", "household_size", "has_bank_account",
           "bank_aadhaar_linked", "already_receiving_pension",
           "owns_pucca_house", "is_pregnant", "category")


def _base(engine, schema, axioms, pinned=None):
    solver = z3.Solver()
    for expr in engine.encoder.background():
        solver.add(expr)
    for axiom in axioms or ():
        solver.add(engine.encoder.compile(axiom.formula))
    for name, value in (pinned or {}).items():
        if name in schema:
            solver.add(engine.encoder.const(name)
                       == engine.encoder.encode_value(name, value))
    return solver


def _read_back(engine, schema, model, interesting) -> Witness:
    facts, about = {}, []
    for attr in schema:
        raw = model.eval(engine.encoder.const(attr.name), model_completion=True)
        if z3.is_true(raw) or z3.is_false(raw):
            value = engine.encoder.decode_value(attr.name, z3.is_true(raw))
        else:
            try:
                value = engine.encoder.decode_value(attr.name, raw.as_long())
            except AttributeError:
                continue
        facts[attr.name] = value
        if attr.name in interesting:
            about.append(Shown(attr.name, value))
    order = {name: i for i, name in enumerate(interesting)}
    about.sort(key=lambda s: order.get(s.attribute, 99))
    return Witness(facts=facts, about=tuple(about))


def who_qualifies(engine, schema: Schema, scheme, axioms=(),
                  pinned=None) -> Witness:
    """A household the rules would say yes to, invented from the rules."""
    solver = _base(engine, schema, axioms, pinned)
    for criterion in scheme.criteria:
        solver.add(engine.encoder.compile(criterion.formula))
    if solver.check() != z3.sat:
        return Witness(found=False)

    wanted = tuple(n for n in TELLING if n in scheme.attributes_used)
    wanted += tuple(n for n in TELLING if n not in wanted)[:4]
    return _read_back(engine, schema, solver.model(), wanted)


def falls_through(engine, schema: Schema, schemes, axioms=(),
                  pinned=None) -> Witness:
    """A household that satisfies no scheme at all, if one exists.

    Pin them to be poor first and the question stops being trivial. Anybody
    can construct a rich family the welfare system ignores; the one worth
    finding is the family it is supposed to catch and does not.
    """
    solver = _base(engine, schema, axioms, pinned)
    for scheme in schemes:
        clauses = [engine.encoder.compile(c.formula) for c in scheme.criteria]
        if clauses:
            solver.add(z3.Not(z3.And(clauses)))
    if solver.check() != z3.sat:
        return Witness(found=False)
    return _read_back(engine, schema, solver.model(), TELLING)


def reachable(engine, schema: Schema, schemes, axioms=()) -> dict:
    """Whether each scheme can be satisfied by anybody at all.

    A scheme nobody can reach is a rule with a typo in it, and the only way to
    notice is to ask.
    """
    out = {}
    for scheme in schemes:
        out[scheme.id] = who_qualifies(engine, schema, scheme, axioms).found
    return out


def single_faults(engine, schema: Schema, scheme, facts: dict) -> list[Fault]:
    """One answer at a time, the smallest change that would refuse them.

    Single-fault first, which is the ordinary assumption in model-based
    diagnosis and the right one here: a clerk mistyping one figure is far more
    likely than two independent errors, and a list of single causes is
    something somebody can actually go and check.
    """
    out: list[Fault] = []
    for criterion in scheme.criteria:
        names = sorted(_vars(criterion.formula) & set(facts))
        if len(names) != 1:
            # A clause reading two facts has no single answer to blame, and
            # guessing which would be worse than saying nothing.
            continue
        name = names[0]
        attr = schema[name]

        opt = z3.Optimize()
        for expr in engine.encoder.background():
            opt.add(expr)
        opt.add(z3.Not(engine.encoder.compile(criterion.formula)))
        for other, value in facts.items():
            if other == name or other not in schema:
                continue
            opt.add(engine.encoder.const(other)
                    == engine.encoder.encode_value(other, value))

        const = engine.encoder.const(name)
        if attr.kind is Kind.INT:
            gap = const - facts[name]
            opt.minimize(z3.If(gap >= 0, gap, -gap))
        if opt.check() != z3.sat:
            continue

        raw = opt.model().eval(const, model_completion=True)
        if z3.is_true(raw) or z3.is_false(raw):
            theirs = engine.encoder.decode_value(name, z3.is_true(raw))
        else:
            try:
                theirs = engine.encoder.decode_value(name, raw.as_long())
            except AttributeError:
                continue
        if theirs == facts[name]:
            continue
        out.append(Fault(criterion=criterion.id, attribute=name,
                         ours=facts[name], theirs=theirs))
    return out


def _vars(formula) -> set:
    from ..model.constraint import variables
    return set(variables(formula))
