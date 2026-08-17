import re
import unicodedata

_ACENTOS = {
    "a": "aáàâã",
    "e": "eéèê",
    "i": "iíìî",
    "o": "oóòôõ",
    "u": "uúùû",
    "c": "cç",
}


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
