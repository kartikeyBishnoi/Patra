"""Language files.

Every string a person sees comes from here. That includes the questions, the
scheme names, the benefit descriptions and the document names, because a
half-translated screen is worse than an English one: it reads as broken rather
than as foreign.

Templated output is what makes this possible. Nothing in the system generates
prose, so the set of sentences is finite and can be translated once, checked by
someone who speaks the language, and then played as recorded audio for people
who do not read.

`complete` on each language says whether a native speaker has been through it.
The picker shows the ones that have, and marks the rest, because guessing at a
welfare entitlement in a language nobody checked is how people end up walking
to the wrong office.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

I18N_DIR = Path(__file__).resolve().parent.parent / "data" / "i18n"


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    """Written in the language itself, since somebody choosing Hindi cannot
    necessarily read the word "Hindi"."""

    strings: dict
    complete: bool
    speech: str
    """BCP 47 tag for the browser's speech synthesiser."""


class Translations:
    def __init__(self, directory: Path = I18N_DIR):
        self.languages: dict[str, Language] = {}
        for path in sorted(directory.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text())
            code = raw["code"]
            self.languages[code] = Language(
                code=code,
                name=raw["name"],
                strings=raw.get("strings", {}),
                complete=raw.get("complete", False),
                speech=raw.get("speech", code),
            )
        if "en" not in self.languages:
            raise ValueError("English is the fallback and must be present")

    def get(self, code: str) -> Language:
        return self.languages.get(code, self.languages["en"])

    def listing(self) -> list[dict]:
        return [
            {
                "code": lang.code,
                "name": lang.name,
                "complete": lang.complete,
                "speech": lang.speech,
            }
            for lang in self.languages.values()
        ]

    def bundle(self, code: str) -> dict:
        """Everything the page needs, with English filling any gap.

        Falling back per key rather than per language means a partly
        translated file still helps, and the untranslated parts stay readable
        instead of turning into blanks.
        """
        english = self.languages["en"].strings
        chosen = self.get(code).strings
        return _merge(english, chosen)


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        elif value not in (None, ""):
            out[key] = value
    return out
