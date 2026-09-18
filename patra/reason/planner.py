"""Working out how to get the papers you are missing.

Given what a household already holds and what a scheme demands, produce an
ordered list of offices to visit. Prerequisites first, nothing listed twice,
and every requirement satisfied by the cheapest acceptable alternative.

This is AND-OR search. A document needs *all* of its requirements, and each
requirement accepts *any one* of several documents, so the search alternates
between conjunction and disjunction as it descends.

One wrinkle makes exact optimisation hard. Routes share prerequisites: Aadhaar
satisfies the identity requirement for almost everything, so once you are
getting it for one document it is free for the next. Choosing each requirement
independently therefore overcounts, and choosing them jointly to exploit
sharing is set cover, which is NP-hard. We resolve each requirement against
what the partial solution has already committed to, which captures sharing
along a branch. `tests/test_planner.py` checks this against exhaustive search
on the real graph, where it currently agrees everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model.document import Document, DocumentGraph


@dataclass(frozen=True)
class Step:
    document: Document
    reason: str

    @property
    def id(self) -> str:
        return self.document.id


@dataclass(frozen=True)
class Plan:
    """An ordered route to a set of documents."""

    targets: tuple[str, ...]
    steps: tuple[Step, ...]
    already_held: tuple[str, ...] = ()

    @property
    def trips(self) -> int:
        return sum(s.document.trips for s in self.steps)

    @property
    def fee(self) -> int:
        return sum(s.document.fee for s in self.steps)

    @property
    def days(self) -> int:
        # Offices run in sequence, not in parallel, because each one wants the
        # output of the last.
        return sum(s.document.days for s in self.steps)

    @property
    def effort(self) -> int:
        return sum(s.document.effort for s in self.steps)

    @property
    def complete(self) -> bool:
        return bool(self.steps) or not self.targets


class Unreachable(Exception):
    """No route exists, usually because a requirement loops back on itself."""


def acquire(graph: DocumentGraph, targets, held) -> frozenset[str] | None:
    """The cheapest set of documents to obtain, or None if there is no route."""
    held = frozenset(held)
    selected: frozenset[str] = frozenset()

    # Targets are resolved in sequence against a growing commitment, so a
    # prerequisite bought for the first target is not bought again for the
    # second.
    for target in targets:
        found = _resolve(graph, target, held, selected, frozenset())
        if found is None:
            return None
        selected |= found
    return selected


def _resolve(
    graph: DocumentGraph,
    doc_id: str,
    held: frozenset[str],
    selected: frozenset[str],
    visiting: frozenset[str],
) -> frozenset[str] | None:
    if doc_id in held or doc_id in selected:
        return frozenset()
    if doc_id in visiting:
        return None  # requirement cycle; this branch cannot terminate

    doc = graph[doc_id]
    acquired = {doc_id}
    descend = visiting | {doc_id}

    for need in doc.needs:
        best: frozenset[str] | None = None
        best_cost: int | None = None

        for option in need.options:
            sub = _resolve(
                graph, option, held, selected | frozenset(acquired), descend
            )
            if sub is None:
                continue
            cost = sum(graph[d].effort for d in sub)
            if best_cost is None or cost < best_cost:
                best, best_cost = sub, cost

        if best is None:
            return None  # no acceptable alternative is reachable
        acquired |= best

    return frozenset(acquired)


def order(graph: DocumentGraph, documents, held) -> list[str]:
    """Sort an acquisition set so nothing is attempted before its inputs exist.

    Raises Unreachable if the set is not self-supporting, which would mean the
    caller assembled it by hand rather than through `acquire`.
    """
    held = set(held)
    remaining = set(documents)
    out: list[str] = []

    while remaining:
        ready = [
            d for d in sorted(remaining)
            if all(
                any(o in held or o in out for o in need.options)
                for need in graph[d].needs
            )
        ]
        if not ready:
            raise Unreachable(
                f"cannot order {sorted(remaining)}: every remaining document "
                "still waits on another"
            )
        # Cheapest first among those available, so the shortest errands happen
        # early and someone who gives up partway still gains something.
        ready.sort(key=lambda d: graph[d].effort)
        pick = ready[0]
        out.append(pick)
        remaining.discard(pick)

    return out


def plan(graph: DocumentGraph, targets, held) -> Plan:
    """Full route to `targets`, ordered, with the reason for each stop."""
    targets = tuple(targets)
    held = frozenset(held)

    have = tuple(sorted(t for t in targets if t in held))
    needed = acquire(graph, targets, held)
    if needed is None:
        raise Unreachable(f"no route to {sorted(set(targets) - held)}")

    sequence = order(graph, needed, held)
    wanted = set(targets)

    steps = []
    for doc_id in sequence:
        doc = graph[doc_id]
        if doc_id in wanted:
            reason = "required by the scheme"
        else:
            reason = _why(graph, doc_id, sequence, wanted)
        steps.append(Step(document=doc, reason=reason))

    return Plan(targets=targets, steps=tuple(steps), already_held=have)


def _why(graph: DocumentGraph, doc_id: str, sequence: list[str], wanted: set[str]) -> str:
    """Name what a prerequisite is for, so the errand does not feel arbitrary."""
    for other in sequence:
        if other == doc_id:
            continue
        for need in graph[other].needs:
            if doc_id in need.options:
                return f"needed as {need.purpose} for {graph[other].name}"
    for target in sorted(wanted):
        if target in graph:
            for need in graph[target].needs:
                if doc_id in need.options:
                    return f"needed as {need.purpose} for {graph[target].name}"
    return "needed along the way"
