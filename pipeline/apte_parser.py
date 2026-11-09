"""Parse the Apte Sanskrit-Hindi XML files into plain Python dicts.

Structure (see data/raw/.../apte.dtd)::

    <dict>
      <lexhead no="N">            one main entry
        <dentry>                  its headword (exactly one per lexhead)
        <prAwipaxikam gen=..>     stem(s)
        <grammar>                 पुं*, नपुं*, वि* ... or <gaNa>/<paxI>/<vform> for roots
        <etymology>               [अव्+ड], may hold <vigrahavAkyam>, <v>, <citation> ...
        <jAwi>/<upAXi>/<kind_of>/<is_a_part>   semantic categories
        <sense no|n="N">          a meaning; may hold <citation>, <vform>, <ref>
        <segmenthd>               a sub-entry (prefixed verb, derivative ...)
          <subsegmenthd>          a sub-sub-entry
        <compound>                a compound
        <sublexhd>/<compoundverb> other sub-entry kinds defined by the DTD

Every entry-like element (lexhead and the sub-entry kinds) becomes one dict:

    {
      "kind": "main" | "segmenthd" | "subsegmenthd" | "compound" | ...,
      "headword": str | None,       # original <dentry> text, never altered
      "stems": [{"text": str, "gen": str | None}],
      "segs": [str],                # word segmentation, e.g. "अग्निः-कुमारः"
      "grammar": [runs],            # one item per <grammar> element
      "etymology": [runs],          # one item per <etymology> element
      "senses": [{"n": str | None, "runs": runs}],
      "semantic": [[tag, text]],    # jAwi / upAXi / kind_of / is_a_part, in order
      "nums": [str], "cats": [str], "gens": [str], "roots": [str], "vforms": [str],
      "notes": [str],               # stray Devanagari text not inside any tag
      "children": [entry],
    }

Mixed content (text interleaved with tags, e.g. a sense with citations) is
kept as *runs*: a list whose items are either plain strings or
``[tag, *runs]`` lists. ``["अर्थ", ["citation", "रघु* १।१"]]`` renders as the
text followed by a citation. Nothing is rewritten here; display conventions
(such as showing the abbreviation mark ``*`` as ``०``) belong to the app.
"""

import re
import xml.etree.ElementTree as ET

# Elements that start an entry of their own.
ENTRY_TAGS = {
    "lexhead": "main",
    "segmenthd": "segmenthd",
    "subsegmenthd": "subsegmenthd",
    "compound": "compound",
    "sublexhd": "sublexhd",
    "compoundverb": "compoundverb",
}
SEMANTIC_TAGS = ("jAwi", "upAXi", "kind_of", "is_a_part")
# Simple text-only children collected into a list field of the entry.
LIST_TAGS = {"seg": "segs", "num": "nums", "cat": "cats", "gen": "gens",
             "root": "roots", "vform": "vforms"}

# Every element apte.dtd defines. Tags seen in the data but *not* in the DTD
# (e.g. <v>, <vigraha_vAkya>, <explanation> inside <etymology>) are still
# kept as inline runs; the build report lists them so they are not a surprise.
DTD_TAGS = {
    "dict", "lexhead", "segmenthd", "dentry", "prAwipaxikam", "cat", "gen",
    "num", "grammar", "compound", "etymology", "vform", "is_a_part", "kind_of",
    "jAwi", "upAXi", "paxI", "gaNa", "sense", "seg", "citation",
    "subsegmenthd", "compoundverb", "sublexhd", "h", "ref", "root",
}

_HAS_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_SPACES = re.compile(r"\s+")


def clean(text):
    """Collapse runs of whitespace (the XML is hand-edited) and strip."""
    return _SPACES.sub(" ", text or "").strip()


def runs(el):
    """Convert an element's mixed content into a list of runs (see module
    docstring). Whitespace is collapsed; empty strings are dropped."""
    out = []

    def add_text(t):
        t = _SPACES.sub(" ", t or "")
        if not t:
            return
        if out and isinstance(out[-1], str):
            out[-1] += t
        else:
            out.append(t)

    add_text(el.text)
    for child in el:
        out.append([child.tag] + runs(child))
        add_text(child.tail)
    # Trim the outer whitespace of the whole run list.
    if out and isinstance(out[0], str):
        out[0] = out[0].lstrip()
    if out and isinstance(out[-1], str):
        out[-1] = out[-1].rstrip()
    return [r for r in out if r != ""]


