"""The question answerer.

People have questions the questionnaire does not cover. What is a domicile
certificate. Which schemes need Aadhaar. Why did it say no. How do I get a
ration card. Where do I go for a pension.

This answers them from the knowledge base, not from a language model. Intent is
matched by keyword against a fixed set of question shapes, the answer is looked
up or computed by the reasoner, and anything that does not match gets an honest
"I do not know that one" rather than an invention.

That is a deliberate trade. A language model would handle phrasing far better
and would occasionally state, fluently and with confidence, that somebody
qualifies for a pension they do not. In a tool about welfare entitlements the
second failure is much worse than the first, and it is the one the user cannot
detect.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

from .model.document import DocumentGraph
from .model.scheme import Scheme
from .reason.planner import Unreachable, plan


class Intent(Enum):
    WHAT_IS_DOC = "what_is_doc"
    HOW_TO_GET_DOC = "how_to_get_doc"
    WHAT_IS_SCHEME = "what_is_scheme"
    SCHEME_NEEDS = "scheme_needs"
    WHO_NEEDS_DOC = "who_needs_doc"
    WHERE_TO_APPLY = "where_to_apply"
    PRIVACY = "privacy"
    UNKNOWN = "unknown"


@dataclass
class Answer:
    intent: Intent
    text: str = ""
    """The headline sentence, already in the user's language where available."""

    bullets: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    """An acquisition route, when the question was about getting a document."""

    subject: str | None = None
    suggestions: list[str] = field(default_factory=list)
    """Questions we can answer, offered when we could not answer this one."""


