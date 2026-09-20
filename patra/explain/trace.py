"""Showing the working.

The reasoning was always there, but the app only ever showed its conclusion, so
from the outside it looked like a lookup table. This turns one decision into a
readable derivation: which clauses were checked, which the answers collided
with, how the smallest reason was isolated, and how the repair was found.

It has two audiences. An applicant who wants to know why should be able to
follow it. And anybody asking whether this is really reasoning or just a filter
can read the query counts and the named algorithm at each step.

Nothing here re-derives anything. Every line reports what the solver already
did, so the trace cannot drift from the decision it describes.
"""

from __future__ import annotations

from ..engine import Engine, Verdict
from ..model.document import DocumentGraph
from ..model.scheme import Scheme
from ..reason.marco import all_mcses, all_muses
from ..reason.oracle import Oracle
from ..reason.planner import Unreachable, acquire, plan
from ..reason.quickxplain import deletion_mus, quickxplain
from ..model.scheme import facts_as_labelled
from .phrase import criterion as say_criterion


def decision_trace(engine: Engine, scheme: Scheme, profile, words=None) -> dict:
    """A step by step account of how one eligibility decision was reached."""
    words = words or {}

    def w(key, default, **vars):
        """A trace line in the reader's language, English if untranslated."""
        text = words.get("trace", {}).get(key) or default
        for k, v in vars.items():
            text = text.replace("{" + k + "}", str(v))
        return text

    def criterion_text(c):
        return say_criterion(engine.schema, words, scheme.id, c)

    def label(name):
        return words.get("attr", {}).get(name, {}).get("label") \
            or engine.schema[name].label

    def value(name, raw):
        """Render the way the rest of the app does, not as a Python repr."""
        attr = engine.schema[name]
        if isinstance(raw, bool):
            return words.get("ui", {}).get("yes" if raw else "no",
                                           "yes" if raw else "no")
        if attr.kind.value == "enum":
            return words.get("attr", {}).get(name, {}).get("options", {}).get(
                raw, str(raw).replace("_", " "))
        unit = words.get("attr", {}).get(name, {}).get("unit") or attr.unit
        text = f"{raw:,}" if isinstance(raw, int) else str(raw)
        return f"{text} {unit}" if unit else text

    soft = scheme.as_labelled() + facts_as_labelled(profile, engine.schema)
    oracle = Oracle(engine.encoder, soft)
    satisfiable = oracle.is_sat(oracle.ids)

    steps = [{
        "stage": "encode",
        "method": w("encode", "constraint encoding"),
        "headline": w("encode_head", "{rules} rules and {facts} answers turned into constraints",
                      rules=len(scheme.criteria), facts=len(profile.facts)),
        "detail": [
            f"{c.id}: {criterion_text(c)}" for c in scheme.criteria
        ],
    }]

    steps.append({
        "stage": "solve",
        "method": w("solve", "satisfiability"),
        "headline": w("solve_yes", "All of it together holds") if satisfiable
                    else w("solve_no", "All of it together cannot hold"),
        "detail": [w("solve_yes_d", "You qualify.") if satisfiable else
                   w("solve_no_d", "Something the rules demand and something you "
                     "told us cannot both be true.")],
        "queries": oracle.stats.calls,
    })

    if satisfiable:
        return {"scheme": scheme.id, "eligible": True, "steps": steps}

    # Smallest reason, and what the naive method would have cost.
    fast = Oracle(engine.encoder, soft)
    core = quickxplain(fast, fast.ids)
    slow = Oracle(engine.encoder, soft)
    deletion_mus(slow, slow.ids)

    def readable(lab):
        """A labelled constraint in the reader's language.

        `str(Labelled)` carries the English text it was built from, which is
        fine in a log and wrong on screen.
        """
        if lab.origin.value == "rule":
            match = next((c for c in scheme.criteria if c.id == lab.id), None)
            return criterion_text(match) if match else lab.text
        name = lab.attribute
        if name and name in profile.facts:
            return f"{label(name)}: {value(name, profile.facts[name])}"
        return lab.text

    named = [readable(fast.label(c)) for c in core]
    steps.append({
        "stage": "shrink",
        "method": w("shrink", "QuickXPlain (Junker 2004)"),
        "headline": w("shrink_head", "Narrowed to {n} that already clash", n=len(core)),
        "detail": named,
        "queries": fast.stats.calls,
        "compare": {
            "label": w("compare", "one at a time would have taken"),
            "queries": slow.stats.calls,
        },
    })

    everything = Oracle(engine.encoder, soft)
    conflicts = all_muses(everything)
    corrections = all_mcses(everything)
    steps.append({
        "stage": "enumerate",
        "method": w("enumerate", "MARCO lattice traversal"),
        "headline": w("enumerate_head", "{r} separate reasons, {c} ways to repair",
                      r=len(conflicts), c=len(corrections)),
        "detail": [w("enumerate_d", "Every repair has to break every reason, and "
                     "breaking each one is enough. That is why one search answers "
                     "both questions.")],
        "queries": everything.stats.calls,
    })

    repairs, hopeless, blocking, redundant = engine.repairs(scheme, profile)
    if hopeless:
        detail = []
        for conflict in blocking:
            detail += [readable(r) for r in conflict.rules]
            detail += [readable(f) for f in conflict.facts]
        steps.append({
            "stage": "repair",
            "method": w("repair", "correction sets over changeable facts"),
            "headline": w("repair_none", "Nothing could be changed to fix this"),
            "detail": detail or [w("repair_none_d", "This rests on facts that cannot change.")],
        })
    elif redundant:
        steps.append({
            "stage": "repair",
            "method": w("repair", "correction sets over changeable facts"),
            "headline": w("repair_redundant", "Every repair meant giving something up"),
            "detail": [w("repair_redundant_d", "This scheme is for people who lack "
                         "something you already have, so it was set aside rather "
                         "than refused.")],
        })
    elif repairs:
        best = repairs[0]
        steps.append({
            "stage": "repair",
            "method": w("repair_best", "cheapest correction set"),
            "headline": w("repair_best_head", "{n} possible repairs, cheapest shown", n=len(repairs)),
            "detail": [
                f"{label(c.attribute)}: {value(c.attribute, c.now)} "
                f"{w('to', 'to')} {value(c.attribute, c.needed)}"
                for c in best.changes
            ],
        })

    return {"scheme": scheme.id, "eligible": False, "steps": steps}


