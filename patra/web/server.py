"""The local web app.

Binds to localhost only. There is no remote service, because the reasoning is a
solver and some YAML rather than a model that needs a server. Answers about
caste, income and disability cannot leak to us because they never reach us.

Standard library only, so it starts anywhere Python does.

    python3 -m patra.web.server
"""

from __future__ import annotations

import hashlib
import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..encode.loader import (
    load_axioms,
    load_documents,
    load_schema,
    load_schemes,
)
from ..assist import Assistant
from ..engine import Engine, Trust
from ..i18n import Translations
from ..model.attributes import Kind
from ..model.household import Profile
from ..model.scheme import say
from ..reason.questions import Status, next_question, status
from ..explain.phrase import criterion as say_criterion
from ..explain.trace import decision_trace, paperwork_trace
from ..reason.unlock import ladder

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "data"
AUDIO = DATA / "audio"


def dig(tree, *path, default=None):
    """Read a nested key, returning `default` rather than raising."""
    node = tree
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node if node not in (None, "") else default


class Brain:
    """Everything loaded once, shared across requests.

    Z3 is not thread safe. Its terms and solvers belong to a context, and two
    threads touching one context at the same moment takes the whole process
    down rather than raising anything catchable. A thread per request plus one
    shared engine is a crash waiting for a second visitor, which is exactly
    what happened the first time this ran.

    Reasoning is therefore serialised behind a lock. Requests take
    milliseconds and the audience is one person on one phone, so the queue
    costs nothing. Serving the page stays outside the lock.
    """

    def __init__(self, data_dir: Path = DATA):
        self.schema = load_schema(data_dir / "attributes.yaml")
        self.schemes = load_schemes(data_dir / "schemes", self.schema)
        self.documents = load_documents(data_dir / "documents.yaml")
        self.axioms = load_axioms(data_dir / "axioms.yaml", self.schema)
        self.engine = Engine(self.schema, self.axioms, self.documents)
        self.translations = Translations(data_dir / "i18n")
        self._lock = threading.Lock()

    # ---- naming things in the chosen language ----

    def attr_label(self, words, name: str) -> str:
        return dig(words, "attr", name, "label", default=self.schema[name].label)

    def attr_question(self, words, name: str) -> str:
        return dig(words, "attr", name, "question", default=self.schema[name].question)

    def option_label(self, words, name: str, value: str) -> str:
        return dig(words, "attr", name, "options", value,
                   default=str(value).replace("_", " "))

    def criterion_text(self, words, scheme_id: str, rule) -> str:
        """The clause that blocked somebody, in their own language.

        This is the explanation itself, so leaving it in English would undo
        the point of translating anything else.
        """
        crit = next((c for s in self.schemes if s.id == scheme_id
                     for c in s.criteria if c.id == rule.id), None)
        if crit is None:
            return dig(words, "criterion", scheme_id, rule.id, default=rule.text)
        return say_criterion(self.schema, words, scheme_id, crit)

    def scheme_text(self, words, scheme, field: str) -> str:
        fallback = {"name": scheme.name, "benefit": " ".join(scheme.benefit.split()),
                    "apply_at": scheme.apply_at}[field]
        return dig(words, "scheme", scheme.id, field, default=fallback)

    def doc_text(self, words, doc, field: str) -> str:
        fallback = doc.name if field == "name" else doc.issuer
        return dig(words, "doc", doc.id, field, default=fallback)

    def value_text(self, words, name: str, raw) -> str:
        """Render a value the way it should be read aloud."""
        attr = self.schema[name]
        if attr.kind is Kind.BOOL:
            key = "yes" if raw else "no"
            return dig(words, "ui", key, default=key)
        if attr.kind is Kind.ENUM:
            return self.option_label(words, name, raw)
        unit = dig(words, "attr", name, "unit", default=attr.unit)
        text = f"{raw:,}" if isinstance(raw, int) else str(raw)
        if attr.open_ended and attr.high is not None and raw >= attr.high:
            text += "+"
        return f"{text} {unit}" if unit else text

    # ---- the interview ----

    def question_for(self, facts: dict, words) -> dict | None:
        known = Profile(id="web", facts=facts)
        with self._lock:
            q = next_question(self.engine, self.schema, self.schemes, known)
        if q is None:
            return None

        attr = self.schema[q.attribute]
        return {
            "attribute": q.attribute,
            "text": self.attr_question(words, q.attribute),
            "label": self.attr_label(words, q.attribute),
            "kind": attr.kind.value,
            "sensitive": attr.sensitive,
            "options": [
                {"value": v, "label": self.option_label(words, q.attribute, v)}
                for v in attr.options
            ],
            "unit": attr.unit,
            "low": attr.low,
            "high": attr.high,
        }

    def result_for(self, facts: dict, documents: list[str], words) -> dict:
        with self._lock:
            return self._result(facts, documents, words)

    def _result(self, facts, documents, words):
        known = Profile(id="web", facts=facts)

        clashes = self.engine.inconsistencies(known)
        if clashes:
            return {
                "clashes": [
                    {
                        "rule": [a.text for a in c.axioms],
                        "answers": [
                            {
                                "label": self.attr_label(words, f.attribute),
                                "value": self.value_text(
                                    words, f.attribute, facts[f.attribute]
                                ),
                            }
                            for f in c.facts if f.attribute in facts
                        ],
                    }
                    for c in clashes
                ],
                "claims": [], "near": [], "paperwork": None,
            }

        claims, near, undecided = [], [], []
        for scheme in self.schemes:
            state = status(self.engine, scheme, known)
            if state is Status.INELIGIBLE:
                continue
            if state is Status.OPEN:
                # Skipping a question used to make these vanish silently, so a
                # scheme somebody might well qualify for simply never appeared.
                missing = sorted(scheme.attributes_used - set(known.facts))
                undecided.append({
                    "id": scheme.id,
                    "name": self.scheme_text(words, scheme, "name"),
                    "missing": [self.attr_label(words, m) for m in missing],
                })
                continue

            verdict = self.engine.adjudicate(scheme, known)
            if state is Status.ELIGIBLE:
                claims.append(self._claim(scheme, verdict, words))
                continue

            # Only call it a near miss once every fact the scheme reads is
            # known. A scheme refused on one answer may be refused again on an
            # answer nobody gave, and "just link your bank account" would then
            # be a promise we cannot keep.
            if scheme.attributes_used <= set(known.facts):
                if verdict.fixes and not verdict.redundant:
                    near.append(self._near(scheme, verdict, words))

        won = {c["id"] for c in claims}
        paper = None
        winners = [s for s in self.schemes if s.id in won]
        if winners:
            paper = self._paper(ladder(self.documents, winners, set(documents)), words)

        near.sort(key=lambda n: n["effort"])
        return {
            "clashes": [], "claims": claims, "near": near, "paperwork": paper,
            "undecided": undecided,
            "targets": sorted({d for s in winners for d in s.documents}),
        }

    def answer(self, question: str, words) -> dict:
        assistant = Assistant(self.schemes, self.documents, words, self.schema)
        with self._lock:
            a = assistant.ask(question)
        return {
            "intent": a.intent.value,
            "text": a.text,
            "bullets": a.bullets,
            "steps": a.steps,
            "suggestions": a.suggestions,
        }

    def trace(self, facts: dict, scheme_id: str, words) -> dict:
        scheme = next((s for s in self.schemes if s.id == scheme_id), None)
        if scheme is None:
            return {"error": "unknown scheme"}
        with self._lock:
            return decision_trace(self.engine, scheme,
                                  Profile(id="web", facts=facts), words)

    def paper_trace(self, targets, held, words) -> dict:
        with self._lock:
            return paperwork_trace(self.documents, targets, set(held), words)

    def _claim(self, scheme, verdict, words):
        out = {
            "id": scheme.id,
            "name": self.scheme_text(words, scheme, "name"),
            "benefit": self.scheme_text(words, scheme, "benefit"),
            "apply_at": self.scheme_text(words, scheme, "apply_at"),
            "check": None,
        }
        if verdict.trust is Trust.PROVISIONAL and verdict.margins:
            m = verdict.margins[0]
            out["check"] = {
                "label": self.attr_label(words, m.attribute),
                "now": self.value_text(words, m.attribute, m.current),
                "flips": self.value_text(words, m.attribute, m.flips_at),
            }
        return out

    def _near(self, scheme, verdict, words):
        fix = verdict.fixes[0]
        first = verdict.conflicts[0] if verdict.conflicts else None
        return {
            "id": scheme.id,
            "name": self.scheme_text(words, scheme, "name"),
            "benefit": self.scheme_text(words, scheme, "benefit"),
            "needed": (
                self.criterion_text(words, scheme.id, first.rules[0])
                if first and first.rules else None
            ),
            "you_said": [
                {
                    "label": self.attr_label(words, f.attribute),
                    "value": self.value_text(words, f.attribute, verdict.profile.facts[f.attribute]),
                }
                for f in (first.facts if first else ())
                if f.attribute in verdict.profile.facts
            ],
            "fix": [
                {
                    "label": self.attr_label(words, c.attribute),
                    "now": self.value_text(words, c.attribute, c.now),
                    "needed": self.value_text(words, c.attribute, c.needed),
                    "easy": c.mutability.value == "paperwork",
                }
                for c in fix.changes
            ],
            "effort": fix.effort,
        }

    def _paper(self, route, words):
        unlocks = {m.after_step: m for m in route.milestones}
        names = {s.id: self.scheme_text(words, s, "name") for s in self.schemes}
        steps = []
        for i, step in enumerate(route.plan.steps, 1):
            doc = step.document
            hit = unlocks.get(i)
            steps.append({
                "name": self.doc_text(words, doc, "name"),
                "issuer": self.doc_text(words, doc, "issuer"),
                "fee": doc.fee,
                "days": doc.days,
                "trips": doc.trips,
                "unlocks": [names.get(s, s) for s in hit.unlocks] if hit else [],
            })
        first = route.first_win
        return {
            "steps": steps,
            "trips": route.plan.trips,
            "fee": route.plan.fee,
            "days": route.plan.days,
            "first": {
                "name": steps[first.after_step - 1]["name"],
                "step": first.after_step,
                "unlocks": [names.get(s, s) for s in first.unlocks],
            } if first and first.after_step <= len(steps) else None,
        }


