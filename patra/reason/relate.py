"""How the schemes in the rulebook relate to each other.

Twenty schemes written by different ministries at different times are not
twenty independent tests. Some ask strictly more than others, so clearing one
settles the other outright. Some cannot both be true of anybody. And some carry
a clause that their own other clauses already force, which is dead weight in a
rulebook and worth finding.

None of this is in the data. It is derived by asking the solver questions about
the rules themselves rather than about a household, which is the same machinery
pointed in a different direction:

    A entails B      (A and not B) is unsatisfiable
    A excludes B     (A and B) is unsatisfiable
    c is redundant   (the other clauses and not c) is unsatisfiable

The first is the one people feel. Being told "you qualify for the old age
pension, and that means you qualify for these two as well, with no further
test" is worth more than two more rows in a list, because it is a guarantee
rather than a coincidence of this household's answers.

Computed once when the app starts. Twenty schemes is a few hundred solver
calls and takes well under a second.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import z3


@dataclass(frozen=True)
class Relation:
    """One proved fact about two schemes."""

    left: str
    right: str


@dataclass
class Rulebook:
    entails: list[Relation] = field(default_factory=list)
    """Anyone eligible for `left` is necessarily eligible for `right`."""

    excludes: list[Relation] = field(default_factory=list)
    """No household can be eligible for both."""

    equivalent: list[Relation] = field(default_factory=list)
    """Each entails the other, so the two ask exactly the same thing."""

    redundant: dict[str, list[str]] = field(default_factory=dict)
    """Criteria a scheme's own other criteria already force."""

    checks: int = 0

    def implied_by(self, scheme_id: str) -> list[str]:
        """What clearing this scheme settles for free."""
        return [r.right for r in self.entails if r.left == scheme_id]

    def implies_of(self, scheme_id: str) -> list[str]:
        """What would have to be cleared first for this to follow."""
        return [r.left for r in self.entails if r.right == scheme_id]

    def conflicts_with(self, scheme_id: str) -> list[str]:
        out = [r.right for r in self.excludes if r.left == scheme_id]
        out += [r.left for r in self.excludes if r.right == scheme_id]
        return sorted(set(out))


def _unsat(encoder, formulas) -> bool:
    solver = z3.Solver()
    for expr in encoder.background():
        solver.add(expr)
    for expr in formulas:
        solver.add(expr)
    return solver.check() == z3.unsat


def analyse(engine, schemes) -> Rulebook:
    """Every provable relation between the schemes, and the dead clauses."""
    book = Rulebook()
    encoder = engine.encoder

    compiled = {
        s.id: [encoder.compile(c.formula) for c in s.criteria] for s in schemes
    }
    scope = {s.id: s.scope for s in schemes}
    checks = 0

    def entails(a: str, b: str) -> bool:
        nonlocal checks
        checks += 1
        return _unsat(encoder, compiled[a] + [z3.Not(z3.And(compiled[b]))])

    seen_pairs = set()
    for a in schemes:
        for b in schemes:
            if a.id == b.id:
                continue
            # A household-scoped scheme and a member-scoped one are awarded to
            # different things, so an implication between them would be read
            # as a promise about the wrong person.
            if scope[a.id] is not scope[b.id]:
                continue

            if entails(a.id, b.id):
                if entails(b.id, a.id):
                    key = tuple(sorted((a.id, b.id)))
                    if key not in seen_pairs:
                        seen_pairs.add(key)
                        book.equivalent.append(Relation(*key))
                else:
                    book.entails.append(Relation(a.id, b.id))

    for i, a in enumerate(schemes):
        for b in schemes[i + 1:]:
            if scope[a.id] is not scope[b.id]:
                continue
            checks += 1
            if _unsat(encoder, compiled[a.id] + compiled[b.id]):
                book.excludes.append(Relation(a.id, b.id))

    for scheme in schemes:
        dead = []
        clauses = compiled[scheme.id]
        for index, criterion in enumerate(scheme.criteria):
            others = clauses[:index] + clauses[index + 1:]
            if not others:
                continue
            checks += 1
            if _unsat(encoder, others + [z3.Not(clauses[index])]):
                dead.append(criterion.id)
        if dead:
            book.redundant[scheme.id] = dead

    book.checks = checks
    return book
