"""The boundary between what was understood and what is true.

These are the tests that make the architecture a property of the code rather
than a claim in a README. Every one of them is a way the perception layer
could have been allowed to decide something, and each is closed.
"""

import pytest

from patra.guard import Doubt, Refused, Source
from patra.model.household import Profile
from patra.nlp.extract import Confidence, Mention


def say(attribute, value, confidence=Confidence.HIGH, hedged=False, start=0):
    return Mention(attribute=attribute, value=value, confidence=confidence,
                   evidence="x", start=start, end=start + 1, hedged=hedged)


# ---- facts in ----

def test_a_certain_reading_goes_through(guard):
    intake = guard.admit([say("age", 62)], {}, Source.SPOKEN)
    assert intake.facts == {"age": 62}


def test_an_unsure_reading_is_held_for_confirmation(guard):
    intake = guard.admit([say("marital_status", "widowed", Confidence.LOW)],
                         {}, Source.SPOKEN)
    assert not intake.accepted
    assert intake.confirm[0].doubt is Doubt.UNSURE


def test_a_hedged_number_is_held_for_confirmation(guard):
    intake = guard.admit([say("annual_income", 100000, hedged=True)],
                         {}, Source.SPOKEN)
    assert not intake.accepted
    assert intake.confirm[0].doubt is Doubt.HEDGED


def test_out_of_range_is_refused_with_a_reason(guard):
    intake = guard.admit([say("age", 480)], {}, Source.SPOKEN)
    assert not intake.accepted
    assert intake.refused[0].reason is Refused.OUT_OF_RANGE
    assert "120" in intake.refused[0].detail


def test_an_unknown_attribute_cannot_be_smuggled_in(guard):
    intake = guard.admit([say("bank_balance", 10)], {}, Source.SPOKEN)
    assert intake.refused[0].reason is Refused.UNKNOWN_ATTRIBUTE
    assert intake.facts == {}


def test_an_axiom_refuses_an_impossible_pair(guard):
    """Nobody is widowed at fifteen, whatever the sentence said."""
    intake = guard.admit([say("age", 15), say("marital_status", "widowed")],
                         {}, Source.SPOKEN)
    assert intake.facts == {"age": 15}
    refusal = intake.refused[0]
    assert refusal.reason is Refused.IMPOSSIBLE
    assert "eighteen" in refusal.axiom


def test_a_reading_cannot_overwrite_a_given_answer(guard):
    intake = guard.admit([say("age", 70)], {"age": 65}, Source.SPOKEN)
    assert not intake.accepted
    assert intake.confirm[0].doubt is Doubt.OVERWRITES
    assert intake.confirm[0].alternative == 65


def test_certain_readings_are_settled_before_unsure_ones(guard):
    """Order of appearance must not decide which reading wins."""
    intake = guard.admit(
        [say("marital_status", "widowed", Confidence.LOW, start=0),
         say("marital_status", "married", Confidence.HIGH, start=40)],
        {}, Source.SPOKEN)
    assert intake.facts == {"marital_status": "married"}


def test_a_document_reading_is_always_read_back(guard):
    """A five read as a six moves an income by ten thousand rupees."""
    intake = guard.admit([say("annual_income", 72000, Confidence.MEDIUM)],
                         {}, Source.DOCUMENT, confirm_all=True)
    assert not intake.accepted
    assert intake.confirm[0].attribute == "annual_income"


def test_an_inferred_fact_says_so(guard):
    mention = Mention(attribute="gender", value="female",
                      confidence=Confidence.HIGH, evidence="maa", start=0, end=3,
                      inferred_from="mother")
    intake = guard.admit([mention], {}, Source.SPOKEN)
    assert intake.accepted[0].source is Source.INFERRED
    assert intake.accepted[0].inferred_from == "mother"


# ---- confirmation is not permission ----

def test_confirming_does_not_waive_the_axioms(guard):
    """An answer somebody stands behind can still be impossible."""
    intake = guard.confirm("marital_status", "widowed", {"age": 15})
    assert not intake.accepted
    assert intake.refused[0].reason is Refused.IMPOSSIBLE


def test_confirming_does_not_waive_the_schema(guard):
    intake = guard.confirm("age", 480, {})
    assert intake.refused[0].reason is Refused.OUT_OF_RANGE


def test_a_confirmed_fact_is_marked_as_theirs(guard):
    intake = guard.confirm("age", 62, {})
    assert intake.accepted[0].source is Source.CONFIRMED
    assert Source.CONFIRMED.firm


# ---- claims out ----

def test_an_entitlement_needs_every_fact_it_reads(guard, by_id):
    check = guard.verify(by_id["ignoaps"], {"age": 70})
    assert not check.sayable
    assert check.eligible is None
    assert check.missing


def test_a_full_profile_gets_a_verdict(guard, by_id, profile_of):
    check = guard.verify(by_id["ignwps"], profile_of("sunita", "sunita").facts)
    assert check.sayable
    assert check.verified
    assert isinstance(check.eligible, bool)


def test_a_disagreement_with_the_solver_is_not_resolved_in_its_favour(
        guard, by_id, profile_of):
    """If some other layer claims eligibility and the solver refuses, the
    answer is neither one, it is "could not verify"."""
    facts = profile_of("sunita", "sunita").facts
    truth = guard.verify(by_id["ignwps"], facts)
    check = guard.verify(by_id["ignwps"], facts, asserted=not truth.eligible)
    assert check.contradicted
    assert not check.verified
    assert not check.sayable


def test_contradictory_answers_void_even_a_favourable_verdict(guard, by_id):
    """Answers that cannot both be true make every conclusion unsound."""
    facts = {"age": 15, "marital_status": "widowed", "ration_card_type": "aay",
             "already_receiving_pension": False, "bank_aadhaar_linked": True,
             "gender": "female"}
    check = guard.verify(by_id["ignwps"], facts)
    assert not check.sayable


def test_only_verified_schemes_are_offered(guard, schemes, profile_of):
    facts = profile_of("sunita", "sunita").facts
    offered = guard.verified_eligible(schemes, facts)
    for scheme in offered:
        assert scheme.attributes_used <= set(facts)
        assert guard.engine.satisfiable(scheme, Profile(id="t", facts=facts))
