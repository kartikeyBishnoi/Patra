"""Attribute declarations.

Two things distinguish this from a plain field list. Attributes carry a
*scope*, because some facts belong to a household (land, ration card) and some
to a person (age, widowhood), and a scheme needs to know which it is asking
about. And they carry a *mutability*, which is what lets us tell someone what
they can actually do about a refusal instead of just listing what went wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Scope(Enum):
    HOUSEHOLD = "household"
    MEMBER = "member"


class Mutability(Enum):
    """Whether any action changes this fact, and how hard that action is."""

    FIXED = "fixed"
    """Age, gender, caste, whether a spouse has died. Nothing changes these."""

    PAPERWORK = "paperwork"
    """Already true of the person, just not recorded. A certificate, a bank
    account, an Aadhaar seeding. These are the ones worth surfacing first
    because they are cheap and they block an enormous number of claims."""

    CIRCUMSTANCE = "circumstance"
    """Genuinely changeable but at real cost: occupation, where you live,
    whether you hold another benefit that excludes this one."""

    @property
    def actionable(self) -> bool:
        return self is not Mutability.FIXED


class Kind(Enum):
    INT = "int"
    BOOL = "bool"
    ENUM = "enum"


@dataclass(frozen=True)
class Attribute:
    name: str
    kind: Kind
    label: str
    scope: Scope
    mutability: Mutability
    question: str
    """How we ask about it. Written for someone reading it aloud."""

    effort: int = 1
    unit: str | None = None
    low: int | None = None
    high: int | None = None
    options: tuple[str, ...] = field(default_factory=tuple)
    sensitive: bool = False
    """Caste, religion, disability, income. We ask these last and skip them
    entirely when the answer is already settled."""

    asset: bool = False
    """Something the household has gained and would not sensibly give up.

    Several schemes are written as alternatives to each other: Jan Dhan is for
    people with no bank account, a priority ration card is for people without
    one. Dropping the fact does make the rules satisfiable, so it turns up as a
    valid correction set, but "close your bank account" is not advice. Marking
    the attribute as an asset tells the recourse layer to discard any repair
    that moves it backwards.

    For enums the declared option order is the ranking, worst first.
    """

    def is_downgrade(self, now, proposed) -> bool:
        """True if moving from `now` to `proposed` makes the household worse off."""
        if not self.asset:
            return False
        if self.kind is Kind.BOOL:
            return bool(now) and not bool(proposed)
        if self.kind is Kind.ENUM:
            return self.options.index(proposed) < self.options.index(now)
        return proposed < now

    def __post_init__(self):
        if self.kind is Kind.ENUM and not self.options:
            raise ValueError(f"{self.name}: enum with no options")
        if self.kind is not Kind.ENUM and self.options:
            raise ValueError(f"{self.name}: options on a non-enum")
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError(f"{self.name}: empty range")

    def check(self, value) -> None:
        if self.kind is Kind.BOOL:
            if not isinstance(value, bool):
                raise ValueError(f"{self.name}: expected yes/no, got {value!r}")
        elif self.kind is Kind.INT:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{self.name}: expected a number, got {value!r}")
            if self.low is not None and value < self.low:
                raise ValueError(f"{self.name}: {value} is below {self.low}")
            if self.high is not None and value > self.high:
                raise ValueError(f"{self.name}: {value} is above {self.high}")
        else:
            if value not in self.options:
                raise ValueError(
                    f"{self.name}: {value!r} not one of {list(self.options)}"
                )


class Schema:
    def __init__(self, attributes: list[Attribute]):
        self._by_name: dict[str, Attribute] = {}
        for a in attributes:
            if a.name in self._by_name:
                raise ValueError(f"duplicate attribute {a.name!r}")
            self._by_name[a.name] = a

    def __contains__(self, name) -> bool:
        return name in self._by_name

    def __getitem__(self, name: str) -> Attribute:
        try:
            return self._by_name[name]
        except KeyError:
            raise KeyError(f"no attribute called {name!r}") from None

    def __iter__(self):
        return iter(self._by_name.values())

    def __len__(self) -> int:
        return len(self._by_name)

    @property
    def names(self) -> list[str]:
        return list(self._by_name)

    def scoped(self, scope: Scope) -> list[Attribute]:
        return [a for a in self._by_name.values() if a.scope is scope]
