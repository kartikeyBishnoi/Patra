"""Evaluation harness.

Six experiments, each answering something somebody would reasonably ask:

    E1  Is the divide-and-conquer conflict search worth writing?
    E2  Does the duality hold on our instances, or did we just cite it?
    E3  Is the acquisition planner finding the cheapest route?
    E4  How much shorter is adaptive questioning, and does it skip the
        intrusive questions?
    E5  What happens across many households rather than our five?
    E6  How does cost grow as the rulebook grows?
    E7  How much of what people say does the understanding layer actually get?
    E8  Does saying it in a sentence shorten the interview?
    E9  What does the guard between the two halves actually stop?

Every number printed here comes from running the system. Run with:

    python3 eval/benchmark.py

E7 carries a caveat printed beside it, and it is not a small one: the labelled
sentences and the cue vocabulary were written by the same hand, so the number
measures coverage of phrasings we thought of rather than generalisation. It is
the first figure that should be replaced with field data.
"""

from __future__ import annotations

import random
import sys
import time
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from patra.encode.loader import (
    load_axioms,
    load_documents,
    load_households,
    load_schema,
    load_schemes,
)
from patra.engine import Engine, Trust
from patra.model.attributes import Kind, Scope
from patra.model.constraint import Cmp, Lit, Var
from patra.model.household import Household, Member, Profile, project
from patra.model.scheme import Criterion, Scheme, facts_as_labelled
from patra.reason.hittingset import minimal_hitting_sets
from patra.reason.marco import all_mcses, all_muses
from patra.reason.oracle import Oracle
from patra.reason.planner import acquire
from patra.reason.questions import interview
from patra.reason.quickxplain import deletion_mus, is_minimal_conflict, quickxplain

DATA = Path(__file__).resolve().parent.parent / "data"
LINE = "-" * 72


def oracle_for(engine, scheme, profile):
    soft = scheme.as_labelled() + facts_as_labelled(profile, engine.schema)
    return Oracle(engine.encoder, soft)


def refusals(engine, schemes, households):
    """Every (scheme, profile) pair in the corpus that comes back refused."""
    out = []
    for household in households:
        for scheme in schemes:
            if scheme.scope is Scope.HOUSEHOLD:
                targets = [(None, project(household, engine.schema))]
            else:
                targets = [
                    (m.id, project(household, engine.schema, m.id))
                    for m in household.members
                ]
            for member_id, profile in targets:
                oracle = oracle_for(engine, scheme, profile)
                if not oracle.is_sat(oracle.ids):
                    out.append((household.id, scheme, member_id, profile))
    return out


def canon(sets):
    return sorted(tuple(sorted(s)) for s in sets)


# ----------------------------------------------------------------- E1

def e1_conflict_search(engine, schemes, households):
    print(LINE)
    print("E1  Finding a minimal reason: divide and conquer vs linear deletion")
    print(LINE)

    fast_total = slow_total = 0
    cases = 0
    worst = None

    for hid, scheme, member_id, profile in refusals(engine, schemes, households):
        fast = oracle_for(engine, scheme, profile)
        core = quickxplain(fast, fast.ids)
        assert is_minimal_conflict(oracle_for(engine, scheme, profile), core)

        slow = oracle_for(engine, scheme, profile)
        deletion_mus(slow, slow.ids)

        fast_total += fast.stats.calls
        slow_total += slow.stats.calls
        cases += 1

        ratio = fast.stats.calls / slow.stats.calls
        if worst is None or ratio > worst[0]:
            worst = (ratio, hid, scheme.id, fast.stats.calls, slow.stats.calls)

    saved = 100.0 * (slow_total - fast_total) / slow_total
    print(f"  {cases} refusals across {len(households)} households")
    print(f"  solver queries: {fast_total} against {slow_total}")
    print(f"  saving: {saved:.0f}%")
    print(f"  worst case: {worst[1]}/{worst[2]} at {worst[3]} vs {worst[4]}")
    print()


# ----------------------------------------------------------------- E2

def e2_duality(engine, schemes, households):
    print(LINE)
    print("E2  Corrections are the hitting sets of the conflicts")
    print(LINE)

    checked = held = 0
    biggest = (0, 0, "")

    for hid, scheme, member_id, profile in refusals(engine, schemes, households):
        oracle = oracle_for(engine, scheme, profile)
        conflicts = all_muses(oracle)
        corrections = all_mcses(oracle)

        forward = canon(minimal_hitting_sets(conflicts)) == canon(corrections)
        backward = canon(minimal_hitting_sets(corrections)) == canon(conflicts)

        checked += 1
        held += int(forward and backward)
        if len(corrections) > biggest[1]:
            biggest = (len(conflicts), len(corrections), f"{hid}/{scheme.id}")

    print(f"  checked {checked} refusals, both directions")
    print(f"  duality held in {held} of {checked}")
    print(f"  largest instance: {biggest[2]} with {biggest[0]} conflicts "
          f"and {biggest[1]} corrections")
    print()


