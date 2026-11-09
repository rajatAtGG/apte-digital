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
ENTRY_START = re.compile(
    r"^\s*(?P<head>[ऀ-ॿ*][^\s(\[]*(?:\s*,\s*[ऀ-ॿ][^\s(\[,]*){0,4})\s*,?\s*"
    r"[\(\[{]\s*" + GRAMMAR + r"[\s.)०॰,]")
GRAMMAR_KEY = {"पु": "पुं", "पुं": "पुं", "नपु": "नपुं", "नपुं": "नपुं", "वि": "वि",
               "स्त्री": "स्त्री", "अव्य": "अव्य"}
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


def segment_entries(pages):
    """Cut the line stream of several pages into printed entries."""
    entries = []
    cur = None
    for page_no, lines, _size in pages:
        for ln in lines:
            m = ENTRY_START.match(ln["text"])
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
                 "keys": {normalize(hw), normalize(stem or hw)}}
            mains.append(m)
            by_main[id_] = m
        else:
            by_main[main_id]["text"] += " " + text
            by_main[main_id]["keys"].add(normalize(hw))
    return mains


def tokens(text):
    """Comparable word tokens: NFC, digits unified to ASCII, punctuation and
    abbreviation marks dropped. Keeps only tokens with Devanagari or digits."""
    t = unicodedata.normalize("NFC", text).translate(DIGITS)
    t = t.replace("‌", "").replace("‍", "").replace("़", "")
    t = re.sub(r"[*॰०.,;:!?'\"‘’“”()\[\]{}<>|/\\=+—–\-_।॥]", " ", t)
    return [w for w in t.split() if DEVA.search(w) or w.isdigit()]


def similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------- alignment

def head_score(entry, main):
    """How well a printed entry's headwords match a digital main entry."""
    best = 0.0
    for h in entry["heads"]:
        k = normalize(h)
        if not k:
            continue
        for mk in main["keys"]:
            if mk:
                best = max(best, similar(k, mk))
    return best


def align(entries, mains, start, lookahead=25, threshold=0.75):
    """Monotone alignment: each printed entry takes the best-matching digital
    main entry within `lookahead` of the current position, then absorbs the
    following digital entries that match its other listed headwords."""
    j = start
    for e in entries:
        cands = [(head_score(e, mains[k]), -(k - j), k) for k in range(j, min(j + lookahead, len(mains)))]
        score, _, k = max(cands) if cands else (0, 0, None)
        if score < threshold:
            e["match"] = []
            continue
        e["skipped"] = list(range(j, k))  # digital entries passed over
        e["match"] = [k]
        k += 1
        while k < len(mains) and head_score(e, mains[k]) >= 0.9:
            e["match"].append(k)
            k += 1
        e["score"] = round(score, 3)
        j = k
    return j


# -------------------------------------------------------------- comparison