def runs_text(rs, skip=()):
    """Plain text of a run list, optionally skipping some tags entirely
    (used to index sense text without the Sanskrit citations)."""
    parts = []
    for r in rs:
        if isinstance(r, str):
            parts.append(r)
        elif r[0] not in skip:
            # Separate tagged runs from their neighbours: <gaNa>चुरा*</gaNa>
            # <paxI>उभ*</paxI> reads "चुरा* उभ*", not "चुरा*उभ*".
            parts.append(" " + runs_text(r[1:], skip) + " ")
    return clean("".join(parts))


def parse_entry(el, warnings):
    """Turn one entry-like element into a dict (recursing into sub-entries)."""
    e = {
        "kind": ENTRY_TAGS[el.tag], "headword": None, "stems": [], "segs": [],
        "grammar": [], "etymology": [], "senses": [], "semantic": [],
        "nums": [], "cats": [], "gens": [], "roots": [], "vforms": [],
        "notes": [], "children": [],
    }
    if el.tag == "lexhead":
        e["no"] = el.get("no")  # usually numeric, but insertions exist: "138a"

    def note(text):
        # Stray text directly inside an entry. Real words (Devanagari) are
        # kept; encoding debris such as "?" or "g" is dropped and counted.
        t = clean(text)
        if not t:
            return
        if _HAS_DEVANAGARI.search(t):
            e["notes"].append(t)
        else:
            warnings["debris_dropped"] = warnings.get("debris_dropped", 0) + 1

    note(el.text)
    for c in el:
        tag = c.tag
        if tag == "dentry":
            hw = clean("".join(c.itertext()))
            if e["headword"] is None:
                e["headword"] = hw
            else:  # never happens in the current data, but keep, don't lose
                e["notes"].append(hw)
        elif tag == "prAwipaxikam":
            e["stems"].append({"text": clean("".join(c.itertext())),
                               "gen": c.get("gen")})
        elif tag == "grammar":
            e["grammar"].append(runs(c))
        elif tag == "etymology":
            e["etymology"].append(runs(c))
        elif tag == "sense":
            # Numbering is given as no="1" on the first sense and n="2".. on
            # later ones (sometimes no= throughout); treat them the same.
            e["senses"].append({"n": c.get("no") or c.get("n"), "runs": runs(c)})
        elif tag in SEMANTIC_TAGS:
            e["semantic"].append([tag, clean("".join(c.itertext()))])
        elif tag in LIST_TAGS:
            e[LIST_TAGS[tag]].append(clean("".join(c.itertext())))
        elif tag in ENTRY_TAGS:
            e["children"].append(parse_entry(c, warnings))
        else:
            # Unknown tag directly under an entry: keep its text as a note.
            warnings.setdefault("unknown_entry_children", {}).setdefault(tag, 0)
            warnings["unknown_entry_children"][tag] += 1
            e["notes"].append(clean("".join(c.itertext())))
        note(c.tail)

    # Sub-entries without a <dentry> (some compounds, all sublexhd) still need
    # something to show: fall back to stray headword text, then to the stem.
    if e["headword"] is None:
        if e["notes"]:
            e["display"] = e["notes"].pop(0)
        elif e["stems"]:
            e["display"] = e["stems"][0]["text"]
    return e


def parse_file(path, warnings=None):
    """Parse one XML file into a list of main-entry dicts."""
    warnings = {} if warnings is None else warnings
    root = ET.parse(path).getroot()
    if root.tag != "dict":
        raise ValueError(f"{path}: root element is <{root.tag}>, expected <dict>")
    return [parse_entry(lx, warnings) for lx in root if lx.tag == "lexhead"]


def iter_entries(entry):
    """Yield an entry and all its descendants, depth first."""
    yield entry
    for ch in entry["children"]:
        yield from iter_entries(ch)


def iter_tags(rs):
    """Yield every tag name inside a run list, recursively."""
    for r in rs:
        if not isinstance(r, str):
            yield r[0]
            yield from iter_tags(r[1:])


def count_citations(rs):
    return sum(1 for t in iter_tags(rs) if t == "citation")
