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


# Search-only extra folding: letters that Persian typing/transliteration swaps freely, so
# either spelling of a name finds the other. Deliberately biased towards *recall* (finding
# more) at the cost of the odd unrelated match — that trade-off was chosen for this catalog
# (foreign doll names spelled many ways). Each group folds to one representative letter;
# direction is irrelevant since query and stored text are folded the same way.
_SEARCH_FOLD = str.maketrans({
    # ch/j — "استیچ"/"استیج" (Stitch)
    "چ": "ج",
    # same-sound letters (homophones in Persian)
    "ذ": "ز", "ض": "ز", "ظ": "ز",   # z-sound
    "ص": "س", "ث": "س",             # s-sound
    "ط": "ت",                       # t-sound
    "غ": "ق",                       # gh-sound
    # foreign consonants transliterated inconsistently
    "گ": "ک",                       # g/k
    "پ": "ب",                       # p/b
    # h-sound (ة→ه already handled by normalize_fa)
    "ح": "ه",
    # hamze and its ye/vav carriers
    "ئ": "ی", "ؤ": "و", "ء": "",
})


def search_fold(text):
    """Lenient fold for search: :func:`normalize_fa` plus transliteration/homophone folding."""
    return normalize_fa(text).translate(_SEARCH_FOLD)
