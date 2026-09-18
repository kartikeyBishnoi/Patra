"""Minimal hitting sets, and the duality that ties refusal to repair.

A hitting set of a collection of sets is a set meeting every member. The
classical result (Reiter 1987, corrected by Greiner et al.) is that the minimal
correction sets of an unsatisfiable constraint system are exactly the minimal
hitting sets of its minimal unsatisfiable subsets, and symmetrically.

That duality is the mathematical centre of this project. Read one way it says:
to repair every conflict you must break each one, and breaking each one is
enough. Read the other way it means a single traversal of the subset lattice
answers both "why not?" and "what would fix it?" - we do not need separate
machinery for explanation and for recourse.

Minimum-cost hitting set is NP-hard (it is set cover in disguise), so the
weighted routine here delegates to Z3's optimiser. Instances arising from a
single scholarship application involve on the order of ten facts, where exact
optimisation is instantaneous.
"""

from __future__ import annotations

from itertools import combinations

import z3


def is_hitting_set(candidate, collection: list[list[str]]) -> bool:
    c = set(candidate)
    return all(c & set(s) for s in collection)


def minimal_hitting_sets(collection: list[list[str]]) -> list[list[str]]:
    """Every irreducible hitting set of `collection`, smallest first.

    Enumerates by increasing size over the union of the input sets, keeping a
    candidate only when no proper subset already hits everything. Exponential
    in the worst case and deliberately unclever: it exists to verify the
    duality theorem empirically against MARCO's output, not to be fast.
    """
    if not collection:
        return [[]]
    if any(not s for s in collection):
        return []  # an empty set cannot be hit

    universe = sorted({c for s in collection for c in s})
    results: list[list[str]] = []

    for size in range(1, len(universe) + 1):
        for combo in combinations(universe, size):
            if not is_hitting_set(combo, collection):
                continue
            if any(set(prev) <= set(combo) for prev in results):
                continue  # a smaller hitting set is already contained here
            results.append(list(combo))
    return results


def min_cost_hitting_set(
    collection: list[list[str]], cost: dict[str, int]
) -> list[str] | None:
    """A hitting set of minimum total cost, or None if none exists.

    Costs come from attribute mutability: correcting a mis-recorded income
    certificate is cheap, changing the course you are enrolled in is not. The
    cheapest hitting set is therefore the least burdensome repair.
    """
    if not collection:
        return []
    if any(not s for s in collection):
        return None

    universe = sorted({c for s in collection for c in s})
    take = {c: z3.Bool(f"__hs_{c}") for c in universe}

    opt = z3.Optimize()
    for s in collection:
        opt.add(z3.Or([take[c] for c in s]))
    opt.minimize(
        z3.Sum([z3.If(take[c], cost.get(c, 1), 0) for c in universe])
    )

    if opt.check() != z3.sat:
        return None
    model = opt.model()
    return [c for c in universe if z3.is_true(model.eval(take[c], True))]
