#!/usr/bin/env bash
# OCR a range of pages of the scanned printed edition with Tesseract.
#
#   tools/scan_compare/ocr_pages.sh SCAN.pdf FIRST LAST OUTDIR
#
# The scan is one photographed JPEG per page (plus a small scanner
# watermark). Rendering the PDF is very slow for a 1 GB file, so the page
# JPEGs are extracted directly with pdfimages, converted to grayscale and
# scaled to ~300 dpi (A4 width = 2480 px), then OCRed with the Hindi +
# Sanskrit "best" LSTM models. Per page:
#   OUTDIR/p-NNNN.png   the page image that was OCRed
#   OUTDIR/p-NNNN.tsv   words with positions and confidences
#   OUTDIR/p-NNNN.txt   plain text
# Set TESSDATA_PREFIX to a directory holding tessdata_best hin/san models.
# OCR output of a copyrighted edition: keep OUTDIR out of the public repo.
set -euo pipefail
PDF=$1; FIRST=$2; LAST=$3; OUT=$4
JOBS=${JOBS:-$(nproc)}
mkdir -p "$OUT/raw"
pdfimages -j -p -f "$FIRST" -l "$LAST" "$PDF" "$OUT/raw/img"
python3 - "$OUT" <<'PY'
import glob, os, re, sys
from collections import defaultdict
from PIL import Image
out = sys.argv[1]
by_page = defaultdict(list)
for f in glob.glob(os.path.join(out, "raw", "img-*")):
    page = int(re.search(r"img-(\d+)-\d+\.", f).group(1))
    by_page[page].append(f)
for page, files in by_page.items():
    dst = os.path.join(out, f"p-{page:04d}.png")
    if os.path.exists(dst):
        continue
    big = max(files, key=os.path.getsize)          # the page photo, not the watermark
    im = Image.open(big).convert("L")
    scale = 2480 / im.width
    im = im.resize((2480, round(im.height * scale)), Image.LANCZOS)
    im.save(dst)
PY
rm -rf "$OUT/raw"
export OMP_THREAD_LIMIT=1   # one thread per page; parallelise across pages
ls "$OUT"/p-*.png | sort | xargs -P "$JOBS" -I{} sh -c '
  base="${1%.png}"
  [ -s "$base.tsv" ] || tesseract "$1" "$base" -l hin+san --oem 1 --psm 3 txt tsv >/dev/null 2>&1
' _ {}
echo "OCR done: $(ls "$OUT"/*.tsv | wc -l) pages in $OUT"
