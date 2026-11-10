"""Load transcribed strips (see tools/scan_compare/make_strips.py) as a
stream of (page, text, starts_at_column_edge) lines in reading order."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "scan_compare"))
from compare import at_column_edge  # noqa: E402

PAGE_W = 2480  # ocr_pages.sh scales every page to this width


def load_lines(strip_dirs, text_dirs, first_page=1, last_page=10**6, override=None):
    """Lines of all transcribed strips, page by page (left column first).
    The column-edge flag comes from the OCR line boxes (matched by position
    when the transcribed and OCR line counts differ)."""
    override = override or {}
    strips = []
    for sd in strip_dirs:
        strips += [(sd, s) for s in json.load(open(os.path.join(sd, "manifest.json"), encoding="utf-8"))]
    strips = [(sd, s) for sd, s in strips if first_page <= s["page"] <= last_page]
    strips.sort(key=lambda x: (x[1]["page"], x[1]["col"], int(x[1]["id"].rsplit("-", 1)[1])))
    out, missing = [], []
    by_page = {}
    for sd, s in strips:
        path = next((os.path.join(td, s["id"] + ".txt") for td in text_dirs
                     if os.path.exists(os.path.join(td, s["id"] + ".txt"))), None)
        if path is None:
            missing.append(s["id"])
            continue
        texts = [t.rstrip("\n") for t in open(path, encoding="utf-8") if t.strip()]
        boxes = s["lines"]
        for i, t in enumerate(texts):
            key = f"{s['id']}#{i}"
            t = override.get(key, t)
            # Same line count as OCR (the normal case): that line's box.
            # Otherwise the proportionally nearest OCR line, which still
            # tells an indented continuation from an entry start.
            n, m = len(texts), len(boxes)
            box = boxes[i] if n == m else boxes[min(m - 1, round(i * (m - 1) / max(n - 1, 1)))] if m else None
            by_page.setdefault(s["page"], []).append({"key": key, "text": t, "box": box})
    for page in sorted(by_page):
        ls = by_page[page]
        boxed = [l for l in ls if l["box"]]
        flags = dict(zip((id(l) for l in boxed), at_column_edge([{"box": l["box"]} for l in boxed], PAGE_W)))
        for l in ls:
            edge = flags[id(l)] if l["box"] else l["text"].lstrip().startswith("**")
            out.append((page, l["text"], edge, l["key"]))
    return out, missing
