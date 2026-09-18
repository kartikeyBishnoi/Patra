"""Satisfiability oracle over labelled constraints.

Every reasoning algorithm in PATRA treats satisfiability as a black box and is
charged for each query. Two consequences:

* We use Z3 *assumption literals* rather than push/pop, so a subset check is a
  single incremental call against one long-lived solver. Each labelled
  constraint `c` is asserted once as `sel_c -> compile(c)`; asking about a
  subset means checking under the assumptions `{sel_c : c in subset}`.
* The oracle counts its own calls. Oracle-call count is the honest cost measure
  for conflict-detection algorithms, since solver time is dominated by it, and
  it is what we report when comparing QuickXPlain against linear deletion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import z3

from ..encode.z3enc import Z3Encoder
from ..model.scheme import Labelled


@dataclass
class OracleStats:
    calls: int = 0
    sat: int = 0
    unsat: int = 0

    def reset(self) -> None:
        self.calls = self.sat = self.unsat = 0


class Oracle:
    """Answers "is this subset of constraints jointly satisfiable?".

    `background` holds constraints that are always true and never explained:
    attribute domain bounds, plus (for recourse queries) the scheme rules,
    which an applicant cannot negotiate.
    """

    def __init__(
        self,
        encoder: Z3Encoder,
        soft: list[Labelled],
        background: list[z3.BoolRef] | None = None,
    ) -> None:
        self.encoder = encoder
        self.soft = {c.id: c for c in soft}
        if len(self.soft) != len(soft):
            raise ValueError("labelled constraints must have unique ids")

        self.stats = OracleStats()
        self._solver = z3.Solver()
        self._selector: dict[str, z3.BoolRef] = {}

        for expr in encoder.background():
            self._solver.add(expr)
        for expr in background or []:
            self._solver.add(expr)

        for c in soft:
            sel = z3.Bool(f"__sel_{c.id}")
            self._selector[c.id] = sel
            self._solver.add(z3.Implies(sel, encoder.compile(c.formula)))

    @property
    def ids(self) -> list[str]:
        return list(self.soft)

    def is_sat(self, subset) -> bool:
        """True iff background together with `subset` is satisfiable."""
        assumptions = [self._selector[i] for i in subset]
        self.stats.calls += 1
        result = self._solver.check(*assumptions)
        if result == z3.sat:
            self.stats.sat += 1
            return True
        if result == z3.unsat:
            self.stats.unsat += 1
            return False
        raise RuntimeError(f"solver returned {result} - constraints may be undecidable")

    def model_for(self, subset) -> dict[str, int | bool | str] | None:
        """A concrete applicant satisfying `subset`, decoded to readable values.

        This is what turns a correction set ("change your income") into
        actionable advice ("your income must be at most Rs 2,50,000").
        """
        assumptions = [self._selector[i] for i in subset]
        self.stats.calls += 1
        if self._solver.check(*assumptions) != z3.sat:
            self.stats.unsat += 1
            return None
        self.stats.sat += 1
        model = self._solver.model()
        out: dict[str, int | bool | str] = {}
        for attr in self.encoder.schema:
            raw = model.eval(self.encoder.const(attr.name), model_completion=True)
            if z3.is_true(raw) or z3.is_false(raw):
                out[attr.name] = self.encoder.decode_value(attr.name, z3.is_true(raw))
            else:
                out[attr.name] = self.encoder.decode_value(attr.name, raw.as_long())
        return out

    def label(self, cid: str) -> Labelled:
        return self.soft[cid]
