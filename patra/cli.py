"""Command line interface.

    python3 -m patra.cli screen --household sunita
    python3 -m patra.cli ask
    python3 -m patra.cli plan --household munni
    python3 -m patra.cli documents
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
from .engine import Engine
from .explain.render import BAR, paperwork, screening, trust_note, what_would_fix, why_refused
from .model.attributes import Kind, Scope
from .model.household import Profile
from .reason.planner import plan as make_plan
from .reason.questions import Status, next_question, status

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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
