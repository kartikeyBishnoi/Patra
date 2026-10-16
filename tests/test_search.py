"""Four strategies over the same state space.

The property that matters is that the heuristic is admissible, and the test
for it is not an argument: A* must agree with uniform cost and with the
planner on every instance, because an inadmissible heuristic produces a fast
answer rather than an error and would otherwise go unnoticed.
"""

import pytest

from patra.reason.planner import Unreachable, plan
from patra.search.graph import (
    STRATEGIES,
    a_star,
    breadth_first,
    depth_first,
    ready,
    uniform_cost,
)

TARGETS = [
    ["aadhaar"],
    ["ration_card"],
    ["income_certificate"],
    ["bank_aadhaar_seeding"],
    ["ration_card", "income_certificate"],
    ["job_card", "bank_aadhaar_seeding"],
    ["caste_certificate", "domicile_certificate", "income_certificate"],
]


def optimum(documents, targets, held=()):
    try:
        return plan(documents, targets, set(held)).effort
    except Unreachable:
        return None


@pytest.mark.parametrize("targets", TARGETS)
def test_a_star_matches_uniform_cost(documents, targets):
    """The admissibility check. If these ever differ the heuristic is wrong."""
    fast = a_star(documents, targets)
    slow = uniform_cost(documents, targets)
    assert fast.found and slow.found
    assert fast.cost == slow.cost, targets


@pytest.mark.parametrize("targets", TARGETS)
def test_a_star_matches_the_planner(documents, targets):
    """Two independent algorithms over the same graph, same answer."""
    assert a_star(documents, targets).cost == optimum(documents, targets)


@pytest.mark.parametrize("targets", TARGETS)
def test_a_star_never_expands_more_than_uniform_cost(documents, targets):
    """What the heuristic is for. Equal is allowed; worse is a bug."""
    fast = a_star(documents, targets)
    slow = uniform_cost(documents, targets)
    assert fast.stats.expanded <= slow.stats.expanded, targets


def test_the_heuristic_actually_saves_something(documents):
    """Across the set, not merely on average."""
    saved = sum(uniform_cost(documents, t).stats.expanded
                - a_star(documents, t).stats.expanded for t in TARGETS)
    assert saved > 0


@pytest.mark.parametrize("targets", TARGETS)
def test_every_route_is_really_a_route(documents, targets):
    """Each paper must be obtainable at the moment it is taken."""
    for find in STRATEGIES.values():
        route = find(documents, targets)
        assert route.found, targets
        held = set()
        for doc_id in route.order:
            assert doc_id in ready(documents, frozenset(held)), \
                f"{doc_id} taken before its requirements"
            held.add(doc_id)
        assert set(targets) <= held


@pytest.mark.parametrize("targets", TARGETS)
def test_reported_cost_matches_the_route(documents, targets):
    for find in STRATEGIES.values():
        route = find(documents, targets)
        assert route.cost == sum(documents[d].effort for d in route.order)


def test_depth_first_is_the_one_that_is_not_optimal(documents):
    """Kept for the contrast, and the contrast should be visible."""
    worse = [t for t in TARGETS
             if depth_first(documents, t).cost > optimum(documents, t)]
    assert worse, "depth first found the optimum everywhere, so it proves nothing"


def test_already_held_targets_need_no_search(documents):
    route = a_star(documents, ["aadhaar"], held=["aadhaar"])
    assert route.found
    assert route.order == ()
    assert route.cost == 0


def test_breadth_first_minimises_papers_not_effort(documents):
    """The textbook point: fewest steps is not least cost."""
    for targets in TARGETS:
        wide = breadth_first(documents, targets)
        best = a_star(documents, targets)
        assert len(wide.order) <= len(best.order), targets