# ----------------------------------------------------------------- E3

def _valid(graph, have, held):
    for doc_id in have - set(held):
        for need in graph[doc_id].needs:
            if not any(o in have for o in need.options):
                return False
    return True


def _brute_force(graph, target, held):
    held = set(held)
    candidates = [d for d in graph.ids if d not in held]
    best_cost = None
    for size in range(1, len(candidates) + 1):
        for combo in combinations(candidates, size):
            have = held | set(combo)
            if target not in have or not _valid(graph, have, held):
                continue
            cost = sum(graph[d].effort for d in combo)
            if best_cost is None or cost < best_cost:
                best_cost = cost
    return best_cost


def e3_planner(documents):
    print(LINE)
    print("E3  Acquisition planner against exhaustive search")
    print(LINE)
    print(f"  {'document':<26}{'planner':>9}{'optimal':>9}{'match':>8}")

    matched = checked = 0
    targets = [d.id for d in documents if d.needs]

    for target in sorted(targets):
        found = acquire(documents, [target], held=set())
        if found is None:
            print(f"  {target:<26}{'no route':>9}")
            continue
        mine = sum(documents[d].effort for d in found)
        best = _brute_force(documents, target, held=set())
        ok = mine == best
        checked += 1
        matched += int(ok)
        print(f"  {target:<26}{mine:>9}{best:>9}{str(ok):>8}")

    print(LINE)
    print(f"  optimal on {matched} of {checked} targets")
    print()


# ----------------------------------------------------------------- E4

def e4_questions(engine, schema, schemes, households):
    print(LINE)
    print("E4  Adaptive questioning against asking everything")
    print(LINE)

    member_schemes = [s for s in schemes if s.scope is Scope.MEMBER]
    everything = {a for s in member_schemes for a in s.attributes_used}
    sensitive = {a for a in everything if schema[a].sensitive}

    print(f"  {len(everything)} attributes appear across {len(member_schemes)} "
          f"member schemes, {len(sensitive)} of them sensitive")
    print()
    print(f"  {'person':<18}{'asked':>7}{'of':>5}{'sensitive asked':>18}")

    asked_total = 0
    people = 0
    sensitive_asked_total = 0

    for household in households:
        for member in household.members:
            profile = project(household, schema, member.id)
            asked = interview(engine, schema, member_schemes, profile.facts)
            names = [q.attribute for q in asked]
            touched = [n for n in names if n in sensitive]

            print(f"  {household.id + '/' + member.id:<18}{len(names):>7}"
                  f"{len(everything):>5}{len(touched):>18}")
            asked_total += len(names)
            sensitive_asked_total += len(touched)
            people += 1

    print(LINE)
    mean = asked_total / people
    print(f"  mean {mean:.1f} questions instead of {len(everything)}, "
          f"a saving of {100 * (1 - mean / len(everything)):.0f}%")
    print(f"  sensitive questions asked: {sensitive_asked_total} across "
          f"{people} people")
    print()


# ----------------------------------------------------------------- E5

def _random_household(rng, schema, ident):
    facts = {}
    for attr in schema.scoped(Scope.HOUSEHOLD):
        if attr.name in _DERIVED:
            continue
        facts[attr.name] = _random_value(rng, attr)

    members = []
    for i in range(rng.randint(1, 5)):
        member_facts = {
            a.name: _random_value(rng, a) for a in schema.scoped(Scope.MEMBER)
        }
        # Keep the household internally plausible, otherwise every sample
        # trips an axiom and the experiment measures our generator instead.
        if member_facts["age"] < 18:
            member_facts["marital_status"] = "unmarried"
            member_facts["already_receiving_pension"] = False
        if member_facts["age"] < 14:
            member_facts["occupation"] = "student"
        if member_facts["age"] < 10:
            member_facts["has_bank_account"] = False
        if not member_facts["has_bank_account"]:
            member_facts["bank_aadhaar_linked"] = False
        if member_facts["gender"] != "female":
            member_facts["is_pregnant"] = False
        if member_facts["is_pregnant"] and not (12 <= member_facts["age"] <= 55):
            member_facts["is_pregnant"] = False
        members.append(Member(id=f"m{i}", facts=member_facts))

    return Household(id=ident, facts=facts, members=members, documents={"aadhaar"})


