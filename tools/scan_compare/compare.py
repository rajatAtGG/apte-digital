#!/usr/bin/env python3
"""Compare OCR of the printed Apte Sanskrit-Hindi dictionary with the
Samsaadhanii digital text, and list the places where they differ.

    python3 tools/scan_compare/compare.py OCR_DIR --batch NAME --out OUT_DIR
        [--first-page N]   first PDF page that holds dictionary entries
        [--db build/apte.sqlite]

OCR_DIR holds p-NNNN.tsv/.png from ocr_pages.sh. Writes to OUT_DIR:
    NAME-findings.csv    one row per finding (for tracking review status)
    NAME-report.html     self-contained review page with a crop of the
                         printed line next to the digital text
    NAME-entries.json    OCR entries and how they were aligned (debugging)

How it works
------------
1. OCR words are read in Tesseract's reading order (it follows the two
   columns), the running header and the scanner watermark are dropped.
2. The word stream is cut into entries: a line that starts with one or more
   headwords followed by a grammar label such as "(पुं)" or "(वि.)" opens a
   new entry.
3. Printed entries are aligned, in order, with the digital main entries
   (fuzzy headword match with a look-ahead window), so OCR noise in one
   headword does not derail the rest.
4. For each aligned pair, the word sequences are diffed. A finding is kept
   only when the evidence is good enough to be worth a human's time:
     - missing_in_digital: >= 3 consecutive printed words, well recognised,
       absent from the digital entry (a dropped sense or phrase);
     - missing_in_print: >= 4 consecutive digital words absent from print;
     - spelling: a single word differs, the OCR word was read with high
       confidence, the two spellings are close, and the printed spelling is
       a word that occurs elsewhere in the dictionary;
     - grammar: the printed part-of-speech label differs from the digital;
     - entry_missing_in_digital / entry_missing_in_print: unaligned entries.
   Every finding is a *candidate*: OCR can be wrong, so each one shows the
   page image crop for the reviewer to decide.
"""

import argparse
import base64
import collections
import csv
import difflib
import glob
import html
import io
import json
import os
import re
import sqlite3
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from normalize import normalize  # noqa: E402

DEVA = re.compile(r"[ऀ-ॿ]")
# Grammar labels that open an entry, as printed (with OCR variants:
# "पु" for "पुं", missing dots and spaces).
GRAMMAR = r"(?:पुं?|नपुं?|वि|स्त्री|अव्य|क्रि|सर्व|संख्या|उभ|भ्वा|अदा|जुहो|दिवा|स्वा|तुदा|रुधा|तना|क्र्या|चुरा|आ|पर)"
# A headword: optional "*", then a letter (not a vowel sign), then letters
# and signs only, so continuation lines like "सम.-पुः" or "-ष्ठः" never match.
HEAD = r"[*]?[ऄ-हक़-ॡॲ-ॿ][ऀ-ॣ‌‍]*"
ENTRY_START = re.compile(
    r"^\s*(?P<head>" + HEAD + r"(?:\s*,\s*" + HEAD + r"){0,4})\s*,?\s*"
    r"[\(\[{]\s*" + GRAMMAR + r"[\s.)०॰,]")
GRAMMAR_KEY = {"पु": "पुं", "पुं": "पुं", "नपु": "नपुं", "नपुं": "नपुं", "वि": "वि",
               "स्त्री": "स्त्री", "अव्य": "अव्य"}
TEXT_MODE = False  # True when reading LLM transcriptions instead of OCR

DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


# ----------------------------------------------------------------- OCR side

