"""Parse transcribed pages of the printed Apte Sanskrit-Hindi dictionary.

Input is the transcription produced from the scan: one text line per printed
line, in reading order (left column, then right column, page by page), with
**bold** runs marked. Bold is what makes the structure recoverable: in the
printed book only headwords, derived forms and compound headwords are bold.

Printed entry layout (all parts after the headword are optional)::

    **अघोर** (वि.) [न घोरः न. त.] जो भायानक न हो, ...,-**रः** (पुं.) शिव ...
    सम.-**पथः** -**मार्गः** (पुं.) शिव का अनुयायी,-**प्रमाणं** (नपुं.) ...

    headword(s)  grammar label(s)  [etymology]  body
    body = numbered senses "1. ... 2. ..." with citations "-रघु. 7/5"
           followed by bold sub-entries: derived forms (-रः = अघोरः) and,
           after "सम.", compounds (-पथः = अघोरपथः)

The output entry dicts use the same "runs" representation as
pipeline/apte_parser.py (strings, or [tag, *runs] for citations), so the
app renders them unchanged.
"""

import re
import unicodedata

DEVA = "ऀ-ॿ"
# A run of bold text: **...**
BOLD = re.compile(r"\*\*(.+?)\*\*")
# Grammar labels: a parenthesised group whose content is abbreviations such
# as "वि.", "पुं.", "नपुं.", "स्त्री.", "अव्य.", "भ्वा. आ.", "चुरा. उभ."
GRAMMAR_WORDS = {
    "वि", "पुं", "पु", "नपुं", "नपु", "स्त्री", "अव्य", "क्रि", "सर्व", "संख्या", "अ",
    "भ्वा", "अदा", "जुहो", "दिवा", "स्वा", "तुदा", "रुधा", "तना", "क्र्या", "चुरा", "चु",
    "उभ", "आ", "पर", "प", "भू", "क", "कृ", "ब", "व", "द्वि", "न", "त", "स", "प्रा",
    "नाम", "धा", "कर्म", "भाव", "पुंस", "बहु", "एक", "क्र", "प्रे", "इच्छा", "आत्म",
}
PAREN = re.compile(r"^\s*\(([^()]{1,40})\)")
BRACKET = re.compile(r"^\s*\[([^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*)\]")
# Citation: a dash, 1-3 abbreviated source words ending in ".", then numbers
# ("-कु. 7/5", "-भर्तृ. नी. 54", "-याज्ञ. 2/114", "-दश. 153").
CITATION = re.compile(
    r"-\s?((?:[" + DEVA + r"]+\.\s?){1,3}\s?\d+(?:\s?[/।]\s?\d+)*(?:\s?-\s?\d+)?)")
# Page furniture that the transcription may contain: printer's signature
# marks at the foot of a page ("संस्कृत-हिन्दी/2").
FURNITURE = re.compile(r"^\s*संस्कृत\s*-\s*हिन्दी\s*/\s*\d+\s*$")
SENSE_NO = re.compile(r"(?:(?<=\s)|(?<=^)|(?<=[;,।]))(\d{1,2})\.\s?(?=\S)")


def clean_line(line):
    return unicodedata.normalize("NFC", line).replace("‌", "").replace("‍", "").strip()


def join_lines(lines):
    """Join printed lines into running text. A line ending in a hyphen
    directly after a letter is a word broken across lines: join without the
    hyphen (त्रिप्वघम-/र्षणम् -> त्रिप्वघमर्षणम्). Otherwise join with a space."""
    out = ""
    for line in lines:
        if not out:
            out = line
        elif re.search(r"[" + DEVA + r"]-$", out) and re.match(r"[" + DEVA + r"]", line):
            out = out[:-1] + line
        else:
            out += " " + line
    return out


def is_grammar(text):
    """A grammar label: all abbreviations ("वि.", "भ्वा. आ."), or, for verb
    roots, abbreviations followed by the verb's forms ("चुरा. उभ. अंशयति-ते")."""
    words = [w for w in re.split(r"[\s.,;]+", text) if w]
    if not words:
        return False
    if all(w in GRAMMAR_WORDS or w == "भी" for w in words):
        return True
    return words[0] in GRAMMAR_WORDS and "." in text.split()[0] and len(words) >= 2


def split_heads(text):
    """Headword list from the bold run(s) at the start of an entry."""
    heads = [h.strip(" ,-") for h in re.split(r",", text)]
    return [h for h in heads if h and re.search("[" + DEVA + "]", h)]


