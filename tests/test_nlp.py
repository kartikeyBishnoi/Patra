"""Reading facts out of a sentence.

Two kinds of test, and the second kind matters more. One checks that real
sentences in five languages produce the right facts. The other checks that
sentences carrying no facts produce none, because a gazetteer that fires on
anything is worse than no gazetteer: a missed fact costs a question, an
invented one costs a day's wages at the wrong office.
"""

import pytest

from patra.nlp.extract import Confidence
from patra.nlp.numbers import Numbers
from patra.nlp.text import phrase_hits, read


# ---- numbers ----

NUMBERS = [
    ("I am 62", 62),
    ("मैं 62 साल का हूँ", 62),
    ("saath saal", 60),
    ("72,000 a year", 72000),
    ("1 lakh", 100000),
    ("a lakh", 100000),
    ("do lakh", 200000),
    ("pachas hazaar", 50000),
    ("do lakh pachas hazaar", 250000),
    ("ek lakh bees hazaar", 120000),
    ("उत्पन्न 50 हजार", 50000),
    ("1.5 lakh", 150000),
]


@pytest.mark.parametrize("text,value", NUMBERS)
def test_numbers_read(cues, text, value):
    found = Numbers(cues).find(read(text))
    assert found, f"no number found in {text!r}"
    assert found[0].value == value


def test_indic_digits_become_arabic(cues):
    assert Numbers(cues).find(read("६२ साल"))[0].value == 62
    assert Numbers(cues).find(read("৭০ বছর"))[0].value == 70


def test_hedged_number_is_marked(cues):
    numbers = Numbers(cues)
    assert numbers.find(read("around 1 lakh"))[0].hedged
    assert not numbers.find(read("exactly 1 lakh"))[0].hedged


# ---- tokens and boundaries ----

def test_devanagari_words_survive_tokenising():
    """A vowel sign is not alphanumeric, which used to split every word."""
    assert [t.text for t in read("उत्पन्न 50 हजार").tokens] == \
        ["उत्पन्न", "50", "हजार"]


def test_cue_does_not_match_inside_a_longer_word():
    assert phrase_hits(read("nobody is here"), "no") == []
    assert phrase_hits(read("dastavez chahiye"), "das") == []


def test_indic_stem_matches_its_inflected_form():
    """Marathi marks case with a suffix, so "गाव" has to reach "गावात"."""
    assert phrase_hits(read("आमचे गावात घर आहे"), "गाव")


# ---- the whole reading ----

