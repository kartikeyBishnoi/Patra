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

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

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


# ---- the cue vocabulary ----

# The names a cue block may carry beside its values.
CUE_KEYS = {"kind", "anchors", "per_month", "plausible", "options", "true", "false"}


def test_every_cue_block_names_a_real_attribute(cues, schema):
    for name in cues["attributes"]:
        assert name in schema, f"cues.yaml has a block for unknown {name!r}"


def test_cue_blocks_have_no_stray_keys(cues):
    """A misspelled key would be silently ignored, and the cue never fire."""
    for name, block in cues["attributes"].items():
        stray = set(block) - CUE_KEYS
        assert not stray, f"{name}: {stray}"


def test_boolean_cue_keys_survived_yaml(cues, schema):
    """YAML 1.1 reads a bare `true:` key as the boolean True.

    The keys are quoted for that reason. Unquoting one would move the whole
    block out of reach without any error, which is the same trap documented in
    docs/LANGUAGES.md.
    """
    from patra.model.attributes import Kind

    for name, block in cues["attributes"].items():
        if schema[name].kind is not Kind.BOOL:
            continue
        assert not any(isinstance(key, bool) for key in block), \
            f"{name}: quote the true/false keys in cues.yaml"
        assert "true" in block or "false" in block, f"{name}: no values declared"


def test_every_cue_option_is_a_real_option(cues, schema):
    for name, block in cues["attributes"].items():
        for option in (block.get("options") or {}):
            assert option in schema[name].options, f"{name}: {option!r}"


def test_every_confidence_tier_is_one_we_have(cues, schema):
    from patra.model.attributes import Kind
    from patra.nlp.extract import Confidence

    tiers = {c.value for c in Confidence}
    for name, block in cues["attributes"].items():
        groups = []
        if schema[name].kind is Kind.BOOL:
            groups = [block.get("true"), block.get("false")]
        else:
            groups = list((block.get("options") or {}).values())
        for group in groups:
            if isinstance(group, dict):
                assert set(group) <= tiers, f"{name}: {set(group) - tiers}"


def test_numeric_cues_declare_a_window_inside_the_schema(cues, schema):
    """The window only breaks ties between anchors, so it must not be wider
    than what the schema would accept anyway."""
    from patra.model.attributes import Kind

    for name, block in cues["attributes"].items():
        if schema[name].kind is not Kind.INT:
            continue
        window = block.get("plausible")
        assert window, f"{name}: a numeric cue needs a plausible window"
        low, high = window
        assert low <= high
        if schema[name].low is not None:
            assert low >= schema[name].low, name
        if schema[name].high is not None:
            assert high <= schema[name].high, name


def test_numeric_cues_have_anchors_and_others_do_not(cues, schema):
    from patra.model.attributes import Kind

    for name, block in cues["attributes"].items():
        if schema[name].kind is Kind.INT:
            assert block.get("anchors"), f"{name}: a number needs anchoring words"
        else:
            assert not block.get("anchors"), f"{name}: anchors on a non-number"


def test_relations_imply_only_facts_that_exist(cues, schema):
    for name, spec in cues["relations"].items():
        assert spec.get("phrases"), f"{name}: no phrases"
        for attribute, value in (spec.get("implies") or {}).items():
            assert attribute in schema, f"{name} implies unknown {attribute!r}"
            attr = schema[attribute]
            if attr.options:
                assert value in attr.options, f"{name} implies {attribute}={value!r}"


def test_no_cue_phrase_is_a_stray_boolean(cues):
    """`- no` in a phrase list parses as False and crashes the matcher."""
    def check(values, where):
        for value in values or ():
            assert not isinstance(value, bool), f"{where}: quote it"

    check(cues.get("negations"), "negations")
    check(cues.get("hedges"), "hedges")
    check(cues.get("first_person"), "first_person")
    for name, spec in cues["relations"].items():
        check(spec.get("phrases"), f"relations.{name}")


# ---- the document signatures ----

def test_every_signature_block_names_a_real_document(signatures, documents):
    for name in signatures["papers"]:
        assert name in documents, f"papers.yaml describes unknown {name!r}"


