"""The ranked errands.

One property carries the feature: an unlock count has to be re-derived, not
tallied. A fact appearing in four conflicts may unlock nothing on its own
because each of those schemes is also blocked by something else, and a tally
would promise four doors that do not open.
"""

from patra.advise import Move, next_actions
from patra.model.household import Profile
from patra.reason.simulate import eligible_now


def advise(engine, schema, schemes, documents, household, profile, limit=6):
    return next_actions(engine, schema, schemes, profile.facts, documents,
                        household.documents, limit=limit)


def test_every_unlock_claim_is_true(engine, schema, schemes, documents,
                                     households, profile_of):
    """Assume each action and ask the solver, exactly as a user would find out."""
    profile = profile_of("sunita", "sunita")
    advice = advise(engine, schema, schemes, documents, households["sunita"], profile)
    by_id = {s.id: s for s in schemes}

    for action in advice.actions:
        if action.move is not Move.FACT:
            continue
        after = Profile(id="after",
                        facts={**profile.facts, action.attribute: action.needed})
        for scheme_id in action.unlocks:
            assert not eligible_now(engine, by_id[scheme_id], profile)
            assert eligible_now(engine, by_id[scheme_id], after), \
                f"{action.attribute} was promised to unlock {scheme_id}"


def test_the_best_action_is_first(engine, schema, schemes, documents,
                                  households, profile_of):
    advice = advise(engine, schema, schemes, documents, households["sunita"],
                    profile_of("sunita", "sunita"))
    counts = [len(a.unlocks) for a in advice.actions]
    assert counts == sorted(counts, reverse=True)


def test_nobody_is_told_to_give_something_up(engine, schema, schemes, documents,
                                              households, profile_of):
    """"Close your bank account" and "sell three acres" are valid corrections
    and worthless advice. An exclusion written against an asset means the
    scheme is aimed at somebody else."""
    for who in ("sunita", "ramlal", "bhola", "kishore", "munni"):
        profile = profile_of(who)
        advice = advise(engine, schema, schemes, documents, households[who], profile)
        for action in advice.actions:
            if action.move is not Move.FACT:
                continue
            attr = schema[action.attribute]
            assert not attr.is_downgrade(profile.facts[action.attribute],
                                         action.needed), \
                f"{who}: told to give up {action.attribute}"


def test_one_errand_is_not_listed_twice(engine, schema, schemes, documents,
                                        households, profile_of):
    """Putting an account on record and fetching the passbook are one visit."""
    for who in ("sunita", "bhola", "ramlal"):
        advice = advise(engine, schema, schemes, documents, households[who],
                        profile_of(who))
        doors = [a.errand.document for a in advice.actions if a.errand]
        assert len(doors) == len(set(doors)), f"{who}: {doors}"


def test_a_prerequisite_says_what_it_is_for(engine, schema, schemes, documents,
                                            households, profile_of):
    """A paper that finishes nothing on its own must not read as pointless."""
    advice = advise(engine, schema, schemes, documents, households["bhola"],
                    profile_of("bhola", "bhola"))
    for action in advice.actions:
        assert action.unlocks or action.toward, \
            f"{action.key} neither opens anything nor leads anywhere"


def test_hopeless_schemes_are_named_and_left_alone(engine, schema, schemes,
                                                   documents, households, profile_of):
    advice = advise(engine, schema, schemes, documents, households["kishore"],
                    profile_of("kishore", "kishore"))
    acted_on = {s for a in advice.actions for s in a.unlocks}
    assert not (set(advice.hopeless) & acted_on)


def test_what_is_claimable_now_is_not_in_the_advice(engine, schema, schemes,
                                                    documents, households, profile_of):
    advice = advise(engine, schema, schemes, documents, households["ramlal"],
                    profile_of("ramlal", "ramlal"))
    assert not (set(advice.eligible) & set(advice.reachable))


def test_the_limit_is_respected(engine, schema, schemes, documents,
                                households, profile_of):
    advice = advise(engine, schema, schemes, documents, households["sunita"],
                    profile_of("sunita", "sunita"), limit=2)
    assert len(advice.actions) <= 2


def test_an_errand_carries_its_office(engine, schema, schemes, documents,
                                       households, profile_of):
    """"Link your Aadhaar" is advice. With a branch, a fee and a trip count it
    is an errand somebody can run."""
    advice = advise(engine, schema, schemes, documents, households["sunita"],
                    profile_of("sunita", "sunita"))
    paperwork = [a for a in advice.actions
                 if a.attribute and schema[a.attribute].document]
    assert paperwork
    for action in paperwork:
        assert action.errand is not None
        assert action.errand.issuer
