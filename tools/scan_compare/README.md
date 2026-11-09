# Comparing the printed edition with the Samsaadhanii text

Checks the digital dictionary against a scan of the printed *संस्कृत-हिन्दी
शब्दकोश* (V. S. Apte, ed. Uma Prasad Pandey, Kamal Prakashan). The printed
edition is not ours to redistribute: **keep the scan, the OCR output and the
reports out of this public repository.** Only the code lives here.

## Pipeline (current): Sonnet transcription + Opus re-read

```sh
# 1. layout only: Tesseract finds the lines, pages are cut into ~10-line strips
tools/scan_compare/ocr_pages.sh scan.pdf 51 100 /scratch/batch02
python3 tools/scan_compare/make_strips.py /scratch/batch02 --out /scratch/b02_strips
# 2. Claude Sonnet 5.5 (low effort) transcribes every strip -> /scratch/b02_text/<strip>.txt
# 3. compare, crop the lines behind findings, have Claude Opus 5.5 (high
#    effort) re-read them blind, then compare again with the re-read lines
python3 tools/scan_compare/compare.py /scratch/batch02 --text /scratch/b02_text \
    --strips /scratch/b02_strips --batch b02 --out /scratch/b02s
python3 tools/scan_compare/recheck.py crops /scratch/b02s/b02-findings.json \
    --strips /scratch/b02_strips --pages /scratch/batch02 --out /scratch/b02_recheck \
    --types spelling,missing_in_digital,grammar,entry_missing_in_digital
#    (Opus writes /scratch/b02_recheck/<crop>.txt)
python3 tools/scan_compare/recheck.py collect /scratch/b02_recheck --out /scratch/b02-override.json
python3 tools/scan_compare/compare.py /scratch/batch02 --text /scratch/b02_text \
    --strips /scratch/b02_strips --override /scratch/b02-override.json --batch b02 --out /scratch/b02
```

Model choice came from an evaluation on 133 hand-transcribed lines
(Devanagari character error rate): Tesseract 5.0%, Sonnet 5.5 low 0.10%,
Opus 5.5 high 0.03%. In batch 1 the Opus re-read removed 15 findings that
were Sonnet misreadings.

## Pipeline (original): Tesseract OCR only

```sh
# Tesseract 5 with Hindi + Sanskrit models (tessdata_best recommended,
# with the configs/ folder copied next to them)
export TESSDATA_PREFIX=/path/to/tessdata_best
tools/scan_compare/ocr_pages.sh scan.pdf 51 100 /scratch/batch02
python3 tools/scan_compare/compare.py /scratch/batch02 --batch b02 --out /scratch/b02
```

`--first-page` skips front matter; the dictionary starts on PDF page 19.

## What the report means

Every finding is a candidate for a human to check against the scan crop
shown next to it. Precision was measured by checking samples by eye in
batch 1 (PDF pages 19–50):

| category | precision | notes |
|---|---|---|
| Spelling differs | ~90% | typos in the digital text (कंघों for कंधों) |
| Printed entry not in digital | ~80% | OCR may garble the headword: read it from the crop |
| Printed text missing in digital | ~60% | dropped senses/glosses; some OCR noise |
| Grammar label differs | — | real differences, but the print is often the one in error |
| Digital text / entry not in print | low | mostly OCR misses; hidden by default |

OCR quality (Tesseract 5.3, tessdata_best hin+san, 16 sampled lines checked
by hand): 4.1% character error rate on Devanagari letters, 22.7% of words
with some error. The commonest errors: dropped anusvara (पुं. → पु), bold
ज read as न, digits (1. → ।.), complex conjuncts (स्त्र → स्र).
