# PATRA (पात्र)

"पात्र" means "eligible".

A household in a village says a sentence, answers a few questions, or
photographs a paper, and finds out which government schemes they can claim, why
they were refused the others, what the smallest change would be, and exactly
which papers to collect in what order.

Speech, typing and photographs go through a layer that reads facts out of them
and can point at the words it read each one from. Nothing that layer produces is
believed. A constraint solver decides, and between the two sits a gate that
refuses anything the schema or the domain axioms will not accept.

The whole thing runs on the device. There is no server to call and no account to
make, because the reasoning is a constraint solver and a few YAML files rather
than a model that needs hosting. Answers about caste, income and disability never
leave the machine, which is a property of how it is built rather than a promise
in a policy. The one exception is the microphone, which is off until you say
yes, and says so in your own language when you press it.

Nothing here is trained. There are no weights and no dataset. The only trained
models anywhere near it are tesseract's character recogniser and the voice that
reads the screen aloud, and neither decides anything.

---

## Why

India's own audit record documents the problem. The Comptroller and Auditor
General reports that over 69 percent of the genuinely poor lack a BPL card and
that leakage in the Public Distribution System runs at 36 percent, and describes
wrongful exclusion as systemic rather than accidental. Courts have repeatedly
held that clerical errors cannot be grounds to deny welfare rights, which would
not need restating if it were rare.

The practical failure is narrower than the statistics suggest. A family is told
to bring an income certificate, walks to the tehsil office, and is turned away
because they needed a ration card first. They go again. Each trip is a lost day
of wages. Nobody ever tells them the order.

## What it does

**Takes it however you can give it.** Type or speak a sentence and it reads
what it can:

```
"Meri maa 62 saal ki hain aur unka husband nahi hai"

  about           your mother        from "maa"
  Age             62                 from "62 saal"
  Gender          female             worked out from the relation
  Marital status  widowed?           from "husband nahi", so we ask
```

That last line is the design. "No husband" is said by unmarried women as often
as by widows, so it is read back rather than assumed. The questions then skip
whatever the sentence already covered.

**Reads a photographed paper.** Point the camera at an income certificate and
it says which document it thinks that is and what it matched on, then reads the
figure off it and asks you to confirm it. Every field off a photograph is a
question, never an answer, because a five read as a six moves an income by ten
thousand rupees and only the person holding the paper can see it happened.
Aadhaar and PAN numbers are used to recognise the card and then thrown away
unread.

**Finds the claims.** Twenty schemes checked against every member of the
household and against the household itself, so a pension for the grandmother, a
savings account for the daughter and a crop payment for whoever farms all come
out of one conversation.

**Explains refusals.** Not "you do not qualify" but the irreducible reason:

```
Indira Gandhi National Widow Pension
  To get this you need: a bank account linked to Aadhaar
  You told us:          Bank account linked to Aadhaar, no

  What would change it: Bank account linked to Aadhaar, no to yes
                        This is only paperwork
```

That one free errand also unlocks two insurance schemes.

**Plans the paperwork.** Document requirements are not a chain. An income
certificate wants proof of identity, proof of address and proof of age, and each
accepts several alternatives, which makes the whole structure an AND-OR graph.
The app searches it and returns an ordered route with offices, fees and how many
trips each takes.

**Says what to do next, in order.** Not six checklists for six refusals, one
ranked list:

```
1. Link your bank account to Aadhaar
   Your own bank branch, free, one trip
   Opens up: widow pension, life insurance, accident insurance
   Needed for: family benefit, rural housing

2. Passport photographs
   Any photo studio in the market, Rs 60, one trip
   Opens up: job card, Antyodaya ration card
```

Those counts are re-derived, not tallied. A fact that appears in four refusals
may unlock nothing on its own, because each of those schemes is also blocked by
something else, so every candidate action is assumed and the solver is asked
again. Changing a fact and obtaining a paper are costed in the same currency, so
they can be ranked against each other, and one trip to the bank is listed once.

**Answers "what if".** Change one answer and every scheme is decided again:

```
Yearly income: 42,000 -> 300,000

  6 now, 5 after the change
  - Antyodaya ration card: yearly household income must be very low
```

Both directions, always. A change that gains three schemes and quietly costs
two is not an improvement, and somebody weighing up a better-paying job is
entitled to see the whole trade. A change that could not be true of anybody is
refused with the rule that says so.

**Answers "when", not only "whether".** Several schemes close with age rather
than open with it, and nobody is ever told:

