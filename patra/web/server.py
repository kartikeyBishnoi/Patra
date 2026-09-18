"""A local web front end.

Runs on the device and binds to localhost only. There is no remote service to
call, because the reasoning is a solver and a few YAML files rather than a
model that needs a server. That is not a privacy policy, it is the shape of the
system: answers cannot leak to us because they never reach us.

Standard library only, so it starts anywhere Python does.

    python3 -m patra.web.server
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..encode.loader import (
    load_axioms,
    load_documents,
    load_households,
    load_schema,
    load_schemes,
)
from ..engine import Engine, Trust
from ..model.attributes import Kind
from ..model.household import Profile
from ..model.scheme import say
from ..reason.questions import Status, next_question, status
from ..reason.unlock import ladder

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "data"



class Brain:
    """Everything loaded once, shared across requests."""

    def __init__(self, data_dir: Path = DATA):
        self.schema = load_schema(data_dir / "attributes.yaml")
        self.schemes = load_schemes(data_dir / "schemes", self.schema)
        self.documents = load_documents(data_dir / "documents.yaml")
        self.axioms = load_axioms(data_dir / "axioms.yaml", self.schema)
        self.engine = Engine(self.schema, self.axioms, self.documents)

    # Every scheme is in play, household ones included. The household-level
    # attributes are derived from the members when a field worker enters a
    # whole family, but a person answering for themselves can simply be asked:
    # "is there a woman over eighteen in the house?" is a question they can
    # answer, and every such attribute already carries its own wording.
    def askable(self):
        return list(self.schemes)

    def question_for(self, facts: dict):
        known = Profile(id="web", facts=facts)
        q = next_question(self.engine, self.schema, self.askable(), known)
        if q is None:
            return None
        attr = self.schema[q.attribute]
        return {
            "attribute": q.attribute,
            "text": q.text,
            "kind": attr.kind.value,
            "sensitive": attr.sensitive,
            "options": list(attr.options),
            "unit": attr.unit,
            "low": attr.low,
            "high": attr.high,
            "waiting": len(q.schemes_waiting),
        }

    def result_for(self, facts: dict, documents: list[str]):
        known = Profile(id="web", facts=facts)

        clashes = self.engine.inconsistencies(known)
        if clashes:
            return {
                "clashes": [
                    {
                        "rule": [a.text for a in c.axioms],
                        "answers": [f.text for f in c.facts],
                    }
                    for c in clashes
                ],
                "claims": [], "near": [], "paperwork": None,
            }

        # Decide only what the answers actually settle. A scheme still missing
        # an answer is left out rather than guessed at.
        claims, near = [], []
        for scheme in self.schemes:
            state = status(self.engine, scheme, known)
            if state is Status.OPEN:
                continue
            verdict = self.engine.adjudicate(scheme, known)
            if state is Status.ELIGIBLE:
                claims.append(self._claim_json(scheme, verdict))
                continue
            if state is Status.INELIGIBLE:
                continue  # nothing could change this one

            # Only call something a near miss once every fact it reads is
            # known. A scheme refused on one answer may be refused again on an
            # answer nobody gave, and "just link your bank account" would be a
            # promise we cannot keep.
            fully_known = scheme.attributes_used <= set(known.facts)
            if fully_known and verdict.fixes and not verdict.redundant:
                near.append(self._near_json(scheme, verdict))

        won = {c["id"] for c in claims}
        eligible_schemes = [s for s in self.schemes if s.id in won]
        paper = None
        if eligible_schemes:
            route = ladder(self.documents, eligible_schemes, set(documents))
            paper = self._paper_json(route)

        near.sort(key=lambda n: n["effort"])
        return {"clashes": [], "claims": claims, "near": near, "paperwork": paper}

    def _claim_json(self, scheme, verdict):
        out = {
            "id": scheme.id,
            "name": scheme.name,
            "benefit": " ".join(scheme.benefit.split()),
            "apply_at": scheme.apply_at,
            "check": None,
        }
        if verdict.trust is Trust.PROVISIONAL and verdict.margins:
            m = verdict.margins[0]
            out["check"] = {
                "label": m.label,
                "now": say(self.schema[m.attribute], m.current),
                "flips_at": say(self.schema[m.attribute], m.flips_at),
            }
        return out

    def _near_json(self, scheme, verdict):
        fix = verdict.fixes[0]
        return {
            "id": scheme.id,
            "name": scheme.name,
            "benefit": " ".join(scheme.benefit.split()),
            "why": [
                {"rule": r.text, "answer": f.text}
                for c in verdict.conflicts
                for r in c.rules
                for f in c.facts
            ][:3],
            "fix": [
                {
                    "label": c.label,
                    "now": say(self.schema[c.attribute], c.now),
                    "needed": say(self.schema[c.attribute], c.needed),
                    "how": c.mutability.value,
                }
                for c in fix.changes
            ],
            "effort": fix.effort,
        }

    def _paper_json(self, route):
        unlocks = {m.after_step: m for m in route.milestones}
        names = {s.id: s.name for s in self.schemes}
        steps = []
        for i, step in enumerate(route.plan.steps, 1):
            doc = step.document
            hit = unlocks.get(i)
            steps.append({
                "name": doc.name,
                "issuer": doc.issuer,
                "fee": doc.fee,
                "days": doc.days,
                "trips": doc.trips,
                "why": step.reason,
                "note": " ".join(doc.note.split()) if doc.note else None,
                "unlocks": [names.get(s, s) for s in hit.unlocks] if hit else [],
            })
        return {
            "steps": steps,
            "trips": route.plan.trips,
            "fee": route.plan.fee,
            "days": route.plan.days,
        }


class Handler(BaseHTTPRequestHandler):
    brain: Brain = None  # set in serve()

    def log_message(self, *args):
        pass  # the console is for the user, not for request logs

    def _send(self, code, body, content_type="application/json"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = (HERE / "index.html").read_bytes()
            return self._send(200, page, "text/html; charset=utf-8")
        if self.path == "/api/documents":
            docs = [
                {"id": d.id, "name": d.name}
                for d in sorted(self.brain.documents, key=lambda d: d.name)
            ]
            return self._send(200, json.dumps(docs))
        self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            return self._send(400, json.dumps({"error": "bad json"}))

        facts = payload.get("facts", {})
        try:
            self._validate(facts)
        except (KeyError, ValueError) as exc:
            return self._send(400, json.dumps({"error": str(exc)}))

        if self.path == "/api/question":
            question = self.brain.question_for(facts)
            return self._send(200, json.dumps({"question": question}))

        if self.path == "/api/result":
            documents = payload.get("documents", [])
            if not isinstance(documents, list):
                return self._send(400, json.dumps({"error": "documents must be a list"}))
            documents = [d for d in documents if d in self.brain.documents]
            result = self.brain.result_for(facts, documents)
            return self._send(200, json.dumps(result))

        self._send(404, json.dumps({"error": "not found"}))

    def _validate(self, facts):
        """Reject anything outside the declared schema before it reaches the
        reasoner. The browser is not trusted any more than a language model."""
        if not isinstance(facts, dict):
            raise ValueError("facts must be an object")
        for name, value in facts.items():
            if name not in self.brain.schema:
                raise ValueError(f"unknown attribute {name!r}")
            self.brain.schema[name].check(value)


def serve(port: int = 8765, data_dir: Path = DATA):
    Handler.brain = Brain(data_dir)
    # Localhost only. Nothing about this should be reachable from elsewhere.
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"PATRA is running at http://127.0.0.1:{port}")
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
