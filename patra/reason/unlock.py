"""Which paper to go and get first.

A household short of documents for six schemes does not want six checklists.
They want to know which single errand opens the most doors, because they may
only manage one.

So instead of reporting a flat list we walk the acquisition plan and record
what becomes reachable after each stop. Somebody who gives up after two offices
still leaves with something.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model.document import DocumentGraph
from ..model.scheme import Scheme
from .planner import Plan, Unreachable, plan


@dataclass(frozen=True)
class Milestone:
    """A point in the plan where one or more schemes become claimable."""

    after_step: int
    document_id: str
    document_name: str
    unlocks: tuple[str, ...]
    running_trips: int


@dataclass(frozen=True)
class Ladder:
    plan: Plan
    milestones: tuple[Milestone, ...]
    ready_now: tuple[str, ...]
    """Schemes whose documents the household already holds."""

    unreachable: tuple[str, ...] = ()

    @property
    def first_win(self) -> Milestone | None:
        return self.milestones[0] if self.milestones else None


def documents_missing(scheme: Scheme, held) -> set[str]:
    return set(scheme.documents) - set(held)


def ladder(graph: DocumentGraph, schemes: list[Scheme], held) -> Ladder:
    """Order the paperwork so the earliest stops pay off soonest."""
    held = set(held)

    ready_now = tuple(
        s.id for s in schemes if not documents_missing(s, held)
    )
    pending = [s for s in schemes if documents_missing(s, held)]

    wanted: list[str] = []
    unreachable: list[str] = []
    for s in pending:
        for d in s.documents:
            if d in held or d in wanted:
                continue
            if d not in graph:
                unreachable.append(s.id)
                break
            wanted.append(d)

    if not wanted:
        return Ladder(
            plan=Plan(targets=(), steps=()),
            milestones=(),
            ready_now=ready_now,
            unreachable=tuple(sorted(set(unreachable))),
        )

    try:
        route = plan(graph, wanted, held)
    except Unreachable:
        return Ladder(
            plan=Plan(targets=tuple(wanted), steps=()),
            milestones=(),
            ready_now=ready_now,
            unreachable=tuple(sorted({s.id for s in pending})),
        )

    milestones = []
    have = set(held)
    trips = 0
    outstanding = {s.id: set(s.documents) for s in pending}

    for i, step in enumerate(route.steps, 1):
        have.add(step.id)
        trips += step.document.trips

        finished = tuple(sorted(
            sid for sid, docs in outstanding.items() if docs <= have
        ))
        if finished:
            for sid in finished:
                outstanding.pop(sid)
            milestones.append(
                Milestone(
                    after_step=i,
                    document_id=step.id,
                    document_name=step.document.name,
                    unlocks=finished,
                    running_trips=trips,
                )
            )

    return Ladder(
        plan=route,
        milestones=tuple(milestones),
        ready_now=ready_now,
        unreachable=tuple(sorted(set(unreachable))),
    )
