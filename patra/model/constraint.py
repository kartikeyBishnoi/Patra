"""Constraint AST for eligibility rules.

Rules are written declaratively in YAML and parsed into this tree. Keeping an
explicit AST (rather than emitting solver objects directly) buys us two things
the project depends on: rules can be pretty-printed back to the applicant in
their own words, and the same tree can be compiled to different back ends.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Union

Expr = Union["Var", "Lit"]


@dataclass(frozen=True)
class Var:
    """Reference to a declared attribute."""

    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Lit:
    """A literal integer, boolean, or enum-member value."""

    value: int | bool | str

    def __str__(self) -> str:
        return repr(self.value)


@dataclass(frozen=True)
class Cmp:
    """Arithmetic or equality comparison between two expressions."""

    op: str  # one of: le lt ge gt eq ne
    lhs: Expr
    rhs: Expr

    OPS = {"le": "≤", "lt": "<", "ge": "≥", "gt": ">", "eq": "=", "ne": "≠"}

    def __post_init__(self) -> None:
        if self.op not in self.OPS:
            raise ValueError(f"unknown comparison operator {self.op!r}")

    def __str__(self) -> str:
        return f"{self.lhs} {self.OPS[self.op]} {self.rhs}"


@dataclass(frozen=True)
class InSet:
    """Membership of an enum-valued attribute in a set of values."""

    var: Var
    values: tuple[str, ...]
    negated: bool = False

    def __str__(self) -> str:
        verb = "∉" if self.negated else "∈"
        return f"{self.var} {verb} {{{', '.join(self.values)}}}"


@dataclass(frozen=True)
class And:
    parts: tuple["Formula", ...]

    def __str__(self) -> str:
        return "(" + " ∧ ".join(str(p) for p in self.parts) + ")"


@dataclass(frozen=True)
class Or:
    parts: tuple["Formula", ...]

    def __str__(self) -> str:
        return "(" + " ∨ ".join(str(p) for p in self.parts) + ")"


@dataclass(frozen=True)
class Not:
    part: "Formula"

    def __str__(self) -> str:
        return f"¬{self.part}"


@dataclass(frozen=True)
class Implies:
    antecedent: "Formula"
    consequent: "Formula"

    def __str__(self) -> str:
        return f"({self.antecedent} → {self.consequent})"


@dataclass(frozen=True)
class IsTrue:
    """Assertion that a boolean attribute holds."""

    var: Var
    negated: bool = False

    def __str__(self) -> str:
        return f"¬{self.var}" if self.negated else str(self.var)


Formula = Union[Cmp, InSet, And, Or, Not, Implies, IsTrue]


def variables(formula: Formula) -> set[str]:
    """Every attribute name occurring in `formula`."""
    return {v.name for v in _walk_vars(formula)}


def _walk_vars(node: object) -> Iterator[Var]:
    if isinstance(node, Var):
        yield node
    elif isinstance(node, Lit):
        return
    elif isinstance(node, Cmp):
        yield from _walk_vars(node.lhs)
        yield from _walk_vars(node.rhs)
    elif isinstance(node, InSet):
        yield node.var
    elif isinstance(node, IsTrue):
        yield node.var
    elif isinstance(node, (And, Or)):
        for part in node.parts:
            yield from _walk_vars(part)
    elif isinstance(node, Not):
        yield from _walk_vars(node.part)
    elif isinstance(node, Implies):
        yield from _walk_vars(node.antecedent)
        yield from _walk_vars(node.consequent)
    else:  # pragma: no cover - guards against AST drift
        raise TypeError(f"not a formula node: {node!r}")
