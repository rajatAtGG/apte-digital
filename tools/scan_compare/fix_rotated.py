#!/usr/bin/env python3
"""Find pages photographed upside down and fix them.

    python3 tools/scan_compare/fix_rotated.py OCR_DIR [--threshold 50]

A few pages of the scan are upside down. Tesseract still finds their
lines, but reads them as near-garbage, so their mean word confidence is far
below the usual ~80. Such pages are rotated by 180 degrees and OCRed again
(same settings as ocr_pages.sh). Prints the page numbers it fixed. Run it
after ocr_pages.sh and before make_strips.py.
"""

import argparse
import csv
import glob
import os
import statistics
import subprocess

from PIL import Image


def mean_conf(tsv):
    confs = []
    with open(tsv, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            try:
                c = float(r["conf"])
            except (TypeError, ValueError):
                continue
            if c >= 0 and (r.get("text") or "").strip():
                confs.append(c)
    return statistics.mean(confs) if len(confs) >= 50 else None  # skip near-empty pages


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ocr_dir")
    ap.add_argument("--threshold", type=float, default=50)
    args = ap.parse_args()
    fixed = []
    for tsv in sorted(glob.glob(os.path.join(args.ocr_dir, "p-*.tsv"))):
        conf = mean_conf(tsv)
        if conf is None or conf >= args.threshold:
            continue
        base = tsv[:-4]
        Image.open(base + ".png").rotate(180).save(base + ".png")
        subprocess.run(["tesseract", base + ".png", base, "-l", "hin+san", "--oem", "1", "--psm", "3", "txt", "tsv"],
                       check=True, capture_output=True, env={**os.environ, "OMP_THREAD_LIMIT": "1"})
        new = mean_conf(tsv)
        fixed.append(os.path.basename(base))
        print(f"{os.path.basename(base)}: mean confidence {conf:.0f} -> {new:.0f} after rotating")
    print(f"rotated {len(fixed)} page(s)")


if __name__ == "__main__":
    main()
