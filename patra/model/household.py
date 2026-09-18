"""Households and the people in them.

A single visit turns up several claims at once: a pension for the grandmother,
a scholarship for the daughter, a crop payment for whoever farms. So the unit
we reason about is the household, but most schemes are awarded to a person.

The bridge is projection. For a member-scoped scheme we build a flat profile of
household facts plus that member's facts, and hand it to the same engine that
would otherwise see a single applicant. Household-scoped schemes get the
household facts plus a few counts derived from the members, because rules like
"a household with no adult male member" cannot be answered from any one person.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .attributes import Schema, Scope

Value = int | bool | str


@dataclass
class Member:
    id: str
    facts: dict[str, Value] = field(default_factory=dict)
    name: str | None = None

    def check(self, schema: Schema) -> None:
        for key, value in self.facts.items():
            attr = schema[key]
            if attr.scope is not Scope.MEMBER:
                raise ValueError(
                    f"member {self.id!r} sets {key!r}, which is a household fact"
                )
            attr.check(value)


@dataclass
class Household:
    id: str
    facts: dict[str, Value] = field(default_factory=dict)
    members: list[Member] = field(default_factory=list)
    documents: set[str] = field(default_factory=set)
    """Documents the household already holds. Drives the acquisition planner."""

    note: str | None = None

    def check(self, schema: Schema) -> None:
        for key, value in self.facts.items():
            attr = schema[key]
            if attr.scope is not Scope.HOUSEHOLD:
                raise ValueError(
                    f"household {self.id!r} sets {key!r}, which is a member fact"
                )
            attr.check(value)
        seen = set()
        for m in self.members:
            if m.id in seen:
                raise ValueError(f"duplicate member id {m.id!r}")
            seen.add(m.id)
            m.check(schema)

    def member(self, member_id: str) -> Member:
        for m in self.members:
            if m.id == member_id:
                return m
        raise KeyError(f"no member {member_id!r} in household {self.id!r}")


@dataclass(frozen=True)
class Profile:
    """A flat set of facts, which is all the reasoning layer ever sees."""

    id: str
    facts: dict[str, Value]
    member_id: str | None = None
    source_text: str | None = None

    def check(self, schema: Schema) -> None:
        for key, value in self.facts.items():
            schema[key].check(value)


def project(household: Household, schema: Schema, member_id: str | None = None) -> Profile:
    """Flatten a household into the profile a scheme should be judged against.

    With a member id, the profile is that person plus their household. Without
    one, it is the household plus counts derived from its members.
    """
    facts: dict[str, Value] = dict(household.facts)
    facts.update(_derived(household, schema))

    if member_id is None:
        return Profile(id=household.id, facts=facts)

    # Member facts go on last so a person's own answer wins over any
    # household-level summary that happens to share a name.
    member = household.member(member_id)
    facts.update(member.facts)
    return Profile(
        id=f"{household.id}/{member_id}",
        facts=facts,
        member_id=member_id,
    )


# Household rules ask about composition, which no single member can answer.
# Only the counts actually used by our schemes are computed; adding one means
# declaring it in attributes.yaml with household scope.
def _derived(household: Household, schema: Schema) -> dict[str, Value]:
    out: dict[str, Value] = {}

    def put(name: str, value: Value) -> None:
        if name in schema:
            out[name] = value

    members = household.members
    put("household_size", len(members))

    ages = [m.facts.get("age") for m in members]
    ages = [a for a in ages if isinstance(a, int)]
    put("has_member_over_60", any(a >= 60 for a in ages))
    put("has_child_under_18", any(a < 18 for a in ages))

    put("has_girl_child", any(
        m.facts.get("gender") == "female" and isinstance(m.facts.get("age"), int)
        and m.facts["age"] < 18
        for m in members
    ))
    put("has_disabled_member", any(
        isinstance(m.facts.get("disability_percent"), int)
        and m.facts["disability_percent"] >= 40
        for m in members
    ))
    put("has_widowed_member", any(
        m.facts.get("marital_status") == "widowed" for m in members
    ))

    adult_males = sum(
        1 for m in members
        if m.facts.get("gender") == "male"
        and isinstance(m.facts.get("age"), int)
        and 18 <= m.facts["age"] < 60
    )
    put("adult_male_count", adult_males)

    # Ujjwala issues the connection in a woman's name, so a household with no
    # adult woman cannot apply however well everything else fits.
    put("has_adult_woman", any(
        m.facts.get("gender") == "female"
        and isinstance(m.facts.get("age"), int)
        and m.facts["age"] >= 18
        for m in members
    ))

    put("has_willing_worker", any(
        m.facts.get("willing_unskilled_work") is True
        and isinstance(m.facts.get("age"), int)
        and m.facts["age"] >= 18
        for m in members
    ))

    put("someone_has_bank_account", any(
        m.facts.get("has_bank_account") is True for m in members
    ))

    return out