def read_page(tsv_path):
    """Lines of one page as dicts {words: [(text, conf, box)], box}, in
    Tesseract's reading order, without the running header and watermark."""
    rows = list(csv.reader(open(tsv_path, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE))
    head, rows = rows[0], rows[1:]
    ix = {k: i for i, k in enumerate(head)}
    page_h = page_w = 1
    lines = collections.OrderedDict()
    for r in rows:
        if len(r) < len(head):
            continue
        level = int(r[ix["level"]])
        box = tuple(int(r[ix[k]]) for k in ("left", "top", "width", "height"))
        if level == 1:
            page_w, page_h = box[2], box[3]
        if level != 5 or not r[ix["text"]].strip():
            continue
        key = (int(r[ix["block_num"]]), int(r[ix["par_num"]]), int(r[ix["line_num"]]))
        lines.setdefault(key, []).append((r[ix["text"]], float(r[ix["conf"]]), box))
    out = []
    for words in lines.values():
        text = " ".join(w[0] for w in words)
        x0 = min(w[2][0] for w in words); y0 = min(w[2][1] for w in words)
        x1 = max(w[2][0] + w[2][2] for w in words); y1 = max(w[2][1] + w[2][3] for w in words)
        if not DEVA.search(text):
            continue  # watermark "Scanned with CamScanner", stray marks
        if y1 < page_h * 0.075:
            continue  # running header: guide words and page number
        out.append({"text": text, "words": words, "box": (x0, y0, x1, y1)})
    return out, (page_w, page_h)


def load_text_pages(strip_dir, text_dir, first_page=1, override=None):
    """Pages built from transcribed strips (see make_strips.py) instead of
    Tesseract: each strip's text file is read line by line and each line is
    given the OCR box of the corresponding printed line (for the indent test
    and for scan crops). `override` maps "STRIP#LINE" to a replacement text
    (the Opus re-read of that line). Lines carry "src" = "STRIP#LINE"."""
    override = override or {}
    manifest = json.load(open(os.path.join(strip_dir, "manifest.json"), encoding="utf-8"))
    by_page = collections.OrderedDict()
    for s in manifest:
        if s["page"] >= first_page:
            by_page.setdefault(s["page"], []).append(s)
    pages = []
    for page, strips in by_page.items():
        lines = []
        for s in strips:  # manifest order: left column top-down, then right
            path = os.path.join(text_dir, s["id"] + ".txt")
            if not os.path.exists(path):
                print(f"warning: missing transcription {path}", file=sys.stderr)
                continue
            texts = [t.strip() for t in open(path, encoding="utf-8") if t.strip()]
            boxes, n, m = s["lines"], len(texts), len(s["lines"])
            for i, t in enumerate(texts):
                # Same line count as OCR (the normal case): use its box;
                # otherwise the proportionally nearest one.
                box = boxes[i] if n == m else boxes[min(m - 1, round(i * (m - 1) / max(n - 1, 1)))]
                key = f"{s['id']}#{i}"
                t = override.get(key, t)
                words = [(w, 99.0, tuple(box)) for w in t.split()]
                lines.append({"text": t, "words": words, "box": tuple(box), "src": key})
        # ocr_pages.sh scales every page to 2480 px wide (A4 at 300 dpi).
        pages.append((page, lines, (2480, 3508)))
    return pages


def at_column_edge(lines, page_w, window=4, indent=0.009):
    """For each line, whether it starts at its column's left edge. Entries
    start there; continuation lines have a hanging indent. The page is a
    photo, so the edge drifts with skew: compare each line with the lines
    around it in the same column rather than with a page-wide edge."""
    flags = [False] * len(lines)
    for col in (0, 1):
        idx = [i for i, l in enumerate(lines) if (l["box"][0] >= page_w * 0.45) == bool(col)]
        idx.sort(key=lambda i: lines[i]["box"][1])
        for n, i in enumerate(idx):
            near = idx[max(0, n - window): n + window + 1]
            edge = min(lines[k]["box"][0] for k in near)
            flags[i] = lines[i]["box"][0] - edge <= page_w * indent
    return flags


def segment_entries(pages):
    """Cut the line stream of several pages into printed entries. A new entry
    starts at a line that begins at a column's left edge (continuation lines
    have a hanging indent) with headword(s) followed by a grammar label."""
    entries = []
    cur = None
    for page_no, lines, (page_w, _h) in pages:
        edge = at_column_edge(lines, page_w)
        for ln, at_edge in zip(lines, edge):
            m = ENTRY_START.match(ln["text"]) if at_edge else None
            if m:
                heads = [h.strip(" ,") for h in m.group("head").split(",") if h.strip(" ,")]
                cur = {"page": page_no, "heads": heads, "lines": []}
                entries.append(cur)
            if cur is None:
                continue  # text before the first entry (end of previous page's entry)
            cur["lines"].append({"page": page_no, **ln})
    for e in entries:
        e["text"] = " ".join(l["text"] for l in e["lines"])
        e["words"] = [w for l in e["lines"] for w in l["words"]]
        m = re.search(r"[\(\[{]\s*(" + GRAMMAR + r")", e["text"])
        e["grammar"] = GRAMMAR_KEY.get(m.group(1)) if m else None
    return entries


# -------------------------------------------------------------- corpus side

def runs_text(rs, skip=()):
    parts = []
    for r in rs:
        if isinstance(r, str):
            parts.append(r)
        elif r[0] not in skip:
            parts.append(" " + runs_text(r[1:], skip) + " ")
    return " ".join("".join(parts).split())


def load_corpus(db_path):
    """Main entries in dictionary order with the full text of the entry and
    all its sub-entries (print runs compounds inline under the main word)."""
    db = sqlite3.connect(db_path)
    rows = db.execute("SELECT id, main_id, kind, headword, stem, grammar, body FROM entries ORDER BY id").fetchall()
    mains = []
    by_main = {}
    for id_, main_id, kind, hw, stem, grammar, body in rows:
        b = json.loads(body)
        parts = [hw, grammar]
        parts += [runs_text(e) for e in b.get("etymology", [])]
        parts += [runs_text(s["runs"]) for s in b.get("senses", [])]
        text = " ".join(p for p in parts if p)
        if kind == "main":
            m = {"id": id_, "headword": hw, "stem": stem or hw, "grammar": grammar, "text": text,
                 "keys": {ocr_key(hw), ocr_key(stem or hw)}}
            mains.append(m)
            by_main[id_] = m
        else:
            by_main[main_id]["text"] += " " + text
            by_main[main_id].setdefault("sub_keys", set()).add(ocr_key(hw))
    return mains


def tokens(text):
    """Comparable word tokens: NFC, digits unified to ASCII, punctuation and
    abbreviation marks dropped. Keeps only tokens with Devanagari or digits."""
    t = unicodedata.normalize("NFC", text).translate(DIGITS)
    t = t.replace("‌", "").replace("‍", "").replace("़", "")
    t = re.sub(r"[*॰०.,;:!?'\"‘’“”()\[\]{}<>|/\\=+—–\-_।॥]", " ", t)
    return [w for w in t.split() if DEVA.search(w) or w.isdigit()]


def cmp_key(word):
    """Form used when diffing words: the search normalisation (visarga, joiners,
    nasal clusters) plus two conventions the print and the digital text write
    differently without meaning anything: a word-final anusvara for -म्
    (अजीकवं = अजीकवम्) and a word-final virama (ल्युट = ल्युट्)."""
    k = normalize(word)
    k = k[:-1] if k.endswith("\u094d") else k
    return k[:-1] + "म" if k.endswith("\u0902") else k


def ocr_key(text):
    """Headword key that also forgives Tesseract's commonest slips: dropped
    anusvara/candrabindu, nukta and a lost virama (joiners are already
    removed by normalize)."""
    return re.sub("[\u0900-\u0902\u093c\u094d]", "", normalize(text))


def similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------- alignment

def head_score(entry, main):
    """How well a printed entry's headwords match a digital main entry."""
    best = 0.0
    for h in entry["heads"]:
        k = ocr_key(h)
        if not k:
            continue
        for mk in main["keys"]:
            if mk:
                best = max(best, similar(k, mk))
    return best


def align(entries, mains, start, end, threshold=0.88):
    """Global, order-preserving alignment of printed entries with digital
    main entries mains[start:end] (dynamic programming, as in sequence
    alignment). A pair scores its headword similarity when that is at least
    `threshold`; gaps cost nothing, so OCR noise in one headword cannot
    derail its neighbours. Each printed entry then also absorbs unmatched
    digital entries right after its match that carry one of its other listed
    headwords (print often lists अंशुक, अंशुकम् together)."""
    seg = mains[start:end]
    n, m = len(entries), len(seg)
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    move = [[0] * (m + 1) for _ in range(n + 1)]  # 0 pair, 1 skip printed, 2 skip digital
    for i in range(1, n + 1):
        e = entries[i - 1]
        for j in range(1, m + 1):
            best, mv = score[i - 1][j], 1
            if score[i][j - 1] > best:
                best, mv = score[i][j - 1], 2
            sc = head_score(e, seg[j - 1])
            if sc >= threshold and score[i - 1][j - 1] + sc > best:
                best, mv = score[i - 1][j - 1] + sc, 0
            score[i][j], move[i][j] = best, mv
    i, j, pairs = n, m, {}
    while i > 0 and j > 0:
        if move[i][j] == 0:
            pairs[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif move[i][j] == 1:
            i -= 1
        else:
            j -= 1
    used = set(pairs.values())
    owner_of = {k: i for i, k in pairs.items()}
    for i, e in enumerate(entries):
        e["match"], e["skipped"] = [], []
        if i not in pairs:
            continue
        k = pairs[i]
        e["match"] = [start + k]
        e["score"] = round(head_score(e, seg[k]), 3)
        k += 1
        while k < m and k not in used and head_score(e, seg[k]) >= 0.9:
            e["match"].append(start + k)
            used.add(k)
            k += 1
    # Digital entries no printed entry claimed, attributed (for the report)
    # to the printed entry they follow.
    last = None
    for k in range(m):
        if k in owner_of:
            last = owner_of[k]
        elif k not in used and last is not None:
            entries[last]["skipped"].append(start + k)


# -------------------------------------------------------------- comparison

def likely_wrong(printed, digital, vocab):
    """Which side of a spelling difference is probably the error, judged by
    how often each spelling occurs elsewhere in the digital dictionary: a
    form found nowhere else, when the other is common, is probably a typo.
    Either side can be wrong: the print has its own misprints."""
    p, d = vocab[printed], vocab[digital] - 1  # minus this occurrence
    if p >= 2 and d == 0:
        return "digital"
    if d >= 2 and p == 0:
        return "print"
    return ""


def compare_entry(e, mains, vocab, window_keys=frozenset()):
    findings = []
    digital_text = " ".join(mains[k]["text"] for k in e["match"])
    d_tok = tokens(digital_text)
    # Words of the neighbouring digital entries: print runs derived forms
    # (-मः, -नं) and compounds inline, the digital text often stores them as
    # separate entries next to this one.
    lo, hi = max(e["match"][0] - 15, 0), min(e["match"][-1] + 16, len(mains))
    near_keys = {cmp_key(t) for k in range(lo, hi) for t in tokens(mains[k]["text"])}
    # Printed tokens keep their OCR confidence and box for evidence.
    p_tok, p_meta = [], []
    for li, ln in enumerate(e["lines"]):
        for text, conf, box in ln["words"]:
            for t in tokens(text):
                p_tok.append(t)
                p_meta.append((conf, li))
    # Diff on comparison keys; report the original spellings.
    sm = difflib.SequenceMatcher(None, [cmp_key(t) for t in p_tok], [cmp_key(t) for t in d_tok], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        pw, dw = p_tok[i1:i2], d_tok[j1:j2]
        confs = [p_meta[i][0] for i in range(i1, i2)]
        lines = sorted({p_meta[i][1] for i in range(i1, i2)}) or [p_meta[min(i1, len(p_meta) - 1)][1]]
        mean = sum(confs) / len(confs) if confs else 0
        ctx_d = " ".join(d_tok[max(0, j1 - 4):j2 + 4])
        # Printed words that are real dictionary words (OCR junk is not).
        known = sum(1 for w in pw if vocab[w] >= 2 and not w.isdigit()) / max(len(pw), 1)
        # A run that starts with a headword the digital text has elsewhere is
        # a following entry whose start OCR missed, not a missing passage.
        starts_entry = any(ocr_key(w) in window_keys for w in pw[:3] if len(w) > 2)
        # A printed word counts as present nearby if a neighbouring digital
        # word is it, or ends with it (compound parts: -जः for अत्रिजः).
        def nearby(w):
            k = cmp_key(w)
            return k in near_keys or (len(k) >= 2 and any(t.endswith(k) for t in near_keys))
        elsewhere = sum(nearby(w) for w in pw) / max(len(pw), 1) >= 0.8
        if op in ("insert", "replace") and len(pw) >= 4 and len(dw) <= len(pw) // 3 and mean >= 80 \
                and known >= 0.7 and not starts_entry and not elsewhere:
            findings.append(("missing_in_digital", pw, dw, mean, lines, ctx_d))
        elif op in ("delete", "replace") and len(dw) >= 4 and len(pw) <= len(dw) // 4:
            findings.append(("missing_in_print", pw, dw, mean, lines, ctx_d))
        elif op == "replace" and len(pw) == 1 and len(dw) == 1:
            a, b = pw[0], dw[0]
            r = similar(a, b)
            # Close spellings, confident OCR, and the printed spelling is a
            # real word elsewhere in the dictionary while the digital one is
            # rare: the strongest single-word evidence we can get.
            ocr_rule = mean >= 90 and vocab[a] >= 2 and vocab[b] <= 2
            # Print abbreviates compounds under the main word (-धूर्तिलः under
            # अक्ष); the digital text spells them out (अक्षधूर्तिलः).
            compound = len(b) > len(a) + 1 and cmp_key(b).endswith(cmp_key(a).lstrip("-"))
            if 0.6 <= r < 1 and len(a) >= 2 and cmp_key(a) != cmp_key(b) and not compound \
                    and (TEXT_MODE or ocr_rule):
                findings.append(("spelling", pw, dw, mean, lines, ctx_d))
    g_print = e.get("grammar")
    g_dig = mains[e["match"][0]]["grammar"] or ""
    g_dig_key = next((GRAMMAR_KEY[g] for g in re.findall(r"[ऀ-ॿ]+", g_dig) if g in GRAMMAR_KEY), None)
    # Only meaningful for the same headword: print often gives the adjective
    # with its noun forms inline, where the digital text has split entries.
    same_head = ocr_key(e["heads"][0]) == ocr_key(mains[e["match"][0]]["headword"])
    if g_print and g_dig_key and g_print != g_dig_key and same_head:
        findings.append(("grammar", [g_print], [g_dig], 100, [0], g_dig))
    return findings


# ------------------------------------------------------------------ report

def crop(page_png, boxes, pad=12, max_w=1100):
    """JPEG data URI of the union of `boxes` on a page image."""
    from PIL import Image
    im = Image.open(page_png)
    x0 = max(min(b[0] for b in boxes) - pad, 0); y0 = max(min(b[1] for b in boxes) - pad, 0)
    x1 = min(max(b[2] for b in boxes) + pad, im.width); y1 = min(max(b[3] for b in boxes) + pad, im.height)
    c = im.crop((x0, y0, x1, y1))
    if c.width > max_w:
        c = c.resize((max_w, int(c.height * max_w / c.width)))
    buf = io.BytesIO()
    c.convert("L").save(buf, "JPEG", quality=70)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


LABEL = {
    "missing_in_digital": "Printed text missing in digital",
    "missing_in_print": "Digital text not found in print",
    "spelling": "Spelling differs",
    "grammar": "Grammar label differs",
    "entry_missing_in_digital": "Printed entry not in digital",
    "entry_missing_in_print": "Digital entry not seen in print",
}
ORDER = list(LABEL)
# Precision measured by checking samples against the scan by eye (batch 1,
# PDF pages 19-50). Low-precision categories start hidden in the report.
PRECISION = {
    "missing_in_digital": "~60% real",
    "missing_in_print": "mostly OCR noise",
    "spelling": "~90% real",
    "grammar": "real differences; print itself is often the one in error",
    "entry_missing_in_digital": "~80% real; read the true headword from the crop",
    "entry_missing_in_print": "mostly OCR missing the entry start",
}
HIDDEN = {"missing_in_print", "entry_missing_in_print"}
# Same, measured for the Sonnet-transcription + Opus-re-read pipeline (batch 1).
PRECISION_TEXT = {
    "missing_in_digital": "~60% real; the rest are compounds stored elsewhere",
    "missing_in_print": "not reviewed; mostly compounds spelled out in the digital text",
    "spelling": "print text verified 12/12; about half are digital typos, half print misprints",
    "grammar": "real differences; the print itself is often the one in error",
    "entry_missing_in_digital": "10/10 sampled were real",
    "entry_missing_in_print": "not reviewed; mostly entries the print gives inline",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ocr_dir")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--first-page", type=int, default=1, help="first PDF page with dictionary entries")
    ap.add_argument("--db", default=os.path.join(ROOT, "build", "apte.sqlite"))
    ap.add_argument("--app-url", default="https://rajatatgg.github.io/apte-digital/")
    ap.add_argument("--text", help="directory of strip transcriptions (instead of OCR text)")
    ap.add_argument("--strips", help="strip directory with manifest.json (with --text)")
    ap.add_argument("--override", help="JSON {\"STRIP#LINE\": text} of re-read lines (with --text)")
    args = ap.parse_args()

    global TEXT_MODE
    if args.text:
        TEXT_MODE = True
        override = json.load(open(args.override, encoding="utf-8")) if args.override else {}
        args.reread = set(override)
        pages = load_text_pages(args.strips, args.text, args.first_page, override)
    else:
        pages = []
        for tsv in sorted(glob.glob(os.path.join(args.ocr_dir, "p-*.tsv"))):
            n = int(re.search(r"p-(\d+)\.tsv", tsv).group(1))
            if n < args.first_page:
                continue
            lines, size = read_page(tsv)
            pages.append((n, lines, size))
    entries = segment_entries(pages)
    mains = load_corpus(args.db)
    vocab = collections.Counter(t for m in mains for t in tokens(m["text"]))

    # The digital range this batch covers: from the first to the last
    # printed entry whose headword matches a digital headword exactly.
    index = collections.defaultdict(list)
    for k, m in enumerate(mains):
        for key in m["keys"]:
            index[key].append(k)

    def anchor(seq, pick):
        for e in seq:
            hits = [k for h in e["heads"] for k in index.get(ocr_key(h), [])]
            if hits:
                return pick(hits)
        return None
    first = anchor(entries[:20], min) or 0
    last = anchor(list(reversed(entries[-20:])), max) or len(mains) - 1
    start, end = max(first - 3, 0), min(last + 4, len(mains))
    align(entries, mains, start, end)
    all_keys = set(index) | {k for m in mains for k in m.get("sub_keys", ())}
    window_keys = {k for m in mains[start:end] for k in m["keys"] | m.get("sub_keys", set()) if k}

    findings = []
    for e in entries:
        if not e["match"]:
            # A candidate only if no digital headword anywhere (main or
            # sub-entry, allowing common nominative endings) has this key.
            keys = {ocr_key(h) for h in e["heads"]}
            variants = {k + suf for k in keys for suf in ("", "म", "ः", "ा", "ी")}
            # ...and no headword in this stretch of the alphabet is a near
            # match either (bold ज is often read as न, ङ्ग as ड्, etc.).
            near = max((similar(k, dk) for k in keys for dk in window_keys), default=0)
            if not variants & all_keys and near < 0.8:
                findings.append(dict(type="entry_missing_in_digital", entry=e, printed=" ".join(e["heads"]),
                                     digital="", conf=None, lines=[0]))
            continue
        for k in e.get("skipped", []):
            findings.append(dict(type="entry_missing_in_print", entry=e, printed="",
                                 digital=mains[k]["headword"], digital_id=mains[k]["id"], conf=None, lines=[0]))
        for typ, pw, dw, conf, lines, ctx in compare_entry(e, mains, vocab, window_keys):
            findings.append(dict(type=typ, entry=e, printed=" ".join(pw), digital=" ".join(dw),
                                 context=ctx, conf=round(conf), lines=lines,
                                 hint=likely_wrong(pw[0], dw[0], vocab) if typ == "spelling" else ""))

    os.makedirs(args.out, exist_ok=True)
    findings.sort(key=lambda f: (f["entry"]["page"], ORDER.index(f["type"])))
    rows = []
    reread = getattr(args, "reread", set())
    for i, f in enumerate(findings, 1):
        e = f["entry"]
        srcs = [e["lines"][j].get("src") for j in f["lines"] if j < len(e["lines"])]
        f["verified"] = bool(srcs) and all(x in reread for x in srcs)
        mid = f.get("digital_id") or (mains[e["match"][0]]["id"] if e["match"] else "")
        f["fid"] = f"{args.batch}-{i:04d}"
        f["digital_id"] = mid
        rows.append({
            "id": f["fid"], "pdf_page": e["page"], "type": f["type"],
            "printed_headword": " ".join(e["heads"]),
            "digital_headword": mains[e["match"][0]]["headword"] if e["match"] else "",
            "digital_entry_id": mid, "printed": f["printed"], "digital": f["digital"],
            "ocr_confidence": "" if TEXT_MODE or f["conf"] is None else f["conf"],
            "verified_by_reread": "yes" if f["verified"] else "",
            "likely_error_in": f.get("hint", ""), "status": "", "note": "",
        })
    with open(os.path.join(args.out, f"{args.batch}-findings.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)

    # Alignment summary
    matched = sum(1 for e in entries if e["match"])
    span = (mains[start]["headword"], mains[end - 1]["headword"]) if end > start else ("", "")
    counts = collections.Counter(f["type"] for f in findings)
    summary = {
        "batch": args.batch, "pages": f"{pages[0][0]}–{pages[-1][0]}" if pages else "",
        "printed_entries": len(entries), "aligned": matched,
        "digital_range": span, "digital_entries_in_range": end - start,
        "findings": {k: counts.get(k, 0) for k in ORDER},
    }
    json.dump({"summary": summary, "entries": [
        {"page": e["page"], "heads": e["heads"], "grammar": e["grammar"],
         "match": [mains[k]["headword"] for k in e["match"]], "score": e.get("score"),
         "text": e["text"][:300]} for e in entries]},
        open(os.path.join(args.out, f"{args.batch}-entries.json"), "w", encoding="utf-8"),
        ensure_ascii=False, indent=1)
    json.dump([{"id": f["fid"], "type": f["type"], "page": f["entry"]["page"],
                "printed_headword": " ".join(f["entry"]["heads"]), "printed": f["printed"], "digital": f["digital"],
                "lines": [{"src": ln.get("src"), "page": ln["page"], "box": ln["box"], "text": ln["text"]}
                          for ln in (f["entry"]["lines"][i] for i in f["lines"] if i < len(f["entry"]["lines"]))]}
               for f in findings],
              open(os.path.join(args.out, f"{args.batch}-findings.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    write_html(args, findings, summary, mains)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def write_html(args, findings, summary, mains):
    esc = html.escape
    cards = []
    for f in findings:
        e = f["entry"]
        lines = [e["lines"][i] for i in f["lines"] if i < len(e["lines"])] or e["lines"][:1]
        by_page = collections.defaultdict(list)
        for ln in lines:
            by_page[ln["page"]].append(ln["box"])
        # No crops for the low-precision categories: keeps the page small.
        imgs = "" if f["type"] in HIDDEN else "".join(
            f'<img alt="scan" src="{crop(os.path.join(args.ocr_dir, f"p-{p:04d}.png"), b)}">'
            for p, b in by_page.items())
        link = f'{args.app_url}#/e/{f["digital_id"]}' if f["digital_id"] else ""
        hidden = " hidden" if f["type"] in HIDDEN else ""
        cards.append(f"""<article class="f t-{f['type']}" data-type="{f['type']}"{hidden}>
  <header><b>{esc(f['fid'])}</b> · PDF p.{e['page']} · <span class="tag">{esc(LABEL[f['type']])}</span>
  · <span class="hw">{esc(' / '.join(e['heads']))}</span>
  {f'· <a href="{esc(link)}" target="_blank" rel="noopener">digital entry</a>' if link else ''}
  {f'· OCR conf {f["conf"]}' if f.get('conf') is not None and not TEXT_MODE else ''}
  {'· <b class="ok">verified by Opus re-read</b>' if f.get('verified') else ''}
  {f'· likely error in <b>{f["hint"]}</b>' if f.get('hint') else ''}</header>
  <div class="scan">{imgs}</div>
  <dl><dt>Print</dt><dd>{esc(f['printed']) or '—'}</dd>
      <dt>Digital</dt><dd>{esc(f['digital']) or '—'}</dd>
      {f"<dt>Digital context</dt><dd class='ctx'>{esc(f.get('context',''))}</dd>" if f.get('context') else ''}</dl>
</article>""")
    s = summary
    counts = "".join(f'<label><input type="checkbox" {"" if k in HIDDEN else "checked"} value="{k}"> '
                     f'{esc(LABEL[k])} <b>{v}</b> <small>({esc((PRECISION_TEXT if TEXT_MODE else PRECISION)[k])})</small></label>'
                     for k, v in s["findings"].items())
    doc = f"""<!doctype html><html lang="hi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Apte print vs digital · {esc(args.batch)}</title>
<style>
:root{{--bg:#fbf8f1;--card:#fff;--ink:#2a2420;--muted:#6f655b;--line:#ddd3c3;--accent:#7a2e1d}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1b1714;--card:#24201c;--ink:#ece4d8;--muted:#a99d8f;--line:#3a332d;--accent:#e3a27f}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 'Noto Serif Devanagari','Kohinoor Devanagari',serif}}
main{{max-width:1000px;margin:0 auto;padding:16px}}
h1{{color:var(--accent);font-size:1.4em;margin:.2em 0}}
.sum{{color:var(--muted);font-size:.92em}} .filters{{display:flex;flex-wrap:wrap;gap:6px 16px;margin:10px 0 16px;font-size:.9em}}
article{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:0 0 12px}}
article header{{font-size:.85em;color:var(--muted)}} .hw{{color:var(--ink);font-weight:700;font-size:1.1em}}
.tag{{color:var(--accent);font-weight:600}} .scan img{{max-width:100%;display:block;margin:8px 0;border:1px solid var(--line);background:#fff}}
dl{{display:grid;grid-template-columns:8em 1fr;gap:2px 10px;margin:4px 0 0}} dt{{color:var(--muted);font-size:.85em}} dd{{margin:0}}
.ctx{{color:var(--muted);font-size:.9em}} a{{color:var(--accent)}} .ok{{color:#2e7d32}}
</style></head><body><main>
<h1>Printed Apte vs Samsaadhanii · {esc(args.batch)}</h1>
<p class="sum">PDF pages {esc(s['pages'])} · {s['printed_entries']} printed entries found, {s['aligned']} aligned with
digital entries ({esc(s['digital_range'][0])} … {esc(s['digital_range'][1])}, {s['digital_entries_in_range']} digital main entries).
{"Print text: Sonnet 5.5 transcription; every line behind a finding re-read by Opus 5.5." if TEXT_MODE else "Print text: Tesseract OCR."}
Every item is a candidate difference: check the scan crop, and remember either side can be the one in error.</p>
<div class="filters">{counts}</div>
{''.join(cards) or '<p>No findings.</p>'}
</main><script>
document.querySelector('.filters').addEventListener('change',()=>{{
  const on=new Set([...document.querySelectorAll('.filters input:checked')].map(i=>i.value));
  document.querySelectorAll('article').forEach(a=>a.hidden=!on.has(a.dataset.type));
}});
</script></body></html>"""
    with open(os.path.join(args.out, f"{args.batch}-report.html"), "w", encoding="utf-8") as fh:
        fh.write(doc)


if __name__ == "__main__":
    main()