def compare_entry(e, mains, vocab):
    findings = []
    digital_text = " ".join(mains[k]["text"] for k in e["match"])
    d_tok = tokens(digital_text)
    # Printed tokens keep their OCR confidence and box for evidence.
    p_tok, p_meta = [], []
    for li, ln in enumerate(e["lines"]):
        for text, conf, box in ln["words"]:
            for t in tokens(text):
                p_tok.append(t)
                p_meta.append((conf, li))
    sm = difflib.SequenceMatcher(None, p_tok, d_tok, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        pw, dw = p_tok[i1:i2], d_tok[j1:j2]
        confs = [p_meta[i][0] for i in range(i1, i2)]
        lines = sorted({p_meta[i][1] for i in range(i1, i2)}) or [p_meta[min(i1, len(p_meta) - 1)][1]]
        mean = sum(confs) / len(confs) if confs else 0
        ctx_d = " ".join(d_tok[max(0, j1 - 4):j2 + 4])
        if op in ("insert", "replace") and len(pw) >= 3 and len(dw) <= len(pw) // 3 and mean >= 80:
            findings.append(("missing_in_digital", pw, dw, mean, lines, ctx_d))
        elif op in ("delete", "replace") and len(dw) >= 4 and len(pw) <= len(dw) // 4:
            findings.append(("missing_in_print", pw, dw, mean, lines, ctx_d))
        elif op == "replace" and len(pw) == 1 and len(dw) == 1:
            a, b = pw[0], dw[0]
            r = similar(a, b)
            # Close spellings, confident OCR, and the printed spelling is a
            # real word elsewhere in the dictionary while the digital one is
            # rare: the strongest single-word evidence we can get.
            if 0.6 <= r < 1 and mean >= 90 and len(a) >= 3 and vocab[a] >= 2 and vocab[b] <= 2 \
                    and normalize(a) != normalize(b):
                findings.append(("spelling", pw, dw, mean, lines, ctx_d))
    g_print = e.get("grammar")
    g_dig = mains[e["match"][0]]["grammar"] or ""
    g_dig_key = next((GRAMMAR_KEY[g] for g in re.findall(r"[ऀ-ॿ]+", g_dig) if g in GRAMMAR_KEY), None)
    if g_print and g_dig_key and g_print != g_dig_key:
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ocr_dir")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--first-page", type=int, default=1, help="first PDF page with dictionary entries")
    ap.add_argument("--db", default=os.path.join(ROOT, "build", "apte.sqlite"))
    ap.add_argument("--app-url", default="https://rajatatgg.github.io/apte-digital/")
    args = ap.parse_args()

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

    # Start the alignment at the first confident match of the first entries.
    start = 0
    for e in entries[:5]:
        scores = [(head_score(e, m), -k, k) for k, m in enumerate(mains[:3000])]
        s, _, k = max(scores)
        if s >= 0.9:
            start = max(k - 2, 0)
            break
    end = align(entries, mains, start)

    findings = []
    for e in entries:
        if not e["match"]:
            findings.append(dict(type="entry_missing_in_digital", entry=e, printed=" ".join(e["heads"]),
                                 digital="", conf=None, lines=[0]))
            continue
        for k in e.get("skipped", []):
            findings.append(dict(type="entry_missing_in_print", entry=e, printed="",
                                 digital=mains[k]["headword"], digital_id=mains[k]["id"], conf=None, lines=[0]))
        for typ, pw, dw, conf, lines, ctx in compare_entry(e, mains, vocab):
            findings.append(dict(type=typ, entry=e, printed=" ".join(pw), digital=" ".join(dw),
                                 context=ctx, conf=round(conf), lines=lines))

    os.makedirs(args.out, exist_ok=True)
    findings.sort(key=lambda f: (f["entry"]["page"], ORDER.index(f["type"])))
    rows = []
    for i, f in enumerate(findings, 1):
        e = f["entry"]
        mid = f.get("digital_id") or (mains[e["match"][0]]["id"] if e["match"] else "")
        f["fid"] = f"{args.batch}-{i:04d}"
        f["digital_id"] = mid
        rows.append({
            "id": f["fid"], "pdf_page": e["page"], "type": f["type"],
            "printed_headword": " ".join(e["heads"]),
            "digital_headword": mains[e["match"][0]]["headword"] if e["match"] else "",
            "digital_entry_id": mid, "printed": f["printed"], "digital": f["digital"],
            "ocr_confidence": f["conf"] if f["conf"] is not None else "", "status": "", "note": "",
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
        imgs = "".join(f'<img alt="scan" src="{crop(os.path.join(args.ocr_dir, f"p-{p:04d}.png"), b)}">'
                       for p, b in by_page.items())
        link = f'{args.app_url}#/e/{f["digital_id"]}' if f["digital_id"] else ""
        cards.append(f"""<article class="f t-{f['type']}" data-type="{f['type']}">
  <header><b>{esc(f['fid'])}</b> · PDF p.{e['page']} · <span class="tag">{esc(LABEL[f['type']])}</span>
  · <span class="hw">{esc(' / '.join(e['heads']))}</span>
  {f'· <a href="{esc(link)}" target="_blank" rel="noopener">digital entry</a>' if link else ''}
  {f'· OCR conf {f["conf"]}' if f.get('conf') is not None else ''}</header>
  <div class="scan">{imgs}</div>
  <dl><dt>Print (OCR)</dt><dd>{esc(f['printed']) or '—'}</dd>
      <dt>Digital</dt><dd>{esc(f['digital']) or '—'}</dd>
      {f"<dt>Digital context</dt><dd class='ctx'>{esc(f.get('context',''))}</dd>" if f.get('context') else ''}</dl>
</article>""")
    s = summary
    counts = "".join(f'<label><input type="checkbox" checked value="{k}"> {esc(LABEL[k])} <b>{v}</b></label>'
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
.ctx{{color:var(--muted);font-size:.9em}} a{{color:var(--accent)}}
</style></head><body><main>
<h1>Printed Apte vs Samsaadhanii · {esc(args.batch)}</h1>
<p class="sum">PDF pages {esc(s['pages'])} · {s['printed_entries']} printed entries found by OCR, {s['aligned']} aligned with
digital entries ({esc(s['digital_range'][0])} … {esc(s['digital_range'][1])}, {s['digital_entries_in_range']} digital main entries).
Every item is a candidate: OCR can misread, so compare against the scan crop before accepting it.</p>
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
