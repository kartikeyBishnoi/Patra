"""Re-deciding everything against a household that does not exist yet.

The property worth protecting is that the simulation uses the same eligibility
rule as the interview and the result page. A count that quietly folds in
schemes nobody could judge would make the whole feature a lie that happens to
look useful.
"""

from patra.reason.simulate import simulate


def run(engine, schema, schemes, facts, changes):
    return simulate(engine, schema, schemes, facts, changes)


def test_a_free_errand_gains_schemes(engine, schema, schemes, profile_of):
    """Sunita's refusals turn on one unlinked bank account."""
    facts = profile_of("sunita", "sunita").facts
    result = run(engine, schema, schemes, facts, {"bank_aadhaar_linked": True})
    assert result.ran
    assert "ignwps" in result.gained
    assert not result.lost


def test_a_loss_names_the_clause_that_caused_it(engine, schema, schemes, profile_of):
    facts = profile_of("sunita", "sunita").facts
    result = run(engine, schema, schemes, facts, {"annual_income": 300000})
    assert result.lost
    loss = result.lost[0]
    assert loss.blocked_by
    assert loss.blocked_by[0].text


def test_both_directions_are_reported(engine, schema, schemes, profile_of):
    """A change that gains and costs at once must show the whole trade."""
    facts = profile_of("sunita", "sunita").facts
    result = run(engine, schema, schemes, facts, {"annual_income": 300000})
    assert set(result.before) - set(result.after) == {l.scheme_id for l in result.lost}
    assert set(result.after) - set(result.before) == set(result.gained)


def test_an_impossible_change_is_refused_with_its_axiom(
        engine, schema, schemes, profile_of):
    facts = profile_of("sunita", "sunita").facts
    result = run(engine, schema, schemes, facts, {"age": 10})
    assert not result.ran
    assert result.impossible
    shift, axiom = result.impossible[0]
    assert shift.attribute == "age"
    assert axiom


def test_a_value_outside_the_schema_is_refused(engine, schema, schemes, profile_of):
    facts = profile_of("sunita", "sunita").facts
    result = run(engine, schema, schemes, facts, {"age": 999})
    assert not result.ran
    assert result.rejected


def test_an_unknown_attribute_is_refused(engine, schema, schemes, profile_of):
    facts = profile_of("sunita", "sunita").facts
    result = run(engine, schema, schemes, facts, {"not_an_attribute": 1})
    assert result.rejected


def test_undecidable_schemes_are_in_neither_total(engine, schema, schemes):
    """With almost nothing known, nothing may be counted as eligible."""
    result = run(engine, schema, schemes, {"age": 70}, {"age": 30})
    assert result.before == ()
    assert result.after == ()
    assert len(result.undecided) == len(schemes)


def test_changing_nothing_changes_nothing(engine, schema, schemes, profile_of):
    facts = profile_of("sunita", "sunita").facts
    result = run(engine, schema, schemes, facts,
                 {"annual_income": facts["annual_income"]})
    assert result.gained == ()
    assert result.lost == ()
    assert set(result.before) == set(result.after)


def test_the_simulation_agrees_with_a_real_screening(
        engine, schema, schemes, profile_of):
    """The after-state must be what the engine would say if it were true."""
    from patra.model.household import Profile
    from patra.reason.simulate import eligible_now

    facts = profile_of("bhola", "bhola").facts
    result = run(engine, schema, schemes, facts, {"has_bank_account": True})
    after = Profile(id="x", facts={**facts, "has_bank_account": True})
    for scheme in schemes:
        if scheme.id in result.undecided:
            continue
        assert eligible_now(engine, scheme, after) == (scheme.id in result.after)


def test_the_original_facts_are_not_touched(engine, schema, schemes, profile_of):
    facts = profile_of("sunita", "sunita").facts
    before = dict(facts)
    run(engine, schema, schemes, facts, {"annual_income": 999999})
    assert facts == before
