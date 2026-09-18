# PATRA

**पात्र, "eligible"**

Tells a rural household what government schemes they can claim, why they were
refused the others, and exactly which papers to collect in which order.

Everything runs on the device. There is no server to call, because the
reasoning is a constraint solver and a few YAML files rather than a model that
needs one. Answers about caste, income and disability never leave the machine,
and that is a property of the architecture rather than a promise in a policy.

Nothing here is trained. There are no weights, no dataset, no model.

---

## Running it

```bash
pip3 install -r requirements.txt
```

The app:

```bash
python3 -m patra.web.server
```

Then open `http://127.0.0.1:8765`. It asks a short series of questions, stops
as soon as the answers are settled, and shows what the family can claim along
with the paperwork route.

From the terminal:

```bash
python3 -m patra.cli screen --household sunita
```

```bash
python3 -m patra.cli plan --household munni
```

```bash
python3 -m patra.cli ask
```

```bash
python3 -m patra.cli documents
```

## What it does

**Finds the claims.** Twenty schemes, checked against every member of the
household and against the household itself. A pension for the grandmother, a
savings account for the daughter and a crop payment for whoever farms all come
out of one conversation.

**Explains refusals.** Not "you do not qualify" but the irreducible reason:

```
Indira Gandhi National Widow Pension for sunita
  The rule says: Payment needs a bank account linked to Aadhaar
  Your answer:   Bank account linked to Aadhaar: no

  Bank account linked to Aadhaar: no -> yes   (paperwork only)
```

That one free errand also unlocks two insurance schemes.

**Plans the paperwork.** The thing that actually defeats people is being told
to bring an income certificate, walking to the tehsil office, and finding out
they needed a ration card first. Document requirements form an AND-OR graph, so
the app searches it and returns an ordered route:

```
1. Passport photographs      Rs 60, 1 trip
   After this you can apply for:
     - MGNREGA job card
     - Antyodaya Anna Yojana ration card
2. Bank account in your own name
   ...
```

**Says when nothing will help.** If the refusal rests on age or caste, the app
names the blocker and offers no advice, because a system that always has a
suggestion is a system that sometimes lies.

**Asks as little as it can.** Questions stop the moment the answers are
settled, and sensitive ones go last, so in most interviews caste and disability
never come up at all.

## How it works

```
answers -> constraint encoding -> Z3 -> QuickXPlain / MARCO / hitting sets
                                     -> AND-OR search over documents
                                     -> templated explanation
```

| Layer | What it is |
|---|---|
| Eligibility | constraint satisfaction |
| Why refused | minimal unsatisfiable subsets, via QuickXPlain |
| All the reasons | MARCO traversal of the subset lattice |
| What would fix it | minimal correction sets, restricted to changeable facts |
| Which paper first | minimum-cost AND-OR search |
| Which questions | adaptive test selection |
| Did we mishear | domain axioms plus the same conflict detection |

The mathematics is load-bearing rather than decorative. Minimal correction sets
are exactly the minimal hitting sets of the minimal conflicts, which is why one
traversal of the lattice answers both "why not" and "what now". We check that
on our own instances rather than citing it.

## Layout

```
patra/
  model/      attributes, households, schemes, the document graph
  encode/     YAML loader, Z3 compiler
  reason/     oracle, quickxplain, marco, hitting sets,
              planner, unlock, questions, consistency, sensitivity
  explain/    templated rendering
  web/        local server and the app itself
  engine.py   adjudication and household screening
  cli.py      terminal interface
data/
  attributes.yaml   33 attributes, with mutability and sensitivity
  schemes/          20 encoded schemes
  documents.yaml    17 documents and what each needs first
  axioms.yaml       what cannot be true of anybody
  cases/            five households used for testing and the walkthrough
tests/        129 tests
eval/         six experiments
```

## Tests and measurements

```bash
python3 -m pytest tests/ -q
```

```bash
python3 eval/benchmark.py
```

Measured, reproducible, nothing hard-coded:

| | |
|---|---|
| Finding a minimal reason | 1238 solver queries against 3671 for linear deletion, a 66% saving |
| Growth with rulebook size | 17 queries at 160 criteria, against 162 |
| Hitting-set duality | held in 106 of 106 refusals, both directions |
| Acquisition planner | optimal on 12 of 12 targets, against exhaustive search |
| Adaptive questioning | mean 7.0 questions instead of 12, a 42% saving |

The questioning saving was 64% before we made the interview keep going when a
refusal rests on something fixable. That costs extra questions and buys the
ability to tell a widow her pension is one free errand away, which is worth
more than the shorter interview.

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
explains infeasible timetables or broken configurations.

## Please read this before trusting it

The twenty encoded schemes and the document requirements are **research
artefacts, not authoritative**. They are transcribed from published criteria
and simplified, and both vary by state and change over time. Verify against
your own district before relying on anything here. See
[docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Requirements

Python 3.11 or newer, `z3-solver`, `PyYAML`. The web app is standard library
only. No GPU, no network, no API keys.
