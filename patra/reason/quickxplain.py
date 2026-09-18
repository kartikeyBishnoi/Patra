"""Minimal conflict detection.

Two algorithms, both implemented here rather than imported, because the
comparison between them is part of what the project demonstrates:

* `deletion_mus` - the textbook linear scan. One oracle call per constraint.
* `quickxplain` - Junker's divide-and-conquer method, which reaches a minimal
  conflict in O(k log(n/k)) oracle calls for a conflict of size k among n
  constraints. When one rule out of forty is to blame, this is the difference
  between forty solver calls and roughly a dozen.

Both return a *minimal unsatisfiable subset* (MUS): a subset that is
unsatisfiable, and every proper subset of which is satisfiable. Minimality is
what makes the output an explanation rather than a data dump - nothing in a MUS
is redundant, so every element genuinely contributes to the refusal.

Reference: Junker, "QUICKXPLAIN: Preferred Explanations and Relaxations for
Over-Constrained Problems", AAAI 2004.
"""

from __future__ import annotations

from .oracle import Oracle


class NoConflict(Exception):
    """Raised when the constraint set is satisfiable, so no MUS exists."""


def deletion_mus(oracle: Oracle, constraints: list[str] | None = None) -> list[str]:
    """Baseline MUS extraction by linear deletion.

    Walk the constraints once, dropping any whose removal keeps the remainder
    unsatisfiable. What survives is minimal.
    """
    current = list(oracle.ids if constraints is None else constraints)
    if oracle.is_sat(current):
        raise NoConflict("constraint set is satisfiable")

    for c in list(current):
        candidate = [x for x in current if x != c]
        if not oracle.is_sat(candidate):
            current = candidate
    return current


def quickxplain(
    oracle: Oracle,
    constraints: list[str] | None = None,
    background: list[str] | None = None,
) -> list[str]:
    """Junker's QuickXPlain: a preferred minimal conflict.

    `constraints` is ordered by *decreasing* preference for retention, so the
    conflict returned prefers to blame constraints appearing later. We exploit
    this by ordering profile facts before rules, which biases explanations
    towards naming the rule that blocks the applicant rather than restating
    the applicant's own facts back at them.
    """
    c = list(oracle.ids if constraints is None else constraints)
    b = list(background or [])

    if oracle.is_sat(b + c):
        raise NoConflict("constraint set is satisfiable")
    if not c:
        return []
    return _qx(oracle, b, b, c)


def _qx(oracle: Oracle, b: list[str], delta: list[str], c: list[str]) -> list[str]:
    """Core recursion.

    `delta` is the set most recently added to `b`. If it was non-empty and `b`
    alone is already unsatisfiable, nothing from `c` is needed for the conflict
    and we can prune the entire branch - this is where the speedup comes from.
    """
    if delta and not oracle.is_sat(b):
        return []
    if len(c) == 1:
        return list(c)

    split = len(c) // 2
    c1, c2 = c[:split], c[split:]

    d1 = _qx(oracle, b + c1, c1, c2)
    d2 = _qx(oracle, b + d1, d1, c1)
    return d1 + d2


def is_minimal_conflict(oracle: Oracle, subset: list[str]) -> bool:
    """Verify the defining property of a MUS.

    Used by the test suite and by the evaluation harness: an algorithm that
    returns a fast wrong answer is worse than a slow right one, so we check
    minimality explicitly rather than trusting the implementation.
    """
    if oracle.is_sat(subset):
        return False
    return all(
        oracle.is_sat([x for x in subset if x != c]) for c in subset
    )
