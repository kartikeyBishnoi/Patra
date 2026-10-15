# What the AI is, and where it is allowed to decide

PATRA has two halves that do different kinds of work and are trusted
differently. This document says which is which, because the distinction is the
project's actual argument and it is easy to lose.

```
                          a person
             speech  ·  typing  ·  a photograph
                              |
    +-------------------------v--------------------------+
    |  PERCEPTION                        patra/nlp       |
    |  normalising, number reading,      patra/vision    |
    |  gazetteer and pattern matching,
    |  document signatures, OCR, intent matching
    |                                                    |
    |  guesses. wrong sometimes. cannot conclude anything |
    +-------------------------+--------------------------+
                              |  proposed facts, each with
                              |  its evidence and a confidence
    +-------------------------v--------------------------+
    |  THE GUARD                         patra/guard.py  |
    |                                                    |
    |  schema range and type                             |
    |  does not overwrite a given answer                 |
    |  consistent with the domain axioms                 |
    |  unsure readings go back to the person             |
    +-------------------------+--------------------------+
                              |  facts
    +-------------------------v--------------------------+
    |  REASONING                         patra/reason    |
    |                                    patra/engine.py |
    |  Z3 satisfiability                                 |
    |  QuickXPlain minimal conflicts                     |
    |  MARCO lattice traversal                           |
    |  Reiter hitting-set duality                        |
    |  minimum-cost AND-OR search                        |
    |  adaptive test selection                           |
    |                                                    |
    |  proves. the only thing allowed to conclude        |
    +-------------------------+--------------------------+
                              |  verdict, conflict, correction set, route
    +-------------------------v--------------------------+
    |  EXPLANATION                       patra/explain   |
    |  sentence generation from the constraint tree,     |
    |  the derivation trace, pre-recorded speech          |
    +----------------------------------------------------+
```

The rule, stated once: **perception proposes, the solver decides.** A language
layer that mis-hears an income costs a clarifying question. A language layer
allowed to conclude costs somebody a day's wages walking to an office for a
scheme they cannot have, and they have no way to tell which happened.

## The AI elements, one by one

| | What it is | Where |
|---|---|---|
| Constraint satisfaction | Eligibility as satisfiability over a declared schema, solved by Z3 with assumption literals | `reason/oracle.py`, `encode/z3enc.py` |
| Minimal conflict extraction | QuickXPlain, divide and conquer, O(k log(n/k)) oracle calls | `reason/quickxplain.py` |
| Enumerating all explanations | MARCO traversal of the subset lattice, yielding every minimal conflict and every minimal correction set in one pass | `reason/marco.py` |
| Hitting-set duality | Reiter 1987: correction sets are exactly the minimal hitting sets of the conflicts | `reason/hittingset.py` |
| Actionability-constrained recourse | Correction sets restricted to the mutable sub-lattice and costed by effort | `engine.repairs` |
| Deviation-minimising witness | Z3 Optimize finds the nearest eligible household, so recourse names the real threshold | `engine._nearest_eligible` |
| AND-OR graph search | Document prerequisites are conjunctions of disjunctions, so acquisition is AND-OR search, not a topological sort | `reason/planner.py` |
| Adaptive test selection | Ask only what the undecided schemes depend on, sensitive questions last | `reason/questions.py` |
| Truth maintenance | Domain axioms catch answers that cannot both be true | `reason/consistency.py` |
| Boundary sensitivity | Which single answer would flip the verdict, and at what value | `reason/sensitivity.py` |
| Counterfactual simulation | Re-decide every scheme against a household that does not exist yet | `reason/simulate.py` |
| Utility-ranked planning | Candidate actions costed in one currency and ranked by re-derived payoff | `advise.py` |
| Symbolic information extraction | Gazetteer, positional rules, clause-scoped negation, numeral grammar across five scripts | `nlp/` |
| Document understanding | Signature-based classification and pattern field extraction over local OCR | `vision/` |
| Intent matching | Keyword intent plus a three-pass subject index over the knowledge base | `assist.py` |
| Natural language generation | Criterion sentences composed from the constraint tree, not translated | `explain/phrase.py` |
| Verification boundary | Every claim re-derived; disagreement reported as unverified | `guard.py` |

## Reading a sentence

