from __future__ import annotations

import hashlib
import json
from pathlib import Path

from render.render_all import render_all_cases
from seed.build_seed import build_seed_json
from tests.render.test_manifest_and_verify import create_test_suite_fixture


def hash_directory_files(dir_path: Path) -> dict:
    hashes = {}
    for p in sorted(dir_path.rglob("*")):
        if p.is_file():
            rel = p.relative_to(dir_path).as_posix()
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
            hashes[rel] = h
    return hashes


def test_render_all_determinism(tmp_path):
    build_dir = create_test_suite_fixture(tmp_path)
    cases_json = build_dir / "cases.json"
    state_json = build_dir / "state.json"

    samples1 = tmp_path / "samples1"
    samples2 = tmp_path / "samples2"

    # Run 1
    render_all_cases(str(cases_json), str(samples1), seed=42)
    build_seed_json(str(state_json), str(samples1 / "seed.json"), embedder_backend="tfidf")

    # Run 2
    render_all_cases(str(cases_json), str(samples2), seed=42)
    build_seed_json(str(state_json), str(samples2 / "seed.json"), embedder_backend="tfidf")

    hashes1 = hash_directory_files(samples1)
    hashes2 = hash_directory_files(samples2)

    assert set(hashes1.keys()) == set(hashes2.keys())
    for rel_path in sorted(hashes1.keys()):
        assert hashes1[rel_path] == hashes2[rel_path], f"Non-deterministic output detected for file: {rel_path}"
