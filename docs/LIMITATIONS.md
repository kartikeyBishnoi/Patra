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

## The understanding layer only knows phrases we wrote down

`data/cues.yaml` is a gazetteer. It reads the phrasings we thought of and
nothing else, so somebody saying something we did not anticipate gets "no
answers came out of that" and falls back to the questions. That failure mode is
the one we chose: a missed fact costs a question, an invented one costs a wasted
trip.

The evaluation figure for this (E7) is weaker than it looks, and the harness
says so when it prints. The labelled sentences in `eval/sentences.yaml` and the
cue vocabulary were written by the same hand, so the numbers measure coverage
of phrasings we thought of rather than generalisation. **It is the first number
in this project that should be thrown away and replaced with field data.**

Dialect is the specific gap. The cues lean on standard Hindi, Marathi, Bengali
and Tamil plus Latin transliteration. Bhojpuri, Awadhi, Haryanvi and Marwari
speakers will not be read well, and those are a large part of the intended
users.

## Marathi, Bengali and Tamil cues were written without a native speaker

The same caveat already on those languages' interface text now extends to their
cue vocabulary, where it matters more. A wrong interface word reads as broken.
A wrong cue word silently reads a fact nobody stated. Tamil marks case by
changing the stem rather than adding a vowel sign, so the matcher cannot reach
inflected forms and they are listed individually; the list is certainly
incomplete.

## Reading a photograph is bounded by what tesseract has installed

The signatures and field patterns are ours, and the character recognition is
tesseract's. On this machine only the English pack is installed, so a
Devanagari-only document will not be read at all. The app says which pack is
missing rather than returning an empty read that looks like a bad photograph,
but the limit is real and most Indian documents are bilingual only by
convention.

Field patterns are regular expressions over OCR output, which is why every
field read off a photograph is read back to the person before use, without
exception and regardless of how clean the output looked. A five read as a six
moves an income by ten thousand rupees, and the person holding the paper is
the only one who can see that it happened.

The specimen documents in `tools/samplecards.py` are drawn from scratch with
invented names and stamped SPECIMEN. They exercise the pipeline and are not
evidence that it works on a creased card photographed in bad light, which is
the real case and which we have not tested.

## The microphone is the one thing that leaves the machine

Browser speech recognition sends the audio to whoever made the browser. There
is no local alternative we can ship in a page. It is off until the person says
yes, the warning says exactly that in their own language, and typing always
works instead.

Everything else is local, including the voice you hear, which is synthesised at
build time. But "nothing leaves this machine" is not true of the microphone and
we would rather say so than carry a privacy claim that is almost right.

## The simulation answers a narrower question than it appears to

"What if our income were eighty thousand" is answered against the encoded
rules, which are research artefacts, and against this household's other answers
held fixed. Real life does not hold them fixed: a better-paying job changes
occupation, and sometimes where you live. The simulation is a conditional, not
a forecast.

## Ranked actions are ranked by our costs

An action's payoff is re-derived by assuming it and asking the solver again,
which is sound. Its cost is `Document.effort` and the schema's effort weights,
which are our judgement. So the ordering of two actions with the same payoff
reflects our assumptions about what is burdensome, not the household's.

Actions are also considered one at a time. Two changes that only pay off
together will not be found, and looking for them jointly is the same
combinatorial problem the planner already avoids.

## The age projection assumes the rest of life holds still

"This opens when you turn sixty" is computed with every unchangeable fact
pinned and the paperwork left free. It does not model the household changing
around the person, which is what actually happens over fourteen years: income
moves, people are born and die, a ration card is reissued under a different
category. It is a conditional about the rules, not a forecast about a family.

Closings more than ten years out are not shown at all. They are true and not
actionable, and printing one that lands in thirty-four years buries the one
that lands in two.

## Relations between schemes are relations between our encodings

"Clearing this clears that" is proved, and proved about `data/schemes/`, which
is a simplified transcription. If a clause was dropped in transcription the
entailment can be real in our rulebook and false in the law. The proof is
sound; what it is sound about is a research artefact.

Household-scoped and member-scoped schemes are never compared, because an
implication across that line would be read as a promise about the wrong
person.

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
- Dialects, which is where most of the intended users actually speak
- Reading handwriting, or any document photographed at an angle
- A model proposing rule changes from a government notification, which is the
  one place a language model would earn its place, because a human checks it
  before it reaches anybody
