"""Enumerating *all* minimal conflicts and all minimal corrections.

One MUS answers "why was I refused?" with one reason. But an applicant blocked
by several independent problems needs all of them, and recourse needs the full
family of corrections to choose the cheapest. So we enumerate.

The algorithm is MARCO (Liffiton et al.): a *map* solver over the powerset
tracks which regions of the subset lattice remain unexplored. Each iteration
draws an unexplored seed and pushes it to a boundary of the satisfiability
frontier - shrinking an unsatisfiable seed to a MUS, or growing a satisfiable
one to a maximal satisfiable subset (MSS) whose complement is an MCS. The
region above a MUS and below an MSS is then blocked, so the lattice is
exhausted without repetition.

Both boundaries fall out of the same traversal, which is exactly what we need:
the MUSes are the explanations, and the MCSes are the repairs.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterator

import z3

from .oracle import Oracle
from .quickxplain import quickxplain


class Boundary(Enum):
    MUS = "mus"
    MCS = "mcs"


def marco(
    oracle: Oracle,
    constraints: list[str] | None = None,
    limit: int | None = None,
) -> Iterator[tuple[Boundary, list[str]]]:
    """Yield every MUS and MCS of `constraints`.

    `limit` caps the number of results, since the count of MUSes can be
    exponential in the number of constraints. Real scholarship rulebooks stay
    small enough that exhaustion is normal, but the guard keeps the interactive
    demo responsive on adversarial inputs.
    """
    items = list(oracle.ids if constraints is None else constraints)
    index = {c: i for i, c in enumerate(items)}
    x = [z3.Bool(f"__map_{i}") for i in range(len(items))]

    map_solver = z3.Solver()
    found = 0

    while map_solver.check() == z3.sat:
        model = map_solver.model()
        seed = [c for c in items if not z3.is_false(model.eval(x[index[c]], True))]

        if oracle.is_sat(seed):
            mss = _grow(oracle, seed, items)
            in_mss = set(mss)
            mcs = [c for c in items if c not in in_mss]
            # Block downward: any future seed must add something outside this MSS.
            map_solver.add(z3.Or([x[index[c]] for c in mcs]))
            yield Boundary.MCS, mcs
        else:
            mus = quickxplain(oracle, seed)
            # Block upward: any future seed must drop something from this MUS.
            map_solver.add(z3.Or([z3.Not(x[index[c]]) for c in mus]))
            yield Boundary.MUS, mus

        found += 1
        if limit is not None and found >= limit:
            return


def _grow(oracle: Oracle, seed: list[str], items: list[str]) -> list[str]:
    """Extend a satisfiable seed to a maximal satisfiable subset."""
    current = list(seed)
    in_current = set(current)
    for c in items:
        if c in in_current:
            continue
        if oracle.is_sat(current + [c]):
            current.append(c)
            in_current.add(c)
    return current


def all_muses(
    oracle: Oracle, constraints: list[str] | None = None, limit: int | None = None
) -> list[list[str]]:
    return [s for kind, s in marco(oracle, constraints, limit) if kind is Boundary.MUS]


def all_mcses(
    oracle: Oracle, constraints: list[str] | None = None, limit: int | None = None
) -> list[list[str]]:
    return [s for kind, s in marco(oracle, constraints, limit) if kind is Boundary.MCS]
