"""Forward and backward chaining over the domain axioms.

The axioms have been doing one job: catching answers that cannot both be true.
They can do a second, and it is the more useful one. An axiom is an
implication, and an implication whose antecedent is known runs forwards:

    A1  pregnant        ->  female
    A4  under ten       ->  no bank account of their own
    A7  account seeded  ->  there is an account

Somebody who says they are expecting has told us their gender without being
asked, and asking anyway is the kind of thing that makes a form feel like it
is not listening. So the chainer runs after every answer, asserts what
follows, and the interview skips those questions. Facts arrive with the rule
that produced them, so the trace says *why* rather than merely *what*.

Three-valued on purpose. A formula whose variables are not all known is
unknown rather than false, which is the difference between "we have not asked"
and "they said no". Closed-world reasoning here would have the app conclude
that somebody who has not answered the pregnancy question is not pregnant.

Backward chaining answers the other direction. Asked why it believes the
gender is female, it returns the rule and the fact underneath it, recursively,
which is a proof rather than an assertion.

Bounds are kept separate from facts. "Pregnant" implies an age between twelve
and fifty-five, which is not an age; it is a narrowing, and it feeds the
interval reasoning in `uncertain.py` rather than pretending to be an answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..model.attributes import Kind, Schema
from ..model.constraint import And, Cmp, Implies, InSet, IsTrue, Lit, Not, Or, Var

UNKNOWN = None


@dataclass(frozen=True)
class Derived:
    attribute: str
    value: object
    axiom: str
    because: tuple[str, ...]
    """The already-known attributes the rule fired on."""


@dataclass(frozen=True)
class Bound:
    """A narrowing rather than an answer.

    "Pregnant" implies an age between twelve and fifty-five, which is not an
    age. Kept apart from the facts for that reason, and fed to the interval
    reasoning in `uncertain.py`, which is built to hold exactly this.
    """

    attribute: str
    low: int | None
    high: int | None
    axioms: tuple[str, ...] = ()


@dataclass
class Chained:
    facts: dict = field(default_factory=dict)
    derived: tuple[Derived, ...] = ()
    bounds: tuple[Bound, ...] = ()
    rounds: int = 0
    """How many passes before nothing new appeared. More than one means a
    rule fired on something another rule had just derived."""

    conflict: str | None = None
    """A rule demanded a value that contradicts one already held."""


def evaluate(formula, facts: dict):
    """True, False, or unknown. Never false merely for want of an answer."""
    if isinstance(formula, IsTrue):
        value = facts.get(formula.var.name, UNKNOWN)
        if value is UNKNOWN:
            return UNKNOWN
        return (not value) if formula.negated else bool(value)

    if isinstance(formula, InSet):
        value = facts.get(formula.var.name, UNKNOWN)
        if value is UNKNOWN:
            return UNKNOWN
        inside = value in formula.values
        return (not inside) if formula.negated else inside

    if isinstance(formula, Cmp):
        left = _operand(formula.lhs, facts)
        right = _operand(formula.rhs, facts)
        if left is UNKNOWN or right is UNKNOWN:
            return UNKNOWN
        return {
            "eq": left == right, "ne": left != right,
            "lt": left < right, "le": left <= right,
            "gt": left > right, "ge": left >= right,
        }[formula.op]

    if isinstance(formula, Not):
        inner = evaluate(formula.part, facts)
        return UNKNOWN if inner is UNKNOWN else (not inner)

    if isinstance(formula, And):
        seen_unknown = False
        for part in formula.parts:
            got = evaluate(part, facts)
            if got is False:
                return False          # one false settles a conjunction
            if got is UNKNOWN:
                seen_unknown = True
        return UNKNOWN if seen_unknown else True

    if isinstance(formula, Or):
        seen_unknown = False
        for part in formula.parts:
            got = evaluate(part, facts)
            if got is True:
                return True           # one true settles a disjunction
            if got is UNKNOWN:
                seen_unknown = True
        return UNKNOWN if seen_unknown else False

    if isinstance(formula, Implies):
        before = evaluate(formula.antecedent, facts)
        if before is False:
            return True
        after = evaluate(formula.consequent, facts)
        if after is True:
            return True
        if before is True and after is False:
            return False
        return UNKNOWN

    return UNKNOWN


def _operand(node, facts):
    if isinstance(node, Lit):
        return node.value
    if isinstance(node, Var):
        return facts.get(node.name, UNKNOWN)
    return UNKNOWN


def _assertions(formula, schema: Schema):
    """What a consequent pins down, if anything.

    Returns definite (attribute, value) pairs and numeric bounds separately,
    because an implication that narrows an age has not supplied one.
    """
    facts, bounds = [], []

    if isinstance(formula, IsTrue):
        facts.append((formula.var.name, not formula.negated))
    elif isinstance(formula, InSet) and not formula.negated \
            and len(formula.values) == 1:
        facts.append((formula.var.name, formula.values[0]))
    elif isinstance(formula, Cmp) and isinstance(formula.lhs, Var) \
            and isinstance(formula.rhs, Lit):
        name, value = formula.lhs.name, formula.rhs.value
        if formula.op == "eq":
            facts.append((name, value))
        elif name in schema and schema[name].kind is Kind.INT:
            if formula.op == "ge":
                bounds.append((name, value, None))
            elif formula.op == "gt":
                bounds.append((name, value + 1, None))
            elif formula.op == "le":
                bounds.append((name, None, value))
            elif formula.op == "lt":
                bounds.append((name, None, value - 1))
    elif isinstance(formula, And):
        for part in formula.parts:
            got_facts, got_bounds = _assertions(part, schema)
            facts += got_facts
            bounds += got_bounds

    return facts, bounds


def forward(schema: Schema, axioms, facts: dict) -> Chained:
    """Assert everything the axioms force, until nothing new appears.

    Repeated to a fixed point rather than run once, because a rule can fire
    on a fact another rule has just derived. On this rulebook that is rare,
    and the round count is reported so it can be seen when it happens.
    """
    known = dict(facts)
    derived: list[Derived] = []
    bounds: list[Bound] = []
    rounds = 0
    conflict = None

    while True:
        rounds += 1
        fired = False
        for axiom in axioms:
            if not isinstance(axiom.formula, Implies):
                continue
            if evaluate(axiom.formula.antecedent, known) is not True:
                continue

            because = tuple(sorted(
                _reads(axiom.formula.antecedent) & set(known)))
            new_facts, new_bounds = _assertions(
                axiom.formula.consequent, schema)

            for name, value in new_facts:
                if name not in schema:
                    continue
                if name in known:
                    if known[name] != value:
                        conflict = (f"{axiom.id} requires {name} to be "
                                    f"{value!r}, but it is {known[name]!r}")
                    continue
                known[name] = value
                derived.append(Derived(name, value, axiom.id, because))
                fired = True

            for name, low, high in new_bounds:
                if name in known:
                    # A bound on an answer we already have is not a
                    # narrowing, it is a check. Skipping it silently let
                    # "widowed at fifteen" through the chainer while the
                    # solver caught it, and two implementations of the same
                    # knowledge disagreeing is worse than either being wrong.
                    value = known[name]
                    if isinstance(value, bool) or not isinstance(value, int):
                        continue
                    if (low is not None and value < low) or \
                            (high is not None and value > high):
                        want = f"at least {low}" if high is None else (
                            f"at most {high}" if low is None
                            else f"between {low} and {high}")
                        conflict = (f"{axiom.id} requires {name} to be "
                                    f"{want}, but it is {value}")
                    continue
                if _narrow(bounds, name, low, high, axiom.id):
                    fired = True

        if not fired or conflict:
            break

    return Chained(facts=known, derived=tuple(derived), bounds=tuple(bounds),
                   rounds=rounds, conflict=conflict)


@dataclass
class Step:
    goal: str
    value: object
    axiom: str | None
    given: tuple[str, ...] = ()
    children: tuple = ()


def backward(schema: Schema, axioms, facts: dict, goal: str,
             seen=None) -> Step | None:
    """Why the system believes what it believes about one attribute.

    Given outright, it says so. Derived, it names the rule and then asks the
    same question of everything that rule stood on, which is a proof rather
    than a claim.
    """
    seen = seen or frozenset()
    if goal in seen:
        return None
    if goal not in facts:
        return None

    for axiom in axioms:
        if not isinstance(axiom.formula, Implies):
            continue
        if evaluate(axiom.formula.antecedent, facts) is not True:
            continue
        pinned, _ = _assertions(axiom.formula.consequent, schema)
        for name, value in pinned:
            if name != goal or facts.get(name) != value:
                continue
            supports = sorted(
                _reads(axiom.formula.antecedent) & set(facts))
            kids = []
            for support in supports:
                deeper = backward(schema, axioms, facts, support,
                                  seen | {goal})
                kids.append(deeper or Step(goal=support, value=facts[support],
                                           axiom=None))
            return Step(goal=goal, value=facts[goal], axiom=axiom.id,
                        given=tuple(supports), children=tuple(kids))

    return Step(goal=goal, value=facts[goal], axiom=None)


def _narrow(bounds: list, name, low, high, axiom) -> bool:
    """Keep one bound per attribute, as tight as the rules make it.

    Two axioms can each put a floor under an age, and reporting both as
    separate findings reads as two discoveries rather than one fact with two
    reasons.
    """
    for i, mark in enumerate(bounds):
        if mark.attribute != name:
            continue
        tighter_low = max(x for x in (mark.low, low) if x is not None) \
            if (mark.low is not None or low is not None) else None
        tighter_high = min(x for x in (mark.high, high) if x is not None) \
            if (mark.high is not None or high is not None) else None
        axioms = mark.axioms if axiom in mark.axioms else mark.axioms + (axiom,)
        fresh = Bound(name, tighter_low, tighter_high, axioms)
        if fresh == mark:
            return False
        bounds[i] = fresh
        return True

    bounds.append(Bound(name, low, high, (axiom,)))
    return True


def _reads(formula) -> set:
    from ..model.constraint import variables
    return set(variables(formula))
