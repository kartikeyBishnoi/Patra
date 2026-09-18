"""Turning results into something a family can act on.

Every line here is built from a solver result. Nothing in this module can
assert a fact the reasoning layer did not derive, which is the whole reason it
is templates and not generated prose.

There is a second reason. Because the sentences come from a fixed set, they can
be recorded once in each language and played back, so somebody who cannot read
still gets the same answer. Generated text would make that impossible.
"""

from __future__ import annotations

from ..engine import Claim, Screening, Trust, Verdict
from ..model.attributes import Kind, Mutability, Schema
from ..model.scheme import say
from ..reason.planner import Plan
from ..reason.unlock import Ladder

BAR = "-" * 68

HOW = {
    Mutability.PAPERWORK: "paperwork only",
    Mutability.CIRCUMSTANCE: "a real change",
    Mutability.FIXED: "cannot be changed",
}


def value(schema: Schema, name: str, raw) -> str:
    return say(schema[name], raw)


def money(rupees: int) -> str:
    return f"Rs {rupees:,}"


# ---------------------------------------------------------------- verdicts


def why_refused(schema: Schema, verdict: Verdict) -> list[str]:
    out = []
    for i, conflict in enumerate(verdict.conflicts, 1):
        if len(verdict.conflicts) > 1:
            out.append(f"  Reason {i}:")
        pad = "    " if len(verdict.conflicts) > 1 else "  "
        for rule in conflict.rules:
            out.append(f"{pad}The rule says: {rule.text}")
        for fact in conflict.facts:
            out.append(f"{pad}Your answer:   {fact.text}")
        out.append("")
    return out


def what_would_fix(schema: Schema, verdict: Verdict, limit: int = 2) -> list[str]:
    if verdict.redundant:
        return [
            "  You do not need this one. It is meant for families who do not",
            "  already have what it provides, and you have it.",
        ]

    if verdict.hopeless:
        out = ["  Nothing would fix this.", ""]
        for conflict in verdict.blocking:
            for rule in conflict.rules:
                out.append(f"    The rule says: {rule.text}")
            for fact in conflict.facts:
                out.append(f"    This cannot change: {fact.text}")
        out.append("")
        out.append("  We will not suggest something that cannot work.")
        return out

    if not verdict.fixes:
        return ["  We could not find a way to fix this."]

    out = []
    for i, fix in enumerate(verdict.fixes[:limit], 1):
        if len(verdict.fixes) > 1:
            out.append(f"  Option {i}:")
        pad = "    " if len(verdict.fixes) > 1 else "  "
        for change in fix.changes:
            now = value(schema, change.attribute, change.now)
            needed = value(schema, change.attribute, change.needed)
            out.append(
                f"{pad}{change.label}: {now} -> {needed}"
                f"   ({HOW[change.mutability]})"
            )
        out.append("")

    extra = len(verdict.fixes) - limit
    if extra > 0:
        out.append(f"  There are {extra} other ways, all of them harder.")
    return out


def trust_note(schema: Schema, verdict: Verdict) -> list[str]:
    if verdict.trust is Trust.UNRELIABLE:
        return [
            "  We are not confident about this one. Some of the answers",
            "  contradict each other, so please check them first.",
        ]
    if verdict.trust is not Trust.PROVISIONAL:
        return []

    out = ["  Please check this before you rely on it:"]
    for m in verdict.margins:
        now = value(schema, m.attribute, m.current)
        flips = value(schema, m.attribute, m.flips_at)
        out.append(f"    {m.label} is {now}. The answer changes at {flips}.")
    out.append("  If the real figure is on the other side of that, this is wrong.")
    return out


# ---------------------------------------------------------------- paperwork


def paperwork(ladder: Ladder, schemes_by_id=None) -> list[str]:
    plan = ladder.plan
    if not plan.steps:
        return ["  Nothing to collect. You have the papers you need."]

    schemes_by_id = schemes_by_id or {}

    out = [
        f"  {len(plan.steps)} things to collect, in this order.",
        f"  About {plan.trips} trips, {money(plan.fee)} in fees, "
        f"roughly {plan.days} days in all.",
        "",
    ]

    unlocks_at = {m.after_step: m for m in ladder.milestones}

    for i, step in enumerate(plan.steps, 1):
        doc = step.document
        out.append(f"  {i}. {doc.name}")
        out.append(f"     Go to: {doc.issuer}")
        detail = []
        if doc.fee:
            detail.append(money(doc.fee))
        if doc.days:
            detail.append(f"about {doc.days} days")
        detail.append(f"{doc.trips} trip" + ("s" if doc.trips > 1 else ""))
        out.append(f"     {', '.join(detail)}")
        if step.reason != "required by the scheme":
            out.append(f"     Why: {step.reason}")
        if doc.note:
            out.append(f"     Note: {' '.join(doc.note.split())}")

        hit = unlocks_at.get(i)
        if hit:
            names = [
                schemes_by_id[s].name if s in schemes_by_id else s
                for s in hit.unlocks
            ]
            out.append("     After this you can apply for:")
            for name in names:
                out.append(f"       - {name}")
        out.append("")

    return out