def take_prefix(text):
    """Split the start of an entry body into grammar labels and etymology.
    Returns (grammar list, etymology list, rest)."""
    grammar, etymology = [], []
    rest = text
    while True:
        m = PAREN.match(rest)
        if m and is_grammar(m.group(1)):
            grammar.append(m.group(1).strip())
            rest = rest[m.end():]
            continue
        m = BRACKET.match(rest)
        if m:
            etymology.append("[" + m.group(1).strip() + "]")
            rest = rest[m.end():]
            continue
        # Alternative forms printed before the label: (**वत्**), (=मितंपच)
        m = PAREN.match(rest)
        if m and not grammar and ("**" in m.group(1) or m.group(1).lstrip().startswith("=")):
            etymology.append("(" + m.group(1).replace("**", "").strip() + ")")
            rest = rest[m.end():]
            continue
        break
    return grammar, etymology, rest.strip(" ,;")


def to_runs(text):
    """Plain text -> runs, with citations marked."""
    runs, pos = [], 0
    for m in CITATION.finditer(text):
        if m.start() > pos:
            runs.append(text[pos:m.start()])
        runs.append(["citation", m.group(1).strip()])
        pos = m.end()
    if pos < len(text):
        runs.append(text[pos:])
    runs = [r for r in runs if not (isinstance(r, str) and not r.strip())]
    if runs and isinstance(runs[0], str):
        runs[0] = runs[0].lstrip(" ,;-")
    if runs and isinstance(runs[-1], str):
        runs[-1] = runs[-1].rstrip(" ,;-")
    return [r for r in runs if r != ""]


def split_senses(text):
    """Numbered senses "1. ... 2. ...". Numbers must run in sequence from 1
    (or 2, when sense 1 is unnumbered), which keeps citation numbers such as
    "-श. 4." from being taken as sense numbers."""
    marks = []
    expect = None
    for m in SENSE_NO.finditer(text):
        n = int(m.group(1))
        if expect is None and n in (1, 2) or n == expect:
            marks.append((m.start(), m.end(), n))
            expect = n + 1
    if not marks:
        return [{"n": None, "runs": to_runs(text)}] if text.strip(" ,;।") else []
    senses = []
    head = text[:marks[0][0]].strip(" ,;")
    if head.strip(" ।"):
        senses.append({"n": None if marks[0][2] == 1 else "1", "runs": to_runs(head)})
    for i, (s, e, n) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[e:end].strip(" ,;")
        senses.append({"n": str(n), "runs": to_runs(body)})
    return [s for s in senses if s["runs"]]


def stem_of(headword):
    """Stem used to spell out compounds: the headword without its
    nominative ending (अघोरः -> अघोर, अङ्कम् -> अङ्क)."""
    h = headword.strip("*")
    for end in ("म्", "ः", "ं"):
        if h.endswith(end) and len(h) > len(end) + 1:
            return h[: -len(end)]
    return h


# Vowel sandhi for joining a compound part to a stem ending in the inherent
# "a": अ + अ/आ = आ, अ + इ/ई = ए, अ + उ/ऊ = ओ, अ + ए/ऐ = ऐ, अ + ओ/औ = औ,
# अ + ऋ = अर्. Enough for the common cases (अङ्क + अवतारः = अङ्कावतारः).
SANDHI = {"अ": "ा", "आ": "ा", "इ": "े", "ई": "े", "उ": "ो", "ऊ": "ो",
          "ए": "ै", "ऐ": "ै", "ओ": "ौ", "औ": "ौ", "ऋ": "र्"}
CONSONANT = re.compile("[\u0915-\u0939\u0958-\u095f]$")


def join_compound(stem, part):
    if part.startswith(stem):
        return part
    if part and part[0] in SANDHI and CONSONANT.search(stem):
        return stem + SANDHI[part[0]] + part[1:]
    return stem + part


def derive(fragment, base):
    """A derived form: replace the end of `base` from the fragment's first
    letter (अघोर + -रः = अघोरः, अङ्कधारणं + -णा = अङ्कधारणा)."""
    b = base.strip("*")
    i = b.rfind(fragment[0]) if fragment else -1
    return b[:i] + fragment if i > 0 else b + fragment


def full_form(fragment, headword, compound, previous=None):
    """Spell out a printed sub-entry head. In the compound section a short
    ending right after a compound derives from that compound (-णा after
    धारणं); otherwise compounds join the headword's stem. Derived forms
    replace the end of the headword."""
    frag = fragment.lstrip("-").strip()
    if not frag:
        return headword
    if compound:
        if previous and len(frag) <= 2:
            return derive(frag, previous)
        return join_compound(stem_of(headword), frag)
    if not fragment.startswith("-") and len(frag) > 2:
        return frag  # printed in full already (अघ्रेयं)
    return derive(frag, headword)