```
"Meri maa 62 saal ki hain aur unka husband nahi hai"

  subject         mother              from "maa", first-person possessive wins
  gender          female              implied by the relation
  age             62                  from "62 saal", anchored and plausible
  marital_status  widowed             from "husband nahi"  ->  read back first
```

Three rules do most of the work.

**Negation is scoped to the clause.** Hindi and Marathi put it after the
phrase, English before, so both directions are searched but only as far as the
nearest punctuation or conjunction. "I have a bank account, no gas connection"
must not come out as having no bank account.

**A number needs an anchoring word and has to be plausible.** A bare 62 could
be an age, an income or a house number, so a number with no anchor is reported
as unused rather than guessed at. Where two anchors compete the schema's own
range settles it: 72000 is not an age, so "72000 saal ki kamai" is income.

**A monthly figure is rescaled.** People state what they earn in a month far
more often than in a year, and reading 6000 a month as 6000 a year clears every
income threshold in the rulebook.

The vocabulary is `data/cues.yaml`, which a Marathi speaker can correct without
reading any Python. That is the same reason the scheme rules are YAML.

## Why not a language model

A small local model would read phrasing far better than a gazetteer. It was
rejected for the perception layer and for the explanation layer, for different
reasons.

**As a reader.** It cannot point at the words that produced a fact. The
extractor returns "age 62, from the words *62 saal*", and a wrong reading is
visible on screen to somebody who cannot read the rules and can still see that
the app has misheard them. A model returns a number.

**As an explainer.** The explanation is the product. It is generated from the
same constraint tree the solver decided on, so it cannot drift from the
decision. A model paraphrasing a verdict can produce a fluent sentence that
says something the solver did not, and the reader has no way to tell. Between a
tool that sometimes says "ask me differently" and one that sometimes invents an
entitlement, only the first belongs in front of somebody deciding whether to
spend a day's wages on a bus fare.

**As the judge.** Never. That is what the guard exists to prevent, and `verify`
in `guard.py` reports a disagreement between any upstream layer and the solver
as *unverified* rather than resolving it either way.

What a model would be legitimately good at, and what the honest version of this
project would use one for, is proposing rule encodings from a government
notification for a human to check. That is the one place a confident wrong
answer is caught before it reaches anybody. It is not built; see
`tools/watch.py` for the shape of it.

## What the guard actually stops

| Reading | Outcome |
|---|---|
| "our income is around a lakh" | read back, hedged: an estimate is not a figure |
| "unka husband nahi hai" | read back: said by unmarried women as often as widows |
| "she is 15 and a widow" | refused: nobody is widowed before eighteen |
| "my age is 480" | refused: outside the schema, and named rather than clamped |
| "I am 70" when 65 was answered | read back: a reading may not overwrite an answer |
| "I am married and unmarried" | held back: one sentence, two readings, neither used |
| "house number 42" | discarded: a number naming nothing |
| anything off a photograph | always read back, however clean the OCR looked |

`python3 eval/benchmark.py` runs all of this as experiment E9.

## Privacy, and the one place it breaks

Everything above runs on the machine. The solver is local, the gazetteer is a
YAML file, OCR is a local tesseract process, and the speech you hear was
synthesised at build time into `data/audio/`, so playback makes no network
call.

The exception is the microphone. Browser speech recognition sends the audio to
whoever made the browser. It is off until the person says yes, the warning says
exactly that in their own language, and typing always works instead. It is the
only part of the app that leaves the device, and it is better to say so than to
quietly have a privacy claim that is almost true.

## Where this sits

Calling it neuro-symbolic would be generous: the perception half is symbolic
too, and the only trained models in the pipeline are tesseract's character
recogniser and the Piper voice, neither of which decides anything. The useful
description is narrower and more defensible.

> A welfare eligibility assistant that accepts speech, typing and photographs
> through a perception layer that can cite its evidence, and admits nothing to
> a constraint solver that the schema and the domain axioms do not accept.

The research contribution is narrower still, and worth stating as narrowly as
it really is: **actionability-constrained minimal recourse**, which is
restricting correction sets to the mutable sub-lattice, costing them, and
discarding the ones that would require giving something up. Everything else
here is known technique applied to a domain where the explanation matters more
than the verdict.
