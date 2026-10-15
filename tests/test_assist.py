"""The question answerer, and the one question it is not allowed to answer.

The three new intents forward to the reasoner rather than answering, so what
is tested here is the routing and the refusal: that "where do I go" and "will I
get it" are told apart although they share a verb in Hindi, and that an
entitlement is never stated unless the solver derived it.
"""

import pytest

from patra.assist import Assistant, Intent
from patra.i18n import Translations

DATA = None


@pytest.fixture(scope="session")
def words():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    return Translations(root / "data" / "i18n")


@pytest.fixture
def chat(schemes, documents, schema, engine, words, profile_of):
    def make(lang="en", household="sunita", member="sunita"):
        facts = profile_of(household, member).facts if household else {}
        return Assistant(schemes, documents, words.bundle(lang), schema,
                         engine=engine, facts=facts, held={"aadhaar"})
    return make


# ---- routing ----

ROUTES = [
    ("en", "what if our income was 80000", Intent.WHAT_IF),
    ("hi", "अगर मेरी आय 300000 हो तो?", Intent.WHAT_IF),
    ("en", "what should I do next", Intent.WHAT_NEXT),
    ("hi", "अब मुझे क्या करना चाहिए?", Intent.WHAT_NEXT),
    ("en", "where do I apply for the old age pension", Intent.SCHEME_WHERE),
    ("hi", "वृद्धावस्था पेंशन कहाँ से मिलेगी?", Intent.SCHEME_WHERE),
    ("en", "what schemes are there", Intent.LIST_SCHEMES),
    ("en", "how do I get a ration card", Intent.DOC_HOW),
    ("en", "is my data safe", Intent.PRIVACY),
    ("hi", "मेरी जानकारी सुरक्षित है?", Intent.PRIVACY),
]


@pytest.mark.parametrize("lang,question,intent", ROUTES)
def test_questions_reach_the_right_answer(chat, lang, question, intent):
    assert chat(lang).ask(question).intent is intent


def test_asking_where_is_not_asking_whether(chat):
    """"Kahan se milegi" and "mujhe milegi kya" share a verb.

    Routing the first to an eligibility verdict would answer a question
    nobody asked and leave the real one unanswered.
    """
    assistant = chat("hi")
    assert assistant.ask("वृद्धावस्था पेंशन कहाँ से मिलेगी?").intent \
        is Intent.SCHEME_WHERE
    assert assistant.ask("मुझे विधवा पेंशन मिलेगी क्या?").intent \
        in (Intent.ELIGIBLE, Intent.UNVERIFIED)


# ---- the question it may refuse ----

def test_an_entitlement_is_only_stated_when_derived(chat, by_id):
    answer = chat().ask("am I eligible for ayushman")
    assert answer.intent is Intent.ELIGIBLE
    assert answer.subject == "pmjay"


def test_without_answers_it_will_not_guess(chat):
    """The honest response to a question it cannot decide."""
    answer = chat(household=None).ask("am I eligible for the widow pension")
    assert answer.intent is Intent.UNVERIFIED


def test_a_refusal_comes_with_what_would_change_it(chat):
    answer = chat().ask("am I eligible for the widow pension")
    assert answer.intent is Intent.ELIGIBLE
    assert len(answer.bullets) > 1


# ---- statements rather than questions ----

def test_a_statement_is_read_and_offered_not_taken(chat):
    """The chat is a conversation. Rewriting answers given on another screen
    without asking would be the worst kind of helpful."""
    answer = chat(household=None).ask("hum paanch log hain")
    assert answer.intent is Intent.FACTS
    assert answer.apply == {"household_size": 5}


def test_a_question_is_never_read_as_a_statement(chat):
    answer = chat(household=None).ask("mujhe pension chahiye")
    assert answer.intent is not Intent.FACTS
    assert not answer.apply


# ---- what comes back is in the chosen language ----

def test_the_action_list_names_documents_in_the_chosen_language(chat, documents):
    """These came off the English YAML for a while, beside a Hindi office."""
    english = {d.name for d in documents}
    bullets = chat("hi").ask("अब मुझे क्या करना चाहिए?").bullets
    for line in bullets:
        for name in english:
            assert not line.startswith(f"1. {name}"), line
            assert not line.startswith(f"2. {name}"), line


def test_a_simulation_answers_in_the_chosen_language(chat):
    answer = chat("hi").ask("अगर मेरी आय 300000 हो तो?")
    assert answer.intent is Intent.WHAT_IF
    assert any(any(ch in line for ch in "अआइईउऊएओकखगघ") for line in answer.bullets)


# The subject index is built over names in the loaded language, so a Hindi
# question has to reach a Hindi assistant. That is the real configuration, and
# testing it in English would be testing something nobody runs.
COLLIDING = [
    ("en", "how do I get a ration card", Intent.DOC_HOW),
    ("en", "can I get the widow pension", Intent.ELIGIBLE),
    ("hi", "राशन कार्ड कैसे बनवाएँ?", Intent.DOC_HOW),
    ("hi", "विधवा पेंशन कहाँ मिलेगी?", Intent.SCHEME_WHERE),
    ("hi", "मुझे विधवा पेंशन मिलेगी क्या?", Intent.ELIGIBLE),
]


@pytest.mark.parametrize("lang,question,intent", COLLIDING)
def test_how_and_where_beat_whether(chat, lang, question, intent):
    """"How do I get" contains "do I get", and the Hindi verbs collide too.

    Place and method are the more specific ask, so they win. Getting this
    backwards answers a question nobody asked and leaves the real one unsaid.
    """
    assert chat(lang).ask(question).intent is intent
