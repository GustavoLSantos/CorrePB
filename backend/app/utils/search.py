import re
import unicodedata
from functools import lru_cache

_ACENTOS = {
    "a": "aáàâã",
    "e": "eéèê",
    "i": "iíìî",
    "o": "oóòôõ",
    "u": "uúùû",
    "c": "cç",
}


@lru_cache(maxsize=512)
def build_search_regex(termo: str) -> str:
    termo = unicodedata.normalize("NFD", termo).lower().strip()
    if not termo:
        return ""
    pattern = ""
    for ch in termo:
        if ch.isspace():
            pattern += r"\s+"
        elif ch in _ACENTOS:
            pattern += f"[{_ACENTOS[ch]}]"
        else:
            pattern += re.escape(ch)
    return pattern