class Handler(BaseHTTPRequestHandler):
    brain: Brain = None

    def log_message(self, *args):
        pass

    def _send(self, code, body, content_type="application/json"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload, ensure_ascii=False))

    def _lang(self):
        query = parse_qs(urlparse(self.path).query)
        return query.get("lang", ["en"])[0]

    def do_GET(self):
        try:
            self._get()
        except Exception:
            traceback.print_exc()
            self._json(500, {"error": "server error"})

    def _get(self):
        route = urlparse(self.path).path

        if route in ("/", "/index.html"):
            return self._send(200, (HERE / "index.html").read_bytes(),
                              "text/html; charset=utf-8")

        if route == "/api/languages":
            return self._json(200, self.brain.translations.listing())

        if route == "/api/strings":
            return self._json(200, self.brain.translations.bundle(self._lang()))

        if route == "/api/voice":
            # Pre-recorded by tools/voice.py. Nothing is fetched here; if the
            # file was never generated we say so and the page falls back to the
            # browser voice, so no request ever leaves this machine.
            query = parse_qs(urlparse(self.path).query)
            lang = query.get("lang", ["en"])[0]
            text = query.get("text", [""])[0]
            if not text or lang not in self.brain.translations.languages:
                return self._json(404, {"error": "no audio"})
            name = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]
            clip = AUDIO / lang / f"{name}.mp3"
            # Resolve before comparing, so a crafted lang or text cannot walk
            # out of the audio directory.
            try:
                clip = clip.resolve()
                clip.relative_to(AUDIO.resolve())
            except (ValueError, OSError):
                return self._json(404, {"error": "no audio"})
            if not clip.is_file():
                return self._json(404, {"error": "no audio"})
            return self._send(200, clip.read_bytes(), "audio/mpeg")

        if route == "/api/documents":
            words = self.brain.translations.bundle(self._lang())
            docs = [
                {"id": d.id, "name": self.brain.doc_text(words, d, "name")}
                for d in self.brain.documents
            ]
            docs.sort(key=lambda d: d["name"])
            return self._json(200, docs)

        self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            self._post()
        except Exception:
            traceback.print_exc()
            self._json(500, {"error": "something went wrong on this machine"})

    def _post(self):
        route = urlparse(self.path).path
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            return self._json(400, {"error": "bad json"})

        facts = payload.get("facts", {})
        try:
            self._check(facts)
        except (KeyError, ValueError) as exc:
            return self._json(400, {"error": str(exc)})

        words = self.brain.translations.bundle(payload.get("lang", "en"))

        if route == "/api/ask":
            question = payload.get("question", "")
            if not isinstance(question, str) or len(question) > 400:
                return self._json(400, {"error": "bad question"})
            return self._json(200, self.brain.answer(question, words))

        if route == "/api/trace":
            scheme_id = payload.get("scheme", "")
            if not isinstance(scheme_id, str):
                return self._json(400, {"error": "bad scheme"})
            return self._json(200, self.brain.trace(facts, scheme_id, words))

        if route == "/api/paper-trace":
            targets = payload.get("targets", [])
            held = payload.get("documents", [])
            if not isinstance(targets, list) or not isinstance(held, list):
                return self._json(400, {"error": "bad lists"})
            return self._json(200, self.brain.paper_trace(
                [t for t in targets if t in self.brain.documents],
                [h for h in held if h in self.brain.documents], words))

        if route == "/api/question":
            return self._json(200, {"question": self.brain.question_for(facts, words)})

        if route == "/api/result":
            documents = payload.get("documents", [])
            if not isinstance(documents, list):
                return self._json(400, {"error": "documents must be a list"})
            documents = [d for d in documents if d in self.brain.documents]
            return self._json(200, self.brain.result_for(facts, documents, words))

        self._json(404, {"error": "not found"})

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _check(self, facts):
        """Nothing outside the declared schema reaches the reasoner. The
        browser is trusted no more than any other input."""
        if not isinstance(facts, dict):
            raise ValueError("facts must be an object")
        for name, value in facts.items():
            if name not in self.brain.schema:
                raise ValueError(f"unknown attribute {name!r}")
            self.brain.schema[name].check(value)


def serve(port: int = 8765, data_dir: Path = DATA):
    Handler.brain = Brain(data_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"PATRA is running. Open http://127.0.0.1:{port} in a browser.")
    print("Everything stays on this machine. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="patra-web")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=DATA)
    args = parser.parse_args()
    serve(args.port, args.data)
