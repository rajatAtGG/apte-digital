"""Devanagari normalisation and varnamala collation.

Two jobs live here:

* ``normalize(text)``: a *search key* for a headword. It is lossy on purpose,
  so that small spelling variants meet at the same key. The original text is
  always kept for display; only the key is normalised.

* ``collation_key(text)``: a string that sorts in traditional varnamala order
  (vowels, then anusvara/visarga, then consonants by place of articulation)
  rather than in Unicode code-point order.

The same normalisation is re-implemented in JavaScript in
``app/js/normalize.js``. Both implementations are tested against the shared
cases in ``tests/shared/normalize_cases.json`` so they cannot drift apart.
"""

import re
import unicodedata

VIRAMA = "्"      # ्
ANUSVARA = "ं"    # ं
CANDRABINDU = "ँ"  # ँ
VISARGA = "ः"     # ः
NUKTA = "़"       # ़
AVAGRAHA = "ऽ"    # ऽ

# Independent vowels and their dependent (matra) forms, in varnamala order.
VOWELS = "अ आ इ ई उ ऊ ऋ ॠ ऌ ॡ ए ऐ ओ औ".split()
MATRAS = {
    "ा": "आ", "ि": "इ", "ी": "ई", "ु": "उ", "ू": "ऊ",
    "ृ": "ऋ", "ॄ": "ॠ", "ॢ": "ऌ", "ॣ": "ॡ",
    "े": "ए", "ै": "ऐ", "ो": "ओ", "ौ": "औ",
    # Rare/foreign vowel signs: fold onto their nearest Sanskrit vowel.
    "ॅ": "ए", "ॆ": "ए", "ॉ": "ओ", "ॊ": "ओ",
}
# Consonants in varnamala order (ळ is the Vedic retroflex l, placed after ल).
CONSONANTS = ("क ख ग घ ङ च छ ज झ ञ ट ठ ड ढ ण त थ द ध न प फ ब भ म "
              "य र ल ळ व श ष स ह").split()

# Rank of every sortable unit. Lower ranks sort first.
_ORDER = VOWELS + [ANUSVARA, VISARGA] + CONSONANTS
RANK = {ch: i for i, ch in enumerate(_ORDER)}
_CONSONANT_SET = set(CONSONANTS)

# Zero-width joiners, BOM, and everything we treat as punctuation in keys.
_INVISIBLE = re.compile("[​-‍﻿]")
_NOT_DEVANAGARI = re.compile(r"[^ऀ-ॣॱ-ॿ]")
# A nasal + virama before a consonant *of its own class* is written either way
# in the dictionary (शङ्कर / शंकर), so both fold to anusvara. Non-homorganic
# clusters such as न्य (अन्य) are genuine consonants and are left alone.
_HOMORGANIC = re.compile(
    "ङ" + VIRAMA + "(?=[कखगघ])|ञ" + VIRAMA + "(?=[चछजझ])|"
    "ण" + VIRAMA + "(?=[टठडढ])|न" + VIRAMA + "(?=[तथदध])|"
    "म" + VIRAMA + "(?=[पफबभ])")


def normalize(text: str) -> str:
    """Return the search key for a Devanagari string.

    * NFC-normalise and drop zero-width characters and the nukta (क़ → क).
    * ASCII ``:`` is a common typo for visarga; visarga is dropped entirely
      (रामः → राम, दुःख → दुख), so nominative endings never block a match.
    * Candrabindu becomes anusvara, and a nasal + virama before a consonant
      of the same class becomes anusvara (शङ्कर → शंकर, सन्त → संत).
    * ``*``, avagraha, digits, spaces, hyphens and all other punctuation are
      removed.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFC", text)
    s = _INVISIBLE.sub("", s)
    s = s.replace(":", VISARGA)
    # Decompose precomposed nukta letters (e.g. U+0958 क़) and drop the nukta.
    s = unicodedata.normalize("NFD", s).replace(NUKTA, "")
    s = unicodedata.normalize("NFC", s)
    s = s.replace(VISARGA, "").replace(CANDRABINDU, ANUSVARA)
    s = s.replace(AVAGRAHA, "")
    s = _NOT_DEVANAGARI.sub("", s)       # *, punctuation, spaces, Latin, digits
    s = re.sub("[।॥०-९॰]", "", s)  # danda, digits, ॰
    s = _HOMORGANIC.sub(ANUSVARA, s)
    return s


def phonemes(text: str):
    """Split Devanagari into sortable units: consonants carry their vowel.

    क → [क, अ];  कि → [क, इ];  क्त → [क, त, अ];  कं → [क, अ, ं].
    Anything that is not a sortable unit (``*``, punctuation, avagraha) is
    skipped.
    """
    s = unicodedata.normalize("NFD", text or "").replace(NUKTA, "")
    s = unicodedata.normalize("NFC", s).replace(CANDRABINDU, ANUSVARA)
    s = s.replace(":", VISARGA)
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in _CONSONANT_SET:
            out.append(ch)
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if nxt == VIRAMA:          # dead consonant: no vowel
                i += 2
                continue
            if nxt in MATRAS:          # explicit vowel sign
                out.append(MATRAS[nxt])
                i += 2
                continue
            out.append("अ")            # inherent vowel
        elif ch in RANK:
            out.append(ch)             # independent vowel, anusvara, visarga
        i += 1
    return out


def collation_key(text: str) -> str:
    """A string that sorts ``text`` in varnamala order under plain binary
    comparison (as SQLite's default BINARY collation does).

    The text is normalised first, so spelling variants (शङ्कर / शंकर) and
    nominative visarga (अः sorts with अ) do not scatter related words.
    """
    return "".join(chr(0x41 + RANK[p]) for p in phonemes(normalize(text)))


def initial_letter(text: str) -> str:
    """The varna a headword is filed under: its first vowel or consonant
    (क्ष is filed under क, ज्ञ under ज, as in the printed dictionary)."""
    p = phonemes(text)
    return p[0] if p and p[0] not in (ANUSVARA, VISARGA) else ""


# Letters in the order they are shown in the "browse" screen.
VARNAMALA = VOWELS + CONSONANTS


_WORD = re.compile(r"[ऀ-ॣॱ-ॿ]+")


def normalize_text(text: str) -> str:
    """Normalise running Hindi text word by word for the full-text index:
    each Devanagari word goes through :func:`normalize` and the words are
    joined with spaces. Non-Devanagari text (Latin glosses, digits) is
    dropped from the index only; the displayed text is untouched."""
    words = (normalize(w) for w in _WORD.findall(unicodedata.normalize("NFC", text or "")))
    return " ".join(w for w in words if w)
