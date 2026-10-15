"""Reading a photographed document.

The specimens are drawn by tools/samplecards.py rather than supplied, because a
test that needs a photograph of somebody's Aadhaar card is a test that never
runs. They carry the phrases a real document carries and invented everything
else.

Skipped where tesseract is not installed, which is a property of the machine
and not a failure of the code.
"""

import pytest

from patra.guard import Source
from patra.vision.ocr import TESSERACT_LANG, capability, scan
from patra.vision.papers import Papers

CARDS = ("income_certificate", "ration_card", "aadhaar",
         "disability_certificate", "land_records")


@pytest.fixture(scope="session")
def reader():
    cap = capability()
    if not cap.available:
        pytest.skip(cap.note or "no text reader on this machine")
    if "eng" not in cap.installed:
        pytest.skip("the English text pack is not installed")
    return cap


@pytest.fixture(scope="session")
def cards(tmp_path_factory, reader):
    import sys
    sys.path.insert(0, "tools")
    from samplecards import SPECIMENS, draw

    folder = tmp_path_factory.mktemp("cards")
    for name, rows in SPECIMENS.items():
        draw(rows).save(folder / f"{name}.png")
    return folder


@pytest.fixture
def papers(schema, signatures):
    return Papers(schema, signatures)


def read_card(papers, cards, reader, name):
    return papers.interpret(scan((cards / f"{name}.png").read_bytes(), "en", reader))


@pytest.mark.parametrize("name", CARDS)
def test_each_specimen_is_recognised(papers, cards, reader, name):
    reading = read_card(papers, cards, reader, name)
    assert reading.document == name, [g.document for g in reading.guesses]
    assert reading.sure


@pytest.mark.parametrize("name", CARDS)
def test_a_guess_can_name_the_phrase_behind_it(papers, cards, reader, name):
    """A classification that cannot cite its evidence cannot be argued with."""
    reading = read_card(papers, cards, reader, name)
    assert reading.guesses[0].matched


def test_fields_come_off_the_certificate(papers, cards, reader):
    reading = read_card(papers, cards, reader, "income_certificate")
    found = {m.attribute: m.value for m in reading.mentions}
    assert found["annual_income"] == 72000


def test_a_field_carries_the_line_it_came_from(papers, cards, reader):
    reading = read_card(papers, cards, reader, "income_certificate")
    assert "72,000" in reading.mentions[0].evidence


def test_a_year_of_birth_becomes_an_age(papers, cards, reader):
    import datetime
    reading = read_card(papers, cards, reader, "aadhaar")
    found = {m.attribute: m.value for m in reading.mentions}
    assert found["age"] == datetime.date.today().year - 1964


def test_an_enum_is_mapped_not_guessed(papers, cards, reader):
    reading = read_card(papers, cards, reader, "ration_card")
    found = {m.attribute: m.value for m in reading.mentions}
    assert found["ration_card_type"] == "aay"


def test_an_aadhaar_number_is_counted_and_discarded(papers, cards, reader):
    """This app tells people it never asks for their Aadhaar number, which has
    to hold while it is looking at the card."""
    reading = read_card(papers, cards, reader, "aadhaar")
    assert reading.redacted
    assert reading.redacted[0].shape == "12 digits"
    for record in reading.redacted:
        assert not any(c.isdigit() for c in record.shape.replace("12", ""))
    assert "number" not in {m.attribute for m in reading.mentions}


@pytest.mark.parametrize("name", CARDS)
def test_nothing_off_a_photograph_is_used_unconfirmed(
        papers, cards, reader, guard, name):
    reading = read_card(papers, cards, reader, name)
    intake = guard.admit_document(reading, {})
    assert not intake.accepted
    assert len(intake.confirm) == len(reading.mentions)


def test_an_unreadable_picture_says_so(papers, reader):
    reading = papers.interpret(scan(b"not an image at all", "en", reader))
    assert reading.document is None
    assert not reading.scan.ok


def test_missing_language_packs_are_named_not_hidden():
    """A machine without the Hindi pack must say which pack, so somebody can
    install it, rather than returning an empty read that looks like bad light."""
    cap = capability()
    if not cap.available:
        pytest.skip("no text reader on this machine")
    for code in cap.missing:
        assert f"tesseract-ocr-{TESSERACT_LANG[code]}" in cap.note
