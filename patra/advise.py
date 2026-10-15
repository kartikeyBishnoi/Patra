"""What to do next, in the order that pays off soonest.

A household refused six schemes for six different reasons does not want six
explanations. They want to know which single thing to do first, because they
may only manage one thing, and the answer is not obvious: the cheapest errand
and the most valuable errand are rarely the same one.

So every candidate action is costed and then *re-decided*. The correction sets
say which facts could matter; they do not say how much each one is worth,
because a fact appearing in four conflicts may unlock nothing on its own if
each of those schemes is also blocked by something else. The only trustworthy
count is the one you get by assuming the change and asking the solver again,
which is what happens here. "Unlocks three schemes" is a re-derived claim, not
a tally of appearances.

Actions come in two kinds and they are costed in the same currency. Changing a
fact costs the effort the schema assigns it. Obtaining a paper costs its fees,
its days and its trips, and a trip is weighted heavily because it is a lost
day of wages. Where a fact has a paper that records it, the two are reported
as one errand with the office attached.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .model.attributes import Mutability, Schema
from .model.household import Profile
from .reason.planner import Unreachable, plan
from .reason.simulate import eligible_now, simulate
from .reason.unlock import ladder


class Move(Enum):
    FACT = "fact"
    """Put something on record, or change a circumstance."""

    PAPER = "paper"
    """Obtain a document that schemes already won require."""


@dataclass(frozen=True)
class Errand:
    """Where to go for this, and what it costs to get there."""

    document: str
    name: str
    issuer: str
    fee: int = 0
    days: int = 0
    trips: int = 1

    @property
    def effort(self) -> int:
        # The same weighting the acquisition planner uses, so the two kinds of
        # action can be ranked against each other at all.
        return self.trips * 10 + self.days + self.fee // 50


@dataclass(frozen=True)
class Action:
    move: Move
    key: str
    attribute: str | None = None
    now: object | None = None
    needed: object | None = None
    errand: Errand | None = None
    unlocks: tuple[str, ...] = ()
    """Schemes that become claimable, verified by re-running the solver."""

    loses: tuple[str, ...] = ()
    """Schemes that stop being claimable. Rare, and never hidden."""

    toward: tuple[str, ...] = ()
    """Schemes this is a prerequisite for without finishing on its own.

    A scheme needing four papers only becomes claimable at the fourth, so the
    first three unlock nothing and are still unavoidable. Reporting them as
    unlocking nothing reads as pointless; naming what they are for does not.
    """

    paperwork_only: bool = False
    """True when nothing about the household changes, only the record of it."""

    effort: int = 1

    @property
    def worth(self) -> float:
        return len(self.unlocks) / max(self.effort, 1)


@dataclass(frozen=True)
class Advice:
    eligible: tuple[str, ...]
    actions: tuple[Action, ...]
    reachable: tuple[str, ...]
    """Schemes not claimable now that at least one action would make so.

    Deliberately excludes what is already claimable. An action's `unlocks`
    carries two meanings, both correct: for a changed fact it is a scheme that
    becomes eligible, and for a paper it is a scheme the household already
    qualifies for and can now actually apply to. Counting the second kind as
    "within reach" would promise doors that are already open.
    """

    hopeless: tuple[str, ...] = ()
    """Refused on something no action changes. Named, and left alone."""

    undecided: tuple[str, ...] = ()
    """Facts missing, so there is nothing to advise about yet."""


def next_actions(
    engine,
    schema: Schema,
    schemes,
    facts: dict,
    documents=None,
    held=(),
    limit: int = 6,
) -> Advice:
    profile = Profile(id="advise", facts=dict(facts))
    held = set(held)

    won, blocked, undecided = [], [], []
    for scheme in schemes:
        if not scheme.attributes_used <= set(facts):
            undecided.append(scheme.id)
        elif eligible_now(engine, scheme, profile):
            won.append(scheme)
        else:
            blocked.append(scheme)

    candidates, hopeless = _candidates(engine, blocked, profile)

    actions = []
    for (name, needed) in candidates:
        result = simulate(engine, schema, schemes, facts, {name: needed})
        if not result.ran or not result.gained:
            continue
        attr = schema[name]
        errand = _errand(documents, attr.document)
        actions.append(Action(
            move=Move.FACT,
            key=f"{name}={needed}",
            attribute=name,
            now=facts.get(name),
            needed=needed,
            errand=errand,
            unlocks=result.gained,
            loses=tuple(l.scheme_id for l in result.lost),
            paperwork_only=attr.mutability is Mutability.PAPERWORK,
            effort=errand.effort if errand else attr.effort,
        ))

    actions += _paper_actions(documents, won, held)
    actions = _merge_errands(actions)

    # Most doors opened first; among equals the cheaper errand, and among
    # those the one that changes nothing about the household but the record.
    actions.sort(key=lambda a: (-len(a.unlocks), -len(a.toward),
                                a.effort, not a.paperwork_only, a.key))

    claimable = {s.id for s in won}
    reachable = []
    for action in actions:
        for scheme_id in action.unlocks:
            if scheme_id not in reachable and scheme_id not in claimable:
                reachable.append(scheme_id)

    return Advice(
        eligible=tuple(s.id for s in won),
        actions=tuple(actions[:limit]),
        reachable=tuple(reachable),
        hopeless=tuple(sorted(hopeless)),
        undecided=tuple(sorted(undecided)),
    )


def _merge_errands(actions):
    """One trip to the bank, not two.

    Putting an account on record and obtaining the passbook a scheme asks for
    are the same visit to the same counter, and they arrive here as two
    actions because one came from a correction set and the other from the
    document plan. Sending somebody twice would be a bug visible from the
    street.
    """
    merged: dict[str, Action] = {}
    out = []
    for action in actions:
        door = action.errand.document if action.errand else None
        if door is None:
            out.append(action)
            continue
        if door not in merged:
            merged[door] = action
            out.append(action)
            continue
        kept = merged[door]
        combined = kept.unlocks + tuple(
            s for s in action.unlocks if s not in kept.unlocks)
        toward = kept.toward + tuple(
            s for s in action.toward if s not in kept.toward)
        # The fact framing carries the attribute and the threshold, so it wins
        # the description; the paper framing only ever carries the errand.
        base = kept if kept.move is Move.FACT else action
        fresh = Action(
            move=base.move, key=base.key, attribute=base.attribute,
            now=base.now, needed=base.needed, errand=base.errand or kept.errand,
            unlocks=combined, loses=kept.loses or action.loses,
            toward=tuple(s for s in toward if s not in combined),
            paperwork_only=kept.paperwork_only and action.paperwork_only,
            effort=min(kept.effort, action.effort),
        )
        merged[door] = fresh
        out[out.index(kept)] = fresh
    return out


def _candidates(engine, blocked, profile):
    """Every single change any correction set says could matter.

    Taken one at a time on purpose. A correction set of two says neither half
    alone rescues *that* scheme, but either half may rescue a different one,
    and the simulation that follows is what finds out.
    """
    seen = {}
    hopeless = []
    for scheme in blocked:
        fixes, no_hope, _, redundant = engine.repairs(scheme, profile)
        if no_hope:
            hopeless.append(scheme.id)
            continue
        if redundant:
            continue
        for fix in fixes:
            for change in fix.changes:
                seen.setdefault((change.attribute, change.needed), None)
    return list(seen), hopeless


def _errand(documents, document_id):
    if documents is None or not document_id or document_id not in documents:
        return None
    doc = documents[document_id]
    return Errand(document=doc.id, name=doc.name, issuer=doc.issuer,
                  fee=doc.fee, days=doc.days, trips=doc.trips)


def _paper_actions(documents, won, held):
    """Papers the schemes already won still need, in the planner's own order.

    These unlock nothing new in the eligibility sense, because the household
    already qualifies. They are what stands between qualifying and being paid,
    which is the gap this whole project exists for, so they are ranked beside
    the rest rather than listed separately.
    """
    if documents is None or not won:
        return []

    route = ladder(documents, list(won), held)
    unlocks = {m.after_step: m for m in route.milestones}
    wanted = {s.id: set(s.documents) for s in won}

    out = []
    for i, step in enumerate(route.plan.steps, 1):
        doc = step.document
        hit = unlocks.get(i)
        errand = Errand(document=doc.id, name=doc.name, issuer=doc.issuer,
                        fee=doc.fee, days=doc.days, trips=doc.trips)
        finished = hit.unlocks if hit else ()
        out.append(Action(
            move=Move.PAPER,
            key=doc.id,
            errand=errand,
            unlocks=finished,
            toward=tuple(sorted(
                sid for sid, docs in wanted.items()
                if doc.id in docs and sid not in finished)),
            paperwork_only=True,
            effort=errand.effort,
        ))
    return out


def route_to(documents, document_id, held=()):
    """The ordered errands behind one paper, for "how do I get this"."""
    try:
        return plan(documents, [document_id], set(held))
    except Unreachable:
        return None
