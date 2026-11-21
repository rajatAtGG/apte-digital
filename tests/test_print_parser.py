"""Printed-edition parser: bold sense numbers are senses, not sub-entries."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
from print_parser import parse_body, unbold_non_words  # noqa: E402


def test_bold_sense_numbers_are_not_sub_entries():
    main, subs = parse_body("[अंश्+अच्] **1**. हिस्सा, भाग **2** संपत्ति में हिस्सा", "अंशः")
    assert subs == []
    assert "1. हिस्सा" in main and "2. संपत्ति" in main


def test_real_sub_entries_survive():
    main, subs = parse_body("**1**. विष्णु **2**. शिव; -**रः** (पुं.) पवन", "अघोरः")
    assert [s["heads"] for s in subs] == [["-रः"]]
    assert "1. विष्णु" in main


def test_unbold_keeps_existing_dot_and_drops_numerals():
    assert unbold_non_words("**3**. घमंड") == "3. घमंड"
    assert unbold_non_words("**ii** अवाप्त करना") == "ii अवाप्त करना"
    assert unbold_non_words("**कमलम्** फूल") == "**कमलम्** फूल"
