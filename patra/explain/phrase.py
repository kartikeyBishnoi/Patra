"""Saying a rule out loud in any language, without translating it first.

Criterion texts are hand-written for English and Hindi because natural phrasing
matters. For every other language we would otherwise need a translator for all
seventy-one of them, and until that happened the most important sentence in the
app, the one that tells somebody why they were refused, would sit there in
English.

There is a way around it. The rules are not prose, they are a constraint tree,
and we already hold every attribute label, enum option and unit translated. So
the sentence can be built from the tree at read time with about eight fragments
per language instead of seventy-one translations.

The shape deliberately reads as a requirement rather than a sentence:

    Age, 60 or more
    Ration card, one of: priority card, Antyodaya card
    Bank account linked to Aadhaar, yes

Composing grammatical prose out of labels that were not written to compose is
how template systems produce nonsense in languages the author does not speak.
A labelled requirement is blunter, survives any word order, and cannot end up
saying something untrue. Hand-written text still wins wherever it exists, so
English and Hindi read naturally and the rest read plainly.
"""

from __future__ import annotations

from ..model.attributes import Kind, Schema
from ..model.constraint import And, Cmp, Implies, InSet, IsTrue, Lit, Not, Or, Var

# Each fragment carries its own {v} placeholder rather than being a prefix,
# because word order moves. English puts the comparison before the number,
# Hindi and Marathi put it after, and a prefix template would produce
# "उम्र, से ज़्यादा 60" instead of "उम्र, 60 से ज़्यादा".
DEFAULTS = {
    "ge_val": "{v} or more",
    "le_val": "{v} or less",
    "gt_val": "more than {v}",
    "lt_val": "less than {v}",
    "ne_val": "not {v}",
    "one_of": "one of",
    "none_of": "not one of",
    "and": "and",
    "or": "or",
    "not": "not",
    "if_then": "if {a} then {b}",
    "join": ", ",
}


class Phraser:
    """Turns a constraint tree into a readable requirement."""

    def __init__(self, schema: Schema, words: dict):
        self.schema = schema
        self.words = words or {}

    # ---- vocabulary ----

    def frag(self, key: str) -> str:
        return self.words.get("phrase", {}).get(key) or DEFAULTS[key]

    def label(self, name: str) -> str:
        return self.words.get("attr", {}).get(name, {}).get("label") \
            or self.schema[name].label

    def unit(self, name: str) -> str:
        return self.words.get("attr", {}).get(name, {}).get("unit") \
            or self.schema[name].unit or ""

    def option(self, name: str, value) -> str:
        return self.words.get("attr", {}).get(name, {}).get("options", {}).get(
            value, str(value).replace("_", " "))

    def yes_no(self, truth: bool) -> str:
        key = "yes" if truth else "no"
        return self.words.get("ui", {}).get(key) or key

    def number(self, name: str, value) -> str:
        attr = self.schema[name]
        text = f"{value:,}" if isinstance(value, int) else str(value)
        unit = self.unit(name)
        return f"{text} {unit}".strip() if unit else text

    # ---- rendering ----

    def say(self, formula) -> str:
        return self._say(formula)

    def _say(self, node) -> str:
        if isinstance(node, Cmp):
            return self._cmp(node)
        if isinstance(node, InSet):
            key = "none_of" if node.negated else "one_of"
            values = self.frag("join").join(
                self.option(node.var.name, v) for v in node.values)
            return f"{self.label(node.var.name)}, {self.frag(key)}: {values}"
        if isinstance(node, IsTrue):
            return f"{self.label(node.var.name)}, {self.yes_no(not node.negated)}"
        if isinstance(node, And):
            sep = f" {self.frag('and')} "
            return sep.join(self._say(p) for p in node.parts)
        if isinstance(node, Or):
            sep = f" {self.frag('or')} "
            return sep.join(self._say(p) for p in node.parts)
        if isinstance(node, Not):
            return f"{self.frag('not')} ({self._say(node.part)})"
        if isinstance(node, Implies):
            return self.frag("if_then") \
                .replace("{a}", self._say(node.antecedent)) \
                .replace("{b}", self._say(node.consequent))
        return str(node)

    def _cmp(self, node: Cmp) -> str:
        """Comparisons carry the meaning, so they get the careful handling.

        Which side holds the attribute is not fixed by the rule format, and an
        enum literal only means anything next to the attribute it is compared
        with, so both are resolved here rather than assumed.
        """
        var, lit, flipped = None, None, False
        if isinstance(node.lhs, Var):
            var, lit = node.lhs, node.rhs
        elif isinstance(node.rhs, Var):
            var, lit, flipped = node.rhs, node.lhs, True
        if var is None or not isinstance(lit, Lit):
            return f"{node.lhs} {Cmp.OPS[node.op]} {node.rhs}"

        name = var.name
        attr = self.schema[name]
        op = node.op
        if flipped:
            op = {"le": "ge", "ge": "le", "lt": "gt", "gt": "lt"}.get(op, op)

        if attr.kind is Kind.ENUM:
            value = self.option(name, lit.value)
            if op == "ne":
                return f"{self.label(name)}, {self.frag('ne_val').replace('{v}', value)}"
            return f"{self.label(name)}, {value}"

        if attr.kind is Kind.BOOL:
            return f"{self.label(name)}, {self.yes_no(bool(lit.value))}"

        value = self.number(name, lit.value)
        key = {"ge": "ge_val", "le": "le_val", "gt": "gt_val",
               "lt": "lt_val", "ne": "ne_val"}.get(op)
        shown = self.frag(key).replace("{v}", value) if key else value
        return f"{self.label(name)}, {shown}"


def criterion(schema: Schema, words: dict, scheme_id: str, crit) -> str:
    """The criterion in the reader's language.

    Hand-written translation first, generated requirement second, and the
    English source only if the attribute is somehow unknown.
    """
    written = (words or {}).get("criterion", {}).get(scheme_id, {}).get(crit.id)
    if written:
        return written
    try:
        return Phraser(schema, words).say(crit.formula)
    except (KeyError, AttributeError):
        return crit.text