CASES = [
    ("Meri maa 62 saal ki hain", {"age": 62, "gender": "female"}),
    ("मेरी माँ 62 साल की हैं और वे विधवा हैं",
     {"age": 62, "gender": "female", "marital_status": "widowed"}),
    ("माझे वय 68 वर्षे आहे, मी विधवा आहे",
     {"age": 68, "marital_status": "widowed"}),
    ("আমার বয়স 70, আমি গ্রামে থাকি", {"age": 70, "area_type": "rural"}),
    ("என் வயது 65, நான் கிராமத்தில் வாழ்கிறேன்",
     {"age": 65, "area_type": "rural"}),
    ("I am a daily wage labourer in a village with 4 acres",
     {"occupation": "daily_wage", "area_type": "rural", "land_acres": 4}),
    ("mera khata nahi hai", {"has_bank_account": False}),
    ("gas connection nahi hai", {"lpg_connection": False}),
    ("hum paanch log hain", {"household_size": 5}),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_sentence_yields_facts(extractor, text, expected):
    got = {m.attribute: m.value for m in extractor.understand(text).mentions}
    for name, value in expected.items():
        assert got.get(name) == value, f"{name} in {text!r}: {got}"


QUIET = [
    "which schemes are there",
    "how do I get a ration card",
    "namaste",
    "thank you",
    "",
]


@pytest.mark.parametrize("text", QUIET)
def test_a_question_is_not_a_statement(extractor, text):
    """Nothing that is not an assertion of fact may produce one.

    "farmers" is excepted: a scheme question mentioning farmers does read as
    an occupation, and the assistant routes list questions before it ever gets
    here, so the only cost is a visible chip on the intake screen.
    """
    assert extractor.understand(text).mentions == ()


# ---- negation ----

def test_negation_reaches_both_directions(extractor):
    """English puts it before the phrase, Hindi after."""
    before = {m.attribute: m.value
              for m in extractor.understand("no gas connection").mentions}
    after = {m.attribute: m.value
             for m in extractor.understand("gas connection nahi hai").mentions}
    assert before["lpg_connection"] is False
    assert after["lpg_connection"] is False


def test_negation_stops_at_the_clause(extractor):
    got = {m.attribute: m.value for m in extractor.understand(
        "I have a bank account, no gas connection").mentions}
    assert got["has_bank_account"] is True
    assert got["lpg_connection"] is False


def test_negated_enum_proposes_nothing(extractor):
    """"Not a farmer" names seven other occupations and settles none."""
    got = {m.attribute for m in extractor.understand("I am not a farmer").mentions}
    assert "occupation" not in got


# ---- confidence ----

def test_a_hint_is_marked_unsure(extractor):
    """"No husband" is said by unmarried women as often as by widows."""
    found = {m.attribute: m for m in extractor.understand(
        "unka husband nahi hai").mentions}
    assert found["marital_status"].confidence is Confidence.LOW


def test_the_word_itself_is_certain(extractor):
    found = {m.attribute: m for m in extractor.understand("she is a widow").mentions}
    assert found["marital_status"].confidence is Confidence.HIGH


def test_hedge_does_not_leak_into_the_previous_clause(extractor):
    found = {m.attribute: m for m in extractor.understand(
        "I am 62 years old, income around 1 lakh").mentions}
    assert found["age"].confidence is Confidence.HIGH
    assert found["annual_income"].confidence is Confidence.LOW


# ---- binding numbers ----

def test_plausibility_settles_competing_anchors(extractor):
    """72000 is not an age, so the income word wins however close it is."""
    got = {m.attribute: m.value
           for m in extractor.understand("72000 saal ki kamai").mentions}
    assert got.get("annual_income") == 72000
    assert "age" not in got


def test_a_monthly_figure_is_scaled_to_a_year(extractor):
    got = {m.attribute: m.value
           for m in extractor.understand("we earn 6000 a month").mentions}
    assert got["annual_income"] == 72000


def test_a_number_with_no_anchor_is_reported_not_used(extractor):
    reading = extractor.understand("house number 42")
    assert reading.mentions == ()
    assert [n.value for n in reading.numbers_unused] == [42]


def test_an_impossible_number_still_names_its_attribute(extractor):
    """So the guard can refuse it by name rather than it vanishing."""
    got = {m.attribute: m.value for m in extractor.understand("my age is 480").mentions}
    assert got["age"] == 480


# ---- who the answers are about ----

def test_the_first_person_relative_is_the_subject(extractor):
    """"Meri maa ... unka husband" is about the mother."""
    assert extractor.understand(
        "meri maa 62 saal ki hain aur unka husband nahi hai").relation == "mother"


def test_a_relation_implies_what_nobody_stated(extractor):
    found = {m.attribute: m for m in extractor.understand("my mother is 62").mentions}
    assert found["gender"].value == "female"
    assert found["gender"].inferred_from == "mother"


def test_evidence_points_at_real_words(extractor):
    for mention in extractor.understand("I am 34 years old, farmer").mentions:
        assert mention.evidence
        assert mention.evidence in read("I am 34 years old, farmer").text


# ---- one sentence saying two things ----

def test_disagreement_is_held_back(extractor):
    reading = extractor.understand("I am married and unmarried")
    assert reading.disagreements
    assert "marital_status" not in {m.attribute for m in reading.mentions}


# ---- wanting a thing is not having it ----

ASKING = [
    "I want to apply for the old age pension",
    "how do I get the widow pension",
    "मुझे पेंशन चाहिए",
    "we need a gas connection",
    "gas connection kaise milega",
    "I want a vehicle loan",
    "how much does a pucca house cost",
    "मुझे पक्का घर चाहिए",
    "which schemes give a bank account",
    "राशन कार्ड कैसे बनवाएँ",
]


@pytest.mark.parametrize("text", ASKING)
def test_asking_for_a_thing_is_not_having_it(extractor, text):
    """The most expensive mistake this system can make.

    "Mujhe pension chahiye" read as already drawing a pension rules somebody
    out of the pension they came to ask about, and they would never know why.
    """
    assert extractor.understand(text).mentions == ()


WISHES = [
    ("I want work", "willing_unskilled_work"),
    ("मुझे काम चाहिए", "willing_unskilled_work"),
    ("kaam chahiye", "willing_unskilled_work"),
]


@pytest.mark.parametrize("text,attribute", WISHES)
def test_a_wish_that_is_itself_the_fact_still_reads(extractor, text, attribute):
    """"Would you take manual work" is answered by wanting it.

    The suppression is skipped where the cue contains the marker, which is the
    same rule that stops "pati nahi" being negated twice.
    """
    got = {m.attribute: m.value for m in extractor.understand(text).mentions}
    assert got.get(attribute) is True


def test_inquiry_suppression_is_scoped_to_the_clause(extractor):
    """A question in one clause must not silence a statement in the next."""
    got = {m.attribute: m.value for m in extractor.understand(
        "how do I get a ration card, we live in a village").mentions}
    assert got.get("area_type") == "rural"


def test_a_relative_said_to_be_gone_is_not_the_subject(extractor):
    """"Unka pati nahi hai" is about a widow, not about a husband."""
    reading = extractor.understand("unka pati nahi hai")
    assert reading.relation != "husband"
    assert "gender" not in {m.attribute for m in reading.mentions}


def test_a_relation_word_anchors_an_age(extractor):
    """"My daughter is 9" says nothing about years and means years."""
    got = {m.attribute: m.value for m in extractor.understand("my daughter is 9").mentions}
    assert got["age"] == 9


def test_english_number_words_are_read(extractor):
    got = {m.attribute: m.value
           for m in extractor.understand("we have two acres").mentions}
    assert got["land_acres"] == 2
