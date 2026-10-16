"""The camp day as a constraint satisfaction problem.

The planner decides which counters to invite and which households they can
get through. It says nothing about when, and "ninety-three households served"
is not a plan: a hundred people arriving at nine is the queue the camp was
meant to prevent.

So the day is cut into sessions and every household is given one:

    variables     the households the plan serves
    domain        the sessions of the day
    constraints   no counter sees more people in a session than it can
                  (n-ary, one per counter and session)
                  households from the same hamlet arrive together, so their
                  sessions are adjacent (binary, and what AC-3 works on)

The hamlet constraint is the one that makes this a constraint problem rather
than a division. Without it every household is independent and a round robin
would do. With it, choosing a session for one household moves its neighbours,
which is exactly the propagation AC-3 exists for.

A hamlet is assigned from the household id by a generator of its own, so it
does not disturb the draws that make the village itself.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .solve import Constraint, Problem, solve

HAMLETS = ("north", "south", "east", "west", "centre")


def hamlet_of(household_id: str) -> str:
    """Stable, and independent of the village generator's own stream."""
    return HAMLETS[random.Random(f"hamlet:{household_id}").randrange(len(HAMLETS))]


@dataclass
class Day:
    sessions: int
    per_session: dict
    """Counter id to how many households it can see in one session."""

    assignment: dict | None = None
    counters: object = None
    consistent: bool = True

    @property
    def found(self) -> bool:
        return self.assignment is not None

    def queue(self) -> dict:
        """Session to the households in it."""
        out = {s: [] for s in range(1, self.sessions + 1)}
        for household, session in (self.assignment or {}).items():
            out[session].append(household)
        return {k: sorted(v) for k, v in out.items()}

    def load(self, needs_by_household) -> dict:
        """Counter and session to how many people turn up."""
        out = {}
        for household, session in (self.assignment or {}).items():
            for counter in needs_by_household.get(household, ()):  
                out[(counter, session)] = out.get((counter, session), 0) + 1
        return out


def build(outcome, offices, needs, sessions=4) -> tuple[Problem, dict, dict]:
    """Turn a planned camp into a CSP.

    Returns the problem, which counters each household needs, and how many
    each counter can see per session.

    Which counters a household needs is the whole shape of the instance. An
    earlier version had every household queueing at every counter, which made
    the day impossible: ninety-three families cannot pass four counters in
    four sessions when each sees a dozen. They do not all need all of them,
    and taking that from the survey is what makes the problem the real one.
    """
    by_household = {n.household: n for n in needs}
    wanted = {}
    for row in outcome.served:
        need = by_household.get(row.household)
        if need is None:
            continue
        counters = frozenset().union(*(need.missing[s] for s in row.schemes)) \
            if row.schemes else frozenset()
        wanted[row.household] = counters & frozenset(outcome.chosen)

    per_session = {o: max(1, math.ceil(offices[o].serves / sessions))
                   for o in outcome.chosen}

    slots = list(range(1, sessions + 1))
    domains = {h: list(slots) for h in wanted}
    constraints = []

    # One cardinality constraint per counter and session. Partial assignments
    # are allowed, so it counts only what has been decided so far and never
    # rejects a prefix that could still work out.
    for counter in outcome.chosen:
        users = [h for h, needs in wanted.items() if counter in needs]
        if not users:
            continue
        room = per_session[counter]
        for session in slots:
            def fits(assignment, users=users, session=session, room=room):
                here = sum(1 for h in users
                           if assignment.get(h) == session)
                return here <= room
            constraints.append(Constraint(tuple(users), fits,
                                          name=f"{counter}@{session}"))

    # Households from one hamlet travel together, so their sessions sit next
    # to each other. Binary, and the only thing AC-3 can work on.
    by_hamlet = {}
    for household in wanted:
        by_hamlet.setdefault(hamlet_of(household), []).append(household)
    for group in by_hamlet.values():
        group.sort()
        for a, b in zip(group, group[1:]):
            def near(assignment, a=a, b=b):
                left, right = assignment.get(a), assignment.get(b)
                if left is None or right is None:
                    return True
                return abs(left - right) <= 1
            constraints.append(Constraint((a, b), near, name=f"{a}~{b}"))

    return Problem(domains=domains, constraints=constraints), wanted, per_session


def plan_day(outcome, offices, needs, sessions=4, **options) -> Day:
    problem, wanted, per_session = build(outcome, offices, needs, sessions)
    found = solve(problem, **options)
    return Day(sessions=sessions, per_session=per_session,
               assignment=found.assignment, counters=found.counters,
               consistent=found.consistent)
