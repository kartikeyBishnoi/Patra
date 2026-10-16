"""Collecting papers as a state-space search, done four ways.

The acquisition planner already finds a cheapest route, and it finds it by
recursive resolution over the AND-OR graph. That is the right algorithm for
that structure and it hides something worth seeing: the same problem is an
ordinary state-space search, and laying it out that way makes the difference
between search strategies visible rather than theoretical.

    state        the set of papers held
    start        what the household already has
    goal         every target held
    action       obtain one paper whose own requirements are already met
    cost         that paper's effort, trips weighted heaviest

Four strategies over exactly that space:

    breadth first   fewest papers, which is not the same as least effort and
                    is the clearest way to show why cost-aware search exists
    depth first     whatever it stumbles into, kept for the contrast
    uniform cost    optimal, and expands a great deal to prove it
    A*              optimal with a heuristic, and expands far less

The heuristic is the sum of the efforts of the targets not yet held. It is
admissible because every one of those papers must be obtained eventually and
each costs at least its own effort, so the estimate can never exceed the true
remaining cost. It is consistent for the same reason: obtaining one paper
lowers the estimate by exactly that paper's effort and the step costs exactly
that much.

Consistency is what lets A* close a state the first time it is reached, and
the tests check the optimum found here against the planner's, because a
heuristic that is subtly wrong produces a fast answer rather than an error.
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field

from ..model.document import DocumentGraph


@dataclass
class Stats:
    expanded: int = 0
    generated: int = 0
    frontier_peak: int = 0

    def saw(self, frontier_size: int) -> None:
        if frontier_size > self.frontier_peak:
            self.frontier_peak = frontier_size


@dataclass
class Route:
    order: tuple[str, ...] = ()
    cost: int = 0
    found: bool = False
    stats: Stats = field(default_factory=Stats)

    @property
    def held(self) -> frozenset[str]:
        return frozenset(self.order)


def ready(graph: DocumentGraph, state: frozenset[str]) -> list[str]:
    """Papers obtainable right now: every requirement already satisfied.

    A requirement is a disjunction, so one of its options is enough. That is
    the AND-OR shape, flattened into an ordinary successor function.
    """
    out = []
    for doc in graph:
        if doc.id in state:
            continue
        if all(any(option in state for option in need.options)
               for need in doc.needs):
            out.append(doc.id)
    return sorted(out)


def _done(state, targets) -> bool:
    return targets <= state


def _heuristic(graph, state, targets) -> int:
    """Sum of the efforts of the targets not yet held.

    Admissible: each of them must still be obtained, and each costs at least
    its own effort. Consistent: taking one step lowers this by exactly the
    step's cost when the step is a target, and by nothing when it is not.
    """
    return sum(graph[t].effort for t in targets if t not in state)


def breadth_first(graph: DocumentGraph, targets, held=()) -> Route:
    """Fewest papers, which is not the same as least effort."""
    start = frozenset(held)
    targets = frozenset(targets)
    if _done(start, targets):
        return Route(found=True)

    stats = Stats()
    queue = deque([(start, ())])
    seen = {start}
    while queue:
        stats.saw(len(queue))
        state, order = queue.popleft()
        stats.expanded += 1
        for doc_id in ready(graph, state):
            step = state | {doc_id}
            stats.generated += 1
            if _done(step, targets):
                stats.saw(len(queue))
                return Route(order=order + (doc_id,),
                             cost=sum(graph[d].effort for d in order + (doc_id,)),
                             found=True, stats=stats)
            if step not in seen:
                seen.add(step)
                queue.append((step, order + (doc_id,)))
    return Route(stats=stats)


def depth_first(graph: DocumentGraph, targets, held=(), limit=24) -> Route:
    """Kept for the contrast. It finds a route, rarely a good one."""
    start = frozenset(held)
    targets = frozenset(targets)
    stats = Stats()
    stack = [(start, ())]
    seen = set()
    while stack:
        stats.saw(len(stack))
        state, order = stack.pop()
        if _done(state, targets):
            return Route(order=order,
                         cost=sum(graph[d].effort for d in order),
                         found=True, stats=stats)
        if state in seen or len(order) >= limit:
            continue
        seen.add(state)
        stats.expanded += 1
        for doc_id in reversed(ready(graph, state)):
            stats.generated += 1
            stack.append((state | {doc_id}, order + (doc_id,)))
    return Route(stats=stats)


def _best_first(graph, targets, held, use_heuristic) -> Route:
    start = frozenset(held)
    targets = frozenset(targets)
    stats = Stats()

    h0 = _heuristic(graph, start, targets) if use_heuristic else 0
    frontier = [(h0, 0, start, ())]
    best = {start: 0}
    closed = set()
    tie = 0

    while frontier:
        stats.saw(len(frontier))
        _, spent, state, order = heapq.heappop(frontier)
        if state in closed:
            continue
        if _done(state, targets):
            return Route(order=order, cost=spent, found=True, stats=stats)
        closed.add(state)
        stats.expanded += 1

        for doc_id in ready(graph, state):
            step = state | {doc_id}
            cost = spent + graph[doc_id].effort
            stats.generated += 1
            if cost < best.get(step, 1 << 30):
                best[step] = cost
                tie += 1
                guess = _heuristic(graph, step, targets) if use_heuristic else 0
                heapq.heappush(frontier,
                               (cost + guess, cost, step, order + (doc_id,)))
    return Route(stats=stats)


def uniform_cost(graph: DocumentGraph, targets, held=()) -> Route:
    """Optimal, and expands a great deal to prove it."""
    return _best_first(graph, targets, held, use_heuristic=False)


def a_star(graph: DocumentGraph, targets, held=()) -> Route:
    """Optimal too, and expands far less for the same answer."""
    return _best_first(graph, targets, held, use_heuristic=True)


STRATEGIES = {
    "breadth": breadth_first,
    "depth": depth_first,
    "uniform": uniform_cost,
    "astar": a_star,
}