def test_every_field_pattern_compiles(signatures):
    import re

    for name, spec in signatures["papers"].items():
        for rule in ((spec or {}).get("fields") or ()):
            re.compile(rule["pattern"])


def test_every_field_names_a_real_attribute_or_is_redacted(signatures, schema):
    for name, spec in signatures["papers"].items():
        for rule in ((spec or {}).get("fields") or ()):
            if rule.get("redact"):
                continue
            attribute = rule.get("attribute")
            assert attribute in schema, f"{name}.{rule['name']}: {attribute!r}"
            attr = schema[attribute]
            for target in (rule.get("map") or {}).values():
                assert target in attr.options, f"{name}: maps to {target!r}"


def test_an_identity_number_is_always_redacted(signatures):
    """Aadhaar and PAN numbers identify the card and are then thrown away.

    The app tells people it never asks for their Aadhaar number. Reading one
    off the card and keeping it would make that false.
    """
    for name in ("aadhaar", "pan_card", "bank_account"):
        rules = signatures["papers"][name].get("fields") or ()
        numbers = [r for r in rules if r["name"] == "number"]
        assert numbers, f"{name}: no number rule"
        for rule in numbers:
            assert rule.get("redact") is True, f"{name}: number is not redacted"
            assert "attribute" not in rule, f"{name}: number is bound to a fact"


# ---- the attribute to document links ----

def test_paperwork_links_point_at_real_documents(schema, documents):
    for attr in schema:
        if attr.document is not None:
            assert attr.document in documents, f"{attr.name} -> {attr.document!r}"


# ---- the language files ----

def test_every_language_covers_every_english_key():
    """English leaking into a Hindi screen is the bug this catches.

    It kept happening one section at a time: criterion texts, then units, then
    the derivation panel, each only visible by walking the whole flow in that
    language. The fallback is per key, so a gap is quiet.
    """
    import yaml

    i18n = ROOT / "data" / "i18n"
    english = yaml.safe_load(
        (i18n / "en.yaml").read_text(encoding="utf-8"))["strings"]

    def flatten(tree, prefix=""):
        out = set()
        for key, value in tree.items():
            path = f"{prefix}{key}"
            if isinstance(value, dict):
                out |= flatten(value, path + ".")
            else:
                out.add(path)
        return out

    # Scheme, document and criterion wording is named per language and falls
    # back to the YAML, so only the sections English actually owns are checked.
    sections = ("ui", "trace", "phrase", "relation")
    wanted = {k for k in flatten(english) if k.split(".")[0] in sections}

    for path in sorted(i18n.glob("*.yaml")):
        if path.stem == "en":
            continue
        strings = yaml.safe_load(path.read_text(encoding="utf-8"))["strings"]
        missing = wanted - flatten(strings)
        assert not missing, f"{path.stem} is missing {sorted(missing)}"


def test_interface_strings_the_code_asks_for_all_exist():
    """Every t("ui.x") in the page and every ui(...) default in the assistant.

    A typo in a key name shows the English default forever and looks like a
    missing translation rather than a missing key.
    """
    import re
    import yaml

    english = yaml.safe_load(
        (ROOT / "data" / "i18n" / "en.yaml").read_text(encoding="utf-8"))["strings"]

    page = (ROOT / "patra" / "web" / "index.html").read_text(encoding="utf-8")
    asked = set(re.findall(r't\("ui\.([a-z0-9_]+)"', page))
    asked |= set(re.findall(
        r'self\.ui\("([a-z0-9_]+)"',
        (ROOT / "patra" / "assist.py").read_text(encoding="utf-8")))

    defined = set(english["ui"])
    missing = []
    for key in sorted(asked):
        if key in defined:
            continue
        # A key built by concatenation, as in "ui.next_threshold_" + "le",
        # arrives here as its literal prefix. One defined key starting with it
        # is enough to show the family exists.
        if key.endswith("_") and any(k.startswith(key) for k in defined):
            continue
        missing.append(key)
    assert not missing, f"used but never defined: {missing}"
