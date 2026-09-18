"""Schemes, criteria, axioms, and the labelled constraints the solver sees.

Everything handed to the reasoner is labelled with where it came from and how
to say it in plain language. That is what lets a conflict point at a numbered
clause in a real notification and at the specific answer it contradicts,
instead of at an anonymous solver term.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .attributes import Schema, Scope
from .constraint import Cmp, Formula, IsTrue, Lit, Var, variables
from .household import Profile, Value


class Origin(Enum):
    RULE = "rule"
    FACT = "fact"
    AXIOM = "axiom"


@dataclass(frozen=True)
class Labelled:
    id: str
    origin: Origin
    formula: Formula
    text: str
    attribute: str | None = None

    def __str__(self) -> str:
        return f"[{self.id}] {self.text}"


@dataclass(frozen=True)
class Criterion:
    id: str
    text: str
    formula: Formula
    clause: str | None = None
    """Where this came from in the source notification, when we could find it."""


@dataclass(frozen=True)
class Axiom:
    """Something that cannot be true of any real person.

    Used to catch misread questions, not to decide eligibility.
    """

    id: str
    text: str
    formula: Formula


@dataclass(frozen=True)
class Scheme:
    id: str
    name: str
    authority: str
    scope: Scope
    criteria: tuple[Criterion, ...]
    benefit: str
    apply_at: str
    documents: tuple[str, ...] = ()
    source_url: str | None = None
    note: str | None = None

    def __post_init__(self):
        seen = set()
        for c in self.criteria:
            if c.id in seen:
                raise ValueError(f"{self.id}: duplicate criterion {c.id!r}")
            seen.add(c.id)

    @property
    def attributes_used(self) -> set[str]:
        used: set[str] = set()
        for c in self.criteria:
            used |= variables(c.formula)
        return used

    def check(self, schema: Schema) -> None:
        for name in sorted(self.attributes_used):
            if name not in schema:
                raise ValueError(f"{self.id}: unknown attribute {name!r}")
            attr = schema[name]
            # A member-scoped scheme may read household facts, since a person
            # is judged in the context of their household. The reverse is not
            # true: a household rule cannot reach into one unnamed member.
            if self.scope is Scope.HOUSEHOLD and attr.scope is Scope.MEMBER:
                raise ValueError(
                    f"{self.id} is household-scoped but reads member fact {name!r}. "
                    "Derive a household-level count instead."
                )

    def as_labelled(self) -> list[Labelled]:
        return [
            Labelled(c.id, Origin.RULE, c.formula, c.text)
            for c in self.criteria
        ]


def facts_as_labelled(profile: Profile, schema: Schema) -> list[Labelled]:
    """One labelled constraint per answer.

    Splitting them apart is what lets a conflict blame a single answer and a
    repair drop a single answer, rather than the whole person.
    """
    out = []
    for name in sorted(profile.facts):
        value = profile.facts[name]
        attr = schema[name]
        formula: Formula
        if isinstance(value, bool):
            formula = IsTrue(Var(name), negated=not value)
        else:
            formula = Cmp("eq", Var(name), Lit(value))
        out.append(
            Labelled(
                id=f"F_{name}",
                origin=Origin.FACT,
                formula=formula,
                text=f"{attr.label}: {say(attr, value)}",
                attribute=name,
            )
        )
    return out


def say(attr, value: Value) -> str:
    """Render a value the way we would read it out loud."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        text = f"{value:,}"
        return f"{text} {attr.unit}" if attr.unit else text
    return str(value).replace("_", " ")
