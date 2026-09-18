"""Compiling the constraint tree to Z3.

Enums become bounded integers with a value-to-index map rather than Z3 enum
sorts. That keeps every attribute inside one arithmetic theory, so a single
unsat-core mechanism covers all of them, and it means the recourse layer can
read a concrete target value straight out of a model without caring what sort
it came from.
"""

from __future__ import annotations

import z3

from ..model.attributes import Kind, Schema
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

_CMP = {
    "le": lambda a, b: a <= b,
    "lt": lambda a, b: a < b,
    "ge": lambda a, b: a >= b,
    "gt": lambda a, b: a > b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


class Z3Encoder:
    def __init__(self, schema: Schema):
        self.schema = schema
        self._const: dict[str, z3.ExprRef] = {}
        self._index: dict[str, dict[str, int]] = {}
        self._value: dict[str, dict[int, str]] = {}

        for attr in schema:
            if attr.kind is Kind.BOOL:
                self._const[attr.name] = z3.Bool(attr.name)
                continue

            self._const[attr.name] = z3.Int(attr.name)
            if attr.kind is Kind.ENUM:
                idx = {v: i for i, v in enumerate(attr.options)}
                self._index[attr.name] = idx
                self._value[attr.name] = {i: v for v, i in idx.items()}

    def const(self, name: str) -> z3.ExprRef:
        return self._const[name]

    def background(self) -> list[z3.BoolRef]:
        """Facts about the representation, never about any scheme.

        These are asserted as hard constraints so they can never turn up inside
        an explanation shown to a household.
        """
        out = []
        for attr in self.schema:
            c = self._const[attr.name]
            if attr.kind is Kind.INT:
                if attr.low is not None:
                    out.append(c >= attr.low)
                if attr.high is not None:
                    out.append(c <= attr.high)
            elif attr.kind is Kind.ENUM:
                out.append(z3.And(c >= 0, c < len(attr.options)))
        return out

    def encode_value(self, name: str, value):
        if self.schema[name].kind is Kind.ENUM:
            try:
                return self._index[name][value]
            except KeyError:
                raise ValueError(f"{name}: unknown value {value!r}") from None
        return value

    def decode_value(self, name: str, raw):
        attr = self.schema[name]
        if attr.kind is Kind.ENUM:
            return self._value[name][int(raw)]
        if attr.kind is Kind.BOOL:
            return bool(raw)
        return int(raw)

    def compile(self, formula: Formula) -> z3.BoolRef:
        return self._compile(formula)

    def _compile(self, node: Formula) -> z3.BoolRef:
        if isinstance(node, Cmp):
            return _CMP[node.op](
                self._operand(node.lhs, node), self._operand(node.rhs, node)
            )

        if isinstance(node, InSet):
            const = self._const[node.var.name]
            idx = self._index.get(node.var.name)
            if idx is None:
                raise ValueError(f"{node.var.name} is not an enum attribute")
            unknown = [v for v in node.values if v not in idx]
            if unknown:
                raise ValueError(f"{node.var.name}: unknown values {unknown}")
            member = z3.Or([const == idx[v] for v in node.values])
            return z3.Not(member) if node.negated else member

        if isinstance(node, IsTrue):
            const = self._const[node.var.name]
            if not z3.is_bool(const):
                raise ValueError(f"{node.var.name} is not a yes/no attribute")
            return z3.Not(const) if node.negated else const

        if isinstance(node, And):
            return z3.And([self._compile(p) for p in node.parts])
        if isinstance(node, Or):
            return z3.Or([self._compile(p) for p in node.parts])
        if isinstance(node, Not):
            return z3.Not(self._compile(node.part))
        if isinstance(node, Implies):
            return z3.Implies(
                self._compile(node.antecedent), self._compile(node.consequent)
            )

        raise TypeError(f"cannot compile {node!r}")

    def _operand(self, node, parent: Cmp):
        if isinstance(node, Var):
            return self._const[node.name]
        if isinstance(node, Lit):
            # An enum literal only means something next to the attribute it is
            # compared with, so resolve it from the other side of the operator.
            if isinstance(node.value, str):
                sibling = parent.rhs if node is parent.lhs else parent.lhs
                if not isinstance(sibling, Var):
                    raise ValueError(
                        f"value {node.value!r} must be compared to an attribute"
                    )
                return self.encode_value(sibling.name, node.value)
            return node.value
        raise TypeError(f"not an operand: {node!r}")
