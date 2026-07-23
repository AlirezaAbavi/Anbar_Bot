"""Persian/Arabic text folding shared by name-matching code.

Two levels of folding:

* :func:`normalize_fa` — the *strict* canonical form used to decide whether two names
  are "the same" (the add-product duplicate detector). It only folds things that are
  visually identical: Arabic vs Persian ye/kaf, the tatweel-style diacritics, ZWNJ, and
  punctuation/whitespace, then casefolds so English names compare case-insensitively.

* :func:`search_fold` — a *lenient* form used only for search. It applies
  ``normalize_fa`` and additionally folds letters that a keyboard/transliteration might
  swap for a foreign name (چ↔ج, as in "استیچ" vs "استیج" for *Stitch*). This is
  deliberately looser than ``normalize_fa`` so it does not make the duplicate detector
  treat genuinely different products as collisions.
"""

import re
import unicodedata

# Arabic ye/kaf and the Persian/Arabic diacritics a keyboard may or may not emit — all
# folded so that visually identical names compare equal.
_CHAR_FOLD = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "أ": "ا", "إ": "ا", "آ": "ا",
    "‌": " ",  # ZWNJ (نیم‌فاصله) -> space
    "‏": "", "‎": "",  # RTL/LTR marks
})
_DIACRITICS = re.compile(r"[ً-ْٰ]")


def normalize_fa(text):
    """Fold a name to a comparable form: NFKC, unified Persian letters, no
    diacritics/punctuation, collapsed whitespace, casefolded (for the English names)."""
    text = unicodedata.normalize("NFKC", text or "").translate(_CHAR_FOLD)
    text = _DIACRITICS.sub("", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().casefold()


# Search-only extra folding: letters commonly swapped when transliterating a foreign name
# into Persian. چ↔ج covers "استیچ"/"استیج" (Stitch); both fold to ج so either spelling
# finds the other. Intentionally kept minimal — each pair risks matching unrelated words.
_SEARCH_FOLD = str.maketrans({"چ": "ج"})


def search_fold(text):
    """Lenient fold for search: :func:`normalize_fa` plus foreign-name letter folding."""
    return normalize_fa(text).translate(_SEARCH_FOLD)
