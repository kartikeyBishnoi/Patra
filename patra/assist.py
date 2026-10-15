"""The question answerer.

People arrive with questions the interview does not cover. Which pensions
exist. What do I need for Ujjwala. How much money is it. Where do I go. What is
a domicile certificate and how do I get one.

They also arrive with the three questions the rest of the app exists to answer,
phrased as conversation: what if we earned more, what should I do next, and am
I actually going to get this.

Everything is answered from the knowledge base. Intent comes from keyword
matching, the subject from a word index built over scheme and document names in
whatever language is loaded, and the answer is looked up or computed by the
same reasoner the rest of the app uses. Nothing is generated.

The three new questions are not answered here at all, they are forwarded. A
"what if" becomes a simulation, a "what next" becomes a ranked action list, and
"am I eligible" goes through `patra.guard`, which will not let an answer out
unless the solver derived it. So the assistant can decline to answer its most
important question, and does, which is the behaviour worth having.

A language model would read phrasing far better. It would also, now and then,
state fluently that somebody qualifies for a pension they do not, and the
person reading it has no way to tell. Between a tool that sometimes says "ask
me differently" and one that sometimes invents an entitlement, the first is the
only defensible choice here.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

from .advise import Move, next_actions
from .guard import Guard
from .model.document import DocumentGraph
from .model.scheme import Scheme
from .explain.phrase import criterion as say_criterion
from .nlp.extract import Extractor
from .reason.planner import Unreachable, plan
from .reason.simulate import simulate


class Intent(Enum):
    LIST_SCHEMES = "list_schemes"
    SCHEME_ABOUT = "scheme_about"
    SCHEME_NEEDS = "scheme_needs"
    SCHEME_DOCS = "scheme_docs"
    SCHEME_WHERE = "scheme_where"
    DOC_ABOUT = "doc_about"
    DOC_HOW = "doc_how"
    DOC_WHO = "doc_who"
    PRIVACY = "privacy"

    WHAT_IF = "what_if"
    """A changed answer, re-decided against every scheme."""

    WHAT_NEXT = "what_next"
    """The ranked errands, cheapest useful one first."""

    ELIGIBLE = "eligible"
    """A direct question about entitlement. Answered only if the solver did."""

    UNVERIFIED = "unverified"
    """Asked about entitlement and we would not stand behind an answer."""

    FACTS = "facts"
    """A statement rather than a question, read into the profile."""

    UNKNOWN = "unknown"


@dataclass
class Answer:
    intent: Intent
    text: str = ""
    bullets: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    subject: str | None = None
    suggestions: list[str] = field(default_factory=list)
    apply: dict = field(default_factory=dict)
    """Facts the person could adopt, offered as one button rather than taken.

    The chat window is a conversation, not the interview. Reading a statement
    back and then quietly changing answers given on another screen would be
    the worst kind of helpful, so the adoption is theirs to make.
    """


def fold(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def words_of(text: str) -> set[str]:
    return {w for w in re.split(r"[^\wऀ-෿]+", fold(text)) if len(w) > 2}


# Topic words that should find a scheme even when its official name is never
# typed. Somebody says "pension", not "Indira Gandhi National Old Age Pension".
TOPICS = {
    "ignoaps":     ["pension", "old age", "elderly", "60", "sixty", "बुढ़ापा", "वृद्ध", "पेंशन", "बुजुर्ग"],
    "ignwps":      ["widow", "pension", "husband died", "विधवा", "पेंशन", "पति"],
    "igndps":      ["disability", "disabled", "handicap", "pension", "दिव्यांग", "विकलांग", "पेंशन"],
    "pm_kisan":    ["kisan", "farmer", "farming", "6000", "किसान", "खेती", "सम्मान"],
    "ration_aay":  ["ration", "antyodaya", "grain", "wheat", "rice", "food", "राशन", "अनाज", "अंत्योदय"],
    "ration_phh":  ["ration", "priority", "grain", "food", "राशन", "अनाज", "प्राथमिकता"],
    "pmay_g":      ["house", "housing", "awas", "pucca", "घर", "मकान", "आवास"],
    "pmuy":        ["gas", "lpg", "ujjwala", "cylinder", "गैस", "उज्ज्वला", "सिलेंडर", "चूल्हा"],
    "pmjay":       ["health", "hospital", "illness", "ayushman", "treatment", "इलाज", "अस्पताल", "आयुष्मान", "बीमारी"],
    "pmmvy":       ["pregnant", "maternity", "matru", "baby", "गर्भ", "मातृ", "बच्चा", "प्रसव"],
    "jsy":         ["delivery", "janani", "hospital birth", "pregnant", "जननी", "प्रसव", "गर्भ"],
    "mgnrega":     ["work", "job", "employment", "mgnrega", "nrega", "labour", "wage", "काम", "मज़दूरी", "रोज़गार", "मनरेगा"],
    "sukanya":     ["girl", "daughter", "savings", "sukanya", "बेटी", "लड़की", "बचत", "सुकन्या"],
    "apy":         ["pension", "atal", "savings", "अटल", "पेंशन", "बचत"],
    "jan_dhan":    ["bank", "account", "jan dhan", "खाता", "बैंक", "जनधन"],
    "pmsby":       ["accident", "insurance", "suraksha", "दुर्घटना", "बीमा", "सुरक्षा"],
    "pmjjby":      ["life insurance", "insurance", "jeevan", "जीवन", "बीमा"],
    "kcc":         ["credit", "loan", "kisan credit", "कर्ज़", "ऋण", "क्रेडिट"],
    "nfbs":        ["death", "died", "family benefit", "मृत्यु", "देहांत", "परिवार लाभ"],
    "pmfby":       ["crop", "fasal", "insurance", "harvest", "फ़सल", "बीमा", "खेती"],
}


class Assistant:
    """Answers from the knowledge base, and forwards the rest to the reasoner.

    `engine` and `facts` are optional because the assistant is also useful
    before the interview starts, when there is nothing to reason about. With
    them it can simulate, advise and verify; without them those questions get
    an honest "answer the questions first" rather than a guess.
    """

    def __init__(self, schemes, documents: DocumentGraph, words: dict, schema=None,
                 engine=None, facts=None, held=()):
        self.schemes = schemes
        self.documents = documents
        self.words = words
        self.schema = schema
        self.engine = engine
        self.facts = dict(facts or {})
        self.held = set(held)
        self.guard = Guard(engine, schema) if engine is not None and schema else None
        self.extractor = Extractor(schema) if schema is not None else None

    # ---- naming, in whatever language is loaded ----

    def doc_name(self, doc_id):
        return self.words.get("doc", {}).get(doc_id, {}).get("name") \
            or self.documents[doc_id].name

    def doc_issuer(self, doc_id):
        return self.words.get("doc", {}).get(doc_id, {}).get("issuer") \
            or self.documents[doc_id].issuer

    def sch(self, scheme, field_name):
        node = self.words.get("scheme", {}).get(scheme.id, {})
        fallback = {"name": scheme.name,
                    "benefit": " ".join(scheme.benefit.split()),
                    "apply_at": scheme.apply_at}[field_name]
        return node.get(field_name) or fallback

    def crit(self, scheme, criterion):
        if self.schema is not None:
            return say_criterion(self.schema, self.words, scheme.id, criterion)
        return self.words.get("criterion", {}).get(scheme.id, {}).get(criterion.id) \
            or criterion.text

    def ui(self, key, default=""):
        return self.words.get("ui", {}).get(key) or default

    # ---- finding the subject ----

    def find_scheme(self, text):
        """Longest name match first, then topic words, then shared vocabulary.

        Three passes because people refer to schemes three ways: by the official
        name, by what it is for, and by a word from the benefit description.
        """
        folded, tokens = fold(text), words_of(text)

        best, best_len = None, 0
        for s in self.schemes:
            for cand in (self.sch(s, "name"), s.name):
                c = fold(cand)
                if len(c) > 5 and c in folded and len(c) > best_len:
                    best, best_len = s, len(c)
        if best:
            return best

        scored = {}
        by_id = {s.id: s for s in self.schemes}
        for sid, topics in TOPICS.items():
            if sid not in by_id:
                continue
            hits = sum(1 for kw in topics if fold(kw) in folded)
            if hits:
                scored[sid] = hits * 10
        if scored:
            return by_id[max(scored, key=scored.get)]

        for s in self.schemes:
            shared = tokens & (words_of(self.sch(s, "name")) | words_of(self.sch(s, "benefit")))
            if shared:
                scored[s.id] = len(shared)
        return by_id[max(scored, key=scored.get)] if scored else None

    def find_doc(self, text):
        folded = fold(text)
        best, best_len = None, 0
        for d in self.documents:
            for cand in (self.doc_name(d.id), d.name, d.id.replace("_", " ")):
                c = fold(cand)
                if len(c) > 3 and c in folded and len(c) > best_len:
                    best, best_len = d.id, len(c)
        return best

    HOW    = ("how do i get","how to get","how can i get","where do i get","how do i make",
              "kaise","कैसे","कहाँ से","बनवा","कसे","কীভাবে","எப்படி")
    WHAT   = ("what is","what's","meaning","tell me about","about","kya hai","क्या है",
              "के बारे","बताइए","बताओ","काय आहे","কী","என்ன")
    NEEDS  = ("what do i need","need for","required","requirement","eligib","qualify",
              "criteria","kya chahiye","क्या चाहिए","ज़रूरी","पात्र","योग्य","शर्त",
              "काय लागते","কী লাগবে","தேவை")
    DOCS   = ("which document","what document","papers for","documents for","kaunse kagaz",
              "कौन से कागज़","कागज़","दस्तावेज़")
    WHERE  = ("where do i apply","where to apply","where should i go","kahan","कहाँ",
              "कुठे","কোথায়","எங்கே")
    LIST   = ("what schemes","which schemes","list","all schemes","show me schemes",
              "kya kya","कौन कौन","कौन सी योजना","सारी योजना","योजनाएँ","सब योजना")
    WHO    = ("which scheme needs","who needs","what needs this","kis yojana",
              "किस योजना","किन योजना")
    PRIVATE= ("private","safe","secure","my data","privacy","सुरक्षित","निजी","डेटा","गोपनीय")
    WHATIF = ("what if","what happens if","what would happen","suppose","if my","if we",
              "agar","agar meri","agar mera","अगर","यदि","मान लो","जर","যদি","ধরা যাক","என்றால்")
    NEXT   = ("what next","what should i do","what do i do","what am i missing","anything else",
              "what more","aur kya","kya karna","kya karu","mujhe aur","और क्या","क्या करना",
              "क्या करूँ","मुझे और","आगे क्या","पुढे काय","আর কী","এখন কী","இன்னும் என்ன")
    ELIGQ  = ("am i eligible","do i qualify","will i get","can i get","do i get","am i entitled",
              "mujhe milega","mujhe milegi","milega kya","milegi kya","main patra",
              "मुझे मिलेगा","मुझे मिलेगी","मिलेगा क्या","मिलेगी क्या","मिलेगी या नहीं",
              "पात्र हूँ","पात्र हूं","पात्र हैं","मिल सकता","मिल सकती",
              "मी पात्र","मला मिळेल का","আমি কি পাব","যোগ্য কি","எனக்கு கிடைக்குமா",
              "தகுதி உண்டா")

    def ask(self, question: str) -> Answer:
        folded = fold(question)
        if not folded:
            return self.dunno()

        # Asked before the knowledge-base lookups, because "what if we earned
        # a lakh" names no scheme and would otherwise fall through to the
        # topic matcher and come back with something about farmers.
        if any(k in folded for k in self.WHATIF):
            return self.what_if(question)
        if any(k in folded for k in self.NEXT):
            return self.what_next()
        # Three questions share their verbs and mean different things:
        # "kahan se milegi" asks where to go, "kaise milegi" asks how to get
        # it, and "mujhe milegi kya" asks whether they qualify. English
        # collides the same way, since "how do I get" contains "do I get".
        # Place and method win, because they are the more specific ask.
        if any(k in folded for k in self.ELIGQ) \
                and not any(k in folded for k in self.WHERE) \
                and not any(k in folded for k in self.HOW):
            return self.eligible(self.find_scheme(question))

        if any(k in folded for k in self.PRIVATE):
            return Answer(Intent.PRIVACY, self.ui("privacy", "Your answers stay here."),
                          [self.ui("assist_privacy_1", "Nothing is sent over the internet."),
                           self.ui("assist_privacy_2", "Nothing is saved."),
                           self.ui("assist_privacy_3", "We never ask for your Aadhaar number.")])

        doc = self.find_doc(question)

        # A document question beats a scheme question when the document is
        # named outright, because "how do I get a ration card" is about the
        # card even though ration schemes exist.
        if doc:
            if any(k in folded for k in self.HOW):
                return self.doc_how(doc)
            if any(k in folded for k in self.WHO):
                return self.doc_who(doc)
            scheme_named = any(fold(self.sch(s, "name")) in folded for s in self.schemes)
            if not scheme_named:
                return self.doc_about(doc)

        if any(k in folded for k in self.LIST):
            return self.list_schemes(question)

        scheme = self.find_scheme(question)
        if scheme:
            if any(k in folded for k in self.DOCS):
                return self.scheme_docs(scheme)
            if any(k in folded for k in self.WHERE):
                return self.scheme_where(scheme)
            if any(k in folded for k in (*self.NEEDS, *self.HOW)):
                return self.scheme_needs(scheme)
            return self.scheme_about(scheme)

        if doc:
            return self.doc_about(doc)

        # Not a question at all. "Meri maa 62 saal ki hain" is somebody
        # answering, and reading it beats apologising at them.
        told = self.facts_told(question)
        if told is not None:
            return told
        return self.dunno()

    # ---- the reasoning questions ----

    def what_if(self, question: str) -> Answer:
        """Re-decide everything against one changed answer.

        Both directions are reported. A change that gains three schemes and
        quietly costs two is not an improvement, and somebody weighing up a
        better-paying job is entitled to see the whole trade.
        """
        if self.engine is None or not self.facts:
            return Answer(Intent.WHAT_IF,
                          self.ui("assist_need_answers",
                                  "Answer the questions first, then I can try this."))
        if self.extractor is None:
            return self.dunno()

        reading = self.extractor.understand(question)
        changes = {m.attribute: m.value for m in reading.mentions
                   if m.attribute in self.facts}
        if not changes:
            return Answer(Intent.WHAT_IF,
                          self.ui("assist_whatif_how",
                                  "Tell me the new number, like: what if our income was 80000"))

        result = simulate(self.engine, self.schema, self.schemes,
                          self.facts, changes)

        if result.impossible:
            shift, axiom = result.impossible[0]
            return Answer(Intent.WHAT_IF,
                          self.ui("assist_whatif_impossible",
                                  "That cannot be true of anybody."),
                          [axiom])

        bullets = []
        for shift in result.shifts:
            bullets.append(f"{self.label(shift.attribute)}: "
                           f"{self.said(shift.attribute, shift.was)} → "
                           f"{self.said(shift.attribute, shift.now)}")
        bullets.append(self.ui("assist_whatif_count",
                               "Now {before}, after the change {after}")
                       .replace("{before}", str(len(result.before)))
                       .replace("{after}", str(len(result.after))))
        for scheme_id in result.gained:
            bullets.append("+ " + self.name_of(scheme_id))
        for loss in result.lost:
            line = "− " + self.name_of(loss.scheme_id)
            if loss.blocked_by:
                line += ": " + self.crit_of(loss.scheme_id, loss.blocked_by[0])
            bullets.append(line)
        if not result.gained and not result.lost:
            bullets.append(self.ui("assist_whatif_same",
                                   "Nothing changes either way."))

        return Answer(Intent.WHAT_IF,
                      self.ui("assist_whatif_title", "If that were different"),
                      bullets)

    def what_next(self) -> Answer:
        """The ranked errands. Counts are re-derived, never tallied."""
        if self.engine is None or not self.facts:
            return Answer(Intent.WHAT_NEXT,
                          self.ui("assist_need_answers",
                                  "Answer the questions first, then I can try this."))

        advice = next_actions(self.engine, self.schema, self.schemes,
                              self.facts, self.documents, self.held, limit=3)
        bullets = [
            self.ui("assist_next_have", "You can claim {n} now")
                .replace("{n}", str(len(advice.eligible))),
        ]
        if advice.reachable:
            bullets.append(self.ui("assist_next_more", "{n} more are within reach")
                           .replace("{n}", str(len(advice.reachable))))
        for i, action in enumerate(advice.actions, 1):
            bullets.append(f"{i}. {self.describe(action)}")
            if action.unlocks:
                bullets.append("   " + self.ui("papers_unlocks", "Opens up") + ": "
                               + ", ".join(self.name_of(s) for s in action.unlocks))
        if not advice.actions:
            bullets.append(self.ui("assist_next_none",
                                   "Nothing left that would change the answer."))
        return Answer(Intent.WHAT_NEXT,
                      self.ui("assist_next_title", "What to do next"), bullets)

    def eligible(self, scheme) -> Answer:
        """The one question the assistant is not allowed to answer by itself.

        The guard re-derives it from the solver. Where a fact the scheme reads
        is missing there is no answer to give, and saying so is the whole
        point: a confident guess here is indistinguishable from knowledge and
        costs somebody a day's wages at an office counter.
        """
        if scheme is None:
            return Answer(Intent.UNVERIFIED,
                          self.ui("assist_which_scheme", "Which scheme do you mean?"),
                          [self.sch(s, "name") for s in self.schemes[:6]])
        if self.guard is None or not self.facts:
            return Answer(Intent.UNVERIFIED,
                          self.ui("assist_need_answers",
                                  "Answer the questions first, then I can try this."),
                          subject=scheme.id)

        check = self.guard.verify(scheme, self.facts)
        if not check.sayable:
            bullets = [self.ui("assist_cannot_verify",
                               "PATRA could not verify this.")]
            if check.missing:
                bullets.append(self.ui("undecided_need", "We still need") + ": "
                               + ", ".join(self.label(m) for m in check.missing))
            return Answer(Intent.UNVERIFIED, self.sch(scheme, "name"), bullets,
                          subject=scheme.id)

        if check.eligible:
            return Answer(Intent.ELIGIBLE, self.sch(scheme, "name"), [
                self.ui("assist_yes_eligible", "Yes, by these rules you qualify."),
                self.sch(scheme, "benefit"),
                f"{self.ui('apply_at','Go to')}: {self.sch(scheme,'apply_at')}",
            ], subject=scheme.id)

        bullets = [self.ui("assist_not_eligible", "Not by these rules, not yet.")]
        fixes, hopeless, _, redundant = self.engine.repairs(
            scheme, self._profile())
        if redundant:
            bullets.append(self.ui("near_redundant",
                                   "You already have what this provides."))
        elif hopeless:
            bullets.append(self.ui("near_hopeless",
                                   "Nothing you can do would change this one."))
        elif fixes:
            for change in fixes[0].changes:
                bullets.append(f"{self.label(change.attribute)}: "
                               f"{self.said(change.attribute, change.now)} → "
                               f"{self.said(change.attribute, change.needed)}")
        return Answer(Intent.ELIGIBLE, self.sch(scheme, "name"), bullets,
                      subject=scheme.id)

    def facts_told(self, text: str) -> Answer | None:
        """Read a statement back, with the words each fact came from."""
        if self.extractor is None or self.guard is None:
            return None
        reading = self.extractor.understand(text)
        if not reading.mentions:
            return None

        intake = self.guard.admit_understanding(reading, self.facts)
        bullets = []
        for admitted in intake.accepted:
            bullets.append(f"{self.label(admitted.attribute)}: "
                           f"{self.said(admitted.attribute, admitted.value)}")
        for query in intake.confirm:
            bullets.append(f"{self.label(query.attribute)}: "
                           f"{self.said(query.attribute, query.value)}?")
        for refusal in intake.refused:
            bullets.append(f"{self.label(refusal.attribute)}: "
                           + (refusal.axiom or self.ui("assist_not_usable",
                                                       "that cannot be right")))
        if not bullets:
            return None
        if intake.accepted:
            bullets.append(self.ui("assist_facts_note",
                                   "Tap below to use these answers."))
        return Answer(Intent.FACTS,
                      self.ui("assist_facts_title", "This is what I understood"),
                      bullets,
                      apply={a.attribute: a.value for a in intake.accepted})

    # ---- naming the things the reasoner hands back ----

    def label(self, attribute: str) -> str:
        node = self.words.get("attr", {}).get(attribute, {})
        if node.get("label"):
            return node["label"]
        return self.schema[attribute].label if self.schema else attribute

    def said(self, attribute: str, value) -> str:
        """A value the way it should be read out, in the chosen language."""
        if value is None:
            return self.ui("assist_unset", "not given")
        attr = self.schema[attribute] if self.schema else None
        if attr is None:
            return str(value)
        if isinstance(value, bool):
            return self.ui("yes", "Yes") if value else self.ui("no", "No")
        if attr.options:
            return self.words.get("attr", {}).get(attribute, {}) \
                .get("options", {}).get(value, str(value).replace("_", " "))
        unit = self.words.get("attr", {}).get(attribute, {}).get("unit") or attr.unit
        text = f"{value:,}" if isinstance(value, int) else str(value)
        if attr.open_ended and attr.high is not None and value >= attr.high:
            text += "+"
        return f"{text} {unit}" if unit else text

    def name_of(self, scheme_id: str) -> str:
        found = next((s for s in self.schemes if s.id == scheme_id), None)
        return self.sch(found, "name") if found else scheme_id

    def crit_of(self, scheme_id: str, rule) -> str:
        found = next((s for s in self.schemes if s.id == scheme_id), None)
        if found is None:
            return rule.text
        criterion = next((c for c in found.criteria if c.id == rule.id), None)
        return self.crit(found, criterion) if criterion else rule.text

    def describe(self, action) -> str:
        if action.move is Move.FACT:
            line = (f"{self.label(action.attribute)}: "
                    f"{self.said(action.attribute, action.now)} → "
                    f"{self.said(action.attribute, action.needed)}")
        elif action.errand:
            line = self.doc_name(action.errand.document)
        else:
            line = action.key
        if action.errand:
            line += f" ({self.doc_issuer(action.errand.document)})"
        return line

    def _profile(self):
        from .model.household import Profile
        return Profile(id="assist", facts=dict(self.facts))

    # ---- answers ----

    def list_schemes(self, question):
        """All of them, or the ones matching a topic word in the question."""
        folded = fold(question)
        by_id = {s.id: s for s in self.schemes}
        picked = [by_id[sid] for sid, topics in TOPICS.items()
                  if sid in by_id and any(fold(k) in folded for k in topics)]
        chosen = picked or self.schemes
        return Answer(
            Intent.LIST_SCHEMES,
            self.ui("assist_list", "Schemes in this app") + f" ({len(chosen)})",
            [self.sch(s, "name") for s in chosen],
            suggestions=[f"{self.ui('assist_eg_needs','What do I need for')} "
                         f"{self.sch(chosen[0], 'name')}?"] if chosen else [],
        )

    def scheme_about(self, s):
        return Answer(Intent.SCHEME_ABOUT, self.sch(s, "name"), [
            self.sch(s, "benefit"),
            f"{self.ui('apply_at','Go to')}: {self.sch(s,'apply_at')}",
        ], subject=s.id, suggestions=[
            f"{self.ui('assist_eg_needs','What do I need for')} {self.sch(s,'name')}?",
        ])

    def scheme_needs(self, s):
        bullets = [self.crit(s, c) for c in s.criteria]
        if s.documents:
            names = ", ".join(self.doc_name(d) for d in s.documents if d in self.documents)
            bullets.append(f"{self.ui('assist_papers','Papers')}: {names}")
        return Answer(Intent.SCHEME_NEEDS, self.sch(s, "name"), bullets, subject=s.id)

    def scheme_docs(self, s):
        have = [d for d in s.documents if d in self.documents]
        return Answer(Intent.SCHEME_DOCS, self.sch(s, "name"),
                      [self.doc_name(d) for d in have]
                      or [self.ui("assist_none", "No papers listed.")],
                      subject=s.id,
                      suggestions=[f"{self.ui('assist_eg_how','How do I get')} "
                                   f"{self.doc_name(have[0])}?"] if have else [])

    def scheme_where(self, s):
        return Answer(Intent.SCHEME_WHERE, self.sch(s, "name"),
                      [self.sch(s, "apply_at")], subject=s.id)

    def doc_about(self, doc_id):
        d = self.documents[doc_id]
        used = [s for s in self.schemes if doc_id in s.documents]
        bullets = [f"{self.ui('papers_where','Go to')}: {self.doc_issuer(doc_id)}"]
        if d.fee:
            bullets.append(f"{self.ui('papers_cost','Cost')}: Rs {d.fee}")
        if d.days:
            bullets.append(self.ui("papers_time", "About {days} days").replace("{days}", str(d.days)))
        if d.note:
            bullets.append(" ".join(d.note.split()))
        if used:
            bullets.append(f"{self.ui('assist_used_by','Needed for')}: "
                           + ", ".join(self.sch(s, "name") for s in used[:4]))
        return Answer(Intent.DOC_ABOUT, self.doc_name(doc_id), bullets, subject=doc_id,
                      suggestions=[f"{self.ui('assist_eg_how','How do I get')} "
                                   f"{self.doc_name(doc_id)}?"])

    def doc_how(self, doc_id):
        try:
            route = plan(self.documents, [doc_id], held=set())
        except Unreachable:
            return Answer(Intent.DOC_HOW, self.doc_name(doc_id),
                          [self.ui("assist_no_route", "No route found.")])
        return Answer(
            Intent.DOC_HOW, self.doc_name(doc_id),
            [self.ui("papers_summary", "About {trips} trips, Rs {fee}, {days} days")
                 .replace("{trips}", str(route.trips))
                 .replace("{fee}", str(route.fee))
                 .replace("{days}", str(route.days))],
            steps=[{"name": self.doc_name(s.id), "issuer": self.doc_issuer(s.id),
                    "fee": s.document.fee, "days": s.document.days,
                    "trips": s.document.trips} for s in route.steps],
            subject=doc_id)

    def doc_who(self, doc_id):
        used = [s for s in self.schemes if doc_id in s.documents]
        return Answer(Intent.DOC_WHO, self.doc_name(doc_id),
                      [self.sch(s, "name") for s in used]
                      or [self.ui("assist_none", "No scheme in this app needs it.")],
                      subject=doc_id)

    def dunno(self):
        """Say so, and hand back questions that do work.

        A dead end that shows three working examples turns into a useful query
        far more often than one that just apologises.
        """
        eg = []
        if self.schemes:
            eg.append(self.ui("chat_eg_list", "What schemes are there?"))
            eg.append(f"{self.ui('assist_eg_needs','What do I need for')} "
                      f"{self.sch(self.schemes[0], 'name')}?")
        if "ration_card" in self.documents:
            eg.append(f"{self.ui('assist_eg_how','How do I get')} "
                      f"{self.doc_name('ration_card')}?")
        return Answer(Intent.UNKNOWN,
                      self.ui("assist_unknown", "I do not know that one."),
                      suggestions=eg)