def first_errand(ladder: Ladder, schemes_by_id) -> list[str]:
    """The single most useful thing to do, for someone who can only do one."""
    win = ladder.first_win
    if win is None:
        return []
    names = [schemes_by_id[s].name for s in win.unlocks if s in schemes_by_id]
    out = [
        "  If you do only one thing:",
        f"    Get your {win.document_name.lower()}.",
    ]
    if names:
        out.append(f"    That alone opens up: {', '.join(names)}")
    return out


# ---------------------------------------------------------------- screening


def claim_line(claim: Claim) -> str:
    who = f" for {claim.member_id}" if claim.member_id else ""
    return f"  {claim.scheme.name}{who}"


def _closest(claim: Claim):
    """Rank one refusal against another for the same scheme.

    Lower is better: a repairable miss beats a redundant one, which beats
    something nothing can change.
    """
    verdict = claim.verdict
    if verdict.hopeless:
        return (3, 0)
    if verdict.redundant:
        return (2, 0)
    if verdict.fixes:
        return (0, verdict.fixes[0].effort)
    return (1, 0)


def best_per_scheme(claims: list[Claim]) -> list[Claim]:
    """Keep only the most promising claim for each scheme.

    A member-scoped scheme is judged once per person, so a household of five
    produces five refusals for the widow pension, four of them about people who
    were never going to qualify. Telling somebody their teenage son is not a
    widow is noise. We report the person who came closest and drop the rest.
    """
    best: dict[str, Claim] = {}
    for claim in claims:
        current = best.get(claim.scheme.id)
        if current is None or _closest(claim) < _closest(current):
            best[claim.scheme.id] = claim
    return list(best.values())


def screening(schema: Schema, result: Screening, schemes_by_id, detail: bool = True) -> str:
    out: list[str] = []
    household = result.household

    out.append(BAR)
    out.append(f"  Household: {household.id}")
    if household.note:
        out.append(f"  {' '.join(household.note.split())}")
    out.append(BAR)
    out.append("")

    if result.clashes:
        out.append("BEFORE ANYTHING ELSE")
        out.append("")
        out.append("  Some answers do not fit together. Please check these:")
        out.append("")
        for clash in result.clashes:
            for axiom in clash.axioms:
                out.append(f"    {axiom.text}")
            for fact in clash.facts:
                out.append(f"      you said: {fact.text}")
            out.append("")

    if result.eligible:
        out.append(f"YOU CAN CLAIM {len(result.eligible)} THINGS")
        out.append("")
        for claim in result.eligible:
            out.append(claim_line(claim))
            if detail:
                out.append(f"      {' '.join(claim.scheme.benefit.split())}")
                out.append(f"      Apply at: {claim.scheme.apply_at}")
            note = trust_note(schema, claim.verdict)
            out.extend("    " + n.strip() for n in note)
            out.append("")
    else:
        out.append("We could not find anything you can claim right now.")
        out.append("")

    if result.paperwork:
        out.append(BAR)
        out.append("  PAPERS YOU NEED")
        out.append(BAR)
        out.append("")
        out.extend(first_errand(result.paperwork, schemes_by_id))
        out.append("")
        out.extend(paperwork(result.paperwork, schemes_by_id))

    claimed = {c.scheme.id for c in result.eligible}
    near, far, spare = [], [], []
    for claim in best_per_scheme(result.blocked):
        if claim.scheme.id in claimed:
            continue  # somebody in the family already qualifies for this
        if claim.verdict.redundant:
            spare.append(claim)
        elif claim.verdict.hopeless:
            far.append(claim)
        else:
            near.append(claim)

    if near:
        out.append(BAR)
        out.append(f"  CLOSE, BUT NOT YET  ({len(near)})")
        out.append(BAR)
        out.append("")
        near.sort(key=lambda c: c.verdict.fixes[0].effort if c.verdict.fixes else 99)
        for claim in near:
            out.append(claim_line(claim).strip())
            out.extend(why_refused(schema, claim.verdict))
            out.extend(what_would_fix(schema, claim.verdict))
            out.append("")

    if spare:
        out.append(BAR)
        out.append(f"  YOU DO NOT NEED THESE  ({len(spare)})")
        out.append(BAR)
        out.append("")
        out.append("  Meant for families who lack something you already have.")
        out.append("")
        for claim in spare:
            out.append(claim_line(claim))
        out.append("")

    if far:
        out.append(BAR)
        out.append(f"  NOT AVAILABLE TO YOU  ({len(far)})")
        out.append(BAR)
        out.append("")
        far.sort(key=lambda c: c.scheme.name)
        for claim in far:
            reason = ""
            for conflict in claim.verdict.blocking:
                if conflict.rules:
                    reason = conflict.rules[0].text
                    break
            out.append(claim_line(claim))
            if reason:
                out.append(f"      {reason}")
        out.append("")

    return "\n".join(out)
