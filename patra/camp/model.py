"""A village, the counters that could come to it, and what a day would open.

The app so far answers one household at a time. A block officer has a
different question: a camp can be held on Tuesday, a fixed number of officials
can be spared, and which counters should come?

The answer is not obvious, and that is what makes it worth computing. The
tehsil clerk issues four papers, so one chair covers a lot of ground, but
costs two officials and gets through only forty people. The photographer costs
one and serves eighty but unlocks almost nothing alone. And the value of
bringing a counter depends on who else comes, because a scheme needs all its
papers and a household short of two gains nothing from fixing one.

That interaction is the whole problem. It is budgeted maximum coverage, which
is NP-hard, and `patra/camp/plan.py` attacks it twice: exactly for small
instances and by local search for real ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..model.document import DocumentGraph
from ..model.household import Household, project
from ..model.scheme import Scheme
from ..reason.planner import acquire


@dataclass(frozen=True)
class Office:
    id: str
    name: str
    slots: int
    """Officials it needs for the day. The budget is counted in these."""

    serves: int
    """Households it can get through before the queue goes home."""

    travels: bool
    """Whether it will come to a village at all. A medical board will not."""


def load_offices(path: Path) -> dict[str, Office]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["offices"]
    return {
        key: Office(id=key, name=spec["name"], slots=int(spec["slots"]),
                    serves=int(spec["serves"]), travels=bool(spec["travels"]))
        for key, spec in raw.items()
    }


@dataclass
class Need:
    """One household's stake in the camp."""

    household: str
    wants: dict[str, int] = field(default_factory=dict)
    """Scheme id to the money a year it would be worth, once claimable."""

    missing: dict[str, frozenset[str]] = field(default_factory=dict)
    """Scheme id to the offices whose papers it still lacks.

    Offices rather than papers, because a camp invites counters. A scheme
    whose missing papers all come from one counter is cheap to finish; one
    needing three counters only pays off if all three come.
    """

    @property
    def total(self) -> int:
        return sum(self.wants.values())


def survey_one(engine, schema, schemes, documents: DocumentGraph,
               offices: dict[str, Office], household: Household) -> Need | None:
    """One household's stake, or None if a camp could do nothing for them.

    Only schemes they already qualify for are counted. A camp cannot change
    anybody's age or widowhood; it can only turn a qualification nobody can
    prove into one they can, which is exactly the gap this project is about.
    """
    need = Need(household=household.id)
    held = set(household.documents)

    for scheme in schemes:
        value = scheme.worth.in_hand
        if value <= 0:
            continue
        short = _offices_behind(documents, offices, scheme.documents, held)
        if short is None or not short:
            continue
        # Cheapest tests first: the paperwork gap is a set lookup and the
        # eligibility test is a solver call, so ask the solver last.
        if not _qualifies(engine, schema, scheme, household):
            continue
        need.wants[scheme.id] = value
        need.missing[scheme.id] = short

    return need if need.wants else None


def survey(engine, schema, schemes, documents: DocumentGraph,
           offices: dict[str, Office], households: list[Household],
           guard=None) -> list[Need]:
    """The whole village, one household at a time.

    `guard` is a context manager taken around each household rather than
    around the survey. That matters: the survey runs in a background thread
    and takes the better part of a minute, and holding the solver lock for all
    of it would stall every page in the app until it finished.

    Releasing it is not enough on its own. Python's locks are not fair, so a
    loop that drops the lock and takes it again in the next statement can run
    to completion while a waiting request never gets scheduled, which is
    exactly what happened: a page load behind the survey waited fourteen
    seconds. The millisecond of sleep is what actually hands the lock over.
    It costs a sixth of a second across the whole village.
    """
    import contextlib
    import time

    hold = guard or (lambda: contextlib.nullcontext())
    out: list[Need] = []
    for household in households:
        with hold():
            found = survey_one(engine, schema, schemes, documents, offices,
                               household)
        if found is not None:
            out.append(found)
        if guard is not None:
            time.sleep(0.001)
    return out


def _qualifies(engine, schema, scheme, household) -> bool:
    """Eligible on the facts, whatever the paperwork says."""
    from ..model.attributes import Scope

    if scheme.scope is Scope.HOUSEHOLD:
        targets = [project(household, schema)]
    else:
        targets = [project(household, schema, m.id) for m in household.members]

    for profile in targets:
        if not scheme.attributes_used <= set(profile.facts):
            continue
        if engine.satisfiable(scheme, profile):
            return True
    return False


def _offices_behind(graph, offices, wanted, held) -> frozenset[str] | None:
    """Every counter whose papers are missing, following prerequisites.

    Resolved for the scheme's papers together rather than one at a time, so a
    prerequisite two of them share is counted once. A birth certificate the
    household lacks may itself need an Aadhaar they also lack, so the Aadhaar
    counter has to come too.

    None means some paper is out of reach at a camp at all, usually because
    its office will not travel.
    """
    targets = [d for d in wanted if d in graph and d not in held]
    if not targets:
        return frozenset()

    route = acquire(graph, targets, set(held))
    if route is None:
        return None

    needed: set[str] = set()
    for step in route:
        office = graph[step].office
        if office is None or office not in offices:
            return None
        if not offices[office].travels:
            return None
        needed.add(office)
    return frozenset(needed)