_DERIVED = {
    "household_size", "has_member_over_60", "has_girl_child",
    "has_disabled_member", "has_widowed_member", "adult_male_count",
    "has_adult_woman", "has_willing_worker", "someone_has_bank_account",
}


def _random_value(rng, attr):
    if attr.kind is Kind.BOOL:
        return rng.random() < 0.4
    if attr.kind is Kind.ENUM:
        return rng.choice(list(attr.options))
    low = attr.low if attr.low is not None else 0
    high = attr.high if attr.high is not None else 100
    if attr.name == "annual_income":
        high = 300_000
    if attr.name == "land_acres":
        high = 10
    if attr.name == "age":
        low, high = 1, 85
    return rng.randint(low, high)


def e5_population(engine, schema, schemes, n=120, seed=7):
    print(LINE)
    print(f"E5  Screening {n} generated households")
    print(LINE)

    rng = random.Random(seed)
    claims = contradictions = provisional = 0
    repairable = hopeless = redundant = 0
    nothing_at_all = 0

    for i in range(n):
        household = _random_household(rng, schema, f"r{i}")
        result = engine.screen(household, schemes)

        claims += len(result.eligible)
        contradictions += len(result.clashes)
        if not result.eligible:
            nothing_at_all += 1

        for claim in result.eligible:
            if claim.verdict.trust is Trust.PROVISIONAL:
                provisional += 1
        for claim in result.blocked:
            if claim.verdict.redundant:
                redundant += 1
            elif claim.verdict.hopeless:
                hopeless += 1
            elif claim.verdict.fixes:
                repairable += 1

    print(f"  mean claims found per household: {claims / n:.1f}")
    print(f"  households finding nothing at all: {nothing_at_all}")
    print(f"  claims flagged provisional: {provisional}")
    print(f"  refusals that are repairable:  {repairable}")
    print(f"  refusals nothing can change:   {hopeless}")
    print(f"  refusals that are redundant:   {redundant}")
    print(f"  households with contradictory answers: {contradictions}")
    print()
    print("  The generator keeps each household internally plausible, so the")
    print("  contradiction count reflects the axioms rather than random noise.")
    print()


# ----------------------------------------------------------------- E6

def e6_scaling(engine, schema):
    print(LINE)
    print("E6  Cost as the rulebook grows")
    print(LINE)
    print(f"  {'criteria':>9}{'divide+conquer':>17}{'deletion':>10}"
          f"{'d+c ms':>9}{'del ms':>9}")

    profile = Profile(id="synthetic", facts={"annual_income": 900_000})

    # All the criteria are slack except the last, so the single conflict sits
    # at the far end of the list. That is the shape the divide and conquer
    # search is for: a small reason buried in a large rulebook. A scheme where
    # everything conflicts would flatter it unfairly.
    for n in (5, 10, 20, 40, 80, 160):
        criteria = []
        for i in range(n - 1):
            ceiling = 2_000_000 + i
            criteria.append(
                Criterion(
                    id=f"S{i}",
                    text=f"income must not exceed {ceiling}",
                    formula=Cmp("le", Var("annual_income"), Lit(ceiling)),
                )
            )
        criteria.append(
            Criterion(
                id=f"S{n - 1}",
                text="income must not exceed 500000",
                formula=Cmp("le", Var("annual_income"), Lit(500_000)),
            )
        )
        criteria = tuple(criteria)
        scheme = Scheme(
            id=f"synth{n}", name="synthetic", authority="benchmark",
            scope=Scope.HOUSEHOLD, criteria=criteria,
            benefit="none", apply_at="nowhere",
        )

        fast = oracle_for(engine, scheme, profile)
        t0 = time.perf_counter()
        quickxplain(fast, fast.ids)
        fast_ms = (time.perf_counter() - t0) * 1000

        slow = oracle_for(engine, scheme, profile)
        t0 = time.perf_counter()
        deletion_mus(slow, slow.ids)
        slow_ms = (time.perf_counter() - t0) * 1000

        print(f"  {n:>9}{fast.stats.calls:>17}{slow.stats.calls:>10}"
              f"{fast_ms:>9.1f}{slow_ms:>9.1f}")
    print()


def _labelled():
    import yaml
    return yaml.safe_load(
        (Path(__file__).resolve().parent / "sentences.yaml").read_text(
            encoding="utf-8"))["sentences"]


