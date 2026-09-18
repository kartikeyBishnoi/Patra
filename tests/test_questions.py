"""Asking as little as possible.

Two things are being tested. That we stop once nothing is undecided, which is
what keeps the interview short. And that sensitive questions go last, so that
in the common case where the answer is already settled, nobody is asked their
caste at all.
"""

import pytest

from patra.model.attributes import Scope
from patra.model.household import Profile
from patra.reason.questions import Status, interview, next_question, status


@pytest.fixture
def member_schemes(schemes):
    return [s for s in schemes if s.scope is Scope.MEMBER]


def test_nothing_left_to_ask_returns_none(engine, schema, by_id):
    scheme = by_id["sukanya"]
    known = Profile(id="x", facts={"gender": "female", "age": 6})
    assert next_question(engine, schema, [scheme], known) is None


def test_a_scheme_is_ruled_out_before_every_answer_is_known(engine, by_id):
    """Ruling something out takes one fact. Confirming it takes all of them.

    That asymmetry is what makes adaptive questioning worth having.
    """
    scheme = by_id["sukanya"]
    known = Profile(id="x", facts={"gender": "male"})
    assert status(engine, scheme, known) is Status.INELIGIBLE
    assert "age" in scheme.attributes_used - set(known.facts)


def test_a_scheme_stays_open_while_answers_are_missing(engine, by_id):
    scheme = by_id["sukanya"]
    known = Profile(id="x", facts={"gender": "female"})
    assert status(engine, scheme, known) is Status.OPEN


def test_the_first_question_serves_the_most_schemes(engine, schema, member_schemes):
    known = Profile(id="x", facts={})
    question = next_question(engine, schema, member_schemes, known)
    assert question is not None
    assert question.weight > 1, "the opening question should unblock several schemes"


def test_sensitive_questions_lose_ties(engine, schema, by_id):
    """Caste and disability wait behind anything equally useful."""
    known = Profile(id="x", facts={})
    schemes = [by_id["igndps"]]

    seen = []
    for _ in range(10):
        question = next_question(engine, schema, schemes, known)
        if question is None:
            break
        seen.append(question)
        # Answer in a way that keeps the scheme open.
        answers = {
            "age": 40,
            "disability_percent": 90,
            "ration_card_type": "phh",
            "already_receiving_pension": False,
            "bank_aadhaar_linked": True,
        }
        if question.attribute not in answers:
            break
        known = Profile(
            id="x", facts={**known.facts, question.attribute: answers[question.attribute]}
        )

    order = [q.attribute for q in seen]
    if "disability_percent" in order and len(order) > 1:
        assert order[0] != "disability_percent", (
            "a sensitive question should not open the interview when "
            "something else was equally useful"
        )


def test_the_interview_is_shorter_than_asking_everything(
    engine, schema, member_schemes
):
    answers = {
        "age": 8,
        "gender": "female",
        "marital_status": "unmarried",
        "category": "sc",
        "disability_percent": 0,
        "is_pregnant": False,
        "first_child": False,
        "has_bank_account": False,
        "bank_aadhaar_linked": False,
        "already_receiving_pension": False,
        "ration_card_type": "phh",
        "income_tax_payer": False,
        "govt_employee_in_family": False,
    }
    asked = interview(engine, schema, member_schemes, answers)
    everything = {a for s in member_schemes for a in s.attributes_used}

    assert len(asked) < len(everything), (
        f"asked {len(asked)} of {len(everything)}, expected a saving"
    )


def test_a_young_girl_is_never_asked_about_pregnancy(engine, schema, member_schemes):
    answers = {
        "age": 7,
        "gender": "female",
        "marital_status": "unmarried",
        "category": "st",
        "disability_percent": 0,
        "has_bank_account": False,
        "bank_aadhaar_linked": False,
        "already_receiving_pension": False,
        "ration_card_type": "phh",
        "income_tax_payer": False,
        "govt_employee_in_family": False,
        "is_pregnant": False,
        "first_child": False,
    }
    asked = [q.attribute for q in interview(engine, schema, member_schemes, answers)]
    if "age" in asked:
        assert "is_pregnant" not in asked, (
            "once we know she is seven, the question should never come up"
        )
