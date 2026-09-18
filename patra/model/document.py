"""Documents and what you need before you can get them.

The thing that actually defeats people is not the scheme rules. It is being
told to bring an income certificate, walking to the tehsil office, and finding
out you needed a ration card first. Then doing it again. Each trip costs a
day's wages.

Requirements are not a simple chain. An income certificate wants proof of
identity, proof of address, and proof of age, and each of those accepts several
alternatives: Aadhaar or voter ID or PAN for identity, ration card or an
electricity bill for address. So the structure is a conjunction of
disjunctions, which makes the whole thing an AND-OR graph rather than a
dependency tree, and finding the cheapest way to obtain something is AND-OR
search rather than a topological sort.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Need:
    """One requirement, satisfied by any one of several documents."""

    purpose: str
    """What this requirement is for, in words: identity, address, age."""

    options: tuple[str, ...]

    def __post_init__(self):
        if not self.options:
            raise ValueError(f"requirement {self.purpose!r} lists no options")


@dataclass(frozen=True)
class Document:
    id: str
    name: str
    issuer: str
    needs: tuple[Need, ...] = ()
    fee: int = 0
    days: int = 0
    trips: int = 1
    note: str | None = None
    source_url: str | None = None

    @property
    def effort(self) -> int:
        """A single number for comparing acquisition routes.

        Trips dominate. A rural applicant losing a day's wage to reach a block
        office is paying far more than the thirty rupee fee, so the weighting
        reflects that rather than treating the costs as comparable.
        """
        return self.trips * 10 + self.days // 7 + self.fee // 50


class DocumentGraph:
    def __init__(self, documents: list[Document]):
        self._by_id: dict[str, Document] = {}
        for d in documents:
            if d.id in self._by_id:
                raise ValueError(f"duplicate document {d.id!r}")
            self._by_id[d.id] = d
        self._check_references()

    def _check_references(self) -> None:
        for doc in self._by_id.values():
            for need in doc.needs:
                for option in need.options:
                    if option not in self._by_id:
                        raise ValueError(
                            f"{doc.id} requires unknown document {option!r}"
                        )

    def __contains__(self, doc_id) -> bool:
        return doc_id in self._by_id

    def __getitem__(self, doc_id: str) -> Document:
        try:
            return self._by_id[doc_id]
        except KeyError:
            raise KeyError(f"no document {doc_id!r}") from None

    def __iter__(self):
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)

    @property
    def ids(self) -> list[str]:
        return list(self._by_id)

    def roots(self) -> list[Document]:
        """Documents you can obtain without holding anything else first."""
        return [d for d in self._by_id.values() if not d.needs]