def e7_understanding(schema):
    """Precision and recall of the reading layer, per language.

    Counted per fact rather than per sentence, and false positives are counted
    against sentences that carry no facts at all, because a question read as
    an answer is the failure that costs somebody a wasted trip.
    """
    from patra.nlp.extract import Extractor

    print(LINE)
    print("  E7  reading facts out of a sentence")
    print(LINE)

    extractor = Extractor(schema)
    cases = _labelled()
    per_lang = {}

    for case in cases:
        got = {m.attribute: m.value for m in extractor.understand(case["text"]).mentions}
        want = dict(case.get("expect") or {})
        unsure = dict(case.get("unsure") or {})
        refused = set(case.get("refused") or ())

        # A fact the sentence only hints at, and one the axioms will refuse,
        # both belong in the extractor's output; the guard decides their fate.
        allowed = {**want, **unsure}
        for name in refused:
            allowed.setdefault(name, got.get(name))

        row = per_lang.setdefault(case["lang"], [0, 0, 0, 0])
        for name, value in want.items():
            if got.get(name) == value:
                row[0] += 1           # found, right
            else:
                row[1] += 1           # wanted, missed
        for name, value in got.items():
            if name not in allowed:
                row[2] += 1           # invented
            elif allowed[name] != value and name in want:
                row[2] += 1           # found, wrong value
        row[3] += 1

    print(f"  {'lang':<6}{'sentences':>11}{'found':>8}{'missed':>8}"
          f"{'wrong':>8}{'recall':>9}{'precision':>11}")
    totals = [0, 0, 0, 0]
    for lang in ("en", "hi", "mr", "bn", "ta"):
        if lang not in per_lang:
            continue
        hit, miss, bad, n = per_lang[lang]
        for i, v in enumerate((hit, miss, bad, n)):
            totals[i] += v
        recall = hit / (hit + miss) if hit + miss else 1.0
        precision = hit / (hit + bad) if hit + bad else 1.0
        print(f"  {lang:<6}{n:>11}{hit:>8}{miss:>8}{bad:>8}"
              f"{recall:>8.0%}{precision:>11.0%}")

    hit, miss, bad, n = totals
    print(f"  {'all':<6}{n:>11}{hit:>8}{miss:>8}{bad:>8}"
          f"{hit/(hit+miss):>8.0%}{hit/(hit+bad):>11.0%}")

    empty = [c for c in cases if not c.get("expect") and not c.get("unsure")
             and not c.get("refused")]
    invented = sum(
        1 for c in empty if extractor.understand(c["text"]).mentions)
    print(f"\n  of {len(empty)} sentences carrying no facts, "
          f"{invented} produced one anyway")
    print("\n  Caveat: these sentences and the cue vocabulary were written by the")
    print("  same hand. This is coverage of phrasings we thought of, not")
    print("  generalisation, and field data should replace it.")
    print()


def e8_spoken_shortens_the_interview(engine, schema, schemes, households):
    """How many questions does describing your family in words save.

    Measured against the adaptive interview, not against asking everything, so
    whatever is saved is saved on top of a baseline that is already short. The
    baseline here counts household and member schemes together, which is why
    it is larger than E4's twelve.

    A fact the reader got wrong cannot show up as a saving: only readings that
    match the household's real answers are credited. That makes the number a
    joint measure of the reader and the interview, which is the honest way to
    report a feature that only exists as the two together.
    """
    from patra.guard import Guard, Source
    from patra.nlp.extract import Extractor

    print(LINE)
    print("  E8  saying it in a sentence, against answering questions")
    print(LINE)

    extractor = Extractor(schema)
    guard = Guard(engine, schema)

    # Written as somebody would actually answer "tell us about your family":
    # two or three sentences, mixed Hinglish, nothing the interview prompted.
    OPENERS = {
        "sunita": "meri maa 62 saal ki hain aur vo vidhwa hain. hum gaon mein "
                  "rehte hain, ghar kaccha hai, koi gaadi nahi hai. antyodaya "
                  "card hai. ghar mein koi sarkari naukri nahi hai",
        "ramlal": "main 45 saal ka kisan hoon, gaon mein rehta hoon. 3 ekad "
                  "zameen hai aur khud kheti karte hain. pakka ghar hai, "
                  "gaadi nahi hai. koi income tax nahi bharta",
        "munni": "main garbhvati hoon aur pehla bachcha hai. hum gaon mein "
                 "rehte hain, ghar kaccha hai. antyodaya card hai, koi "
                 "sarkari naukri nahi hai",
        "kishore": "main shahar mein rehta hoon, naukri hai. pakka ghar hai "
                   "aur gaadi bhi hai. income tax bharta hoon",
        "bhola": "main 52 saal ka hoon, gaon mein rehte hain. mera bank khata "
                 "nahi hai. ghar kaccha hai, gaadi nahi hai. kaam chahiye",
    }

    print(f"  {'household':<10}{'read':>6}{'right':>7}{'asked cold':>12}"
          f"{'asked after':>13}{'saved':>7}")

    saved_total = cold_total = 0
    for household in households:
        if household.id not in OPENERS:
            continue
        member = household.members[0].id if household.members else None
        full = project(household, schema, member).facts

        cold = len(interview(engine, schema, schemes, full))

        reading = extractor.understand(OPENERS[household.id])
        intake = guard.admit(reading.mentions, {}, Source.SPOKEN,
                             reading.disagreements)
        # Only readings that match the household's real answers are credited,
        # so a mis-read fact cannot show up as a saving.
        given = {k: v for k, v in intake.facts.items() if full.get(k) == v}

        asked = [q for q in interview(engine, schema, schemes, full)
                 if q.attribute not in given]
        saved = cold - len(asked)
        saved_total += saved
        cold_total += cold
        print(f"  {household.id:<10}{len(intake.facts):>6}{len(given):>7}"
              f"{cold:>12}{len(asked):>13}{saved:>7}")

    print(f"\n  {saved_total} of {cold_total} questions skipped, "
          f"{saved_total / cold_total:.0%}")
    print("  The saving is bounded by what the sentence actually covered: the")
    print("  interview was already asking only what it needed.")
    print()


