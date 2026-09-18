"""How close a verdict sits to its own boundary.

Households estimate their income. They round, they guess, they quote last
year's figure. Telling someone they qualify when a five percent correction
would reverse it is claiming more than we know, and they are the ones who make
a wasted trip to find out.

For each number a scheme depends on we compute the smallest change that flips
the verdict. When that gap is small next to the value itself, the answer is
reported as provisional with the threshold named, so they can check their
papers before walking anywhere.

Different question from recourse. Recourse asks what the household should
change. This asks how far our own answer can be trusted.
"""

from __future__ import annotations

from dataclasses import dataclass

import z3

from ..encode.z3enc import Z3Encoder
from ..model.attributes import Kind, Schema
from ..model.household import Profile
from ..model.scheme import Scheme


@dataclass(frozen=True)
class Margin:
    attribute: str
    label: str
    current: int
    flips_at: int

    @property
    def distance(self) -> int:
        return abs(self.flips_at - self.current)

    @property
    def relative(self) -> float:
        # Guarded so a reported zero does not divide by nothing.
        return self.distance / max(abs(self.current), 1)


def margins(
    encoder: Z3Encoder,
    schema: Schema,
    scheme: Scheme,
    profile: Profile,
    eligible: bool,
) -> list[Margin]:
    out = []
    for name in sorted(scheme.attributes_used):
        if name not in profile.facts:
            continue
        if schema[name].kind is not Kind.INT:
            continue

        flip = _nearest_flip(encoder, scheme, profile, name, eligible)
        if flip is None:
            continue  # this number cannot swing the verdict on its own

        out.append(
            Margin(
                attribute=name,
                label=schema[name].label,
                current=int(profile.facts[name]),
                flips_at=flip,
            )
        )

    out.sort(key=lambda m: m.relative)
    return out


def borderline(
    encoder: Z3Encoder,
    schema: Schema,
    scheme: Scheme,
    profile: Profile,
    eligible: bool,
    tolerance: float = 0.1,
) -> list[Margin]:
    """Margins tight enough that the verdict should be offered as provisional.

    Ten percent is our judgement of how precisely a household knows its own
    annual income, not a measured figure. Recorded in the limitations.
    """
    found = margins(encoder, schema, scheme, profile, eligible)
    return [m for m in found if m.relative <= tolerance]


def _nearest_flip(
    encoder: Z3Encoder,
    scheme: Scheme,
    profile: Profile,
    varying: str,
    eligible: bool,
) -> int | None:
    opt = z3.Optimize()
    for expr in encoder.background():
        opt.add(expr)

    rules = z3.And([encoder.compile(c.formula) for c in scheme.criteria])
    opt.add(z3.Not(rules) if eligible else rules)

    # Pin everything else so the result isolates this one number.
    for name, value in profile.facts.items():
        if name != varying:
            opt.add(encoder.const(name) == encoder.encode_value(name, value))

    const = encoder.const(varying)
    gap = const - int(profile.facts[varying])
    opt.minimize(z3.If(gap >= 0, gap, -gap))

    if opt.check() != z3.sat:
        return None
    return opt.model().eval(const, model_completion=True).as_long()
