# Limitations

What this does not do, and where the evidence is thin. Better to state these
than to have them found.

## The encoded rules are not authoritative

Twenty schemes transcribed from published criteria and simplified in the
process. Real eligibility carries state variation, periodic revision,
administrative discretion and cross-references we did not model. Three of them
say so in their own notes: Antyodaya and priority ration cards are set by state
tests rather than a single income line, and the disability pension threshold
differs between the central scheme and several state ones.

**Nothing in `data/schemes/` should decide a real application.** The system's
claim is conditional: *given* these rules, the explanations and repairs are
provably minimal. Whether the rules match the law is a separate question, and
it is the failure we are least protected against.

## The document graph was built by hand

Seventeen documents with their prerequisites, assembled from official service
pages and general practice. Requirements differ by district and sometimes by
the clerk. Fees, waiting times and trip counts are indicative.

The weighting inside `Document.effort` treats one trip as worth ten units,
a week of waiting as one, and fifty rupees as one. That reflects our reading
that a lost day of wages dominates a thirty rupee fee for a rural household. It
is a judgement, not a measurement, and it changes which route the planner
prefers.

## The planner is greedy about shared prerequisites

Requirements share inputs: Aadhaar satisfies identity for nearly everything, so
once it is being fetched for one document it is free for the next. Choosing
each requirement independently overcounts, and choosing them jointly to exploit
sharing is set cover, which is NP-hard.

We resolve each requirement against what the partial solution has already
committed to, which captures sharing along a branch but is not a proof of
optimality. `tests/test_planner.py` checks it against exhaustive search on the
real graph, where it currently agrees on all twelve reachable targets. A
different graph could break that, and the test would catch it.

## Aadhaar is modelled as obtainable from nothing

Enrolment accepts an introducer or the head of a family vouching for somebody
who holds no papers at all, so Aadhaar is a root of the graph. This is both
accurate and load-bearing: without it, identity proof and address proof would
require each other forever and the graph would have no foundation.

In practice the introducer route is harder to use than the model suggests.

## Effort and sensitivity rankings are ours

Which attributes count as sensitive, and how burdensome each change is, were
set by us. Obtaining a corrected income certificate is trivial for one family
and a serious obstacle for another. "Cheapest" currently means cheapest by our
assumptions.

## Enumeration is exponential in the worst case

The number of minimal conflicts can grow exponentially with the number of
constraints. The largest instance in our corpus produced 5 conflicts and 32
correction sets. At this scale it is immediate, but a rulebook an order of
magnitude larger would need reconsidering. Minimum-cost hitting set is NP-hard.

## Unstated answers are treated as unknown, not false

If an attribute is never given, the solver may assign it any value the rules
permit. The interface guards against the consequences: a scheme is only called
a near miss once every fact it reads is known, and one still missing answers is
left out rather than guessed at. But the engine itself does not enforce
completeness, and a production system would need an explicit decision about
open versus closed world.

## Literacy

Questions and explanations are templated rather than generated, so the set of
sentences is finite and could be recorded once per language and played back.
That is designed for but **not built**. As it stands the app needs a reader.

Even with audio, somebody who cannot read cannot independently verify what the
app claims about them. The intended answer is a printable summary any literate
neighbour can check, which lowers the bar from "the user must read" to
"somebody they trust must read". Full independence is not achievable and we do
not claim it.

## Nobody validates the answers

Without a field worker present, a misheard question produces a wrong answer
nobody notices. The axioms catch contradictions, and boundary margins catch
numbers close to a threshold, but neither catches a confident wrong answer that
happens to be internally consistent. Somebody who misreports their income by a
wide margin gets a wrong result, stated firmly.

## Two states, not the country

Income thresholds and ration card categories differ across states. We encoded
central schemes and treated the thresholds as national, which is wrong at the
edges. Scoping properly would mean a state dimension on every rule.

## What we did not attempt

- Competitive schemes where everyone clears the minimum and a cutoff decides
- Reasoning about when somebody might become eligible rather than whether
- Scraping live scheme data, so the corpus goes stale by hand
- Detecting contradictions inside a rulebook, though the machinery supports it
- Any evaluation with real households
