"""The question answerer.

People arrive with questions the interview does not cover. Which pensions
exist. What do I need for Ujjwala. How much money is it. Where do I go. What is
a domicile certificate and how do I get one.

Everything is answered from the knowledge base. Intent comes from keyword
matching, the subject from a word index built over scheme and document names in
whatever language is loaded, and the answer is looked up or computed by the
same reasoner the rest of the app uses. Nothing is generated.

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

from .model.document import DocumentGraph
from .model.scheme import Scheme
from .explain.phrase import criterion as say_criterion
from .reason.planner import Unreachable, plan


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
    UNKNOWN = "unknown"


@dataclass
class Answer:
    intent: Intent
    text: str = ""
    bullets: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    subject: str | None = None
    suggestions: list[str] = field(default_factory=list)


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
    def __init__(self, schemes, documents: DocumentGraph, words: dict, schema=None):
        self.schemes = schemes
        self.documents = documents
        self.words = words
        self.schema = schema

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

    def ask(self, question: str) -> Answer:
        folded = fold(question)
        if not folded:
            return self.dunno()

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
        return self.dunno()

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
