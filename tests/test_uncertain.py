"""Answers given as a range, and the third verdict that admits it.

Two solver questions instead of one: can the clauses hold anywhere in the
range, and must they hold everywhere in it. The pair of answers is what makes
"depends, and here is the number it depends on" sayable.
"""

import pytest

from patra.model.household import Profile
from patra.model.scheme import Worth
from patra.reason.uncertain import Range, Standing, judge, screen


def test_a_range_that_settles_it_either_way(engine, schema, by_id, profile_of):
    """Narrow enough and the third answer does not arise."""
    facts = dict(profile_of("sunita", "sunita").facts)
    said = facts.pop("annual_income")
    tight = Range("annual_income", said - 500, said + 500, said)
    found = judge(engine, schema, by_id["ration_aay"], facts, [tight])
    assert found.standing is Standing.CERTAIN
    assert found.hinge is None


def test_a_range_across_a_threshold_depends(engine, schema, by_id, profile_of):
    """The Antyodaya income line is 46,080, so a range around it must not
    produce a confident answer in either direction."""
    facts = dict(profile_of("sunita", "sunita").facts)
    facts.pop("annual_income")
    wide = Range("annual_income", 40000, 60000, 50000)
    found = judge(engine, schema, by_id["ration_aay"], facts, [wide])
    assert found.standing is Standing.DEPENDS
    assert found.hinge is not None
    assert found.hinge.attribute == "annual_income"
    assert found.hinge.at == 46080
    assert found.hinge.keeps == "le"


def test_the_hinge_really_is_the_hinge(engine, schema, by_id, profile_of):
    """Check the boundary by standing on both sides of it."""
    facts = dict(profile_of("sunita", "sunita").facts)
    facts.pop("annual_income")
    found = judge(engine, schema, by_id["ration_aay"], facts,
                  [Range("annual_income", 40000, 60000, 50000)])
    at = found.hinge.at
    scheme = by_id["ration_aay"]
    assert engine.satisfiable(scheme, Profile(
        id="under", facts={**facts, "annual_income": at}))
    assert not engine.satisfiable(scheme, Profile(
        id="over", facts={**facts, "annual_income": at + 1}))


def test_a_range_that_cannot_work_is_impossible(engine, schema, by_id, profile_of):
    facts = dict(profile_of("sunita", "sunita").facts)
    facts.pop("annual_income")
    found = judge(engine, schema, by_id["ration_aay"], facts,
                  [Range("annual_income", 200000, 400000, 300000)])
    assert found.standing is Standing.IMPOSSIBLE
    assert found.hinge is None


def test_two_ranges_claim_no_single_hinge(engine, schema, by_id, profile_of):
    """With two uncertain facts the boundary is a line, not a number, and
    there is no honest way to say it in one sentence."""
    facts = dict(profile_of("sunita", "sunita").facts)
    facts.pop("annual_income")
    facts.pop("land_acres")
    found = judge(engine, schema, by_id["ration_aay"], facts, [
        Range("annual_income", 40000, 60000, 50000),
        Range("land_acres", 0, 9, 4),
    ])
    assert found.hinge is None


def test_certain_agrees_with_the_ordinary_verdict(engine, schema, schemes,
                                                   profile_of):
    """A range of one value must give exactly what the firm answer gives."""
    profile = profile_of("sunita", "sunita")
    facts = dict(profile.facts)
    said = facts.pop("annual_income")
    point = Range("annual_income", said, said, said)

    for found in screen(engine, schema, schemes, facts, [point]):
        scheme = next(s for s in schemes if s.id == found.scheme_id)
        firm = engine.satisfiable(scheme, profile)
        assert (found.standing is Standing.CERTAIN) == firm, found.scheme_id
        assert found.standing is not Standing.DEPENDS


def test_an_empty_range_is_refused(engine, schema):
    with pytest.raises(ValueError):
        Range("annual_income", 90000, 10000)


def test_schemes_with_missing_facts_are_left_out(engine, schema, schemes):
    """Nothing is claimed about a scheme whose facts nobody gave."""
    found = screen(engine, schema, schemes, {"age": 70},
                   [Range("annual_income", 1000, 2000, 1500)])
    assert found == []


# ---- what a scheme is worth ----

def test_cover_is_never_counted_as_income():
    """Five lakh of hospital cover is not five lakh in hand, and a ranking
    that added them would put insurance above every pension."""
    cover = Worth(kind="cover", cover=500000)
    assert cover.in_hand == 0
    assert cover.stated


def test_a_one_time_payment_is_spread(schema):
    once = Worth(kind="cash", once=120000)
    assert once.in_hand == 120000 // Worth.SPREAD


def test_every_scheme_says_where_its_figure_came_from(schemes):
    """A number without its provenance gets quoted back as fact."""
    for scheme in schemes:
        if scheme.worth.stated:
            assert scheme.worth.basis, scheme.id
            assert len(scheme.worth.basis) > 30, scheme.id


def test_worth_kinds_are_ones_we_handle(schemes):
    allowed = {"cash", "grain", "cover", "credit", "savings", "enabler"}
    for scheme in schemes:
        assert scheme.worth.kind in allowed, (scheme.id, scheme.worth.kind)
