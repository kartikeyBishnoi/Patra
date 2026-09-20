# Languages

Every string a person sees lives in `data/i18n/`. That includes the questions,
the scheme names, the benefit descriptions, the document names and, critically,
the criterion text that explains a refusal. A half-translated screen reads as
broken rather than as foreign, so partial files fall back to English **per key**
and the picker marks them.

## What is ready

| Code | Language | Reviewed | Covers |
|---|---|---|---|
| `en` | English | yes | everything |
| `hi` | हिन्दी | yes | everything, including all 71 criterion texts |
| `mr` | मराठी | **no** | everything, criteria generated |
| `bn` | বাংলা | **no** | everything, criteria generated |
| `ta` | தமிழ் | **no** | everything, criteria generated |

**Only English and Hindi are fit to put in front of a real applicant.** The
other three were written without a native speaker and are flagged in the picker
as "not checked yet". A wrong word in a question about caste or income sends
somebody on a wasted trip to a government office, so please do not promote them
until somebody who speaks the language has read every line.

## Criteria you do not have to translate

A criterion is not prose, it is a constraint tree, and every attribute label,
enum option and unit is already translated. So `patra/explain/phrase.py` builds
the sentence from the tree at read time out of a dozen fragments in the
`phrase` section, and a language needs none of the seventy-one criterion texts
to be readable.

Hand-written text in `criterion` always wins where it exists, which is why
English and Hindi read as natural sentences and the rest read as labelled
requirements:

    वय, 60 वर्षे किंवा त्याहून जास्त
    রেশন কার্ড, এর মধ্যে একটি: অগ্রাধিকার কার্ড, অন্ত্যোদয় কার্ড

Blunter than prose, and it cannot end up saying something untrue, which
composing grammar out of labels in a language you do not speak very easily can.
It also means a scheme added tomorrow is readable in all five languages at once.

Each fragment carries its own `{v}` placeholder because word order moves.
English puts the comparison before the number and Hindi after, so a prefix
template would produce "उम्र, से ज़्यादा 60".

## Adding a language

It is a data task. No code changes.

1. Copy `data/i18n/en.yaml` to `data/i18n/<code>.yaml`.
2. Set `code`, `name` (written **in that language**, since somebody choosing
   Tamil cannot necessarily read the word "Tamil"), and `speech` to the BCP 47
   tag the browser's speech synthesiser expects.
3. Translate. Leave `complete: false` while you work.
4. Set `complete: true` once a native speaker has checked it.

Restart the server and it appears in the picker.

## What each section is for

- `ui`, the interface chrome: buttons, headings, warnings
- `attr`, one entry per fact, with `label`, `question`, `unit`, and `options`
  for the multiple-choice ones. The `question` is read aloud, so write it the
  way somebody would actually say it on a doorstep
- `doc`, document names and which office issues them
- `scheme`, scheme names, what the benefit is, and where to apply
- `criterion`, the clause that blocked somebody, keyed by scheme and criterion
  id. **This is the explanation itself.** Leaving it untranslated undoes the
  point of translating anything else

## Two traps

**YAML eats `yes` and `no`.** Under YAML 1.1 a bare `yes:` key parses as the
boolean `true`, so `ui.yes` silently never exists and the interface falls back
to English. The keys are quoted for this reason. Do not unquote them.

**Units are separate.** `annual_income` carries a unit of "rupees a year" in
the schema. Without `attr.annual_income.unit` in your file, an otherwise
perfect Hindi sentence ends in English.

## Why this can become audio

Nothing in the system generates prose. Explanations are assembled from
templates, so the set of sentences a person can ever see is finite and known in
advance. That means each one can be recorded once by a speaker of the language
and played back, which is the only real answer for somebody who cannot read at
all. Generated text would make that impossible.

The app currently uses the browser's own speech synthesiser, which needs no
network and no model but sounds robotic and is missing for some Indian
languages. Recorded audio is the upgrade path, and the architecture already
allows it.