def e9_guard(engine, schema):
    """What the boundary between the two halves actually refuses.

    Four kinds of bad reading, each put through on purpose. A guard nobody can
    see working is indistinguishable from no guard.
    """
    from patra.guard import Doubt, Guard, Refused, Source
    from patra.nlp.extract import Extractor

    print(LINE)
    print("  E9  the guard between understanding and deciding")
    print(LINE)

    extractor = Extractor(schema)
    guard = Guard(engine, schema)

    PROBES = [
        ("hedged estimate", "our income is around a lakh", {}),
        ("a hint, not a statement", "unka husband nahi hai", {}),
        ("impossible together", "she is 15 years old and a widow", {}),
        ("outside the schema", "my age is 480", {}),
        ("contradicts an answer", "I am 70 years old", {"age": 65}),
        ("two readings at once", "I am married and unmarried", {}),
        ("a number naming nothing", "house number 42", {}),
        ("plain and usable", "I am 62 years old, we live in a village", {}),
        ("asking, not telling", "mujhe pension chahiye", {}),
    ]

    print(f"  {'probe':<26}{'used':>6}{'read back':>11}{'refused':>9}  why")
    for label, text, known in PROBES:
        reading = extractor.understand(text)
        intake = guard.admit_understanding(reading, known)
        why = ""
        if intake.refused:
            why = intake.refused[0].reason.value
        elif intake.confirm:
            why = intake.confirm[0].doubt.value
        elif reading.numbers_unused and not intake.accepted:
            why = "no anchor"
        print(f"  {label:<26}{len(intake.accepted):>6}"
              f"{len(intake.confirm):>11}{len(intake.refused):>9}  {why}")

    cases = _labelled()
    proposed = used = asked = refused = 0
    for case in cases:
        reading = extractor.understand(case["text"])
        intake = guard.admit_understanding(reading, {})
        proposed += len(reading.mentions)
        used += len(intake.accepted)
        asked += len(intake.confirm)
        refused += len(intake.refused)
    print(f"\n  over the {len(cases)} labelled sentences: {proposed} readings "
          f"proposed, {used} used,")
    print(f"  {asked} read back for confirmation, {refused} refused outright")
    print()


def main():
    schema = load_schema(DATA / "attributes.yaml")
    schemes = load_schemes(DATA / "schemes", schema)
    documents = load_documents(DATA / "documents.yaml")
    axioms = load_axioms(DATA / "axioms.yaml", schema)
    households = load_households(DATA / "cases" / "households.yaml", schema)
    engine = Engine(schema, axioms, documents)

    print()
    print("=" * 72)
    print("  PATRA evaluation".center(72))
    print("=" * 72)
    print(f"  {len(schemes)} schemes, {len(documents)} documents, "
          f"{len(schema)} attributes, {len(axioms)} axioms")
    print()

    e1_conflict_search(engine, schemes, households)
    e2_duality(engine, schemes, households)
    e3_planner(documents)
    e4_questions(engine, schema, schemes, households)
    e5_population(engine, schema, schemes)
    e6_scaling(engine, schema)
    e7_understanding(schema)
    e8_spoken_shortens_the_interview(engine, schema, schemes, households)
    e9_guard(engine, schema)


if __name__ == "__main__":
    main()
