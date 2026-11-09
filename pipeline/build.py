#!/usr/bin/env python3
"""Build the Apte Sanskrit-Hindi dictionary database.

    python3 pipeline/build.py [--src DIR] [--out DIR]

Reads every *.xml in the Apte_dict directory and writes:

    build/apte.sqlite   SQLite database (schema below) with an FTS5 index
    build/apte.json     the same data as one nested JSON document
    build/report.txt    the validation report (also printed)

The build fails (exit status 1) if the parsed counts differ from
pipeline/expected.json.
"""

import argparse
import collections
import glob
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apte_parser import (DTD_TAGS, count_citations, iter_entries, iter_tags,  # noqa: E402
                         parse_file, runs_text)
from normalize import collation_key, initial_letter, normalize, normalize_text  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = os.path.join(ROOT, "data", "raw", "scl", "MT", "data", "hi", "Apte_dict")

# Devanagari vowel signs and other combining marks. FTS5's unicode61
# tokenizer treats these as separators by default, which splits पात्र into
# प / त / र; declaring them as token characters keeps words whole.
TOKENCHARS = "".join(chr(c) for c in range(0x0900, 0x0904)) + \
    "".join(chr(c) for c in range(0x093a, 0x0950) if c != 0x093d) + \
    "".join(chr(c) for c in range(0x0951, 0x0958)) + "ॢॣ"

SENSE_STRIDE = 1000  # senses_fts rowid = entry_id * SENSE_STRIDE + sense index

SCHEMA = f"""
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- One row per main entry and per sub-entry, in dictionary (file) order.
CREATE TABLE entries (
  id         INTEGER PRIMARY KEY,
  main_id    INTEGER NOT NULL,      -- the <lexhead> this belongs to (= id for main)
  parent_id  INTEGER,               -- direct parent entry; NULL for main entries
  kind       TEXT NOT NULL,         -- main | segmenthd | subsegmenthd | compound | sublexhd
  depth      INTEGER NOT NULL,      -- 0 main, 1 sub-entry, 2 sub-sub-entry
  src_file   TEXT NOT NULL,         -- e.g. 'k.xml'
  lexhead_no TEXT NOT NULL,         -- <lexhead no="..."> in that file ("138a" occurs)
  headword   TEXT NOT NULL,         -- original text, shown as is
  has_dentry INTEGER NOT NULL,      -- 0 if headword was taken from stray text / stem
  stem       TEXT,                  -- first <prAwipaxikam>
  norm       TEXT NOT NULL,         -- normalised headword (search key)
  letter     TEXT NOT NULL,         -- initial varna, for browsing
  sort_key   TEXT NOT NULL,         -- varnamala collation key (BINARY-sortable)
  grammar    TEXT NOT NULL,         -- plain grammar text, for result lists
  body       TEXT NOT NULL          -- full structured content as JSON
);
CREATE INDEX entries_main ON entries(main_id);
CREATE INDEX entries_browse ON entries(letter, sort_key) WHERE kind = 'main';

-- Normalised headword and stem keys -> entries (prefix search uses the PK).
CREATE TABLE search_keys (
  key      TEXT NOT NULL,
  entry_id INTEGER NOT NULL,
  PRIMARY KEY (key, entry_id)
) WITHOUT ROWID;

-- Contentless FTS5 index over the normalised Hindi text of every sense
-- (citations removed). It stores no text, only the index; the rowid encodes
-- where the sense lives:  rowid = entry_id * 1000 + (index in body.senses).
-- The sense itself is read from entries.body, so nothing is stored twice.
CREATE VIRTUAL TABLE senses_fts USING fts5(
  text, content='', prefix='2 3',
  tokenize="unicode61 remove_diacritics 0 tokenchars '{TOKENCHARS}'"
);
"""


# File name (a loose WX-style romanisation of the initial letter) -> letter.
FILE_LETTERS = {
    "a": "अ", "aa": "आ", "i": "इ", "ii": "ई", "u": "उ", "uu": "ऊ", "q": "ऋ",
    "e": "ए", "ai": "ऐ", "o": "ओ", "au": "औ",
    "k": "क", "kh": "ख", "g": "ग", "gh": "घ", "c": "च", "ch": "छ", "j": "ज",
    "jh": "झ", "t": "ट", "th": "ठ", "d": "ड", "dh": "ढ", "nn": "ण", "w": "त",
    "wh": "थ", "x": "द", "xh": "ध", "n": "न", "p": "प", "ph": "फ", "b": "ब",
    "bh": "भ", "m": "म", "y": "य", "r": "र", "l": "ल", "v": "व", "sh": "श",
    "ss": "ष", "s": "स", "h": "ह",
}


