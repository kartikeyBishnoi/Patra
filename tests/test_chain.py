"""Forward and backward chaining over the domain axioms.

Three-valued on purpose. A formula whose variables are not all known is
unknown rather than false, which is the difference between "we have not
asked" and "they said no". Closed-world reasoning here would have the app
conclude that anybody who has not answered the pregnancy question is not
pregnant.
"""

import pytest

from patra.reason.chain import backward, evaluate, forward

CASES = [
    ({"is_pregnant": True}, "gender", "female", "A1"),
    ({"age": 8}, "has_bank_account", False, "A4"),
    ({"bank_aadhaar_linked": True}, "has_bank_account", True, "A7"),
]


@pytest.mark.parametrize("given,attribute,value,axiom", CASES)
def test_an_axiom_runs_forwards(schema, axioms, given, attribute, value, axiom):
    found = forward(schema, axioms, given)
    assert found.facts[attribute] == value
    fired = {d.attribute: d for d in found.derived}
    assert fired[attribute].axiom == axiom


def test_nothing_is_derived_from_nothing(schema, axioms):
    found = forward(schema, axioms, {})
    assert found.derived == ()
    assert found.bounds == ()


def test_an_unknown_formula_is_unknown_not_false(schema, axioms):
    """The whole reason this is three-valued."""
    pregnant = next(a for a in axioms if a.id == "A1")
    assert evaluate(pregnant.formula.antecedent, {}) is None
    assert evaluate(pregnant.formula.antecedent, {"is_pregnant": False}) is False


def test_a_conjunction_is_false_on_one_false(schema, axioms):
    """Even with the rest unknown, which is what makes it useful."""
    from patra.model.constraint import And, Cmp, Lit, Var
    formula = And((Cmp("ge", Var("age"), Lit(18)),
                   Cmp("le", Var("land_acres"), Lit(5))))
    assert evaluate(formula, {"age": 12}) is False
    assert evaluate(formula, {"age": 20}) is None


def test_a_disjunction_is_true_on_one_true(schema):
    from patra.model.constraint import Cmp, Lit, Or, Var
    formula = Or((Cmp("ge", Var("age"), Lit(60)),
                  Cmp("le", Var("land_acres"), Lit(2))))
    assert evaluate(formula, {"age": 70}) is True
    assert evaluate(formula, {"age": 30}) is None


def test_a_bound_is_not_an_answer(schema, axioms):
    """"Pregnant" implies an age between twelve and fifty-five, which is a
    narrowing and not an age. It must never arrive as a fact."""
    found = forward(schema, axioms, {"is_pregnant": True})
    assert "age" not in found.facts
    ages = [b for b in found.bounds if b.attribute == "age"]
    assert len(ages) == 1, "bounds on one attribute should be merged into one"
    assert ages[0].low == 12 and ages[0].high == 55


def test_bounds_from_two_axioms_are_merged(schema, axioms):
    found = forward(schema, axioms,
                    {"marital_status": "widowed",
                     "already_receiving_pension": True})
    ages = [b for b in found.bounds if b.attribute == "age"]
    assert len(ages) == 1
    assert len(ages[0].axioms) >= 2, "both reasons should be kept"


def test_a_contradiction_is_reported_not_overwritten(schema, axioms):
    """Somebody expecting who has already said male. The answer they gave
    stands, and the clash is named."""
    found = forward(schema, axioms, {"is_pregnant": True, "gender": "male"})
    assert found.conflict
    assert found.facts["gender"] == "male"


def test_derived_facts_never_overwrite_given_ones(schema, axioms):
    found = forward(schema, axioms,
                    {"bank_aadhaar_linked": True, "has_bank_account": True})
    assert found.facts["has_bank_account"] is True
    assert not any(d.attribute == "has_bank_account" for d in found.derived)


def test_chaining_agrees_with_the_consistency_checker(engine, schema, axioms):
    """Two implementations of the same knowledge must not disagree.

    If the chainer finds a conflict, the solver must find one too.
    """
    from patra.model.household import Profile
    for facts in ({"is_pregnant": True, "gender": "male"},
                  {"age": 15, "marital_status": "widowed"},
                  {"age": 5, "has_bank_account": True}):
        found = forward(schema, axioms, facts)
        clashes = engine.inconsistencies(Profile(id="t", facts=facts))
        assert bool(found.conflict) == bool(clashes), facts


def test_backward_chaining_gives_a_proof(schema, axioms):
    found = forward(schema, axioms, {"is_pregnant": True})
    step = backward(schema, axioms, found.facts, "gender")
    assert step.axiom == "A1"
    assert step.children, "a derived fact should name what it stood on"
    leaf = step.children[0]
    assert leaf.goal == "is_pregnant"
    assert leaf.axiom is None, "a given answer has no rule above it"


def test_a_given_fact_is_not_dressed_up_as_derived(schema, axioms):
    step = backward(schema, axioms, {"age": 40}, "age")
    assert step.axiom is None


def test_backward_chaining_on_an_unknown_returns_nothing(schema, axioms):
    assert backward(schema, axioms, {}, "gender") is None


def test_chaining_reaches_a_fixed_point(schema, axioms):
    """It must stop, and say how many passes it took."""
    found = forward(schema, axioms, {"bank_aadhaar_linked": True})
    assert found.rounds >= 1
    assert found.rounds < 10
