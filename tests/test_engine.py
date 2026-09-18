"""End to end behaviour on the five households."""

import pytest

from patra.engine import Trust
from patra.model.attributes import Mutability
from patra.model.household import project


def claims_for(result, scheme_id):
    return [c for c in result.eligible if c.scheme.id == scheme_id]


def blocked_for(result, scheme_id):
    return [c for c in result.blocked if c.scheme.id == scheme_id]


def test_one_free_errand_unlocks_three_schemes(engine, schemes, households):
    """Sunita's account was never linked to Aadhaar.

    That single piece of paperwork is the only thing standing between her and
    the widow pension plus two insurance schemes.
    """
    result = engine.screen(households["sunita"], schemes)

    blocked_on_seeding = []
    for claim in result.blocked:
        for fix in claim.verdict.fixes:
            names = {c.attribute for c in fix.changes}
            if names == {"bank_aadhaar_linked"}:
                blocked_on_seeding.append(claim.scheme.id)
                break

    assert "ignwps" in blocked_on_seeding
    assert len(blocked_on_seeding) >= 3


def test_the_widow_pension_fix_is_paperwork_not_a_life_change(engine, schemes, households):
    result = engine.screen(households["sunita"], schemes)
    claim = blocked_for(result, "ignwps")[0]

    assert claim.verdict.fixes
    fix = claim.verdict.fixes[0]
    assert len(fix.changes) == 1
    change = fix.changes[0]
    assert change.attribute == "bank_aadhaar_linked"
    assert change.now is False and change.needed is True
    assert change.mutability is Mutability.PAPERWORK


def test_a_settled_household_gets_no_manufactured_problems(engine, schemes, households):
    result = engine.screen(households["ramlal"], schemes)
    assert len(result.eligible) >= 8
    assert result.clashes == []
    assert {c.scheme.id for c in result.eligible} >= {"ignoaps", "pm_kisan", "pmjay"}


def test_both_elderly_members_are_found_separately(engine, schemes, households):
    """A household scan must not stop at the first person who qualifies."""
    result = engine.screen(households["ramlal"], schemes)
    pensioners = {c.member_id for c in claims_for(result, "ignoaps")}
    assert pensioners == {"ramlal", "kamla"}


def test_refusal_on_something_unchangeable_offers_nothing(engine, schemes, households):
    """Kishore's family is refused the old age pension on age, which no
    advice can alter. Saying so is the honest answer."""
    result = engine.screen(households["kishore"], schemes)
    claim = blocked_for(result, "ignoaps")[0]

    assert claim.verdict.hopeless
    assert claim.verdict.fixes == []
    assert claim.verdict.blocking, "the unchangeable blocker must be named"


def test_a_scheme_you_already_have_is_not_a_refusal(engine, schemes, households):
    """Sunita has a bank account, so Jan Dhan is redundant, not denied.

    Without this the system would advise her to close her account in order to
    qualify for an account.
    """
    result = engine.screen(households["sunita"], schemes)
    claim = next(
        c for c in blocked_for(result, "jan_dhan") if c.member_id == "sunita"
    )
    assert claim.verdict.redundant
    assert claim.verdict.fixes == []


def test_no_repair_ever_asks_somebody_to_give_something_up(engine, schemes, households):
    for household in households.values():
        result = engine.screen(household, schemes)
        for claim in result.blocked:
            for fix in claim.verdict.fixes:
                for change in fix.changes:
                    attr = engine.schema[change.attribute]
                    assert not attr.is_downgrade(change.now, change.needed), (
                        f"{household.id}/{claim.scheme.id} advises losing "
                        f"{change.attribute}"
                    )


def test_income_near_the_line_is_flagged(engine, schemes, by_id, households):
    """Sunita reports 42,000 against an Antyodaya line of 46,080."""
    profile = project(households["sunita"], engine.schema)
    verdict = engine.adjudicate(by_id["ration_aay"], profile)

    assert verdict.eligible
    assert verdict.trust is Trust.PROVISIONAL
    flagged = {m.attribute for m in verdict.margins}
    assert "annual_income" in flagged


def test_comfortable_margin_is_not_flagged(engine, by_id, households):
    profile = project(households["munni"], engine.schema)
    verdict = engine.adjudicate(by_id["mgnrega"], profile)
    assert verdict.eligible
    assert verdict.trust is Trust.FIRM


def test_landless_family_is_eligible_but_short_of_papers(engine, schemes, households):
    """Munni's problem is paperwork, not eligibility."""
    result = engine.screen(households["munni"], schemes)
    assert result.eligible
    assert result.paperwork is not None
    assert result.paperwork.plan.steps, "they hold only Aadhaar, so there is work to do"
    assert result.paperwork.milestones, "some scheme must open up along the way"


def test_the_first_errand_is_the_one_that_unlocks_most(engine, schemes, households):
    result = engine.screen(households["munni"], schemes)
    first = result.paperwork.first_win
    assert first is not None
    assert len(first.unlocks) >= 2


def test_screening_is_stable_across_runs(engine, schemes, households):
    a = engine.screen(households["bhola"], schemes)
    b = engine.screen(households["bhola"], schemes)
    assert {(c.scheme.id, c.member_id) for c in a.eligible} == {
        (c.scheme.id, c.member_id) for c in b.eligible
    }
