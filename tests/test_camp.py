"""Planning a day in the village.

The property that matters is that the heuristics are measured against the
truth. Eleven counters is 2048 subsets, so the optimum is available by
enumeration, and a heuristic with nothing to compare against is an opinion
with a runtime.
"""

import pytest

from patra.camp.plan import anneal, evaluate, exact, greedy

BUDGETS = (1, 2, 3, 4, 6, 8)


def test_the_village_has_something_at_stake(needs):
    assert needs, "nobody in the village would gain from a camp"
    assert sum(n.total for n in needs) > 0


def test_a_scheme_only_counts_if_every_counter_it_needs_comes(needs, offices):
    """The interaction that makes this hard rather than a ranking."""
    for need in needs:
        for scheme_id, wanted in need.missing.items():
            if len(wanted) < 2:
                continue
            one = next(iter(wanted))
            got = evaluate(needs, offices, [one])
            for row in got.served:
                if row.household == need.household:
                    assert scheme_id not in row.schemes
            return
    pytest.skip("no household in this village needs two counters")


@pytest.mark.parametrize("budget", BUDGETS)
def test_nothing_is_planned_over_budget(needs, offices, budget):
    for find in (exact, greedy, anneal):
        found = find(needs, offices, budget)
        outcome = found[0] if isinstance(found, tuple) else found
        assert outcome.slots <= budget, (find.__name__, budget)


@pytest.mark.parametrize("budget", BUDGETS)
def test_no_counter_is_asked_past_its_capacity(needs, offices, budget):
    """A counter that sees forty does not see the forty-first, and a plan
    that pretends otherwise sends people home."""
    outcome, _ = exact(needs, offices, budget)
    for office_id, queue in outcome.load.items():
        assert queue <= offices[office_id].serves, office_id


@pytest.mark.parametrize("budget", BUDGETS)
def test_heuristics_never_beat_the_optimum(needs, offices, budget):
    """They can tie it. Beating it would mean the enumeration is wrong."""
    best, _ = exact(needs, offices, budget)
    for found in (greedy(needs, offices, budget)[0],
                  anneal(needs, offices, budget)[0]):
        assert found.value <= best.value, budget


@pytest.mark.parametrize("budget", BUDGETS)
def test_annealing_gets_somewhere(needs, offices, budget):
    """Not optimality, which is not guaranteed, but that it moves at all.

    An earlier neighbourhood proposed only removals once the budget was
    spent, so every proposal was worse, every proposal was rejected, and the
    search froze on the first thing it found. This is the test that would
    have caught it.
    """
    found, trace = anneal(needs, offices, budget, rounds=300)
    best, _ = exact(needs, offices, budget)
    if best.value == 0:
        pytest.skip("nothing to find at this budget")
    assert found.value >= best.value * 0.6, (budget, found.value, best.value)
    assert len({tuple(p["chosen"]) for p in trace}) > 1, "the search never moved"


def test_a_bigger_budget_never_unlocks_less(needs, offices):
    """More officials cannot make the best possible day worse."""
    seen = [exact(needs, offices, b)[0].value for b in range(1, 9)]
    assert seen == sorted(seen), seen


def test_the_trace_is_shaped_for_drawing(needs, offices):
    _, trace = anneal(needs, offices, 4)
    assert len(trace) > 5
    for point in trace:
        assert {"round", "value", "best", "chosen", "took"} <= set(point)
    bests = [p["best"] for p in trace]
    assert bests == sorted(bests), "the best found should never go down"


def test_an_office_that_does_not_travel_is_never_invited(needs, offices):
    staying = {o.id for o in offices.values() if not o.travels}
    assert staying, "no office stays put, so this proves nothing"
    for budget in BUDGETS:
        outcome, _ = exact(needs, offices, budget)
        assert not (set(outcome.chosen) & staying)


def test_greedy_can_lose_even_though_it_does_not_here():
    """Constructed, and labelled as such.

    On our village greedy ties the optimum at every budget, which is the real
    result and a quiet one. It is not a guarantee, and this is the standard
    way it fails: one counter looks best alone, and two cheaper ones together
    beat it.
    """
    from patra.camp.model import Need, Office

    offices = {
        "big": Office("big", "Big", slots=2, serves=99, travels=True),
        "a": Office("a", "A", slots=1, serves=99, travels=True),
        "b": Office("b", "B", slots=1, serves=99, travels=True),
    }
    needs = [
        Need("h1", {"s": 60}, {"s": frozenset({"big"})}),
        Need("h2", {"s": 50}, {"s": frozenset({"a", "b"})}),
        Need("h3", {"s": 50}, {"s": frozenset({"a", "b"})}),
    ]
    best, _ = exact(needs, offices, 2)
    rough, _ = greedy(needs, offices, 2)
    assert best.value == 100, best.value
    assert rough.value == 60, rough.value
    assert rough.value < best.value