```
41   Atal Pension Yojana
     Closes when you turn 41. Apply within 4 years.

60   Indira Gandhi National Old Age Pension
     Opens when you turn 60, in 14 years.
     You will also need the paperwork done.
```

Two questions to the optimiser, not a loop: the youngest age at which the
clauses can hold, and the first at which they cannot. Only the facts that
cannot change are held fixed, so the answer is "once the paperwork is done,
this opens at sixty" rather than the useless "never".

**Knows how its own rules relate.** Asked of the rulebook rather than of
anybody, when the app starts:

```
PM Kisan Samman Nidhi                    -> Pradhan Mantri Fasal Bima Yojana
Pradhan Mantri Jeevan Jyoti Bima Yojana  -> Pradhan Mantri Suraksha Bima Yojana
```

Those arrows are proved, not noticed. Anyone who satisfies the first
necessarily satisfies the second, so clearing one settles the other with no
second test. The same pass finds the seventeen pairs nobody can hold together
and any clause a scheme's own other clauses already force.

**Says when nothing will help.** If a refusal rests on age or caste, the app
names the blocker and offers no advice. A system that always has a suggestion is
a system that sometimes lies.

**Will not say what it cannot verify.** Ask the chatbot whether you qualify and
it puts the question to the solver. If a fact the scheme reads is missing, the
answer is not a guess, it is "PATRA could not verify this" and a list of what is
still needed.

**Asks as little as it can.** Questions stop the moment the answers are settled,
and the sensitive ones go last, so in most interviews caste and disability never
come up at all.

**Shows its working, on both halves.** Every result opens into the actual
derivation: what was encoded, what the solver found, how the smallest reason was
isolated and at what cost, and how the repair was chosen. So does every sentence
it reads, down to the numbers it threw away for naming nothing. A word list that
cannot show its working is indistinguishable from a model that guessed, which is
the whole reason for using a word list.

## The interface

