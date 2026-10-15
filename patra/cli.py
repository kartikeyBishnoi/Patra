"""Command line interface.

    python3 -m patra.cli screen --household sunita
    python3 -m patra.cli ask
    python3 -m patra.cli plan --household munni
    python3 -m patra.cli documents
    python3 -m patra.cli read "meri maa 62 saal ki hain"
    python3 -m patra.cli whatif --household sunita --set annual_income=300000
    python3 -m patra.cli next --household sunita
    python3 -m patra.cli paper --household sunita --image card.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .encode.loader import (
    load_axioms,
    load_documents,
    load_households,
    load_schema,
    load_schemes,
)
from .advise import Move, next_actions
from .engine import Engine
from .explain.render import BAR, paperwork, screening, trust_note, what_would_fix, why_refused
from .guard import Guard
from .model.attributes import Kind, Scope
from .model.household import Profile, project
from .nlp.extract import Extractor
from .reason.planner import plan as make_plan
from .reason.questions import Status, next_question, status
from .reason.simulate import simulate
from .vision.ocr import capability, scan
from .vision.papers import Papers

DATA = Path(__file__).resolve().parent.parent / "data"


class Bundle:
    def __init__(self, data_dir: Path):
        self.schema = load_schema(data_dir / "attributes.yaml")
        self.schemes = load_schemes(data_dir / "schemes", self.schema)
        self.documents = load_documents(data_dir / "documents.yaml")
        self.axioms = load_axioms(data_dir / "axioms.yaml", self.schema)
        self.households = load_households(
            data_dir / "cases" / "households.yaml", self.schema
        )
        self.engine = Engine(self.schema, self.axioms, self.documents)

    @property
    def by_id(self):
        return {s.id: s for s in self.schemes}

    def household(self, ident: str):
        for h in self.households:
            if h.id == ident:
                return h
        known = ", ".join(h.id for h in self.households)
        raise SystemExit(f"no household called {ident!r}. try: {known}")


def cmd_screen(args) -> int:
    bundle = Bundle(args.data)
    household = bundle.household(args.household)
    result = bundle.engine.screen(household, bundle.schemes)
    print(screening(bundle.schema, result, bundle.by_id, detail=not args.brief))
    return 0


def cmd_plan(args) -> int:
    bundle = Bundle(args.data)
    household = bundle.household(args.household)
    result = bundle.engine.screen(household, bundle.schemes)

    if result.paperwork is None or not result.paperwork.plan.steps:
        print("Nothing to collect.")
        return 0

    print(BAR)
    print(f"  Papers for {household.id}")
    print(BAR)
    print()
    print("\n".join(paperwork(result.paperwork, bundle.by_id)))
    return 0


def cmd_documents(args) -> int:
    bundle = Bundle(args.data)
    graph = bundle.documents

    print(f"{len(graph)} documents\n")
    for doc in sorted(graph, key=lambda d: d.id):
        print(f"{doc.name}")
        print(f"  from: {doc.issuer}")
        if doc.needs:
            for need in doc.needs:
                print(f"  needs {need.purpose}: any of {', '.join(need.options)}")
        else:
            print("  needs nothing first")
        print()
    return 0


def cmd_ask(args) -> int:
    """Walk somebody through only the questions their answer depends on."""
    bundle = Bundle(args.data)
    engine, schema = bundle.engine, bundle.schema

    # One person answering for themselves, so member schemes are the ones in
    # play. Household-only schemes need the whole family and are handled by
    # `screen`.
    schemes = [s for s in bundle.schemes if s.scope is Scope.MEMBER]

    print(BAR)
    print("  A few questions. We stop as soon as we know the answer.")
    print(BAR)
    print()

    known = Profile(id="you", facts={})
    asked = 0

    while True:
        question = next_question(engine, schema, schemes, known)
        if question is None:
            break

        attr = schema[question.attribute]
        answer = _prompt(attr, question.text)
        if answer is None:
            print("  (skipped)\n")
            # Drop every scheme that needed it, otherwise we ask forever.
            schemes = [
                s for s in schemes
                if question.attribute not in s.attributes_used
            ]
            continue

        asked += 1
        known = Profile(id="you", facts={**known.facts, question.attribute: answer})

        clashes = engine.inconsistencies(known)
        if clashes:
            print()
            print("  That does not fit with something you said earlier:")
            for clash in clashes:
                for axiom in clash.axioms:
                    print(f"    {axiom.text}")
                for fact in clash.facts:
                    print(f"      you said: {fact.text}")
            print("  Please start again and check those two answers.")
            return 2
        print()

    total = len({a for s in schemes for a in s.attributes_used})
    print(BAR)
    print(f"  Asked {asked} questions. Everything else we did not need.")
    if total:
        print(f"  Asking about every rule would have taken {total}.")
    print(BAR)
    print()

    good = [s for s in schemes if status(engine, s, known) is Status.ELIGIBLE]
    if good:
        print(f"You can claim {len(good)}:\n")
        for scheme in good:
            print(f"  {scheme.name}")
            print(f"    {' '.join(scheme.benefit.split())}")
            print(f"    Apply at: {scheme.apply_at}")
            verdict = engine.adjudicate(scheme, known)
            for line in trust_note(schema, verdict):
                print(f"  {line}")
            print()
    else:
        print("Nothing came through on these answers alone.\n")

    blocked = [s for s in schemes if status(engine, s, known) is Status.FIXABLE]
    if blocked and args.show_refused:
        print(BAR)
        print("  Refused, and why")
        print(BAR)
        print()
        for scheme in blocked:
            verdict = engine.adjudicate(scheme, known)
            print(f"  {scheme.name}")
            print("\n".join(why_refused(schema, verdict)))
            print("\n".join(what_would_fix(schema, verdict, limit=1)))
            print()
    return 0


# ---- the perception and simulation commands ----


def _facts_of(bundle, ident: str, member: str | None):
    """One household flattened the way the reasoner sees it.

    Member scope matters: an age and a marital status belong to a person, and
    screening a household without naming one leaves every member-scoped
    scheme undecidable.
    """
    household = bundle.household(ident)
    if member is None and household.members:
        member = household.members[0].id
    profile = project(household, bundle.schema, member)
    return household, profile


def cmd_read(args) -> int:
    """Read a sentence, and show every check it had to pass."""
    bundle = Bundle(args.data)
    extractor = Extractor(bundle.schema)
    guard = Guard(bundle.engine, bundle.schema)

    known = {}
    if args.household:
        _, profile = _facts_of(bundle, args.household, args.member)
        known = profile.facts

    reading = extractor.understand(args.text)
    intake = guard.admit_understanding(reading, known)

    print(BAR)
    print(f"  {args.text}")
    print(BAR)
    if reading.relation:
        print(f"\n  about: {reading.relation}   from \"{reading.relation_evidence}\"")

    if intake.accepted:
        print("\n  used")
        for a in intake.accepted:
            where = f"inferred from {a.inferred_from}" if a.inferred_from \
                else f'from "{a.evidence}"'
            print(f"    {bundle.schema[a.attribute].label:34} {str(a.value):12} {where}")

    if intake.confirm:
        print("\n  would have to be confirmed")
        for q in intake.confirm:
            extra = f" (or {q.alternative}?)" if q.alternative is not None else ""
            print(f"    {bundle.schema[q.attribute].label:34} {str(q.value):12} "
                  f"{q.doubt.value}{extra}")

    if intake.refused:
        print("\n  refused")
        for r in intake.refused:
            print(f"    {bundle.schema[r.attribute].label:34} {str(r.value):12} "
                  f"{r.axiom or r.detail}")

    if reading.numbers_unused:
        print("\n  numbers with nothing to attach them to: "
              + ", ".join(n.text for n in reading.numbers_unused))
    if not (intake.accepted or intake.confirm or intake.refused):
        print("\n  nothing in that sentence named a fact.")
    return 0


def cmd_whatif(args) -> int:
    """Re-decide every scheme against one changed answer."""
    bundle = Bundle(args.data)
    _, profile = _facts_of(bundle, args.household, args.member)

    changes = {}
    for pair in args.set:
        if "=" not in pair:
            raise SystemExit(f"--set wants name=value, got {pair!r}")
        name, _, raw = pair.partition("=")
        if name not in bundle.schema:
            raise SystemExit(f"no attribute called {name!r}")
        changes[name] = _coerce(bundle.schema[name], raw)

    result = simulate(bundle.engine, bundle.schema, bundle.schemes,
                      profile.facts, changes)

    print(BAR)
    for shift in result.shifts:
        print(f"  {bundle.schema[shift.attribute].label}: "
              f"{shift.was} -> {shift.now}")
    print(BAR)

    if result.rejected:
        for shift, detail in result.rejected:
            print(f"\n  cannot: {detail}")
        return 1
    if result.impossible:
        for shift, axiom in result.impossible:
            print(f"\n  impossible: {axiom}")
        return 1

    names = bundle.by_id
    print(f"\n  eligible now {len(result.before)}, after the change {len(result.after)}")
    for scheme_id in result.gained:
        print(f"    + {names[scheme_id].name}")
    for loss in result.lost:
        why = loss.blocked_by[0].text if loss.blocked_by else ""
        print(f"    - {names[loss.scheme_id].name}"
              + (f"   ({why})" if why else ""))
    if not result.gained and not result.lost:
        print("    nothing changes either way")
    if result.undecided:
        print(f"\n  {len(result.undecided)} could not be judged either way")
    return 0


def cmd_next(args) -> int:
    """The ranked errands, with every unlock count re-derived."""
    bundle = Bundle(args.data)
    household, profile = _facts_of(bundle, args.household, args.member)

    advice = next_actions(bundle.engine, bundle.schema, bundle.schemes,
                          profile.facts, bundle.documents, household.documents,
                          limit=args.limit)
    names = bundle.by_id

    print(BAR)
    print(f"  claimable now: {len(advice.eligible)}"
          f"   within reach: {len(advice.reachable)}"
          f"   out of reach: {len(advice.hopeless)}")
    print(BAR)

    for i, action in enumerate(advice.actions, 1):
        if action.move is Move.FACT:
            attr = bundle.schema[action.attribute]
            head = f"{attr.label}: {action.now} -> {action.needed}"
        else:
            head = action.errand.name
        print(f"\n  {i}. {head}")
        if action.errand:
            e = action.errand
            cost = "free" if not e.fee else f"Rs {e.fee}"
            print(f"     {e.issuer}   {cost}, {e.days} days, "
                  f"{e.trips} trip{'s' if e.trips > 1 else ''}")
        if action.unlocks:
            print("     opens up: "
                  + ", ".join(names[s].name for s in action.unlocks))
        if action.toward:
            print("     needed for: "
                  + ", ".join(names[s].name for s in action.toward))
        if action.loses:
            print("     would lose: "
                  + ", ".join(names[s].name for s in action.loses))
    if not advice.actions:
        print("\n  nothing left that would change the answer")
    if advice.hopeless:
        print("\n  nothing will help with: "
              + ", ".join(names[s].name for s in advice.hopeless))
    return 0


def cmd_paper(args) -> int:
    """Read a photographed document, and show what reached the solver."""
    bundle = Bundle(args.data)
    cap = capability()
    if not cap.available:
        raise SystemExit(cap.note or "no text reader on this machine")
    if cap.missing:
        print(f"  note: {cap.note}\n")

    got = scan(args.image.read_bytes(), args.lang, cap)
    if not got.ok:
        raise SystemExit(got.error or "could not read that picture")

    reading = Papers(bundle.schema).interpret(got)
    guard = Guard(bundle.engine, bundle.schema)

    known = {}
    if args.household:
        _, profile = _facts_of(bundle, args.household, args.member)
        known = profile.facts
    intake = guard.admit_document(reading, known)

    print(BAR)
    print(f"  {args.image.name}")
    print(BAR)
    for guess in reading.guesses[:3]:
        mark = "*" if guess is reading.guesses[0] else " "
        print(f"  {mark} {guess.document:24} score {guess.score}   "
              f'matched "{guess.matched[0]}"')
    if not reading.guesses:
        print("  no document recognised")
    print(f"\n  confident: {reading.sure}")

    for x in reading.redacted:
        print(f"  redacted: {x.field}, {x.shape}, used to recognise the card "
              f"and then discarded")
    if intake.confirm:
        print("\n  read off it, every field to be confirmed before use")
        for q in intake.confirm:
            print(f"    {bundle.schema[q.attribute].label:30} {str(q.value):12} "
                  f'from "{q.evidence}"')
    for r in intake.refused:
        print(f"    refused: {bundle.schema[r.attribute].label} "
              f"{r.value}   {r.axiom or r.detail}")
    if reading.unreadable:
        print("\n  could not read: " + ", ".join(reading.unreadable))
    return 0


def _coerce(attr, raw: str):
    if attr.kind is Kind.BOOL:
        if raw.lower() in ("yes", "true", "y", "1"):
            return True
        if raw.lower() in ("no", "false", "n", "0"):
            return False
        raise SystemExit(f"{attr.name} wants yes or no, got {raw!r}")
    if attr.kind is Kind.INT:
        try:
            return int(raw)
        except ValueError:
            raise SystemExit(f"{attr.name} wants a number, got {raw!r}") from None
    if raw not in attr.options:
        raise SystemExit(f"{attr.name} wants one of {list(attr.options)}")
    return raw


def _prompt(attr, text: str):
    """Ask one question. Returns None if the person would rather not say."""
    print(f"  {text}")

    if attr.kind is Kind.BOOL:
        print("    1) yes    2) no    (enter to skip)")
        raw = input("  > ").strip()
        if raw in ("1", "y", "yes"):
            return True
        if raw in ("2", "n", "no"):
            return False
        return None

    if attr.kind is Kind.ENUM:
        for i, option in enumerate(attr.options, 1):
            print(f"    {i}) {option.replace('_', ' ')}")
        raw = input("  > ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(attr.options):
            return attr.options[int(raw) - 1]
        return None

    hint = ""
    if attr.low is not None and attr.high is not None:
        hint = f" ({attr.low} to {attr.high})"
    raw = input(f"  >{hint} ").strip().replace(",", "")
    if not raw.isdigit():
        return None
    number = int(raw)
    try:
        attr.check(number)
    except ValueError as exc:
        print(f"    {exc}")
        return None
    return number


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="patra",
        description="Find out what your family can claim, and what stands in the way.",
    )
    parser.add_argument("--data", type=Path, default=DATA)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("screen", help="everything one household can claim")
    p.add_argument("--household", required=True)
    p.add_argument("--brief", action="store_true")
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("plan", help="the papers to collect, in order")
    p.add_argument("--household", required=True)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("ask", help="answer a few questions yourself")
    p.add_argument("--show-refused", action="store_true")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("documents", help="what each document needs first")
    p.set_defaults(func=cmd_documents)

    p = sub.add_parser("read", help="read facts out of a sentence")
    p.add_argument("text")
    p.add_argument("--household", help="check against this household's answers")
    p.add_argument("--member")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("whatif", help="re-decide everything against a changed answer")
    p.add_argument("--household", required=True)
    p.add_argument("--member")
    p.add_argument("--set", action="append", required=True, metavar="NAME=VALUE")
    p.set_defaults(func=cmd_whatif)

    p = sub.add_parser("next", help="the ranked errands, cheapest useful one first")
    p.add_argument("--household", required=True)
    p.add_argument("--member")
    p.add_argument("--limit", type=int, default=6)
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("paper", help="read a photographed document")
    p.add_argument("--image", type=Path, required=True)
    p.add_argument("--lang", default="en")
    p.add_argument("--household")
    p.add_argument("--member")
    p.set_defaults(func=cmd_paper)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
