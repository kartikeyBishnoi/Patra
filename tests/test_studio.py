"""The rulebook asked about itself: abduction, verification, diagnosis.

None of these needs an applicant, and all three answer a question about the
rules rather than about a person. The property worth protecting is that what
comes back is real: a witness the solver invents must actually satisfy the
scheme when fed back through the ordinary screening.
"""

import pytest

from patra.model.household import Profile
from patra.studio.witness import (
    falls_through,
    reachable,
    single_faults,
    who_qualifies,
)

POOR = {"ration_card_type": "aay", "area_type": "rural", "annual_income": 30000}
DILIGENT = {**POOR, "has_bank_account": True, "bank_aadhaar_linked": True,
            "cultivates_land": True, "willing_unskilled_work": True,
            "someone_has_bank_account": True, "has_willing_worker": True,
            "income_tax_payer": False, "govt_employee_in_family": False,
            "already_receiving_pension": False}


# ---- abduction ----

def test_every_scheme_can_be_satisfied_by_somebody(engine, schema, schemes, axioms):
    """A scheme nobody can reach is a rule with a typo in it."""
    found = reachable(engine, schema, schemes, axioms)
    unreachable = [k for k, v in found.items() if not v]
    assert not unreachable, unreachable


def test_an_invented_witness_really_does_qualify(engine, schema, schemes, axioms):
    """The whole point. A witness that does not survive the ordinary
    screening is a bug in the abduction, not a finding about the rules."""
    for scheme in schemes:
        witness = who_qualifies(engine, schema, scheme, axioms)
        assert witness.found, scheme.id
        profile = Profile(id="witness", facts=witness.facts)
        assert engine.satisfiable(scheme, profile), scheme.id


def test_a_witness_breaks_no_domain_axiom(engine, schema, schemes, axioms):
    """Nobody widowed at fifteen, even when the solver invented them."""
    for scheme in schemes:
        witness = who_qualifies(engine, schema, scheme, axioms)
        profile = Profile(id="witness", facts=witness.facts)
        assert not engine.inconsistencies(profile), scheme.id


def test_a_witness_is_shown_the_facts_that_matter(engine, schema, by_id, axioms):
    """Thirty-three facts is a dump. The ones the scheme reads are a witness."""
    witness = who_qualifies(engine, schema, by_id["ignwps"], axioms)
    shown = {s.attribute for s in witness.about}
    assert "marital_status" in shown
    assert "age" in shown


def test_an_unsatisfiable_scheme_yields_no_witness(engine, schema, by_id, axioms):
    """Proved by breaking one on purpose, since the real rulebook has none."""
    from dataclasses import replace

    from patra.model.constraint import Cmp, Lit, Var
    from patra.model.scheme import Criterion

    broken = replace(by_id["ignoaps"], criteria=(
        Criterion(id="X1", text="at least sixty", formula=Cmp("ge", Var("age"), Lit(60))),
        Criterion(id="X2", text="under thirty", formula=Cmp("lt", Var("age"), Lit(30))),
    ))
    assert not who_qualifies(engine, schema, broken, axioms).found


# ---- verification ----

def test_somebody_can_always_be_constructed_who_gets_nothing(
        engine, schema, schemes, axioms):
    """With nothing pinned the question is trivial, and the answer is yes.

    That is worth asserting because it is the baseline the interesting
    question is measured against.
    """
    assert falls_through(engine, schema, schemes, axioms).found


def test_the_gaps_are_all_paperwork_gaps(engine, schema, schemes, axioms):
    """The project's own thesis, checked rather than asserted.

    Pin a household poor and rural and somebody still falls through. Pin them
    to have also done what the paperwork asks and nobody does. So within this
    rulebook every gap is a paperwork gap, which is exactly what the app
    exists to close.
    """
    assert falls_through(engine, schema, schemes, axioms, POOR).found
    assert not falls_through(engine, schema, schemes, axioms, DILIGENT).found


def test_a_household_that_falls_through_really_qualifies_for_nothing(
        engine, schema, schemes, axioms):
    witness = falls_through(engine, schema, schemes, axioms, POOR)
    assert witness.found
    profile = Profile(id="gap", facts=witness.facts)
    for scheme in schemes:
        assert not engine.satisfiable(scheme, profile), scheme.id


def test_pinned_facts_are_respected(engine, schema, schemes, axioms):
    witness = falls_through(engine, schema, schemes, axioms, POOR)
    for name, value in POOR.items():
        assert witness.facts[name] == value, name


# ---- diagnosis ----

def test_a_fault_would_really_cause_a_refusal(engine, schema, by_id, profile_of):
    """Each suggested answer, fed back, must actually refuse them. A
    diagnosis that does not explain the symptom is not a diagnosis."""
    facts = profile_of("sunita", "sunita").facts
    scheme = by_id["ignwps"]
    found = single_faults(engine, schema, scheme, facts)
    assert found, "no single answer explains a refusal, so nothing is tested"

    for fault in found:
        altered = {**facts, fault.attribute: fault.theirs}
        assert not engine.satisfiable(scheme, Profile(id="theirs", facts=altered)), \
            f"{fault.criterion} was offered as a cause and is not one"


def test_a_fault_is_always_a_change(engine, schema, by_id, profile_of):
    facts = profile_of("sunita", "sunita").facts
    for fault in single_faults(engine, schema, by_id["ignwps"], facts):
        assert fault.theirs != fault.ours


def test_a_clause_reading_two_facts_is_not_blamed_on_one(engine, schema, by_id,
                                                         profile_of):
    """Guessing which of two a clerk got wrong would be worse than silence."""
    facts = profile_of("munni", "munni").facts
    scheme = by_id["ignwps"]
    two_fact = {c.id for c in scheme.criteria
                if len(_reads(c) & set(facts)) > 1}
    blamed = {f.criterion for f in single_faults(engine, schema, scheme, facts)}
    assert not (two_fact & blamed)


def _reads(criterion):
    from patra.model.constraint import variables
    return set(variables(criterion.formula))
