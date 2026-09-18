"""The reasoning engine.

Four questions, one body of machinery:

    Do they qualify?        satisfiability of rules against answers
    Why not?                minimal unsatisfiable subsets
    What would fix it?      minimal correction sets over changeable facts
    Can we trust that?      contradiction checks and boundary margins

The soft/hard split differs between the second and third, and that difference
is the design. Explaining a refusal leaves both rules and answers soft, so a
conflict can name a clause and the answer it collides with. Computing recourse
hardens the rules, because nobody negotiates with a notification, and leaves
only the household's changeable facts soft.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import z3

from .encode.z3enc import Z3Encoder
from .model.attributes import Kind, Mutability, Schema, Scope
from .model.document import DocumentGraph
from .model.household import Household, Profile, project
from .model.scheme import Axiom, Labelled, Origin, Scheme, facts_as_labelled
from .reason.consistency import Clash, check as check_axioms
from .reason.hittingset import min_cost_hitting_set
from .reason.marco import all_mcses, all_muses
from .reason.oracle import Oracle
from .reason.quickxplain import NoConflict, quickxplain
from .reason.sensitivity import Margin, borderline
from .reason.unlock import Ladder, ladder


class Trust(Enum):
    """How far we are willing to stand behind an answer."""

    FIRM = "firm"
    PROVISIONAL = "provisional"
    """A small correction to a reported number would reverse it."""

    UNRELIABLE = "unreliable"
    """The answers contradict each other. No verdict should be offered."""


@dataclass(frozen=True)
class Conflict:
    rules: tuple[Labelled, ...]
    facts: tuple[Labelled, ...]


@dataclass(frozen=True)
class Change:
    attribute: str
    label: str
    now: object
    needed: object
    mutability: Mutability
    effort: int


@dataclass(frozen=True)
class Fix:
    changes: tuple[Change, ...]

    @property
    def effort(self) -> int:
        return sum(c.effort for c in self.changes)


@dataclass
class Verdict:
    scheme: Scheme
    profile: Profile
    eligible: bool
    conflicts: list[Conflict] = field(default_factory=list)
    fixes: list[Fix] = field(default_factory=list)
    hopeless: bool = False
    """No combination of changeable facts would help."""

    blocking: list[Conflict] = field(default_factory=list)
    redundant: bool = False
    """Refused only because the household already holds what this provides.

    Jan Dhan is for people with no bank account; a priority ration card is for
    people without one. Somebody who already has the thing has not been turned
    away, they simply have no use for the scheme, and saying "refused" would be
    both alarming and wrong.
    """

    trust: Trust = Trust.FIRM
    margins: list[Margin] = field(default_factory=list)
    queries: int = 0


@dataclass
class Claim:
    scheme: Scheme
    member_id: str | None
    verdict: Verdict

    @property
    def eligible(self) -> bool:
        return self.verdict.eligible


@dataclass
class Screening:
    household: Household
    eligible: list[Claim]
    blocked: list[Claim]
    clashes: list[Clash]
    paperwork: Ladder | None = None


class Engine:
    def __init__(
        self,
        schema: Schema,
        axioms: list[Axiom] | None = None,
        documents: DocumentGraph | None = None,
    ):
        self.schema = schema
        self.axioms = axioms or []
        self.documents = documents
        self.encoder = Z3Encoder(schema)
        self._queries = 0

    # ---- satisfiability ----

    def satisfiable(self, scheme: Scheme, profile: Profile) -> bool:
        oracle = self._oracle(scheme, profile)
        answer = oracle.is_sat(oracle.ids)
        self._queries += oracle.stats.calls
        return answer

    def inconsistencies(self, profile: Profile) -> list[Clash]:
        return check_axioms(self.encoder, self.schema, profile, self.axioms)

    # ---- explanation ----

    def explain(self, scheme: Scheme, profile: Profile, every: bool = True):
        oracle = self._oracle(scheme, profile)
        if oracle.is_sat(oracle.ids):
            self._queries += oracle.stats.calls
            return []

        if every:
            cores = all_muses(oracle)
        else:
            # Facts first, so the preference ordering blames the clause that
            # blocks them rather than restating their own answer back at them.
            ordered = [c for c in oracle.ids if c.startswith("F_")]
            ordered += [c for c in oracle.ids if not c.startswith("F_")]
            try:
                cores = [quickxplain(oracle, ordered)]
            except NoConflict:
                cores = []

        out = [self._as_conflict(oracle, c) for c in cores]
        self._queries += oracle.stats.calls
        return out

    # ---- recourse ----

    def repairs(self, scheme: Scheme, profile: Profile):
        """Minimal changes that would make them eligible, cheapest first."""
        changeable = {
            name for name in profile.facts
            if self.schema[name].mutability.actionable
        }
        fixed = [
            l for l in facts_as_labelled(profile, self.schema)
            if l.attribute not in changeable
        ]

        background = [self.encoder.compile(c.formula) for c in scheme.criteria]
        background += [self.encoder.compile(l.formula) for l in fixed]

        soft = [
            l for l in facts_as_labelled(profile, self.schema)
            if l.attribute in changeable
        ]
        oracle = Oracle(self.encoder, soft, background=background)

        if oracle.is_sat(oracle.ids):
            self._queries += oracle.stats.calls
            return [], False, [], False
        if not oracle.is_sat([]):
            # Even dropping every changeable answer leaves a conflict, so the
            # obstruction is among the rules and the facts they cannot change.
            self._queries += oracle.stats.calls
            return [], True, self._hard_core(scheme, fixed), False

        out: list[Fix] = []
        discarded_as_downgrade = 0

        for correction in all_mcses(oracle):
            target = self._nearest_eligible(scheme, profile, correction, fixed)
            if target is None:
                continue

            changes = []
            giving_something_up = False
            for cid in correction:
                name = oracle.label(cid).attribute
                attr = self.schema[name]
                if attr.is_downgrade(profile.facts[name], target[name]):
                    # Telling somebody to close their bank account so they
                    # qualify for a scheme meant for the unbanked is a valid
                    # correction set and worthless advice.
                    giving_something_up = True
                    break
                changes.append(
                    Change(
                        attribute=name,
                        label=attr.label,
                        now=profile.facts[name],
                        needed=target[name],
                        mutability=attr.mutability,
                        effort=attr.effort,
                    )
                )

            if giving_something_up:
                discarded_as_downgrade += 1
                continue
            changes.sort(key=lambda c: (c.effort, c.attribute))
            out.append(Fix(changes=tuple(changes)))

        out.sort(key=lambda f: (f.effort, len(f.changes)))
        self._queries += oracle.stats.calls

        # Every route out required giving something up, which means the scheme
        # duplicates something the household already has.
        redundant = not out and discarded_as_downgrade > 0
        return out, False, [], redundant

    def cheapest_by_duality(self, scheme: Scheme, profile: Profile):
        """Minimum-effort repair found by hitting the conflicts instead.

        Takes the long way round on purpose, so the evaluation harness can
        check that the duality actually holds on our own instances rather than
        taking the theorem on trust.
        """
        conflicts = self.explain(scheme, profile, every=True)
        if not conflicts:
            return []

        sets = []
        for c in conflicts:
            movable = [
                f.attribute for f in c.facts
                if f.attribute and self.schema[f.attribute].mutability.actionable
            ]
            if not movable:
                return None
            sets.append(movable)

        cost = {a.name: a.effort for a in self.schema}
        return min_cost_hitting_set(sets, cost)

    # ---- assembly ----

    def adjudicate(self, scheme: Scheme, profile: Profile) -> Verdict:
        profile.check(self.schema)
        scheme.check(self.schema)

        self._queries = 0
        eligible = self.satisfiable(scheme, profile)
        verdict = Verdict(scheme=scheme, profile=profile, eligible=eligible)

        if self.inconsistencies(profile):
            verdict.trust = Trust.UNRELIABLE
        else:
            verdict.margins = borderline(
                self.encoder, self.schema, scheme, profile, eligible
            )
            if verdict.margins:
                verdict.trust = Trust.PROVISIONAL

        if not eligible:
            verdict.conflicts = self.explain(scheme, profile)
            (
                verdict.fixes,
                verdict.hopeless,
                verdict.blocking,
                verdict.redundant,
            ) = self.repairs(scheme, profile)

        verdict.queries = self._queries
        return verdict

    def screen(self, household: Household, schemes: list[Scheme]) -> Screening:
        """Everything this household can claim, and what stands in the way.

        Household-scoped schemes are judged once against derived counts.
        Member-scoped schemes are judged once per person, because a pension for
        the grandmother and a scholarship for the daughter are separate claims
        arising from the same visit.
        """
        household.check(self.schema)

        eligible: list[Claim] = []
        blocked: list[Claim] = []
        clashes: list[Clash] = []

        seen_clash_keys: set[tuple] = set()

        for scheme in schemes:
            if scheme.scope is Scope.HOUSEHOLD:
                targets = [(None, project(household, self.schema))]
            else:
                targets = [
                    (m.id, project(household, self.schema, m.id))
                    for m in household.members
                ]

            for member_id, profile in targets:
                for clash in self.inconsistencies(profile):
                    key = tuple(sorted(clash.attributes))
                    if key not in seen_clash_keys:
                        seen_clash_keys.add(key)
                        clashes.append(clash)

                verdict = self.adjudicate(scheme, profile)
                claim = Claim(scheme=scheme, member_id=member_id, verdict=verdict)
                (eligible if verdict.eligible else blocked).append(claim)

        paperwork = None
        if self.documents is not None:
            claimable = [c.scheme for c in eligible]
            paperwork = ladder(self.documents, claimable, household.documents)

        return Screening(
            household=household,
            eligible=eligible,
            blocked=blocked,
            clashes=clashes,
            paperwork=paperwork,
        )

    # ---- internals ----

    def _oracle(self, scheme: Scheme, profile: Profile) -> Oracle:
        soft = scheme.as_labelled() + facts_as_labelled(profile, self.schema)
        return Oracle(self.encoder, soft)

    def _as_conflict(self, oracle: Oracle, core) -> Conflict:
        labels = [oracle.label(c) for c in core]
        return Conflict(
            rules=tuple(l for l in labels if l.origin is Origin.RULE),
            facts=tuple(l for l in labels if l.origin is Origin.FACT),
        )

    def _hard_core(self, scheme: Scheme, fixed: list[Labelled]) -> list[Conflict]:
        """The minimal set of rules and unchangeable facts that blocks recourse.

        Naming it is the difference between "nothing will help" and "nothing
        will help, and this is exactly why".
        """
        oracle = Oracle(self.encoder, scheme.as_labelled() + fixed)
        try:
            core = quickxplain(oracle, oracle.ids)
        except NoConflict:
            self._queries += oracle.stats.calls
            return []
        out = [self._as_conflict(oracle, core)]
        self._queries += oracle.stats.calls
        return out

    def _nearest_eligible(self, scheme, profile, relaxed, fixed):
        """The closest eligible version of this household to the real one.

        Without this a correction set only says which answer must change, and
        the solver is free to reply that their income should be zero. Minimising
        the distance turns that into the actual threshold, which is something
        they can check against their papers.
        """
        loosened = {c[2:] for c in relaxed if c.startswith("F_")}

        opt = z3.Optimize()
        for expr in self.encoder.background():
            opt.add(expr)
        for c in scheme.criteria:
            opt.add(self.encoder.compile(c.formula))
        for l in fixed:
            opt.add(self.encoder.compile(l.formula))

        gaps = []
        for name, value in profile.facts.items():
            const = self.encoder.const(name)
            if name not in loosened:
                opt.add(const == self.encoder.encode_value(name, value))
                continue
            if self.schema[name].kind is Kind.INT:
                gap = const - value
                gaps.append(z3.If(gap >= 0, gap, -gap))
            else:
                gaps.append(
                    z3.If(const == self.encoder.encode_value(name, value), 0, 1)
                )

        if gaps:
            opt.minimize(z3.Sum(gaps))
        if opt.check() != z3.sat:
            return None

        model = opt.model()
        out = {}
        for attr in self.schema:
            raw = model.eval(self.encoder.const(attr.name), model_completion=True)
            if z3.is_true(raw) or z3.is_false(raw):
                out[attr.name] = self.encoder.decode_value(attr.name, z3.is_true(raw))
            else:
                out[attr.name] = self.encoder.decode_value(attr.name, raw.as_long())
        return out
