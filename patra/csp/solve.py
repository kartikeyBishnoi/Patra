"""A constraint solver written out rather than called.

Z3 does the eligibility reasoning and does it better than anything written by
hand. It is also a black box: it reports that the constraints hold and says
nothing about how a search for an assignment actually behaves. This is the
same machinery in the open, on a problem Z3 is not being asked about, so the
cost of each classical technique can be measured rather than described.

    backtracking      assign, check, undo
    forward checking  after assigning, strike impossible values from the
                      domains that remain, and give up early when one empties
    AC-3              make every binary constraint arc consistent before and
                      during the search, which prunes before a single guess
    MRV               branch on the variable with the fewest values left,
                      because a variable about to fail should fail now
    degree            among equals, branch on the one tied to the most others
    LCV               try the value that rules out least for the neighbours

Constraints are predicates over a scope, so n-ary ones are as natural as
binary. AC-3 is only defined over binary constraints and is applied only to
those; the n-ary ones are enforced by forward checking, which is the ordinary
division of labour.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from itertools import product


@dataclass(frozen=True)
class Constraint:
    scope: tuple[str, ...]
    test: object
    """Called with a dict of the scope's assigned values. Partial
    assignments are allowed, and a constraint that cannot yet tell says
    True."""

    name: str = ""

    @property
    def binary(self) -> bool:
        return len(self.scope) == 2

    def holds(self, assignment: dict) -> bool:
        return bool(self.test(assignment))


@dataclass
class Counters:
    assignments: int = 0
    backtracks: int = 0
    pruned: int = 0
    revisions: int = 0
    """Arcs examined by AC-3."""


@dataclass
class Problem:
    domains: dict
    constraints: list = field(default_factory=list)

    def about(self, name: str):
        return [c for c in self.constraints if name in c.scope]

    def neighbours(self, name: str) -> set:
        out = set()
        for c in self.about(name):
            out |= set(c.scope)
        out.discard(name)
        return out


@dataclass
class Solution:
    assignment: dict | None
    counters: Counters
    consistent: bool = True
    """False when AC-3 emptied a domain before the search began."""

    @property
    def found(self) -> bool:
        return self.assignment is not None


def ac3(problem: Problem, domains: dict, counters: Counters,
        queue=None) -> bool:
    """Make every binary arc consistent. False if a domain empties.

    Run once before the search and again after each assignment, which is the
    maintaining-arc-consistency variant. On this problem it is what turns an
    unsolvable instance from a long search into an immediate answer.
    """
    binary = [c for c in problem.constraints if c.binary]
    if queue is None:
        queue = deque((c, a, b) for c in binary
                      for a, b in (c.scope, c.scope[::-1]))
    else:
        queue = deque(queue)

    while queue:
        constraint, here, there = queue.popleft()
        counters.revisions += 1
        if _revise(constraint, here, there, domains, counters):
            if not domains[here]:
                return False
            for other in binary:
                if here in other.scope and there not in other.scope:
                    far = other.scope[0] if other.scope[1] == here \
                        else other.scope[1]
                    queue.append((other, far, here))
    return True


def _revise(constraint, here, there, domains, counters) -> bool:
    """Drop values of `here` with no partner in `there`."""
    keep = []
    dropped = False
    for value in domains[here]:
        if any(constraint.holds({here: value, there: other})
               for other in domains[there]):
            keep.append(value)
        else:
            dropped = True
            counters.pruned += 1
    if dropped:
        domains[here] = keep
    return dropped


def _consistent(problem, name, value, assignment) -> bool:
    trial = {**assignment, name: value}
    for constraint in problem.about(name):
        if not constraint.holds(trial):
            return False
    return True


def _forward_check(problem, name, value, assignment, domains, counters):
    """Strike values the new assignment has just made impossible."""
    trimmed = {}
    for other in problem.neighbours(name):
        if other in assignment:
            continue
        keep = [v for v in domains[other]
                if _consistent(problem, other, v, {**assignment, name: value})]
        if len(keep) != len(domains[other]):
            counters.pruned += len(domains[other]) - len(keep)
            trimmed[other] = keep
            if not keep:
                return None
    return trimmed


def _pick(problem, assignment, domains, use_mrv, use_degree) -> str:
    left = [n for n in domains if n not in assignment]
    if not use_mrv:
        return left[0]
    best = min(len(domains[n]) for n in left)
    tied = [n for n in left if len(domains[n]) == best]
    if len(tied) == 1 or not use_degree:
        return tied[0]
    # Among equals, the one tied to the most unassigned others: failing early
    # is cheaper than failing late.
    return max(tied, key=lambda n: len(problem.neighbours(n) - set(assignment)))


def _order(problem, name, assignment, domains, use_lcv):
    values = list(domains[name])
    if not use_lcv:
        return values

    def cost(value):
        total = 0
        for other in problem.neighbours(name):
            if other in assignment:
                continue
            total += sum(1 for v in domains[other]
                         if not _consistent(problem, other, v,
                                            {**assignment, name: value}))
        return total

    return sorted(values, key=cost)


def solve(problem: Problem, mrv=True, degree=True, lcv=True,
          forward=True, arc=True, cap=200000) -> Solution:
    """Backtracking search, with each technique switchable so it can be
    measured rather than assumed."""
    counters = Counters()
    domains = {k: list(v) for k, v in problem.domains.items()}

    if arc and not ac3(problem, domains, counters):
        return Solution(None, counters, consistent=False)

    def walk(assignment, domains):
        if len(assignment) == len(problem.domains):
            return dict(assignment)
        if counters.assignments > cap:
            return None

        name = _pick(problem, assignment, domains, mrv, degree)
        for value in _order(problem, name, assignment, domains, lcv):
            if not _consistent(problem, name, value, assignment):
                continue
            counters.assignments += 1
            assignment[name] = value

            nxt = {k: list(v) for k, v in domains.items()}
            nxt[name] = [value]
            ok = True
            if forward:
                trimmed = _forward_check(problem, name, value, assignment,
                                         nxt, counters)
                if trimmed is None:
                    ok = False
                else:
                    nxt.update(trimmed)
            if ok and arc:
                ok = ac3(problem, nxt, counters)

            if ok:
                found = walk(assignment, nxt)
                if found is not None:
                    return found

            del assignment[name]
            counters.backtracks += 1
        return None

    return Solution(walk({}, domains), counters)
