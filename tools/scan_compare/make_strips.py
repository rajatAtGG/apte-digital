#!/usr/bin/env python3
"""Cut OCRed page images into strips of ~10 printed lines for transcription.

    python3 tools/scan_compare/make_strips.py OCR_DIR --first-page 19 --out STRIP_DIR

Tesseract is used here only for layout: its line boxes say where each column
and line is, so strips are cut between lines (never through one) and each
strip stays small enough to be read at full resolution. Writes:

    STRIP_DIR/pNNNN-L-1.png ...       strip images (column L/R, top to bottom)
    STRIP_DIR/manifest.json           per strip: page, column, crop box, and
                                      the OCR box of every line in it (used
                                      later to place transcribed lines)
"""

import argparse
import glob
import json
import os
import re
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare import read_page  # noqa: E402

LINES_PER_STRIP = 10


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ocr_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--first-page", type=int, default=1)
    ap.add_argument("--last-page", type=int, default=10**6)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    manifest = []
    for tsv in sorted(glob.glob(os.path.join(args.ocr_dir, "p-*.tsv"))):
        page = int(re.search(r"p-(\d+)\.tsv", tsv).group(1))
        if not args.first_page <= page <= args.last_page:
            continue
        lines, (w, _h) = read_page(tsv)
        im = Image.open(os.path.join(args.ocr_dir, f"p-{page:04d}.png"))
        # The gutter: just left of where right-column lines start. Tesseract
        # sometimes merges a left and a right line into one box spanning both
        # columns (seen on the first page, under the letter heading); such a
        # line belongs to both columns, and every strip is cropped to its own
        # column, so a strip never shows text from the other column.
        right_starts = [l["box"][0] for l in lines if l["box"][0] >= w * 0.45]
        gutter = (min(right_starts) - 15) if right_starts else w // 2
        for col, name in ((0, "L"), (1, "R")):
            if col == 0:
                ls = [l for l in lines if l["box"][0] < gutter]
            else:
                ls = [l for l in lines if l["box"][2] > gutter + 40]
            ls.sort(key=lambda l: l["box"][1])
            if not ls:
                continue
            if col == 0:
                x0, x1 = max(min(l["box"][0] for l in ls) - 20, 0), gutter
            else:
                x0 = gutter
                x1 = min(max(l["box"][2] for l in ls) + 20, im.width)
            for k in range(0, len(ls), LINES_PER_STRIP):
                group = ls[k:k + LINES_PER_STRIP]
                y0 = max(group[0]["box"][1] - 14, 0)
                y1 = min(group[-1]["box"][3] + 14, im.height)
                sid = f"p{page:04d}-{name}-{k // LINES_PER_STRIP + 1}"
                im.crop((x0, y0, x1, y1)).save(os.path.join(args.out, sid + ".png"))
                manifest.append({"id": sid, "page": page, "col": name, "box": [x0, y0, x1, y1],
                                 "lines": [l["box"] for l in group]})
    json.dump(manifest, open(os.path.join(args.out, "manifest.json"), "w"), indent=0)
    print(f"{len(manifest)} strips from {len({m['page'] for m in manifest})} pages in {args.out}")


if __name__ == "__main__":
    main()
