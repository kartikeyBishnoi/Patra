"""The two guards that exist because nobody is sitting beside the applicant.

A field worker would notice a misheard question. On a phone in somebody's own
hand, a wrong answer produces a verdict that cites a real clause, reads as
perfectly traceable, and is nonsense. So we check answers against each other,
and we refuse to state firmly anything that a small correction would reverse.
"""

import pytest

from patra.engine import Engine, Trust
from patra.model.household import Profile


def test_the_real_households_are_all_consistent(engine, households):
    from patra.model.household import project

    for household in households.values():
        assert engine.inconsistencies(project(household, engine.schema)) == []
        for member in household.members:
            profile = project(household, engine.schema, member.id)
            assert engine.inconsistencies(profile) == [], (
                f"{household.id}/{member.id} trips an axiom"
            )


def test_a_pregnant_man_is_caught(engine):
    profile = Profile(id="misheard", facts={"is_pregnant": True, "gender": "male"})
    clashes = engine.inconsistencies(profile)
    assert clashes
    assert {a for c in clashes for a in c.attributes} == {"is_pregnant", "gender"}


def test_a_married_eight_year_old_is_caught(engine):
    profile = Profile(id="misheard", facts={"marital_status": "married", "age": 8})
    clashes = engine.inconsistencies(profile)
    assert clashes
    assert {a for c in clashes for a in c.attributes} == {"marital_status", "age"}


def test_linking_an_account_that_does_not_exist_is_caught(engine):
    profile = Profile(
        id="misheard",
        facts={"bank_aadhaar_linked": True, "has_bank_account": False},
    )
    clashes = engine.inconsistencies(profile)
    assert clashes


def test_only_the_answers_that_disagree_are_named(engine):
    """Nobody should have to start over because one answer was misheard."""
    profile = Profile(
        id="misheard",
        facts={
            "is_pregnant": True,
            "gender": "male",
            "age": 30,
            "annual_income": 50000,
            "category": "sc",
            "marital_status": "married",
        },
    )
    named = {a for c in engine.inconsistencies(profile) for a in c.attributes}
    assert named == {"is_pregnant", "gender"}
    assert "annual_income" not in named
    assert "category" not in named


def test_a_verdict_on_contradictory_answers_is_marked_unreliable(
    engine, by_id
):
    profile = Profile(
        id="misheard",
        facts={
            "is_pregnant": True,
            "gender": "male",
            "age": 30,
            "first_child": True,
            "bank_aadhaar_linked": True,
            "has_bank_account": True,
            "govt_employee_in_family": False,
        },
    )
    verdict = engine.adjudicate(by_id["pmmvy"], profile)
    assert verdict.trust is Trust.UNRELIABLE


def test_a_number_just_inside_the_line_is_provisional(engine, by_id):
    profile = Profile(
        id="tight",
        facts={
            "area_type": "rural",
            "annual_income": 45_500,
            "ration_card_type": "phh",
            "owns_pucca_house": False,
            "has_widowed_member": False,
            "has_disabled_member": False,
            "adult_male_count": 1,
            "owns_vehicle": False,
        },
    )
    verdict = engine.adjudicate(by_id["ration_aay"], profile)
    assert verdict.eligible
    assert verdict.trust is Trust.PROVISIONAL

    income = next(m for m in verdict.margins if m.attribute == "annual_income")
    assert income.flips_at == 46_081, "the threshold itself must be named"


def test_a_number_well_inside_the_line_is_firm(engine, by_id):
    profile = Profile(
        id="clear",
        facts={
            "area_type": "rural",
            "annual_income": 12_000,
            "ration_card_type": "phh",
            "owns_pucca_house": False,
            "has_widowed_member": False,
            "has_disabled_member": False,
            "adult_male_count": 1,
            "owns_vehicle": False,
        },
    )
    verdict = engine.adjudicate(by_id["ration_aay"], profile)
    assert verdict.eligible
    assert verdict.trust is Trust.FIRM
    assert verdict.margins == []


def test_axioms_are_optional(schema, by_id, households, documents):
    """Running without them must not change any eligibility answer."""
    from patra.model.household import project

    with_axioms = Engine(schema, [], documents)
    profile = project(households["sunita"], schema, "sunita")
    verdict = with_axioms.adjudicate(by_id["ignwps"], profile)
    assert not verdict.eligible
    assert with_axioms.inconsistencies(profile) == []
