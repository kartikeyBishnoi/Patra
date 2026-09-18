"""Deciding what to ask next, and when to stop.

Asking a household for their caste when the answer is already settled is not
merely inefficient, it is intrusive. So we ask only what the remaining schemes
actually depend on, stop the moment nothing is left undecided, and push the
sensitive questions to the back of the queue where they are often never
reached.

A scheme is settled as soon as the answers so far rule it out, which usually
happens long before every question is asked. That asymmetry is what makes the
approach worth having: ruling something out takes one fact, confirming it takes
all of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..model.attributes import Schema
from ..model.household import Profile
from ..model.scheme import Scheme


class Status(Enum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    """Ruled out by something no action can change."""

    FIXABLE = "fixable"
    """Ruled out, but only by facts the household could change.

    Kept separate from INELIGIBLE because these are the ones worth pursuing.
    A widow refused her pension over an unlinked bank account needs to hear
    about it, and we cannot tell her without asking the rest of the questions,
    so the interview carries on rather than dropping the scheme.
    """

    OPEN = "open"
    """Still undecided: nothing so far rules it out, but facts are missing."""

    @property
    def still_worth_asking(self) -> bool:
        return self in (Status.OPEN, Status.FIXABLE)


@dataclass(frozen=True)
class Question:
    attribute: str
    text: str
    sensitive: bool
    schemes_waiting: tuple[str, ...]

    @property
    def weight(self) -> int:
        return len(self.schemes_waiting)


def status(engine, scheme: Scheme, known: Profile) -> Status:
    """Where a scheme stands given only the answers collected so far.

    Eligible needs every attribute the scheme reads, since an unknown answer
    could still rule it out. A refusal splits by whether anything could be done
    about it, which decides whether the interview keeps going.
    """
    if engine.satisfiable(scheme, known):
        if scheme.attributes_used <= set(known.facts):
            return Status.ELIGIBLE
        return Status.OPEN

    for conflict in engine.explain(scheme, known, every=False):
        for fact in conflict.facts:
            if fact.attribute and engine.schema[fact.attribute].mutability.actionable:
                return Status.FIXABLE
    return Status.INELIGIBLE


def open_schemes(engine, schemes: list[Scheme], known: Profile) -> list[Scheme]:
    """Schemes the interview should keep gathering answers for."""
    return [s for s in schemes if status(engine, s, known).still_worth_asking]


def next_question(
    engine, schema: Schema, schemes: list[Scheme], known: Profile
) -> Question | None:
    """The most useful thing left to ask, or None when nothing is undecided."""
    still_open = open_schemes(engine, schemes, known)
    if not still_open:
        return None

    waiting: dict[str, list[str]] = {}
    for scheme in still_open:
        for name in scheme.attributes_used - set(known.facts):
            waiting.setdefault(name, []).append(scheme.id)

    if not waiting:
        return None

    def rank(item):
        name, schemes_waiting = item
        attr = schema[name]
        # Most schemes unblocked first; among equals, ask the harmless
        # questions before the intrusive ones.
        return (-len(schemes_waiting), attr.sensitive, name)

    name, schemes_waiting = min(waiting.items(), key=rank)
    attr = schema[name]
    return Question(
        attribute=name,
        text=attr.question,
        sensitive=attr.sensitive,
        schemes_waiting=tuple(sorted(schemes_waiting)),
    )


def interview(engine, schema: Schema, schemes: list[Scheme], answers: dict) -> list[Question]:
    """Replay a full set of answers to see which questions were actually needed.

    Used by the evaluation harness to measure how much shorter the adaptive
    sequence is than asking everything, and how often sensitive questions never
    come up at all.
    """
    asked: list[Question] = []
    known = Profile(id="interview", facts={})

    while True:
        question = next_question(engine, schema, schemes, known)
        if question is None:
            break
        if question.attribute not in answers:
            # The interviewee cannot answer; drop the scheme that needed it
            # rather than looping forever on an unanswerable question.
            break
        asked.append(question)
        known = Profile(
            id="interview",
            facts={**known.facts, question.attribute: answers[question.attribute]},
        )

    return asked
