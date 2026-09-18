"""Minimal conflict detection.

The property under test is minimality, not merely that a conflict exists. An
algorithm returning the whole constraint set is always right about there being
a problem and always useless as an explanation, so every test here checks the
defining property directly rather than trusting the implementation.
"""

import pytest

from patra.model.household import project
from patra.model.scheme import facts_as_labelled
from patra.reason.oracle import Oracle
from patra.reason.quickxplain import (
    NoConflict,
    deletion_mus,
    is_minimal_conflict,
    quickxplain,
)

REFUSALS = [
    ("sunita", "ignoaps"),
    ("sunita", "pm_kisan"),
    ("kishore", "ignoaps"),
    ("kishore", "pmjay"),
    ("munni", "jsy"),
    ("munni", "pm_kisan"),
    ("bhola", "igndps"),
    ("ramlal", "ignwps"),
]


def oracle_for(engine, scheme, household, member_id=None):
    profile = project(household, engine.schema, member_id)
    soft = scheme.as_labelled() + facts_as_labelled(profile, engine.schema)
    return Oracle(engine.encoder, soft)


def a_refused_oracle(engine, by_id, households, hid, sid):
    """Pick a projection of this household that the scheme actually refuses."""
    household = households[hid]
    scheme = by_id[sid]
    candidates = [None] + [m.id for m in household.members]
    for member_id in candidates:
        try:
            oracle = oracle_for(engine, scheme, household, member_id)
        except ValueError:
            continue
        if not oracle.is_sat(oracle.ids):
            return oracle
    pytest.skip(f"{hid} is not refused {sid}")


@pytest.mark.parametrize("hid,sid", REFUSALS)
def test_quickxplain_returns_a_minimal_conflict(engine, by_id, households, hid, sid):
    oracle = a_refused_oracle(engine, by_id, households, hid, sid)
    core = quickxplain(oracle, oracle.ids)
    assert is_minimal_conflict(oracle, core)


@pytest.mark.parametrize("hid,sid", REFUSALS)
def test_deletion_returns_a_minimal_conflict(engine, by_id, households, hid, sid):
    oracle = a_refused_oracle(engine, by_id, households, hid, sid)
    core = deletion_mus(oracle, oracle.ids)
    assert is_minimal_conflict(oracle, core)


@pytest.mark.parametrize("hid,sid", REFUSALS)
def test_divide_and_conquer_costs_no_more_queries(engine, by_id, households, hid, sid):
    """Asserted as an inequality on purpose.

    How much QuickXPlain saves depends on where the conflict sits among the
    constraints, so pinning a ratio would measure the fixtures rather than the
    algorithm.
    """
    fast = a_refused_oracle(engine, by_id, households, hid, sid)
    quickxplain(fast, fast.ids)

    slow = a_refused_oracle(engine, by_id, households, hid, sid)
    deletion_mus(slow, slow.ids)

    assert fast.stats.calls <= slow.stats.calls


def test_a_satisfiable_set_raises_rather_than_inventing_a_conflict(
    engine, by_id, households
):
    household = households["ramlal"]
    oracle = oracle_for(engine, by_id["ignoaps"], household, "ramlal")
    assert oracle.is_sat(oracle.ids)

    with pytest.raises(NoConflict):
        quickxplain(oracle, oracle.ids)
    with pytest.raises(NoConflict):
        deletion_mus(oracle, oracle.ids)


def test_conflict_names_both_a_rule_and_an_answer(engine, by_id, households):
    """An explanation that only names rules tells somebody nothing about
    themselves, and one that only names answers blames them for the law."""
    profile = project(households["sunita"], engine.schema, "sunita")
    conflicts = engine.explain(by_id["ignwps"], profile)

    assert conflicts
    conflict = conflicts[0]
    assert conflict.rules and conflict.facts


def test_all_enumerated_conflicts_are_minimal(engine, by_id, households):
    from patra.reason.marco import all_muses

    oracle = oracle_for(engine, by_id["pmay_g"], households["kishore"])
    cores = all_muses(oracle)
    assert len(cores) > 1, "this fixture should fail on several counts"
    for core in cores:
        assert is_minimal_conflict(oracle, core)
