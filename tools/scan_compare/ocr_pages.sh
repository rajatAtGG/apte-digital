#!/usr/bin/env bash
# OCR a range of pages of the scanned printed edition with Tesseract.
#
#   tools/scan_compare/ocr_pages.sh SCAN.pdf FIRST LAST OUTDIR
#
# Renders each page at 300 dpi (grayscale) and runs Tesseract with the
# Hindi + Sanskrit "best" LSTM models, writing per page:
#   OUTDIR/p-NNNN.png   the rendered page
#   OUTDIR/p-NNNN.tsv   words with positions and confidences
#   OUTDIR/p-NNNN.txt   plain text
# Set TESSDATA_PREFIX to a directory holding tessdata_best hin/san models.
# OCR output of a copyrighted edition: keep OUTDIR out of the public repo.
set -euo pipefail
PDF=$1; FIRST=$2; LAST=$3; OUT=$4
JOBS=${JOBS:-$(nproc)}
mkdir -p "$OUT"
pdftoppm -f "$FIRST" -l "$LAST" -r 300 -gray -png "$PDF" "$OUT/p"
export OMP_THREAD_LIMIT=1   # one thread per page; parallelise across pages
ls "$OUT"/p-*.png | sort | xargs -P "$JOBS" -I{} sh -c '
  base="${1%.png}"
  [ -s "$base.tsv" ] || tesseract "$1" "$base" -l hin+san --oem 1 --psm 3 txt tsv >/dev/null 2>&1
' _ {}
echo "OCR done: $(ls "$OUT"/*.tsv | wc -l) pages in $OUT"
