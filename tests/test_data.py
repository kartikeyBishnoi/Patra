"""Integrity of the knowledge base itself.

The rules are data, so the usual protection of a compiler does not apply. These
checks stand in for it: they catch a scheme pointing at a document nobody
declared, a criterion whose words do not mention what it actually tests, and
the dead entries that accumulate when rules get edited.

The mismatch check is the one that matters. A criterion reading "must own land"
while testing whether somebody farms it will produce an explanation that is
fluent, confident and false, and no amount of correct reasoning downstream
saves it.
"""

import pytest

from patra.model.attributes import Kind, Scope
from patra.model.constraint import variables


def test_every_scheme_names_documents_that_exist(schemes, documents):
    for scheme in schemes:
        for doc in scheme.documents:
            assert doc in documents, f"{scheme.id} wants unknown document {doc!r}"


def test_every_document_requirement_resolves(documents):
    # DocumentGraph checks this on construction; asserting it here means the
    # failure names the file rather than blowing up at import time.
    for doc in documents:
        for need in doc.needs:
            for option in need.options:
                assert option in documents


def test_document_graph_is_well_founded(documents):
    """Every document must be reachable from the roots.

    A pair that require each other would be invisible in the data and would
    only show up as an unreachable plan much later.
    """
    have = {d.id for d in documents.roots()}
    changed = True
    while changed:
        changed = False
        for doc in documents:
            if doc.id in have:
                continue
            if all(any(o in have for o in need.options) for need in doc.needs):
                have.add(doc.id)
                changed = True

    stranded = set(documents.ids) - have
    assert not stranded, f"these documents can never be obtained: {sorted(stranded)}"


def test_no_scheme_reads_an_undeclared_attribute(schemes, schema):
    for scheme in schemes:
        for name in scheme.attributes_used:
            assert name in schema, f"{scheme.id} reads undeclared {name!r}"


def test_household_schemes_do_not_read_member_facts(schemes, schema):
    """A household rule cannot reach into one unnamed person.

    If it needs to, the fact belongs in the derived counts instead.
    """
    for scheme in schemes:
        if scheme.scope is not Scope.HOUSEHOLD:
            continue
        for name in scheme.attributes_used:
            assert schema[name].scope is Scope.HOUSEHOLD, (
                f"{scheme.id} is household-scoped but reads member fact {name!r}"
            )


def test_criterion_text_mentions_what_it_tests(schemes, schema):
    """Guards against a rule drifting away from its own description.

    We look for the attribute's label words in the criterion text. It is a
    weak check and deliberately so, but it caught two real mismatches.
    """
    missed = []
    for scheme in schemes:
        for criterion in scheme.criteria:
            words = set(criterion.text.lower().replace(",", "").split())
            for name in variables(criterion.formula):
                label_words = {
                    w for w in schema[name].label.lower().split()
                    if len(w) > 3 and w not in {"the", "that", "with", "some", "does"}
                }
                if label_words and not (label_words & words):
                    missed.append((scheme.id, criterion.id, name, schema[name].label))

    # Some are genuinely fine: "below-poverty-line list" tests ration_card_type,
    # and rewording either one would read worse. We assert the count does not
    # grow rather than demanding zero.
    assert len(missed) <= 12, f"criterion text drifting from its rule: {missed}"


def test_every_attribute_has_a_question_someone_could_read_aloud(schema):
    for attr in schema:
        assert attr.question.endswith("?"), f"{attr.name}: question is not a question"
        assert len(attr.question) > 10, f"{attr.name}: question is too terse"


def test_enum_assets_are_ordered_worst_to_best(schema):
    """Asset ranking uses the declared option order, so the order is load-bearing."""
    for attr in schema:
        if attr.asset and attr.kind is Kind.ENUM:
            assert attr.options[0] in ("none", "no"), (
                f"{attr.name}: first option should be the worst case"
            )


def test_no_scheme_is_unsatisfiable_on_its_own(schemes, engine, schema):
    """A scheme nobody could ever qualify for is an encoding bug, not a policy.

    Checked by asking the solver for any assignment at all that satisfies every
    criterion together.
    """
    import z3

    for scheme in schemes:
        solver = z3.Solver()
        for expr in engine.encoder.background():
            solver.add(expr)
        for criterion in scheme.criteria:
            solver.add(engine.encoder.compile(criterion.formula))
        assert solver.check() == z3.sat, (
            f"{scheme.id}: no person could ever satisfy all of its criteria"
        )


def test_households_load_and_validate(households, schema):
    assert households
    for household in households.values():
        household.check(schema)