def file_order(path):
    """Sort key putting the XML files in varnamala order (a, aa, i ... h)."""
    name = os.path.splitext(os.path.basename(path))[0]
    if name not in FILE_LETTERS:
        sys.exit(f"Unexpected source file {path}: add it to FILE_LETTERS")
    return collation_key(FILE_LETTERS[name])


def body_json(e):
    """The JSON stored per entry: everything except fields kept as columns
    and the children (which are rows of their own). Empty lists are omitted
    to keep the database small."""
    skip = {"kind", "headword", "children", "no", "display", "id", "parent_id", "depth"}
    return {k: v for k, v in e.items() if k not in skip and v not in ([], None)}


def build(src, out):
    files = sorted(glob.glob(os.path.join(src, "*.xml")), key=file_order)
    if not files:
        sys.exit(f"No XML files in {src}. Run scripts/fetch_data.sh first.")
    os.makedirs(out, exist_ok=True)
    db_path = os.path.join(out, "apte.sqlite")
    if os.path.exists(db_path):
        os.remove(db_path)
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)

    warnings = {}
    stats = collections.Counter()
    by_kind = collections.Counter()
    tags_seen = collections.Counter()
    main_headwords = collections.Counter()
    star_headwords = []
    letters = collections.Counter()
    export = []
    next_id = 1

    # Files are processed in varnamala order, so ids follow the printed
    # dictionary; the browse screen additionally sorts by sort_key.
    for path in files:
        fname = os.path.basename(path)
        mains = parse_file(path, warnings)
        stats["files"] += 1
        for main in mains:
            # Assign ids depth-first so a main entry precedes its sub-entries.
            def assign(e, parent_id, depth):
                nonlocal next_id
                e["id"], e["parent_id"], e["depth"] = next_id, parent_id, depth
                next_id += 1
                for ch in e["children"]:
                    assign(ch, e["id"], depth + 1)
            assign(main, None, 0)

            for e in iter_entries(main):
                by_kind[e["kind"]] += 1
                hw = e["headword"]
                if hw is not None:
                    stats["dentry"] += 1
                    if hw.startswith("*"):
                        star_headwords.append(f"{fname} #{main['no']}: {hw}")
                display = hw if hw is not None else e.get("display", "")
                if hw is None:
                    stats["no_dentry"] += 1
                stats["sense"] += len(e["senses"])
                all_runs = [s["runs"] for s in e["senses"]] + e["grammar"] + e["etymology"]
                stats["citation"] += sum(count_citations(r) for r in all_runs)
                for g in e["grammar"]:
                    if not runs_text(g):
                        stats["empty_grammar"] += 1
                for r in all_runs:
                    tags_seen.update(iter_tags(r))
                for t, _ in e["semantic"]:
                    tags_seen[t] += 1

                stem = e["stems"][0]["text"] if e["stems"] else None
                norm = normalize(display)
                letter = initial_letter(display) or initial_letter(stem or "")
                # Sort by stem first (so अः sits with अ), then headword.
                sort_key = collation_key(stem or display) + " " + collation_key(display)
                grammar = "; ".join(t for t in (runs_text(g) for g in e["grammar"]) if t)
                letters[letter] += e["kind"] == "main"
                if e["kind"] == "main":
                    main_headwords[hw] += 1

                db.execute(
                    "INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (e["id"], main["id"], e["parent_id"], e["kind"], e["depth"],
                     fname, main["no"], display, int(hw is not None), stem, norm,
                     letter, sort_key, grammar,
                     json.dumps(body_json(e), ensure_ascii=False, separators=(",", ":"))))

                keys = {norm} | {normalize(s["text"]) for s in e["stems"]}
                for k in keys - {""}:
                    db.execute("INSERT OR IGNORE INTO search_keys VALUES (?,?)", (k, e["id"]))

                assert len(e["senses"]) < SENSE_STRIDE, "rowid encoding would overflow"
                for i, s in enumerate(e["senses"]):
                    text = normalize_text(runs_text(s["runs"], skip={"citation"}))
                    if text:
                        db.execute("INSERT INTO senses_fts(rowid, text) VALUES (?,?)",
                                   (e["id"] * SENSE_STRIDE + i, text))

            stats["lexhead"] += 1
            export.append(_export_tree(main, fname))

    # ---------------------------------------------------------------- report
    expected = json.load(open(os.path.join(ROOT, "pipeline", "expected.json"), encoding="utf-8"))
    raw = raw_tag_counts(files)
    parsed = {
        "lexhead": stats["lexhead"],
        "dentry": stats["dentry"],
        "sense": stats["sense"],
        "citation": stats["citation"],
        "duplicate_main_headwords": sum(n - 1 for n in main_headwords.values() if n > 1),
        "star_headwords": len(star_headwords),
        "empty_grammar": stats["empty_grammar"],
    }
    source_commit = _read(os.path.join(src, *[".."] * 4, ".source-commit")).strip()

    lines = ["Apte Sanskrit-Hindi build report",
             f"source: samsaadhanii/scl @ {source_commit or 'unknown'}  ({stats['files']} XML files)",
             "", f"{'check':28} {'expected':>9} {'parsed':>9} {'raw grep':>9}  result"]
    failed = False
    for key, exp in expected.items():
        if key.startswith("_"):
            continue
        got = parsed[key]
        ok = got == exp and raw.get(key, got) == got
        failed |= not ok
        lines.append(f"{key:28} {exp:>9} {got:>9} {raw.get(key, ''):>9}  {'OK' if ok else 'MISMATCH'}")

    lines += ["", "entries by kind: " + ", ".join(f"{k}={v}" for k, v in by_kind.most_common()),
              f"sub-entries without <dentry> (headword from stray text/stem): {stats['no_dentry']}",
              f"stray non-Devanagari debris dropped ('?', 'g' ...): {warnings.get('debris_dropped', 0)}",
              "headwords starting with '*': " + "; ".join(star_headwords)]
    undocumented = sorted(t for t in tags_seen if t not in DTD_TAGS)
    lines.append("tags used in the data but not in apte.dtd (kept as inline runs): "
                 + ", ".join(f"{t}({tags_seen[t]})" for t in undocumented))
    unseen = sorted(DTD_TAGS - set(tags_seen) - {
        "dict", "lexhead", "segmenthd", "subsegmenthd", "compound", "compoundverb",
        "sublexhd", "dentry", "prAwipaxikam", "grammar", "etymology", "sense",
        "seg", "num", "cat", "gen", "root", "vform"})  # structural, counted elsewhere
    lines.append("DTD inline tags never used in the data: " + (", ".join(unseen) or "none"))
    if warnings.get("unknown_entry_children"):
        lines.append(f"unknown tags directly under entries: {warnings['unknown_entry_children']}")
    lines.append("main entries per letter: " + " ".join(f"{k}{v}" for k, v in letters.items() if v))
    lines.append("")
    lines.append("RESULT: " + ("FAILED - parsed counts do not match expected" if failed else "all checks passed"))
    report = "\n".join(lines)

    meta = {
        "title": "आप्टे संस्कृत-हिन्दी कोश (V. S. Apte, Sanskrit-Hindi Dictionary)",
        "source": "https://github.com/samsaadhanii/scl/tree/master/MT/data/hi/Apte_dict",
        "source_commit": source_commit,
        "licence": "GPL-2.0 (as distributed by the Samsaadhanii project)",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": "1",
        "counts": json.dumps(parsed),
    }
    db.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    db.commit()
    db.execute("INSERT INTO senses_fts(senses_fts) VALUES ('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()

    with open(os.path.join(out, "apte.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "entries": export}, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out, "report.txt"), "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(report)
    print(f"\nwrote {db_path} ({os.path.getsize(db_path) / 1e6:.1f} MB), "
          f"apte.json ({os.path.getsize(os.path.join(out, 'apte.json')) / 1e6:.1f} MB)")
    return not failed


def _export_tree(e, fname):
    """Nested JSON form of a main entry for apte.json."""
    d = {"id": e["id"], "kind": e["kind"]}
    if e["kind"] == "main":
        d.update(file=fname, no=e["no"])
    d["headword"] = e["headword"] if e["headword"] is not None else e.get("display")
    d.update(body_json(e))
    if e["children"]:
        d["children"] = [_export_tree(c, fname) for c in e["children"]]
    return d


def raw_tag_counts(files):
    """Count opening tags with a regex, independently of the XML parser, so a
    parser bug that silently drops elements shows up as a mismatch."""
    pats = {"lexhead": r"<lexhead[\s>]", "dentry": r"<dentry[\s>]",
            "sense": r"<sense[\s>]", "citation": r"<citation[\s>]"}
    counts = collections.Counter()
    for p in files:
        text = open(p, encoding="utf-8").read()
        for k, pat in pats.items():
            counts[k] += len(re.findall(pat, text))
    return counts


def _read(path):
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return ""


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default=DEFAULT_SRC, help="directory with the Apte *.xml files")
    ap.add_argument("--out", default=os.path.join(ROOT, "build"), help="output directory")
    args = ap.parse_args()
    sys.exit(0 if build(args.src, args.out) else 1)
