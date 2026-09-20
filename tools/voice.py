"""Pre-recording every sentence the app can say.

Browser speech synthesis is robotic and missing outright for several Indian
languages. Real neural voices exist, but calling one at runtime would send what
the household is being asked and told to somebody else's server, and the
privacy claim this app rests on would be gone.

So the network call happens here instead, once, before anybody uses the app.
The set of sentences is finite, which is only true because nothing in the
system generates prose: every string lives in `data/i18n/`. This walks them,
asks a TTS service for each, and writes the audio into `data/audio/<lang>/`.

At runtime the app plays a local file and makes no network call at all. Where a
file is missing it falls back to the browser voice, so a partial run still
helps and a missing API key is not fatal.

    export BHASHINI_KEY=...            # free tier, bhashini.gov.in
    export BHASHINI_ID=...
    python3 tools/voice.py --lang hi

Providers are behind one small interface because the free tiers move around.
Bhashini is the default: it is the Government of India's own platform, free for
low volume, and its Indic models come from IITM, IITB, IIITH and CDAC, which is
the right provenance for a welfare tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "data" / "i18n"
AUDIO = ROOT / "data" / "audio"

# Bhashini speaks ISO codes, the app speaks BCP 47.
BHASHINI_LANG = {"hi": "hi", "mr": "mr", "bn": "bn", "ta": "ta", "en": "en"}


def key_for(text: str) -> str:
    """Stable filename for a sentence, computed identically by the server."""
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]


def speakable(strings: dict) -> list[str]:
    """Every sentence a person could hear, and nothing else.

    Interface chrome that is never read aloud is skipped, because each entry
    costs an API call and a file on disk.
    """
    out: list[str] = []

    def add(value):
        if isinstance(value, str) and value.strip():
            out.append(" ".join(value.split()))

    for key, value in (strings.get("ui") or {}).items():
        # Placeholders cannot be voiced as-is; they are spoken with the numbers
        # already substituted, which the app does at runtime.
        if isinstance(value, str) and "{" not in value:
            add(value)

    for node in (strings.get("attr") or {}).values():
        if isinstance(node, dict):
            add(node.get("question"))
            add(node.get("label"))
            for option in (node.get("options") or {}).values():
                add(option)

    for node in (strings.get("scheme") or {}).values():
        if isinstance(node, dict):
            add(node.get("name"))
            add(node.get("benefit"))
            add(node.get("apply_at"))

    for node in (strings.get("doc") or {}).values():
        if isinstance(node, dict):
            add(node.get("name"))
            add(node.get("issuer"))

    for scheme in (strings.get("criterion") or {}).values():
        if isinstance(scheme, dict):
            for line in scheme.values():
                add(line)

    seen, unique = set(), []
    for line in out:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique


class Bhashini:
    """Government of India's language platform. Free for low volume.

    Two calls: the pipeline config names a service for the language, then the
    compute endpoint returns base64 audio.
    """

    CONFIG = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
    PIPELINE = "64392f96daac500b55c543cd"  # MeitY's published TTS pipeline

    def __init__(self, key: str, user_id: str):
        self.key = key
        self.user_id = user_id
        self._cache: dict[str, tuple[str, str]] = {}

    def _post(self, url, payload, headers):
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def _service(self, lang: str):
        if lang in self._cache:
            return self._cache[lang]
        body = {
            "pipelineTasks": [{"taskType": "tts",
                               "config": {"language": {"sourceLanguage": lang}}}],
            "pipelineRequestConfig": {"pipelineId": self.PIPELINE},
        }
        data = self._post(self.CONFIG, body,
                          {"ulcaApiKey": self.key, "userID": self.user_id})
        task = data["pipelineResponseConfig"][0]
        endpoint = data["pipelineInferenceAPIEndPoint"]
        found = (
            task["config"][0]["serviceId"],
            endpoint["callbackUrl"],
            endpoint["inferenceApiKey"]["name"],
            endpoint["inferenceApiKey"]["value"],
        )
        self._cache[lang] = found
        return found

    def speak(self, text: str, lang: str) -> bytes:
        service, url, header_name, header_value = self._service(lang)
        body = {
            "pipelineTasks": [{
                "taskType": "tts",
                "config": {"language": {"sourceLanguage": lang},
                           "serviceId": service, "gender": "female",
                           "samplingRate": 22050},
            }],
            "inputData": {"input": [{"source": text}]},
        }
        data = self._post(url, body, {header_name: header_value})
        import base64
        return base64.b64decode(data["pipelineResponse"][0]["audio"][0]["audioContent"])


PROVIDERS = {"bhashini": Bhashini}


def build(lang: str, provider_name: str, limit: int | None, pause: float) -> int:
    path = I18N / f"{lang}.yaml"
    if not path.exists():
        print(f"no language file for {lang!r}", file=sys.stderr)
        return 1

    strings = yaml.safe_load(path.read_text(encoding="utf-8")).get("strings", {})
    lines = speakable(strings)
    if limit:
        lines = lines[:limit]

    out_dir = AUDIO / lang
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}

    key = os.environ.get("BHASHINI_KEY")
    user = os.environ.get("BHASHINI_ID")
    if not key or not user:
        print("BHASHINI_KEY and BHASHINI_ID are not set.\n"
              "Register free at https://bhashini.gov.in and export both.\n"
              f"{len(lines)} sentences would be generated for {lang!r}.",
              file=sys.stderr)
        return 2

    provider = PROVIDERS[provider_name](key, user)
    source_lang = BHASHINI_LANG.get(lang, lang)

    made = skipped = failed = 0
    for i, line in enumerate(lines, 1):
        name = key_for(line)
        target = out_dir / f"{name}.mp3"
        if target.exists():
            index[name] = line
            skipped += 1
            continue
        try:
            target.write_bytes(provider.speak(line, source_lang))
            index[name] = line
            made += 1
            print(f"  [{i}/{len(lines)}] {line[:58]}")
        except (urllib.error.URLError, KeyError, ValueError) as exc:
            failed += 1
            print(f"  [{i}/{len(lines)}] failed: {exc}", file=sys.stderr)
        # The free tier is rate limited, and hammering it gets the key blocked.
        time.sleep(pause)

    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    print(f"\n{lang}: {made} new, {skipped} already there, {failed} failed")
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="voice",
        description="Pre-record every sentence the app can say, so playback "
                    "needs no network.")
    parser.add_argument("--lang", required=True,
                        help="language code, or 'all'")
    parser.add_argument("--provider", default="bhashini", choices=list(PROVIDERS))
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after this many sentences, for a trial run")
    parser.add_argument("--pause", type=float, default=0.4,
                        help="seconds between calls, to stay inside the free tier")
    args = parser.parse_args()

    langs = [p.stem for p in sorted(I18N.glob("*.yaml"))] \
        if args.lang == "all" else [args.lang]

    worst = 0
    for lang in langs:
        print(f"\n=== {lang} ===")
        worst = max(worst, build(lang, args.provider, args.limit, args.pause))
    return worst


if __name__ == "__main__":
    sys.exit(main())