Built after [usa.gov](https://www.usa.gov/), which is the clearest government
service index anyone has shipped, and coloured from our own logo: the navy of
the wordmark, the teal of the check, the gold of the rules beneath it.

The structural borrowings are deliberate and each does work. A strip above the
header saying what kind of site this is. A serif heading with a heavy rule
under it. A tinted band behind every card grid. Square cards with a thin
border and a dotted rule under the icon. A breadcrumb and a left rail on every
inner page. A "How do I ..." block holding the four questions most visits are
about. A great deal of air.

The one thing it does not borrow is the sentence in that top strip. usa.gov
says "An official website of the United States government". PATRA says the
opposite, in the same place and as plainly, because that strip is where
somebody decides whether to trust what follows and this is a student project.
`tests/test_web.py` checks that the disclaimer is still there in all five
languages.

Icons are line drawings defined in the page, not emoji and not photographs.
Emoji render differently on every machine and read as decoration; a stock
photograph would be the only thing in the app that came from somewhere else.
The one deliberate exception is the document pictures on the papers screen,
where a recognisable object means something to somebody who cannot read the
label and a line glyph does not.

## Running it

```bash
pip3 install -r requirements.txt
```

```bash
python3 -m patra.web.server
```

Open `http://127.0.0.1:8765`. Pick a language, tap the papers you already hold,
say or type a sentence about your family if you want to, answer the questions.
Opening `index.html` straight off the disk will not work, because the page needs
the app running behind it; it says so rather than sitting blank.

Reading photographed documents needs tesseract, which is a system package rather
than a Python one. Without it the camera card simply does not appear.

```bash
sudo apt install tesseract-ocr tesseract-ocr-hin tesseract-ocr-mar tesseract-ocr-ben tesseract-ocr-tam
```

The app asks which language packs are installed and names the missing ones
rather than returning an empty read that looks like a bad photograph.

There is a terminal interface too, and every feature is reachable from it:

```bash
python3 -m patra.cli screen --household sunita
python3 -m patra.cli plan --household munni
python3 -m patra.cli ask
python3 -m patra.cli documents
python3 -m patra.cli read "meri maa 62 saal ki hain aur unka husband nahi hai"
python3 -m patra.cli next --household sunita
python3 -m patra.cli whatif --household sunita --set annual_income=300000
python3 -m patra.cli paper --image some-certificate.png
```

Specimen documents to try the reader on, drawn from scratch and stamped
SPECIMEN so nothing here resembles a real record:

```bash
python3 tools/samplecards.py --out /tmp/cards
```

## Languages

English, Hindi, Marathi, Bengali and Tamil. The language is chosen once, with
each name written in its own script, and remembered after that. It can be changed
from the header at any time. Questions and results can be read aloud.

Every language is complete end to end: interface, questions, options, scheme
names, benefit descriptions, document names and the criterion texts that explain
a refusal. The chatbot answers in whichever language is selected.

English and Hindi carry hand-written criterion wording. The other three generate
theirs from the constraint tree at read time, using about a dozen sentence
fragments per language instead of seventy-one translations, so they read as
labelled requirements ("वय, 60 वर्षे किंवा त्याहून जास्त") rather than prose.
That also means a newly added scheme is readable in every language immediately,
with no translation step. Marathi, Bengali and Tamil are still marked in the
picker as awaiting a native speaker's review.

See [docs/LANGUAGES.md](docs/LANGUAGES.md).

## Voice

Browser speech synthesis is robotic and missing outright for several Indian
languages. Real neural voices exist, but calling one at runtime would send what
the household is being asked and told to somebody else's server, and the
privacy property this app rests on would be gone.

So the synthesis happens once, before anybody uses the app. The set of
sentences is finite, which is only true because nothing here generates prose,
so `tools/voice.py` walks every string in `data/i18n/`, synthesises each one,
and writes the audio into `data/audio/<lang>/`. At runtime the app plays a
local file and makes no network call at all, falling back to the browser voice
wherever a clip is missing.

```bash
pip3 install piper-tts
python3 tools/voice.py --lang all
```

The default is [Piper](https://github.com/rhasspy/piper), a small open-source
neural TTS. The voice is a 60MB ONNX model fetched once; after that nothing
leaves the machine even during generation, and no key or account is involved.
It covers Hindi, Marathi, Bengali and English.

Piper has no Tamil voice. For Tamil, [Bhashini](https://bhashini.gov.in), the
Government of India's own language platform, is free at low volume and its
Indic models come from IITM, IITB, IIITH and CDAC:

```bash
export BHASHINI_KEY=your_key
export BHASHINI_ID=your_user_id
python3 tools/voice.py --lang ta --provider bhashini
```

Around 200 to 300 clips per language, a couple of minutes each. The audio and
the voice models are build artefacts and are not in the repository.

## How it works

```
   speech / typing / a photograph
             |
     perception            gazetteer, numeral grammar, OCR, signatures
             |             guesses, and can cite the words it read
             |
      the guard            schema, no overwriting, domain axioms,
             |             unsure readings go back to the person
             |
      reasoning            Z3 -> QuickXPlain, MARCO, hitting sets
             |                -> AND-OR search over documents
             |                -> counterfactual simulation
             |                -> utility-ranked actions
             |
     explanation           sentences built from the constraint tree,
                           the derivation, pre-recorded speech
```

Perception proposes. The solver decides. Nothing crosses the middle that the
schema and the axioms do not accept, and that is enforced in `patra/guard.py`
rather than left to whoever calls it.

| Layer | Technique |
|---|---|
| Eligibility | constraint satisfaction |
| Why refused | minimal unsatisfiable subsets, via QuickXPlain |
| All the reasons | MARCO traversal of the subset lattice |
| What would fix it | minimal correction sets, restricted to changeable facts |
| Which paper first | minimum-cost AND-OR search |
| Which question next | adaptive test selection |
| When, not whether | optimisation over age with the immutable facts pinned |
| How the rules relate | entailment, exclusion and redundancy proved over the rulebook |
| What if | counterfactual re-decision over the whole rulebook |
| What to do next | candidate actions costed and ranked by re-derived payoff |
| Did we mishear | domain axioms and the same conflict detection |
| Reading a sentence | gazetteer, positional rules, clause-scoped negation |
| Reading a document | signature classification and pattern extraction over local OCR |
| Questions in plain words | keyword intent matching over the knowledge base |
| Will not say what it cannot prove | re-derivation at the verification boundary |
| Rules read aloud in any language | sentence generation from the constraint tree |

The mathematics carries weight rather than decorating. Minimal correction sets
are exactly the minimal hitting sets of the minimal conflicts, which is why a
single traversal of the subset lattice answers both "why not" and "what now". We
verify that on our own instances rather than citing it and moving on.

Three things that look like one feature and are not. The understanding layer is
a word list, so it can point at the evidence for every fact and fails by saying
it did not catch that. The explanation is generated from the same constraint
tree the solver decided on, so it cannot drift from the decision. And no
statement about entitlement leaves the system unless the solver derived it from
facts that are all known, which is why the chatbot can answer "PATRA could not
verify this" to its own most important question, and does.

A language model would read phrasing far better than any of this and would
also, now and then, state fluently that somebody qualifies for a pension they do
not, in a way the reader cannot detect. Between a tool that sometimes says "ask
me differently" and one that sometimes invents an entitlement, only the first is
defensible here. The full argument, and the one place a language model would
earn its keep, is in [docs/AI.md](docs/AI.md).

## Layout

```
patra/
  model/      attributes, households, schemes, the document graph
  encode/     YAML loader, Z3 compiler
  nlp/        normalising, numeral grammar, fact extraction
  vision/     local OCR and document signatures
  reason/     oracle, quickxplain, marco, hitting sets, planner,
              unlock, questions, consistency, sensitivity, simulate,
              relate, timeline
  explain/    templated rendering and the derivation traces
  web/        local server, the app, and the logo
  guard.py    the boundary: what may become a fact, what may be claimed
  advise.py   candidate actions, costed and ranked by re-derived payoff
  assist.py   the question answerer
  engine.py   adjudication and household screening
  cli.py      terminal interface
data/
  attributes.yaml   33 facts, with mutability, sensitivity and paper
  schemes/          20 encoded schemes
  documents.yaml    17 documents and what each needs first
  axioms.yaml       what cannot be true of anybody
  cues.yaml         the phrases that propose a fact, in five languages
  papers.yaml       what is printed on each document, and what to read off it
  topics.yaml       how the schemes are grouped, and the four common questions
  i18n/             five languages
  cases/            five households used for testing
tests/        303 tests
eval/         nine experiments, and the labelled sentences for one of them
docs/         the AI argument, limitations, languages
```

## Tests and measurements

```bash
python3 -m pytest tests/ -q
python3 eval/benchmark.py
```

Measured by running the system, nothing hard-coded:

| | |
|---|---|
| Finding a minimal reason | 1238 solver queries against 3671 for linear deletion, 66 percent fewer |
| Growth with rulebook size | 17 queries at 160 criteria, against 162 |
| Hitting-set duality | held in 106 of 106 refusals, both directions |
| Acquisition planner | optimal on 12 of 12 targets, against exhaustive search |
| Adaptive questioning | mean 7 questions instead of 12 |
| Reading a sentence | 61 labelled sentences across five languages, no fact invented from the 17 that carry none |
| Describing your family in words | 21 of 120 interview questions skipped |
| The guard | 70 readings proposed, 66 used, 2 read back, 2 refused |

The reading figure is the weakest number here and the harness says so when it
prints it: the labelled sentences and the cue vocabulary were written by the
same hand, so it measures coverage of phrasings we thought of rather than
generalisation. It is the first number that should be replaced with field data.

## Adding a scheme

Rules are data. Drop a file into `data/schemes/`:

```yaml
id: my_scheme
name: Example Pension
authority: Example Ministry
scope: member
benefit: A monthly payment.
apply_at: Gram panchayat
documents: [aadhaar, bank_account, bank_aadhaar_seeding]
criteria:
  - id: C1
    text: "Must be sixty years of age or older"
    rule: {ge: [age, 60]}
  - id: C2
    text: "Household must be on the below-poverty-line list"
    rule: {in: [ration_card_type, [phh, aay]]}
```

The engine is not welfare-specific. Swap the rulebook and the same machinery
explains infeasible timetables or broken product configurations.

## Please read this before trusting it

**The encoded schemes and document requirements are research artefacts, not
authoritative.** They were transcribed from published criteria and simplified.
Thresholds vary by state, change over time, and are subject to administrative
discretion we do not model. Nothing here should be relied on for a real
application. Verify against the current notification at
[scholarships.gov.in](https://scholarships.gov.in/),
[myScheme](https://www.myscheme.gov.in/) or your own district office.

Other limits, including where the effort estimates come from and what the
evaluation does not prove, are in [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Prior work

[Haqdarshak](https://www.haqdarshak.com/) covers far more ground, with over
6,000 schemes and a network of trained field agents. [myScheme](https://www.myscheme.gov.in/)
is the government's own discovery portal. Both tell you which schemes you match.
Neither tells you why you were excluded, what the smallest change would be, or
which paper to collect first.

## Requirements

Python 3.11 or newer, `z3-solver`, `PyYAML`. The web app uses the standard
library only. No GPU, no network, no API keys.

## Licence

MIT.