def parse_body(text, headword):
    """Split an entry's running text after the head into the main part and
    bold sub-entries (derived forms and compounds)."""
    pieces = []  # (bold heads, is_compound, text after)
    pos = 0
    main_text = None
    in_compounds = False
    # Group consecutive bold runs separated only by commas/dashes/spaces:
    # "-**पथः** -**मार्गः**" is one sub-entry with two headwords.
    def depth(i):
        d = 0
        for ch in text[:i]:
            d += ch in "([" and 1 or (ch in ")]" and -1 or 0)
        return d
    matches = [m for m in BOLD.finditer(text) if depth(m.start()) <= 0]
    groups = []
    for m in matches:
        if groups and not text[groups[-1][-1].end():m.start()].strip(" ,-"):
            groups[-1].append(m)
        else:
            groups.append([m])
    for g in groups:
        before = text[pos:g[0].start()]
        if main_text is None:
            main_text = before
        else:
            pieces[-1][2] = before
        if re.search(r"सम\s*[.:ः]\s*-?\s*$", before.strip()) or re.search(r"सम\s*[.:ः]", before):
            in_compounds = True
        heads = []
        for m in g:
            dash = "-" if text[max(0, m.start() - 2):m.start()].strip().endswith("-") else ""
            heads.append(dash + m.group(1).strip())
        pieces.append([heads, in_compounds, ""])
        pos = g[-1].end()
    if main_text is None:
        main_text = text[pos:]
    elif pieces:
        pieces[-1][2] = text[pos:]
    main_text = re.sub(r"सम\s*[.:ः]\s*-?\s*$", "", main_text.strip()).strip(" ,;-")
    subs = []
    previous = None
    for heads, compound, body in pieces:
        body = re.sub(r"सम\s*[.:ः]\s*-?\s*$", "", body.strip()).strip(" ,;-")
        grammar, etymology, rest = take_prefix(body)
        full = [full_form(h, headword, compound, previous) for h in heads]
        previous = full[0]
        subs.append({
            "kind": "compound" if compound else "form",
            "heads": heads,
            "full": full,
            "grammar": grammar, "etymology": etymology,
            "senses": split_senses(rest),
        })
    return main_text, subs


def parse_entry(text, page):
    """One printed entry (its lines already joined) -> entry dict."""
    m = re.match(r"^\s*((?:\*\*.+?\*\*\s*,?\s*)+)", text)
    head_text = BOLD.sub(lambda b: b.group(1), m.group(1)) if m else ""
    heads = split_heads(head_text) or ["?"]
    rest = text[m.end():] if m else text
    grammar, etymology, rest = take_prefix(rest)
    main_text, subs = parse_body(rest, heads[0])
    return {
        "page": page, "heads": heads, "grammar": grammar, "etymology": etymology,
        "senses": split_senses(main_text), "subs": subs,
    }


HEADWORD_START = re.compile(r"^\*\*([^*]+)\*\*")
# An entry's bold headword(s) are followed by a grammar label "(", an
# etymology "[" (or, in a list of headwords, another bold word after ",").
# Bold followed by anything else (a dash, ")", text) is a verb prefix,
# a compound continued from the previous line, or "सम.".
ENTRY_HEAD = re.compile(r"^(?:\*\*[^*]+\*\*\s*,?\s*)+[(\[]")


def starts_entry(text, at_edge):
    """A line opens an entry when it starts, at the column edge, with a bold
    run that looks like a headword: Devanagari letters (bold sense numbers
    such as **5.** don't count), no danda, at most four words."""
    m = HEADWORD_START.match(text)
    if not (m and at_edge):
        return False
    head = m.group(1).strip()
    return (re.search("[\u0904-\u0939]", head) is not None and "।" not in head
            and not head.startswith("-") and len(head.split()) <= 4
            and ENTRY_HEAD.match(text) is not None)


def segment(lines):
    """Cut a stream of (page, text, starts_at_column_edge) into entries.
    A new entry starts at a line that begins with a bold headword at the
    column edge (continuation lines have a hanging indent)."""
    entries, cur, cur_page = [], [], None
    lead = []  # text before the first entry (continues an earlier batch)
    prev = ""
    starts = []  # index in `lines` of each entry's first line
    for index, (page, text, at_edge) in enumerate(lines):
        text = clean_line(text)
        if not text or FURNITURE.match(text):
            continue
        # After a line ending in a dash or comma, a bold word continues a
        # list of compounds ("...;-" / "**त्राणं** ...") rather than
        # starting a new entry.
        continues = prev.rstrip().endswith(("-", ",", "—", "**"))
        prev = text
        if starts_entry(text, at_edge) and not continues:
            if cur:
                entries.append((cur_page, cur))
            cur, cur_page = [text], page
            starts.append(index)
        elif cur:
            cur.append(text)
        else:
            lead.append(text)
    if cur:
        entries.append((cur_page, cur))
    parsed = [parse_entry(join_lines(ls), page) for page, ls in entries]
    for e, i in zip(parsed, starts):
        e["line_index"] = i
    return lead, parsed
