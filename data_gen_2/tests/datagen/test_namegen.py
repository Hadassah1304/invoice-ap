"""Tests for lookalike vendor name generation."""

import pytest
from rapidfuzz import fuzz

from datagen.mutate.namegen import generate_lookalike_name
from datagen.norm import normalize_vendor_name


def test_lookalike_in_band_and_deterministic():
    vendor = "Falcon Precision Components"
    others = ["Sri Balaji Foods Pvt Ltd", "Apex Tech Solutions"]

    res1 = generate_lookalike_name(vendor, others, match_threshold=0.90, reject_threshold=0.75)
    res2 = generate_lookalike_name(vendor, others, match_threshold=0.90, reject_threshold=0.75)

    assert res1 == res2
    sim = fuzz.token_set_ratio(normalize_vendor_name(res1), normalize_vendor_name(vendor)) / 100.0
    assert 0.78 <= sim <= 0.87
