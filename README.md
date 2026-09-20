# PATRA (पात्र)

"पात्र" means "eligible".

A household in a village answers a few questions and finds out which government
schemes they can claim, why they were refused the others, and exactly which
papers to collect in what order.

The whole thing runs on the device. There is no server to call and no account to
make, because the reasoning is a constraint solver and a few YAML files rather
than a model that needs hosting. Answers about caste, income and disability never
leave the machine, which is a property of how it is built rather than a promise
in a policy.

Nothing here is trained. There are no weights, no dataset, no model.

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

**Says when nothing will help.** If a refusal rests on age or caste, the app
names the blocker and offers no advice. A system that always has a suggestion is
a system that sometimes lies.

**Asks as little as it can.** Questions stop the moment the answers are settled,
and the sensitive ones go last, so in most interviews caste and disability never
come up at all.

**Shows its working.** Every result has a panel that opens into the actual
derivation: what was encoded, what the solver found, how the smallest reason was
isolated and at what cost, and how the repair was chosen.

## Running it

```bash
pip3 install -r requirements.txt
```

```bash
python3 -m patra.web.server
```

Open `http://127.0.0.1:8765`. Pick a language, tap the papers you already hold,
answer the questions. Opening `index.html` straight off the disk will not work,
because the page needs the app running behind it; it says so rather than sitting
blank.

There is a terminal interface too:

```bash
python3 -m patra.cli screen --household sunita
python3 -m patra.cli plan --household munni
python3 -m patra.cli ask
python3 -m patra.cli documents
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

## How it works

```
answers -> constraint encoding -> Z3 -> QuickXPlain, MARCO, hitting sets
                                     -> AND-OR search over documents
                                     -> templated explanation
```

| Layer | Technique |
|---|---|
| Eligibility | constraint satisfaction |
| Why refused | minimal unsatisfiable subsets, via QuickXPlain |
| All the reasons | MARCO traversal of the subset lattice |
| What would fix it | minimal correction sets, restricted to changeable facts |
| Which paper first | minimum-cost AND-OR search |
| Which question next | adaptive test selection |
| Did we mishear | domain axioms and the same conflict detection |
| Questions in plain words | keyword intent matching over the knowledge base |
| Rules read aloud in any language | sentence generation from the constraint tree |

The mathematics carries weight rather than decorating. Minimal correction sets
are exactly the minimal hitting sets of the minimal conflicts, which is why a
single traversal of the subset lattice answers both "why not" and "what now". We
verify that on our own instances rather than citing it and moving on.

The assistant answers from the knowledge base, not a language model. A language
model would read phrasing far better and would also, now and then, state fluently
that somebody qualifies for a pension they do not, in a way the reader cannot
detect. Between a tool that sometimes says "ask me differently" and one that
sometimes invents an entitlement, only the first is defensible here.

## Layout

```
patra/
  model/      attributes, households, schemes, the document graph
  encode/     YAML loader, Z3 compiler
  reason/     oracle, quickxplain, marco, hitting sets,
              planner, unlock, questions, consistency, sensitivity
  explain/    templated rendering and the derivation trace
  web/        local server and the app
  assist.py   the question answerer
  engine.py   adjudication and household screening
  cli.py      terminal interface
data/
  attributes.yaml   33 facts, with mutability and sensitivity
  schemes/          20 encoded schemes
  documents.yaml    17 documents and what each needs first
  axioms.yaml       what cannot be true of anybody
  i18n/             five languages
  cases/            five households used for testing
tests/        129 tests
eval/         six experiments
docs/         limitations, languages, build plan
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
