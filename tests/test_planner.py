"""The acquisition planner.

Two properties matter. A plan must be *valid*, meaning nothing is attempted
before the papers it needs exist, because an invalid plan sends somebody to an
office to be turned away. And it should be *cheap*, because every trip is a
lost day of wages.

Validity we assert outright. Cheapness we check against exhaustive search over
the real graph, since the planner resolves each requirement against what the
partial solution has already committed to, which is a greedy treatment of
shared prerequisites rather than a provably optimal one.
"""

from itertools import combinations

import pytest

from patra.reason.planner import Unreachable, acquire, order, plan


def satisfied_by(graph, have, held):
    """True if every acquired document's requirements are met inside `have`."""
    for doc_id in have - set(held):
        for need in graph[doc_id].needs:
            if not any(option in have for option in need.options):
                return False
    return True


def brute_force(graph, target, held):
    """Cheapest valid acquisition set, by trying every subset.

    Exponential and deliberately unclever. It exists to check the planner, not
    to replace it.

    Note it cannot stop at the smallest set that works. Documents carry
    different costs, so a longer route can be cheaper: three cheap errands beat
    one expensive one, and an earlier version of this function got that wrong
    and reported the planner as broken when the planner was right.
    """
    held = set(held)
    if target in held:
        return frozenset()

    candidates = [d for d in graph.ids if d not in held]
    best = None
    best_cost = None

    for size in range(1, len(candidates) + 1):
        for combo in combinations(candidates, size):
            have = held | set(combo)
            if target not in have:
                continue
            if not satisfied_by(graph, have, held):
                continue
            cost = sum(graph[d].effort for d in combo)
            if best_cost is None or cost < best_cost:
                best, best_cost = frozenset(combo), cost

    return best


ALL_TARGETS = [
    "income_certificate",
    "caste_certificate",
    "bank_aadhaar_seeding",
    "ration_card",
    "job_card",
    "disability_certificate",
    "land_records",
    "death_certificate",
    "pan_card",
    "voter_id",
    "domicile_certificate",
]


@pytest.mark.parametrize("target", ALL_TARGETS)
def test_plan_is_valid_from_nothing(documents, target):
    """Starting with no papers at all, every step must be reachable in turn."""
    route = plan(documents, [target], held=set())
    have = set()
    for step in route.steps:
        for need in step.document.needs:
            assert any(o in have for o in need.options), (
                f"{step.id} attempted before its {need.purpose} exists"
            )
        have.add(step.id)
    assert target in have


@pytest.mark.parametrize("target", ALL_TARGETS)
def test_plan_is_valid_holding_aadhaar(documents, target):
    held = {"aadhaar"}
    route = plan(documents, [target], held=held)
    have = set(held)
    for step in route.steps:
        for need in step.document.needs:
            assert any(o in have for o in need.options)
        have.add(step.id)
    assert target in have or target in held


@pytest.mark.parametrize("target", ALL_TARGETS)
def test_planner_matches_exhaustive_search(documents, target):
    """Greedy sharing versus the real optimum, on the real graph."""
    found = acquire(documents, [target], held=set())
    optimal = brute_force(documents, target, held=set())

    assert found is not None and optimal is not None
    cost = sum(documents[d].effort for d in found)
    best = sum(documents[d].effort for d in optimal)
    assert cost == best, (
        f"{target}: planner found {sorted(found)} at {cost}, "
        f"exhaustive search found {sorted(optimal)} at {best}"
    )


def test_nothing_to_do_when_already_held(documents):
    route = plan(documents, ["aadhaar"], held={"aadhaar"})
    assert route.steps == ()
    assert route.already_held == ("aadhaar",)


def test_shared_prerequisites_are_collected_once(documents):
    """Two targets that both need Aadhaar must not fetch it twice."""
    route = plan(documents, ["income_certificate", "caste_certificate"], held=set())
    ids = [s.id for s in route.steps]
    assert len(ids) == len(set(ids)), f"a document appears twice: {ids}"


def test_holding_more_never_costs_more(documents):
    """Adding a document to what you hold cannot make the plan more expensive."""
    for target in ALL_TARGETS:
        bare = acquire(documents, [target], held=set())
        with_aadhaar = acquire(documents, [target], held={"aadhaar"})
        assert with_aadhaar is not None and bare is not None
        assert sum(documents[d].effort for d in with_aadhaar) <= sum(
            documents[d].effort for d in bare
        )


def test_order_refuses_a_set_that_cannot_stand_up(documents):
    """An acquisition set assembled by hand, missing a prerequisite."""
    with pytest.raises(Unreachable):
        order(documents, {"income_certificate"}, held=set())


def test_every_step_explains_itself(documents):
    route = plan(documents, ["income_certificate"], held=set())
    for step in route.steps:
        assert step.reason, f"{step.id} has no reason given"


def test_trips_and_fees_add_up(documents):
    route = plan(documents, ["job_card"], held=set())
    assert route.trips == sum(s.document.trips for s in route.steps)
    assert route.fee == sum(s.document.fee for s in route.steps)
