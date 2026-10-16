"""A constraint solver written out, and what each technique is worth.

Z3 does the eligibility reasoning better than anything written by hand. This
is the same machinery in the open on a problem Z3 is not asked about, so the
cost of backtracking, forward checking, AC-3 and the orderings can be
measured rather than described.
"""

import pytest

from patra.camp.plan import exact
from patra.csp.schedule import build, hamlet_of, plan_day
from patra.csp.solve import Constraint, Problem, ac3, solve

PLAIN = dict(mrv=False, degree=False, lcv=False, forward=False, arc=False)
FULL = dict(mrv=True, degree=True, lcv=True, forward=True, arc=True)


# ---- the solver itself ----

def test_it_solves_map_colouring():
    """The textbook instance, so a failure here is the solver and not the
    camp."""
    regions = ["wa", "nt", "sa", "q", "nsw", "v", "t"]
    borders = [("wa","nt"),("wa","sa"),("nt","sa"),("nt","q"),("sa","q"),
               ("sa","nsw"),("sa","v"),("q","nsw"),("nsw","v")]
    problem = Problem(
        domains={r: ["red", "green", "blue"] for r in regions},
        constraints=[
            Constraint((a, b), lambda d, a=a, b=b: (
                d.get(a) is None or d.get(b) is None or d[a] != d[b]))
            for a, b in borders
        ],
    )
    found = solve(problem, **FULL)
    assert found.found
    for a, b in borders:
        assert found.assignment[a] != found.assignment[b], (a, b)


def test_it_knows_when_there_is_no_answer():
    """Three mutually bordering regions cannot take two colours."""
    problem = Problem(
        domains={"a": [1, 2], "b": [1, 2], "c": [1, 2]},
        constraints=[
            Constraint((x, y), lambda d, x=x, y=y: (
                d.get(x) is None or d.get(y) is None or d[x] != d[y]))
            for x, y in (("a","b"), ("b","c"), ("a","c"))
        ],
    )
    assert not solve(problem, **FULL).found


def test_ac3_prunes_before_a_single_guess():
    """Arc consistency is meant to do work up front. If it empties a domain
    the search never starts at all."""
    from patra.csp.solve import Counters
    problem = Problem(
        domains={"a": [1, 2, 3], "b": [1, 2, 3]},
        constraints=[Constraint(("a", "b"), lambda d: (
            d.get("a") is None or d.get("b") is None or d["a"] > d["b"] + 5))],
    )
    domains = {k: list(v) for k, v in problem.domains.items()}
    counters = Counters()
    assert not ac3(problem, domains, counters)
    assert counters.revisions > 0


# ---- the camp day ----

@pytest.fixture(scope="module")
def day_problem(needs, offices):
    outcome, _ = exact(needs, offices, 4)
    problem, wanted, per_session = build(outcome, offices, needs, sessions=4)
    return outcome, problem, wanted, per_session


def test_the_instance_is_a_real_one(day_problem):
    """Every household needing every counter made the day impossible and
    looked like a hard instance instead of a wrong one. Each needs only what
    its own missing papers need."""
    _, problem, wanted, _ = day_problem
    assert problem.domains, "no households to schedule"
    sizes = {len(v) for v in wanted.values()}
    assert min(sizes) >= 1
    assert len(sizes) > 1, (
        "every household needs the same number of counters, which is the bug "
        "this test exists to catch")


def test_it_has_both_binary_and_n_ary_constraints(day_problem):
    """AC-3 is only defined over the binary ones, so there had better be
    some."""
    _, problem, _, _ = day_problem
    binary = [c for c in problem.constraints if c.binary]
    wider = [c for c in problem.constraints if not c.binary]
    assert binary and wider


def test_a_solution_respects_every_counter(day_problem):
    outcome, problem, wanted, per_session = day_problem
    found = solve(problem, **FULL)
    assert found.found

    load = {}
    for household, session in found.assignment.items():
        for counter in wanted[household]:
            load[(counter, session)] = load.get((counter, session), 0) + 1
    for (counter, session), queue in load.items():
        assert queue <= per_session[counter], (counter, session, queue)


def test_a_solution_keeps_hamlets_together(day_problem):
    _, problem, wanted, _ = day_problem
    found = solve(problem, **FULL)
    by_hamlet = {}
    for household in wanted:
        by_hamlet.setdefault(hamlet_of(household), []).append(household)
    for group in by_hamlet.values():
        group.sort()
        for a, b in zip(group, group[1:]):
            assert abs(found.assignment[a] - found.assignment[b]) <= 1


def test_mrv_never_costs_more_than_going_in_order(day_problem):
    """At the size the suite runs, both strategies walk straight through, so
    the only thing worth asserting is that the heuristic does not hurt.

    The dramatic version of this needs the whole village and lives in the
    evaluation harness, where plain backtracking fails outright on ninety
    three households and MRV solves it with no backtracking at all. A test
    that surveyed a hundred and fifty households would make the suite
    unusable, and one that asserted the dramatic number on thirty would be
    asserting something that is not true at this size.
    """
    _, problem, _, _ = day_problem
    blind = solve(problem, cap=20000, **PLAIN)
    smart = solve(problem, mrv=True, degree=False, lcv=False,
                  forward=True, arc=False)
    assert smart.found
    if blind.found:
        assert smart.counters.assignments <= blind.counters.assignments
        assert smart.counters.backtracks <= blind.counters.backtracks


def test_mrv_branches_on_the_tightest_variable(day_problem):
    """What MRV is, checked directly rather than through a node count."""
    from patra.csp.solve import _pick
    _, problem, _, _ = day_problem
    domains = {k: list(v) for k, v in problem.domains.items()}
    squeezed = sorted(domains)[3]
    domains[squeezed] = domains[squeezed][:1]
    assert _pick(problem, {}, domains, True, False) == squeezed


def test_forward_checking_prunes(day_problem):
    _, problem, _, _ = day_problem
    with_fc = solve(problem, mrv=True, degree=False, lcv=False,
                    forward=True, arc=False)
    assert with_fc.counters.pruned > 0


def test_plan_day_returns_a_usable_queue(needs, offices):
    outcome, _ = exact(needs, offices, 4)
    day = plan_day(outcome, offices, needs, sessions=4, **FULL)
    assert day.found
    queue = day.queue()
    assert set(queue) == {1, 2, 3, 4}
    assert sum(len(v) for v in queue.values()) == len(day.assignment)


def test_a_hamlet_is_stable(needs):
    """Derived from the id, so it cannot drift between runs or disturb the
    village generator's own stream."""
    first = [hamlet_of(n.household) for n in needs]
    again = [hamlet_of(n.household) for n in needs]
    assert first == again
    assert len(set(first)) > 1
