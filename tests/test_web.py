"""The web layer, and the one invariant that keeps it alive.

Z3 is not thread safe. Its terms and solvers belong to a context, and two
threads touching one context takes the whole process down rather than raising
anything catchable. A thread per request plus one shared engine is a crash
waiting for a second visitor, which is what happened the first time this ran
and again the day the topic pages were added.

So reaching the solver without holding the lock is not a style question, it is
the bug. This checks it statically, because the dynamic version of this test
is a process that dies.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "patra" / "web" / "server.py"

# Private helpers that are only ever reached from a method that already holds
# the lock. Each is named here deliberately rather than matched by a pattern,
# so adding one is a decision somebody makes on purpose.
UNDER_CALLER = {"_result", "_topic_page", "_card"}

REACHES_SOLVER = re.compile(r"self\.(engine|guard|extractor|papers)\b")
DELEGATES = re.compile(r"self\.(_scheme_card|_horizon)\b")


def brain_methods():
    src = SERVER.read_text(encoding="utf-8")
    body = src[src.index("class Brain"):src.index("class Handler")]
    for chunk in re.split(r"\n    (?=def )", body)[1:]:
        yield chunk.split("(")[0].replace("def ", "").strip(), chunk


def test_every_path_to_the_solver_holds_the_lock():
    unguarded = [
        name for name, code in brain_methods()
        if (REACHES_SOLVER.search(code) or DELEGATES.search(code))
        and "self._lock" not in code
        and name not in UNDER_CALLER
    ]
    assert not unguarded, (
        "these reach Z3 without the lock and will crash the process on a "
        f"second visitor: {unguarded}"
    )


def test_the_lock_is_reentrant():
    """The page methods call each other, so a plain lock would deadlock.

    A topic page builds scheme cards and a scheme card asks for an age
    horizon. With threading.Lock the helpers could not take the lock for
    themselves, and every caller would have to remember instead.
    """
    src = SERVER.read_text(encoding="utf-8")
    assert "threading.RLock()" in src
    assert "self._lock = threading.Lock()" not in src


def test_helpers_named_as_caller_guarded_really_are_private():
    names = {name for name, _ in brain_methods()}
    for helper in UNDER_CALLER:
        assert helper in names, f"{helper} no longer exists"
        assert helper.startswith("_"), helper


# ---- the knowledge base behind the new pages ----

@pytest.fixture(scope="session")
def topics():
    import yaml
    return yaml.safe_load(
        (ROOT / "data" / "topics.yaml").read_text(encoding="utf-8"))


def test_every_scheme_sits_under_exactly_one_topic(topics, schemes):
    placed = [s for t in topics["topics"].values() for s in t["schemes"]]
    known = {s.id for s in schemes}

    assert not (set(placed) - known), "topics.yaml names a scheme that does not exist"
    assert not (known - set(placed)), "a scheme has no topic, so nothing links to it"
    doubled = [s for s in set(placed) if placed.count(s) > 1]
    assert not doubled, f"listed twice: {doubled}"


def test_every_shortcut_points_at_something_real(topics, schemes, documents):
    known = {s.id for s in schemes}
    for entry in topics["how_do_i"]:
        if entry["kind"] == "document":
            assert entry["target"] in documents, entry
        elif entry["kind"] == "scheme":
            assert entry["target"] in known, entry
        else:
            pytest.fail(f"unknown kind {entry['kind']!r}")


def test_topics_and_shortcuts_are_named_in_every_language(topics):
    import yaml

    i18n = ROOT / "data" / "i18n"
    for path in sorted(i18n.glob("*.yaml")):
        strings = yaml.safe_load(path.read_text(encoding="utf-8"))["strings"]
        named = strings.get("topic") or {}
        for topic_id in topics["topics"]:
            assert (named.get(topic_id) or {}).get("name"), \
                f"{path.stem}: topic {topic_id} has no name"
        asked = strings.get("how") or {}
        for entry in topics["how_do_i"]:
            assert (asked.get(entry["id"]) or {}).get("question"), \
                f"{path.stem}: shortcut {entry['id']} has no question"


def test_the_front_page_does_not_claim_to_be_official():
    """The one thing this layout borrows from usa.gov and must invert.

    Mimicking a government service index is a design decision. Mimicking a
    government is not, and the strip in that position is where somebody
    decides whether to trust what follows.
    """
    import yaml

    i18n = ROOT / "data" / "i18n"
    page = (ROOT / "patra" / "web" / "index.html").read_text(encoding="utf-8")
    assert "not_official" in page

    for path in sorted(i18n.glob("*.yaml")):
        ui = yaml.safe_load(path.read_text(encoding="utf-8"))["strings"]["ui"]
        assert ui.get("not_official"), path.stem
        assert ui.get("foot_note"), path.stem


# ---- the relations the new pages are built on ----

def test_entailment_survives_a_real_screening(engine, schemes, profile_of):
    """If the rulebook says clearing A clears B, a household that clears A
    must clear B. The page states it as a guarantee, so it has to be one."""
    from patra.model.household import Profile
    from patra.reason.relate import analyse
    from patra.reason.simulate import eligible_now

    book = analyse(engine, schemes)
    by_id = {s.id: s for s in schemes}
    assert book.entails, "no entailments found, so this proves nothing"

    for who in ("sunita", "ramlal", "bhola", "munni", "kishore"):
        facts = profile_of(who).facts
        profile = Profile(id=who, facts=facts)
        for relation in book.entails:
            left, right = by_id[relation.left], by_id[relation.right]
            if not (left.attributes_used | right.attributes_used) <= set(facts):
                continue
            if eligible_now(engine, left, profile):
                assert eligible_now(engine, right, profile), \
                    f"{who}: {relation.left} was supposed to settle {relation.right}"


def test_exclusions_really_exclude(engine, schemes, profile_of):
    from patra.model.household import Profile
    from patra.reason.relate import analyse
    from patra.reason.simulate import eligible_now

    book = analyse(engine, schemes)
    by_id = {s.id: s for s in schemes}
    for who in ("sunita", "ramlal", "bhola", "munni", "kishore"):
        facts = profile_of(who).facts
        profile = Profile(id=who, facts=facts)
        for relation in book.excludes:
            left, right = by_id[relation.left], by_id[relation.right]
            if not (left.attributes_used | right.attributes_used) <= set(facts):
                continue
            both = (eligible_now(engine, left, profile)
                    and eligible_now(engine, right, profile))
            assert not both, f"{who} holds both {relation.left} and {relation.right}"


def test_a_scheme_never_entails_itself(engine, schemes):
    from patra.reason.relate import analyse
    book = analyse(engine, schemes)
    for relation in book.entails + book.excludes + book.equivalent:
        assert relation.left != relation.right


# ---- when, rather than whether ----

def test_an_opening_is_always_in_the_future(engine, schema, schemes, profile_of):
    from patra.reason.timeline import horizons
    for who in ("sunita", "ramlal", "bhola", "munni", "kishore"):
        facts = profile_of(who).facts
        for h in horizons(engine, schema, schemes, facts):
            if h.opens_at is not None:
                assert h.opens_at > facts["age"], f"{who}: {h.scheme_id}"
            if h.closes_at is not None:
                assert h.closes_at > facts["age"], f"{who}: {h.scheme_id}"


def test_waiting_really_does_open_it(engine, schema, schemes, profile_of):
    """Where the horizon says age alone is enough, check it by setting the
    age and asking again. A date somebody plans around has to be right."""
    from patra.model.household import Profile
    from patra.reason.timeline import horizons

    by_id = {s.id: s for s in schemes}
    for who in ("sunita", "ramlal", "bhola", "munni", "kishore"):
        facts = profile_of(who).facts
        for h in horizons(engine, schema, schemes, facts):
            if h.opens_at is None or not h.only_age:
                continue
            later = dict(facts)
            later["age"] = h.opens_at
            if h.opens_at >= 60 and "has_member_over_60" in later:
                later["has_member_over_60"] = True
            assert engine.satisfiable(by_id[h.scheme_id],
                                      Profile(id="later", facts=later)), \
                f"{who}: {h.scheme_id} was promised to open at {h.opens_at}"


def test_a_scheme_with_no_age_rule_has_no_horizon(engine, schema, by_id, profile_of):
    from patra.reason.timeline import horizon
    facts = profile_of("sunita", "sunita").facts
    # PM-KISAN turns on land and tax, never on age.
    assert horizon(engine, schema, by_id["pm_kisan"], facts) is None


def test_distant_closings_are_not_reported(engine, schema, schemes, profile_of):
    """True and not actionable. Nobody plans around a scheme that stops
    taking them in thirty years, and printing it buries the one that closes
    in two."""
    from patra.reason.timeline import SOON, horizons
    for who in ("sunita", "munni", "bhola"):
        facts = profile_of(who).facts
        for h in horizons(engine, schema, schemes, facts):
            if h.closes_at is not None:
                assert h.closes_at - facts["age"] <= SOON
