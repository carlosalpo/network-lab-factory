"""English display of editorial text in recipes saved by earlier releases.

Match only known text. Never rewrite saved plans, commands or user-provided names.
"""

import json
from pathlib import Path

_LEGACY = json.loads(
    Path(__file__).with_name("data").joinpath("legacy_english.json").read_text(encoding="utf-8")
)


def english(text):
    return _LEGACY.get(text, text)
