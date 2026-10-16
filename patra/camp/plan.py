"""Which counters to bring to the village, with a fixed number of officials.

The block office can spare so many people for a day. Each counter costs some
of them and gets through so many households. A household gains nothing from a
counter unless every counter its missing papers need also comes, so the value
of a choice is not the sum of its parts and no amount of ranking counters
individually will find the best day.

That is budgeted maximum coverage with a capacity constraint, and it is
NP-hard. Three ways at it, on purpose:

    exhaustive   every subset. Eleven counters is 2048 of them, so the true
                 optimum is available, which is the only reason the other two
                 can be said to be any good.
    greedy       take the best value per official, repeatedly. Fast, and the
                 standard first thing anybody tries.
    annealing    start somewhere and keep swapping, accepting a worse day now
                 and then so as not to settle in the first dip.

Keeping the exact answer is what makes this honest rather than decorative.
A heuristic with nothing to compare against is just an opinion with a
runtime, and here we can say exactly how far from optimal each one lands.

What it says, on our village, is that greedy ties the optimum at every
budget. That is the real result and it is reported rather than hidden,
although it makes for a quiet demonstration. It is also not a guarantee:
greedy on budgeted maximum coverage is only (1 - 1/e) approximate, and
`eval/benchmark.py` carries a small constructed instance where it loses, so
the gap can be seen rather than taken on trust.
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Served:
    household: str
    schemes: tuple[str, ...]
    value: int


@dataclass
class Outcome:
    """What a given set of counters would actually achieve."""

    chosen: tuple[str, ...]
    slots: int
    value: int = 0
    served: tuple[Served, ...] = ()
    turned_away: int = 0
    """Households covered on paper but past a counter's capacity for the day."""

    load: dict[str, int] = field(default_factory=dict)

    @property
    def households(self) -> int:
        return len(self.served)


def evaluate(needs, offices, chosen) -> Outcome:
    """What this set of counters opens, respecting what each can get through.

    Capacity is the part that makes a plan a plan rather than a wish. A
    counter that serves forty does not serve the forty-first, so once more
    households qualify than can be seen, somebody is chosen. Highest value
    first, which is a decision worth stating out loud rather than an accident
    of iteration order.
    """
    chosen = frozenset(chosen)
    slots = sum(offices[o].slots for o in chosen)

    candidates = []
    for need in needs:
        gained = tuple(sorted(
            s for s, wanted in need.missing.items() if wanted <= chosen))
        if not gained:
            continue
        worth = sum(need.wants[s] for s in gained)
        wants = frozenset().union(*(need.missing[s] for s in gained))
        candidates.append((worth, need.household, gained, wants))

    candidates.sort(key=lambda row: (-row[0], row[1]))

    load = {o: 0 for o in chosen}
    served, turned_away, total = [], 0, 0
    for worth, household, gained, wants in candidates:
        if any(load[o] + 1 > offices[o].serves for o in wants):
            turned_away += 1
            continue
        for o in wants:
            load[o] += 1
        served.append(Served(household=household, schemes=gained, value=worth))
        total += worth

    return Outcome(chosen=tuple(sorted(chosen)), slots=slots, value=total,
                   served=tuple(served), turned_away=turned_away, load=load)


def affordable(offices, budget):
    return [o for o in offices.values() if o.travels and o.slots <= budget]


# ---- exhaustive ----

def exact(needs, offices, budget):
    """Every subset within budget. The optimum, and what it cost to find."""
    usable = affordable(offices, budget)
    best, looked = None, 0

    for size in range(len(usable) + 1):
        for combo in itertools.combinations(usable, size):
            looked += 1
            if sum(o.slots for o in combo) > budget:
                continue
            found = evaluate(needs, offices, [o.id for o in combo])
            if best is None or found.value > best.value or (
                    found.value == best.value and found.slots < best.slots):
                best = found
    return best, looked


# ---- greedy ----

def greedy(needs, offices, budget):
    """Best value per official, repeatedly, never undoing a choice.

    The standard first attempt, and it fails in the standard way: the counter
    that pays nothing on its own but completes three others is never picked
    first, so it is never picked.
    """
    usable = affordable(offices, budget)
    chosen, spent, steps = [], 0, []

    while True:
        best = None
        for office in usable:
            if office.id in chosen or spent + office.slots > budget:
                continue
            found = evaluate(needs, offices, chosen + [office.id])
            gain = found.value - (steps[-1]["value"] if steps else 0)
            rate = gain / office.slots
            if best is None or rate > best[0]:
                best = (rate, office, found)
        if best is None or best[0] <= 0:
            break
        _, office, found = best
        chosen.append(office.id)
        spent += office.slots
        steps.append({"office": office.id, "value": found.value, "slots": spent})

    return evaluate(needs, offices, chosen), steps


# ---- local search ----

def anneal(needs, offices, budget, seed=7, rounds=400, start=None):
    """Keep swapping counters, accepting a worse day less and less often.

    The trace is returned because it is the interesting part. A plot of it
    shows the search climbing, stalling, taking a step backwards and finding
    something better, which is what a local search actually does and what a
    final number hides.
    """
    rng = random.Random(seed)
    usable = [o.id for o in affordable(offices, budget)]
    if not usable:
        return evaluate(needs, offices, []), []

    def cost(ids):
        return sum(offices[i].slots for i in ids)

    current = list(start) if start else []
    best = list(current)
    here = evaluate(needs, offices, current)
    top = here
    trace = [{"round": 0, "value": here.value, "best": here.value,
              "chosen": list(here.chosen), "took": True}]

    for step in range(1, rounds + 1):
        heat = max(0.02, 1.0 - step / rounds)
        trial = _move(rng, current, usable, offices, budget)
        if trial is None:
            continue

        found = evaluate(needs, offices, trial)
        gap = found.value - here.value
        # Temperature scaled to the values actually in play. A fixed constant
        # either accepts everything or nothing, depending on whether the
        # rupees happen to be in thousands or lakhs.
        warmth = max(1.0, heat * 0.06 * max(top.value, 1))
        take = gap >= 0 or rng.random() < math.exp(gap / warmth)
        if take:
            current, here = trial, found
            if found.value > top.value:
                top, best = found, list(trial)
        if step % 4 == 0 or take:
            trace.append({"round": step, "value": here.value,
                          "best": top.value, "chosen": list(here.chosen),
                          "took": bool(take)})

    return evaluate(needs, offices, best), trace


def _move(rng, current, usable, offices, budget):
    """One neighbour: swap, add or drop, always inside the budget.

    Swapping has to be possible from a full day, which is the whole point. An
    earlier version proposed a drop whenever the budget was spent, so once it
    filled the day every proposal was strictly worse, every proposal was
    rejected, and the search froze on the first thing it happened to find.
    """
    spare = [o for o in usable if o not in current]
    roll = rng.random()

    if roll < 0.5 and current and spare:
        trial = list(current)
        trial.remove(rng.choice(trial))
        trial.append(rng.choice(spare))
    elif roll < 0.75 and spare:
        trial = list(current) + [rng.choice(spare)]
    elif current:
        trial = list(current)
        trial.remove(rng.choice(trial))
    else:
        return None

    # Evict at random until it fits rather than giving up, so a swap onto a
    # counter that costs two officials is still reachable.
    guard = 0
    while sum(offices[i].slots for i in trial) > budget and trial and guard < 20:
        trial.remove(rng.choice(trial))
        guard += 1
    if sum(offices[i].slots for i in trial) > budget:
        return None
    return trial if sorted(trial) != sorted(current) else None
