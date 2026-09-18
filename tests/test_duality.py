"""The hitting-set duality, checked rather than assumed.

Reiter's result says the minimal correction sets of an unsatisfiable system are
exactly the minimal hitting sets of its minimal unsatisfiable subsets, and the
other way round. It is why one traversal of the subset lattice answers both
"why not" and "what would fix it".

We compute the two families independently and confirm they stand in the
predicted relationship. Citing a theorem is not the same as knowing your code
obeys it.
"""

import pytest

from patra.model.household import project
from patra.model.scheme import facts_as_labelled
from patra.reason.hittingset import (
    is_hitting_set,
    min_cost_hitting_set,
    minimal_hitting_sets,
)
from patra.reason.marco import all_mcses, all_muses
from patra.reason.oracle import Oracle

CASES = [
    ("sunita", "ignoaps", "sunita"),
    ("sunita", "ignwps", "sunita"),
    ("kishore", "pmjay", None),
    ("munni", "jsy", "munni"),
    ("bhola", "igndps", "bhola"),
    ("ramlal", "pmuy", None),
]


def oracle_for(engine, scheme, household, member_id):
    profile = project(household, engine.schema, member_id)
    soft = scheme.as_labelled() + facts_as_labelled(profile, engine.schema)
    return Oracle(engine.encoder, soft)


def canon(sets):
    return sorted(tuple(sorted(s)) for s in sets)


@pytest.mark.parametrize("hid,sid,member", CASES)
def test_corrections_are_the_hitting_sets_of_the_conflicts(
    engine, by_id, households, hid, sid, member
):
    oracle = oracle_for(engine, by_id[sid], households[hid], member)
    if oracle.is_sat(oracle.ids):
        pytest.skip(f"{hid} is not refused {sid}")

    conflicts = all_muses(oracle)
    corrections = all_mcses(oracle)
    assert canon(minimal_hitting_sets(conflicts)) == canon(corrections)


@pytest.mark.parametrize("hid,sid,member", CASES)
def test_conflicts_are_the_hitting_sets_of_the_corrections(
    engine, by_id, households, hid, sid, member
):
    oracle = oracle_for(engine, by_id[sid], households[hid], member)
    if oracle.is_sat(oracle.ids):
        pytest.skip(f"{hid} is not refused {sid}")

    conflicts = all_muses(oracle)
    corrections = all_mcses(oracle)
    assert canon(minimal_hitting_sets(corrections)) == canon(conflicts)


@pytest.mark.parametrize("hid,sid,member", CASES)
def test_every_correction_hits_every_conflict(
    engine, by_id, households, hid, sid, member
):
    oracle = oracle_for(engine, by_id[sid], households[hid], member)
    if oracle.is_sat(oracle.ids):
        pytest.skip(f"{hid} is not refused {sid}")

    conflicts = all_muses(oracle)
    for correction in all_mcses(oracle):
        assert is_hitting_set(correction, conflicts)


@pytest.mark.parametrize("hid,sid,member", CASES)
def test_dropping_a_correction_set_restores_satisfiability(
    engine, by_id, households, hid, sid, member
):
    """A correction must actually correct."""
    oracle = oracle_for(engine, by_id[sid], households[hid], member)
    if oracle.is_sat(oracle.ids):
        pytest.skip(f"{hid} is not refused {sid}")

    for correction in all_mcses(oracle):
        rest = [c for c in oracle.ids if c not in set(correction)]
        assert oracle.is_sat(rest)


def test_empty_and_impossible_inputs(engine):
    assert minimal_hitting_sets([]) == [[]]
    assert min_cost_hitting_set([], {}) == []
    assert minimal_hitting_sets([["a"], []]) == []
    assert min_cost_hitting_set([["a"], []], {"a": 1}) is None