def fold(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


class Assistant:
    def __init__(self, schemes: list[Scheme], documents: DocumentGraph, words: dict):
        self.schemes = schemes
        self.documents = documents
        self.words = words

    # ---- naming, in whatever language is loaded ----

    def _doc_name(self, doc_id: str) -> str:
        node = self.words.get("doc", {}).get(doc_id, {})
        return node.get("name") or self.documents[doc_id].name

    def _doc_issuer(self, doc_id: str) -> str:
        node = self.words.get("doc", {}).get(doc_id, {})
        return node.get("issuer") or self.documents[doc_id].issuer

    def _scheme_field(self, scheme: Scheme, field_name: str) -> str:
        node = self.words.get("scheme", {}).get(scheme.id, {})
        fallback = {
            "name": scheme.name,
            "benefit": " ".join(scheme.benefit.split()),
            "apply_at": scheme.apply_at,
        }[field_name]
        return node.get(field_name) or fallback

    def _criterion(self, scheme: Scheme, criterion) -> str:
        node = self.words.get("criterion", {}).get(scheme.id, {})
        return node.get(criterion.id) or criterion.text

    def _ui(self, key: str, default: str = "") -> str:
        return self.words.get("ui", {}).get(key) or default

    # ---- finding what the question is about ----

    def _find_document(self, text: str) -> str | None:
        """Match on the name in the current language and on the English id.

        Somebody typing in Hindi should be understood, and so should somebody
        typing "aadhaar" in Latin script, which is extremely common.
        """
        folded = fold(text)
        best, best_len = None, 0
        for doc in self.documents:
            for candidate in (self._doc_name(doc.id), doc.name, doc.id.replace("_", " ")):
                c = fold(candidate)
                if c and c in folded and len(c) > best_len:
                    best, best_len = doc.id, len(c)
        return best

    def _find_scheme(self, text: str) -> Scheme | None:
        folded = fold(text)
        best, best_len = None, 0
        for scheme in self.schemes:
            for candidate in (self._scheme_field(scheme, "name"), scheme.name,
                              scheme.id.replace("_", " ")):
                c = fold(candidate)
                # Short ids like "apy" would match inside unrelated words.
                if len(c) < 4:
                    continue
                if c in folded and len(c) > best_len:
                    best, best_len = scheme, len(c)
        return best

    # Keyword sets per intent, in the languages we ship. Crude on purpose: the
    # cost of a wrong match is a wrong-but-checkable answer, and the cost of a
    # miss is a polite refusal, so both are recoverable.
    HOW = ("how do i get", "how to get", "how can i get", "where do i get",
           "kaise", "कैसे", "कहाँ से", "कसे", "কীভাবে", "எப்படி")
    WHAT = ("what is", "what's", "meaning of", "kya hai", "क्या है", "काय आहे",
            "কী", "என்ன")
    NEEDS = ("what do i need", "what is needed", "requirements", "documents for",
             "kya chahiye", "क्या चाहिए", "ज़रूरी", "काय लागते", "কী লাগবে", "தேவை")
    WHO = ("which scheme", "what scheme", "which schemes", "kaun si yojana",
           "कौन सी योजना", "कोणती योजना", "কোন প্রকল্প", "எந்தத் திட்டம்")
    WHERE = ("where do i apply", "where to apply", "kahan jaana", "कहाँ जाएँ",
             "कहाँ जाना", "कुठे जायचे", "কোথায় যাব", "எங்கே")
    PRIVATE = ("private", "safe", "data", "store", "privacy", "सुरक्षित",
               "निजी", "डेटा", "गोपनीय")

    def ask(self, question: str) -> Answer:
        folded = fold(question)
        if not folded:
            return self._dunno()

        if any(k in folded for k in self.PRIVATE):
            return Answer(
                intent=Intent.PRIVACY,
                text=self._ui("privacy", "Your answers stay on this device."),
                bullets=[
                    self._ui("assist_privacy_1",
                             "Nothing is sent over the internet."),
                    self._ui("assist_privacy_2",
                             "Nothing is saved after you close the page."),
                    self._ui("assist_privacy_3",
                             "We never ask for your Aadhaar number, only whether "
                             "your account is linked."),
                ],
            )

        doc = self._find_document(question)
        scheme = self._find_scheme(question)

        if doc and any(k in folded for k in self.HOW):
            return self._how_to_get(doc)
        if doc and any(k in folded for k in self.WHO):
            return self._who_needs(doc)
        if doc and any(k in folded for k in self.WHAT):
            return self._what_is_doc(doc)

        if scheme and any(k in folded for k in self.WHERE):
            return self._where_to_apply(scheme)
        if scheme and any(k in folded for k in (*self.NEEDS, *self.HOW)):
            return self._scheme_needs(scheme)
        if scheme:
            return self._what_is_scheme(scheme)

        # A bare document name with no question word is almost always "what is
        # this", which is the commonest thing people type.
        if doc:
            return self._what_is_doc(doc)

        return self._dunno()

    # ---- the answers ----

    def _what_is_doc(self, doc_id: str) -> Answer:
        doc = self.documents[doc_id]
        wanted = [s for s in self.schemes if doc_id in s.documents]
        bullets = [f"{self._ui('papers_where', 'Go to')}: {self._doc_issuer(doc_id)}"]
        if doc.fee:
            bullets.append(f"{self._ui('papers_cost', 'Cost')}: Rs {doc.fee}")
        if doc.days:
            bullets.append(self._ui("papers_time", "About {days} days")
                           .replace("{days}", str(doc.days)))
        if doc.note:
            bullets.append(" ".join(doc.note.split()))
        if wanted:
            names = ", ".join(self._scheme_field(s, "name") for s in wanted[:4])
            bullets.append(f"{self._ui('assist_used_by', 'Needed for')}: {names}")
        return Answer(intent=Intent.WHAT_IS_DOC, text=self._doc_name(doc_id),
                      bullets=bullets, subject=doc_id)

    def _how_to_get(self, doc_id: str) -> Answer:
        try:
            route = plan(self.documents, [doc_id], held=set())
        except Unreachable:
            return Answer(intent=Intent.HOW_TO_GET_DOC,
                          text=self._doc_name(doc_id),
                          bullets=[self._ui("assist_no_route",
                                            "We could not work out a route to this one.")])
        steps = [
            {
                "name": self._doc_name(s.id),
                "issuer": self._doc_issuer(s.id),
                "fee": s.document.fee,
                "days": s.document.days,
                "trips": s.document.trips,
            }
            for s in route.steps
        ]
        return Answer(
            intent=Intent.HOW_TO_GET_DOC,
            text=self._doc_name(doc_id),
            bullets=[self._ui("papers_summary", "About {trips} trips, Rs {fee}, {days} days")
                     .replace("{trips}", str(route.trips))
                     .replace("{fee}", str(route.fee))
                     .replace("{days}", str(route.days))],
            steps=steps,
            subject=doc_id,
        )

    def _who_needs(self, doc_id: str) -> Answer:
        wanted = [s for s in self.schemes if doc_id in s.documents]
        return Answer(
            intent=Intent.WHO_NEEDS_DOC,
            text=self._doc_name(doc_id),
            bullets=[self._scheme_field(s, "name") for s in wanted]
                    or [self._ui("assist_none", "No scheme in our list needs this.")],
            subject=doc_id,
        )

    def _what_is_scheme(self, scheme: Scheme) -> Answer:
        return Answer(
            intent=Intent.WHAT_IS_SCHEME,
            text=self._scheme_field(scheme, "name"),
            bullets=[
                self._scheme_field(scheme, "benefit"),
                f"{self._ui('apply_at', 'Go to')}: {self._scheme_field(scheme, 'apply_at')}",
            ],
            subject=scheme.id,
        )

    def _scheme_needs(self, scheme: Scheme) -> Answer:
        bullets = [self._criterion(scheme, c) for c in scheme.criteria]
        if scheme.documents:
            names = ", ".join(self._doc_name(d) for d in scheme.documents
                              if d in self.documents)
            bullets.append(f"{self._ui('assist_papers', 'Papers')}: {names}")
        return Answer(intent=Intent.SCHEME_NEEDS,
                      text=self._scheme_field(scheme, "name"),
                      bullets=bullets, subject=scheme.id)

    def _where_to_apply(self, scheme: Scheme) -> Answer:
        return Answer(intent=Intent.WHERE_TO_APPLY,
                      text=self._scheme_field(scheme, "name"),
                      bullets=[self._scheme_field(scheme, "apply_at")],
                      subject=scheme.id)

    def _dunno(self) -> Answer:
        """Say so, and show what can be asked instead.

        Offering examples turns a dead end into a working query, which matters
        far more here than pretending to have understood.
        """
        examples = []
        if self.documents.ids:
            first = self._doc_name("ration_card") if "ration_card" in self.documents \
                    else self._doc_name(self.documents.ids[0])
            examples.append(f"{self._ui('assist_eg_how', 'How do I get')} {first}?")
            examples.append(f"{self._ui('assist_eg_what', 'What is')} {first}?")
        if self.schemes:
            examples.append(
                f"{self._ui('assist_eg_needs', 'What do I need for')} "
                f"{self._scheme_field(self.schemes[0], 'name')}?"
            )
        return Answer(
            intent=Intent.UNKNOWN,
            text=self._ui("assist_unknown",
                          "I do not know that one. I can only answer about the "
                          "schemes and papers in this app."),
            suggestions=examples,
        )
