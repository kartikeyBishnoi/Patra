"""Reading the knowledge base off disk.

The YAML is the knowledge base. Keeping scheme rules declarative means someone
can check a clause against the notification it came from without reading any
Python, which matters because that check is the only thing standing between us
and confidently wrong answers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..model.attributes import Attribute, Kind, Mutability, Schema, Scope
from ..model.constraint import (
    And,
    Cmp,
    Formula,
    Implies,
    InSet,
    IsTrue,
    Lit,
    Not,
    Or,
    Var,
)
from ..model.document import Document, DocumentGraph, Need
from ..model.household import Household, Member
from ..model.scheme import Axiom, Criterion, Scheme

COMPARISONS = {"le", "lt", "ge", "gt", "eq", "ne"}


def load_schema(path: Path) -> Schema:
    raw = yaml.safe_load(path.read_text())
    attributes = []
    for name, spec in raw["attributes"].items():
        attributes.append(
            Attribute(
                name=name,
                kind=Kind(spec["kind"]),
                label=spec["label"],
                scope=Scope(spec["scope"]),
                mutability=Mutability(spec["mutability"]),
                question=spec["question"],
                effort=spec.get("effort", 1),
                unit=spec.get("unit"),
                low=spec.get("low"),
                high=spec.get("high"),
                options=tuple(spec.get("options", ())),
                sensitive=spec.get("sensitive", False),
                open_ended=spec.get("open_ended", False),
                asset=spec.get("asset", False),
            )
        )
    return Schema(attributes)


def load_scheme(path: Path, schema: Schema | None = None) -> Scheme:
    raw = yaml.safe_load(path.read_text())
    criteria = tuple(
        Criterion(
            id=c["id"],
            text=c["text"],
            formula=parse(c["rule"], schema),
            clause=c.get("clause"),
        )
        for c in raw["criteria"]
    )
    scheme = Scheme(
        id=raw["id"],
        name=raw["name"],
        authority=raw["authority"],
        scope=Scope(raw["scope"]),
        criteria=criteria,
        benefit=raw["benefit"],
        apply_at=raw["apply_at"],
        documents=tuple(raw.get("documents", ())),
        source_url=raw.get("source_url"),
        note=raw.get("note"),
    )
    if schema is not None:
        scheme.check(schema)
    return scheme


def load_schemes(directory: Path, schema: Schema | None = None) -> list[Scheme]:
    return [load_scheme(p, schema) for p in sorted(directory.glob("*.yaml"))]


def load_documents(path: Path) -> DocumentGraph:
    raw = yaml.safe_load(path.read_text())
    documents = []
    for doc_id, spec in raw["documents"].items():
        needs = tuple(
            Need(purpose=n["purpose"], options=tuple(n["any"]))
            for n in spec.get("needs", ())
        )
        documents.append(
            Document(
                id=doc_id,
                name=spec["name"],
                issuer=spec["issuer"],
                needs=needs,
                fee=spec.get("fee", 0),
                days=spec.get("days", 0),
                trips=spec.get("trips", 1),
                note=spec.get("note"),
                source_url=spec.get("source_url"),
            )
        )
    return DocumentGraph(documents)


def load_axioms(path: Path, schema: Schema | None = None) -> list[Axiom]:
    raw = yaml.safe_load(path.read_text())
    return [
        Axiom(id=a["id"], text=a["text"], formula=parse(a["rule"], schema))
        for a in raw["axioms"]
    ]


def load_households(path: Path, schema: Schema | None = None) -> list[Household]:
    raw = yaml.safe_load(path.read_text())
    out = []
    for entry in raw["households"]:
        household = Household(
            id=entry["id"],
            facts=dict(entry.get("facts", {})),
            members=[
                Member(id=m["id"], facts=dict(m.get("facts", {})), name=m.get("name"))
                for m in entry.get("members", [])
            ],
            documents=set(entry.get("documents", [])),
            note=entry.get("note"),
        )
        if schema is not None:
            household.check(schema)
        out.append(household)
    return out


def parse(node: Any, schema: Schema | None = None) -> Formula:
    """Turn one YAML rule node into the constraint tree.

    With a schema in hand, a bare string resolves to an attribute if one is
    declared under that name and to a literal otherwise. That lets rules read
    as `{eq: [category, sc]}` without quoting ceremony, while still catching a
    misspelled attribute name instead of silently treating it as a value.
    """
    if not isinstance(node, dict) or len(node) != 1:
        raise ValueError(f"a rule must be a single-key mapping, got {node!r}")

    (op, arg), = node.items()

    if op in COMPARISONS:
        if not isinstance(arg, list) or len(arg) != 2:
            raise ValueError(f"{op!r} takes two operands, got {arg!r}")
        return Cmp(op, _operand(arg[0], schema), _operand(arg[1], schema))

    if op == "all":
        return And(tuple(parse(p, schema) for p in arg))
    if op == "any":
        return Or(tuple(parse(p, schema) for p in arg))
    if op == "not":
        return Not(parse(arg, schema))
    if op == "implies":
        if not isinstance(arg, list) or len(arg) != 2:
            raise ValueError(f"'implies' takes two operands, got {arg!r}")
        return Implies(parse(arg[0], schema), parse(arg[1], schema))

    if op == "in":
        return InSet(Var(arg[0]), tuple(arg[1]))
    if op == "not_in":
        return InSet(Var(arg[0]), tuple(arg[1]), negated=True)

    if op == "is_true":
        return IsTrue(Var(arg))
    if op == "is_false":
        return IsTrue(Var(arg), negated=True)

    raise ValueError(f"unknown rule operator {op!r}")


def _operand(node: Any, schema: Schema | None = None):
    if isinstance(node, dict) and set(node) == {"value"}:
        return Lit(node["value"])
    if isinstance(node, str):
        if schema is None or node in schema:
            return Var(node)
        return Lit(node)
    if isinstance(node, (int, bool)):
        return Lit(node)
    raise ValueError(f"cannot read operand {node!r}")
