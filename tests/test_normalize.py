import json
import os

import pytest

from normalize import (VARNAMALA, collation_key, initial_letter, normalize,
                       normalize_text, phonemes)

HERE = os.path.dirname(__file__)
CASES = json.load(open(os.path.join(HERE, "shared", "normalize_cases.json"), encoding="utf-8"))["cases"]


@pytest.mark.parametrize("text,expected", CASES)
def test_shared_normalize_cases(text, expected):
    assert normalize(text) == expected


def test_normalize_is_idempotent():
    for text, _ in CASES:
        assert normalize(normalize(text)) == normalize(text)


def test_phonemes_inherent_vowel_and_virama():
    assert phonemes("क") == ["क", "अ"]
    assert phonemes("कि") == ["क", "इ"]
    assert phonemes("क्त") == ["क", "त", "अ"]
    assert phonemes("अंश्") == ["अ", "ं", "श"]


def test_varnamala_order():
    words = ["क्त", "कौ", "क", "का", "कृ", "कं", "अक", "अंश्", "ऋषि", "औषध"]
    assert sorted(words, key=collation_key) == [
        "अंश्", "अक", "ऋषि", "औषध", "क", "कं", "का", "कृ", "कौ", "क्त"]


def test_varnamala_order_differs_from_unicode_order():
    # ॠ is U+0960, after ह (U+0939) in code-point order, but in the
    # varnamala it follows ऋ. Likewise ॄ/ॢ vowel signs.
    words = ["हरि", "एक", "ॠ", "ऋषि"]
    assert sorted(words) == ["ऋषि", "एक", "हरि", "ॠ"]
    assert sorted(words, key=collation_key) == ["ऋषि", "ॠ", "एक", "हरि"]
    # A homorganic nasal cluster sorts like anusvara (before all consonants),
    # whereas code-point order sorts ङ (U+0919) after क (U+0915).
    words = ["शकट", "शङ्ख"]
    assert sorted(words) == ["शकट", "शङ्ख"]
    assert sorted(words, key=collation_key) == ["शङ्ख", "शकट"]


def test_visarga_and_variants_sort_together():
    assert collation_key("अः") == collation_key("अ")
    assert collation_key("शङ्कर") == collation_key("शंकर")


def test_initial_letter():
    assert initial_letter("*द") == "द"
    assert initial_letter("क्षमा") == "क"   # क्ष is filed under क
    assert initial_letter("ज्ञानम्") == "ज"
    assert initial_letter("ॠ") == "ॠ"
    assert len(VARNAMALA) == len(set(VARNAMALA))


def test_normalize_text_for_reverse_search():
    assert normalize_text("जल पीने का पात्र, प्याला (cup)") == "जल पीने का पात्र प्याला"
    assert normalize_text("काँसा  सफेद ताँबा") == "कांसा सफेद तांबा"