def paperwork_trace(documents: DocumentGraph, targets, held, words=None) -> dict:
    """How the document route was searched.

    Requirements are conjunctions of disjunctions, so the search alternates
    between "all of these" and "any one of these" as it descends. Spelling that
    out is the difference between a checklist and a plan.
    """
    words = words or {}

    def w(key, default, **vars):
        text = words.get("trace", {}).get(key) or default
        for k, v in vars.items():
            text = text.replace("{" + k + "}", str(v))
        return text

    def name(doc_id):
        return words.get("doc", {}).get(doc_id, {}).get("name") \
            or documents[doc_id].name

    targets = [t for t in targets if t in documents]
    steps = [{
        "stage": "goal",
        "method": w("goal", "AND-OR graph"),
        "headline": w("goal_head", "{want} papers wanted, {have} already held",
                      want=len(targets), have=len(set(held) & set(documents.ids))),
        "detail": [name(t) for t in targets],
    }]

    needed = acquire(documents, targets, held)
    if needed is None:
        steps.append({
            "stage": "search",
            "method": "AND-OR search",
            "headline": "No route exists",
            "detail": ["A requirement loops back on itself."],
        })
        return {"steps": steps}

    branches = []
    for doc_id in sorted(needed):
        doc = documents[doc_id]
        for need in doc.needs:
            chosen = [o for o in need.options if o in needed or o in held]
            if len(need.options) > 1 and chosen:
                branches.append(
                    f"{name(doc_id)} needs {need.purpose}: "
                    f"{len(need.options)} would do, picked {name(chosen[0])}"
                )

    steps.append({
        "stage": "search",
        "method": w("search", "minimum-cost AND-OR search"),
        "headline": w("search_head", "{n} papers to collect", n=len(needed)),
        "detail": branches[:6] or ["No choices to make; each requirement had one option."],
    })

    try:
        route = plan(documents, targets, held)
    except Unreachable:
        return {"steps": steps}

    steps.append({
        "stage": "order",
        "method": w("order", "topological ordering"),
        "headline": w("order_head", "Ordered so nothing is attempted before its inputs exist"),
        "detail": [f"{i}. {name(s.id)}" for i, s in enumerate(route.steps, 1)],
    })
    return {"steps": steps}
