"""Parser tests on a fixture that reproduces the known quirks, plus an
integration test that runs the full build when the source data is present."""

import os
import subprocess
import sys

import pytest

from apte_parser import count_citations, iter_entries, parse_file, runs_text

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, "fixtures", "sample.xml")


@pytest.fixture(scope="module")
def parsed():
    warnings = {}
    return parse_file(FIXTURE, warnings), warnings


def test_main_entries_and_lexhead_numbers(parsed):
    mains, _ = parsed
    assert [m["no"] for m in mains] == ["1", "2", "2a", "3"]  # "2a" is not an int
    assert all(m["kind"] == "main" for m in mains)


def test_star_headword_kept_verbatim(parsed):
    mains, _ = parsed
    assert mains[0]["headword"] == "*द"


def test_homonyms_are_both_kept(parsed):
    mains, _ = parsed
    assert [m["headword"] for m in mains[1:3]] == ["कंसः", "कंसः"]
    assert mains[1]["senses"][0]["runs"] != mains[2]["senses"][0]["runs"]


def test_empty_grammar_and_debris(parsed):
    mains, warnings = parsed
    assert mains[2]["grammar"] == [[]]          # element kept, content empty
    assert runs_text(mains[2]["grammar"][0]) == ""
    assert warnings["debris_dropped"] == 1      # the stray "?"
    assert mains[2]["notes"] == []


def test_sense_numbering_no_and_n(parsed):
    mains, _ = parsed
    assert [s["n"] for s in mains[1]["senses"]] == ["1", "2"]


def test_stem_gender_and_semantic_tags(parsed):
    mains, _ = parsed
    kamsa = mains[1]
    assert kamsa["stems"] == [{"text": "कंस", "gen": "puM"}]
    assert kamsa["semantic"] == [["is_a_part", "पाकस्थानम्"], ["kind_of", "पात्रम्"],
                                 ["upAXi", "गार्हिकोपकरणम्"]]
    assert kamsa["etymology"] == [["[कंस्-अ]"]]


def test_nested_citations(parsed):
    mains, _ = parsed
    runs = mains[2]["senses"][0]["runs"]
    assert runs == ["मथुरा का राजा", ["citation", "भाग* १०।१", ["citation", "विष्णु*"]]]
    assert count_citations(runs) == 2
    assert runs_text(runs, skip={"citation"}) == "मथुरा का राजा"


def test_verb_root_grammar_and_etymology_runs(parsed):
    root = parsed[0][3]
    assert root["grammar"] == [[["gaNa", "चुरा*"], ["paxI", "उभ*"], ["vform", "अंशयति,अंशते"]]]
    # <vigrahavAkyam> is not in the DTD but must survive as an inline run.
    assert root["etymology"] == [["[अंश+ला+क] ", ["vigrahavAkyam", "अंशं लाति इति"]]]


def test_sub_entries_are_linked(parsed):
    root = parsed[0][3]
    kinds = [(e["kind"], e["headword"]) for e in iter_entries(root)]
    assert kinds == [("main", "अंश्"), ("segmenthd", "व्यंश्"),
                     ("subsegmenthd", "अग्निकुमारः"), ("compound", None), ("sublexhd", None)]
    seg = root["children"][0]
    assert seg["segs"] == ["वि-अंश्"]
    assert seg["children"][0]["segs"] == ["अग्निः-कुमारः"]


def test_entries_without_dentry_get_a_display_headword(parsed):
    root = parsed[0][3]
    compound, sublex = root["children"][1], root["children"][2]
    # Stray Devanagari text inside the compound becomes its display headword.
    assert compound["display"] == "मध्येगङ्गम्" and compound["notes"] == []
    assert "display" not in sublex  # nothing to fall back on
    assert sublex["senses"][0]["runs"] == ["उप-अर्थ"]


def test_counts_on_fixture(parsed):
    mains, _ = parsed
    entries = [e for m in mains for e in iter_entries(m)]
    assert sum(e["headword"] is not None for e in entries) == 6
    assert sum(len(e["senses"]) for e in entries) == 9


RAW = os.path.join(ROOT, "data", "raw", "scl", "MT", "data", "hi", "Apte_dict")


@pytest.mark.skipif(not os.path.isdir(RAW), reason="run scripts/fetch_data.sh first")
def test_full_build_validates(tmp_path):
    """The real build must reproduce every expected count (exit status 0)."""
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "pipeline", "build.py"),
                           "--out", str(tmp_path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RESULT: all checks passed" in proc.stdout
    assert (tmp_path / "apte.sqlite").exists() and (tmp_path / "apte.json").exists()
