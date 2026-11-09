#!/usr/bin/env python3
"""Second-opinion step: re-read, from the scan, the lines behind each finding.

    # 1. crop the lines behind the findings of a text-mode comparison
    python3 tools/scan_compare/recheck.py crops FINDINGS.json --strips STRIP_DIR \
        --pages OCR_DIR --out RECHECK_DIR [--types spelling,missing_in_digital,...]

    # 2. (a stronger model transcribes RECHECK_DIR/*.png into RECHECK_DIR/*.txt)

    # 3. collect its readings into an override file for compare.py --override
    python3 tools/scan_compare/recheck.py collect RECHECK_DIR --out override.json

Each crop holds exactly one printed line (the full column width, so nothing
is cut off), named after its source "STRIP#LINE" key. Re-running compare.py
with the override replaces those lines with the re-read text: a finding that
came from a misreading disappears, a real difference stays.
"""

import argparse
import json
import os
import sys

from PIL import Image

DEFAULT_TYPES = "spelling,missing_in_digital,missing_in_print,grammar,entry_missing_in_digital"


def safe(key):
    return key.replace("#", "_L")


def crops(args):
    findings = json.load(open(args.findings, encoding="utf-8"))
    manifest = {s["id"]: s for s in json.load(open(os.path.join(args.strips, "manifest.json")))}
    types = set(args.types.split(","))
    os.makedirs(args.out, exist_ok=True)
    keys = {}
    for f in findings:
        if f["type"] not in types:
            continue
        for ln in f["lines"]:
            if ln.get("src"):
                keys[ln["src"]] = ln
    for key, ln in sorted(keys.items()):
        strip = manifest[key.split("#")[0]]
        im = Image.open(os.path.join(args.pages, f"p-{ln['page']:04d}.png"))
        x0, _, x1, _ = strip["box"]
        _, y0, _, y1 = ln["box"]
        im.crop((x0, max(y0 - 10, 0), x1, min(y1 + 10, im.height))).save(os.path.join(args.out, safe(key) + ".png"))
    json.dump(sorted(keys), open(os.path.join(args.out, "keys.json"), "w"), indent=0)
    print(f"{len(keys)} line crops for {sum(1 for f in findings if f['type'] in types)} findings in {args.out}")


def collect(args):
    keys = json.load(open(os.path.join(args.dir, "keys.json")))
    override, missing = {}, []
    for key in keys:
        # Accept NAME.txt and NAME.png.txt (both readings of "same name").
        path = next((p for p in (os.path.join(args.dir, safe(key) + ext) for ext in (".txt", ".png.txt"))
                     if os.path.exists(p)), None)
        if path is None:
            missing.append(key)
            continue
        text = " ".join(l.strip() for l in open(path, encoding="utf-8") if l.strip())
        if text:
            override[key] = text
    json.dump(override, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"{len(override)} re-read lines -> {args.out}" + (f"; {len(missing)} missing" if missing else ""))
    if missing:
        print("missing:", " ".join(missing[:20]), file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crops")
    c.add_argument("findings")
    c.add_argument("--strips", required=True)
    c.add_argument("--pages", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--types", default=DEFAULT_TYPES)
    k = sub.add_parser("collect")
    k.add_argument("dir")
    k.add_argument("--out", required=True)
    args = ap.parse_args()
    crops(args) if args.cmd == "crops" else collect(args)


if __name__ == "__main__":
    main()
