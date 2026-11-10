#!/usr/bin/env python3
"""Build the app database from the digitised printed edition.

    python3 pipeline/build_print.py --strips DIR [DIR ...] --text DIR [DIR ...] \
        --first-page 19 --last-page 300 [--override FILE] --out build_print/

Reads the page transcriptions (see tools/scan_compare/make_strips.py and the
transcription brief), parses them into entries (pipeline/print_parser.py)
and writes the same SQLite layout as pipeline/build.py, so the app works
unchanged:

    build_print/apte.sqlite    entries, search keys, FTS5 over senses
    build_print/entries.json   parsed entries (for checking and re-use)
    build_print/report.txt     counts and the quality checks below

Quality checks (printed in the report, written to suspects.json):
  * headword order: the dictionary is in varnamala order, so a headword that
    sorts out of place relative to both neighbours is probably misread;
  * entries with no grammar label or no senses (often a broken entry start).
The lines behind suspects can be re-read by a stronger model and fed back
with --override (see tools/scan_compare/recheck.py).
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build import SCHEMA, SENSE_STRIDE  # noqa: E402
from normalize import collation_key, initial_letter, normalize, normalize_text  # noqa: E402
from print_pages import load_lines  # noqa: E402
from print_parser import segment, stem_of  # noqa: E402

FRONT_MATTER_PAGES = 18  # PDF page 19 is printed page 1


def runs_text(runs, skip=("citation",)):
    parts = []
    for r in runs:
        if isinstance(r, str):
            parts.append(r)
        elif r[0] not in skip:
            parts.append(" " + runs_text(r[1:], skip) + " ")
    return " ".join("".join(parts).split())


def find_suspects(entries):
    """Entries whose headword is out of varnamala order with respect to both
    neighbours (an isolated dip or spike), or that lack a label or senses."""
    keys = [collation_key(stem_of(e["heads"][0])) for e in entries]
    out = []
    for i, e in enumerate(entries):
        reasons = []
        if 0 < i < len(entries) - 1:
            # Only gross misplacement: the neighbours share their first two
            # sounds and this headword neither shares them nor sorts between
            # the neighbours. (The book has its own ordering conventions for
            # anusvara, virama etc., so finer order checks are mostly noise.)
            a, b, c = keys[i - 1], keys[i], keys[i + 1]
            if a[:2] == c[:2] and b[:2] != a[:2] and not (a <= b <= c):
                reasons.append("out of order")
        if not e["grammar"]:
            reasons.append("no grammar label")
        if not e["senses"] and not e["subs"]:
            reasons.append("no senses")
        if reasons:
            out.append({"index": i, "page": e["page"], "heads": e["heads"], "reasons": reasons,
                        "line": e.get("line_key")})
    return out


def build(args):
    override = json.load(open(args.override, encoding="utf-8")) if args.override else {}
    lines, missing = load_lines(args.strips, args.text, args.first_page, args.last_page, override)
    # Remember which source line starts each entry (for re-reading suspects).
    lead, entries = segment([(p, t, e) for (p, t, e, k) in lines])
    for e in entries:
        e["line_key"] = lines[e.pop("line_index")][3]  # source line, for re-reading

    os.makedirs(args.out, exist_ok=True)
    db_path = os.path.join(args.out, "apte.sqlite")
    if os.path.exists(db_path):
        os.remove(db_path)
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)

    next_id, n_sub, n_sense = 1, 0, 0
    for seq, e in enumerate(entries, 1):
        heads = e["heads"]
        main_id = next_id
        next_id += 1
        sort_key = f"{seq:06d}"  # printed order (already varnamala order)
        body = {"heads": heads, "page": e["page"], "book_page": e["page"] - FRONT_MATTER_PAGES,
                "grammar": [[g] for g in e["grammar"]], "etymology": [[x] for x in e["etymology"]],
                "senses": e["senses"]}
        rows = [(main_id, None, "main", 0, ", ".join(heads), heads[0], body, sort_key,
                 " ".join(e["grammar"]), e["senses"], heads)]
        for j, s in enumerate(e["subs"], 1):
            sid = next_id
            next_id += 1
            n_sub += 1
            sbody = {"heads": s["heads"], "full": s["full"], "page": e["page"],
                     "book_page": e["page"] - FRONT_MATTER_PAGES,
                     "grammar": [[g] for g in s["grammar"]], "etymology": [[x] for x in s["etymology"]],
                     "senses": s["senses"]}
            rows.append((sid, main_id, s["kind"], 1, ", ".join(s["heads"]), s["full"][0], sbody,
                         f"{sort_key}.{j:03d}", " ".join(s["grammar"]), s["senses"],
                         s["full"] + [h.lstrip("-") for h in s["heads"]]))
        for (eid, parent, kind, depth, display, stem_src, b, skey, grammar, senses, keyforms) in rows:
            letter = initial_letter(stem_src.lstrip("*-")) or initial_letter(heads[0].lstrip("*"))
            db.execute("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (eid, main_id, parent, kind, depth, "print", str(seq), display, 1,
                        stem_of(stem_src), normalize(stem_src), letter, skey, grammar,
                        json.dumps(b, ensure_ascii=False, separators=(",", ":"))))
            for k in {normalize(f) for f in keyforms} | {normalize(stem_of(f)) for f in keyforms}:
                if k:
                    db.execute("INSERT OR IGNORE INTO search_keys VALUES (?,?)", (k, eid))
            for i, s in enumerate(senses):
                text = normalize_text(runs_text(s["runs"]))
                if text:
                    db.execute("INSERT INTO senses_fts(rowid, text) VALUES (?,?)", (eid * SENSE_STRIDE + i, text))
                    n_sense += 1

    suspects = find_suspects(entries)
    pages = sorted({e["page"] for e in entries})
    counts = {"pages": len(pages), "entries": len(entries), "sub_entries": n_sub, "senses": n_sense,
              "suspects": len(suspects), "missing_strips": len(missing)}
    about = (
        "<p>This edition is digitised from a scan of the printed <b>संस्कृत-हिन्दी शब्दकोश</b> by "
        "<b>Vaman Shivram Apte</b>, Hindi edition revised and edited by <b>Dr. Uma Prasad Pandey</b> "
        "(Kamal Prakashan, New Delhi; second revised edition).</p>"
        f"<p>Coverage so far: printed pages {pages[0] - FRONT_MATTER_PAGES}–{pages[-1] - FRONT_MATTER_PAGES} "
        f"(PDF pages {pages[0]}–{pages[-1]}): {len(entries):,} entries and {n_sub:,} compounds and derived forms."
        "</p><p>Text was transcribed from the page images by Claude (Sonnet 5.5), with doubtful lines re-read "
        "by Claude (Opus 5.5). Transcription follows the print exactly, including its misprints. "
        "Compound headwords are printed in the book as fragments (-पथः); the full form shown beside them "
        "(अघोरपथः) is reconstructed and may occasionally miss a sandhi.</p>"
        "<p>The printed edition is under copyright. This copy is for private use and is not for "
        "redistribution.</p>")
    meta = {
        "title": "आप्टे संस्कृत-हिन्दी शब्दकोश (मुद्रित संस्करण)",
        "source": "print scan",
        "edition": "Kamal Prakashan, ed. Uma Prasad Pandey",
        "pages": f"{pages[0]}-{pages[-1]}",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": "1",
        "counts": json.dumps(counts),
        "about_html": about,
    }
    db.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    db.commit()
    db.execute("INSERT INTO senses_fts(senses_fts) VALUES ('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()

    json.dump({"lead": lead, "entries": entries}, open(os.path.join(args.out, "entries.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=0)
    json.dump(suspects, open(os.path.join(args.out, "suspects.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    by_reason = {}
    for s in suspects:
        for r in s["reasons"]:
            by_reason[r] = by_reason.get(r, 0) + 1
    report = "\n".join([
        "Apte (printed edition) build report",
        f"PDF pages {pages[0]}-{pages[-1]} ({len(pages)} pages); missing strip transcriptions: {len(missing)}",
        f"entries {len(entries)}, sub-entries {n_sub}, indexed senses {n_sense}",
        f"suspects {len(suspects)}: " + ", ".join(f"{k} {v}" for k, v in by_reason.items()),
        f"database {os.path.getsize(db_path) / 1e6:.1f} MB",
    ])
    open(os.path.join(args.out, "report.txt"), "w").write(report + "\n")
    print(report)
    if missing:
        print("missing:", " ".join(missing[:30]), file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strips", nargs="+", required=True)
    ap.add_argument("--text", nargs="+", required=True)
    ap.add_argument("--first-page", type=int, default=19)
    ap.add_argument("--last-page", type=int, default=10**6)
    ap.add_argument("--override")
    ap.add_argument("--out", required=True)
    build(ap.parse_args())
