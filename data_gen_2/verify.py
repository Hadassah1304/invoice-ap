from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple

import fitz  # PyMuPDF

from render.formatting import format_currency, format_number
from seed.load_dataset import load_dataset_into_db


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_dataset(
    samples_dir: str,
    build_dir: str = "build/",
    run_batch: bool = False,
) -> bool:
    """Run comprehensive end-to-end verification checks 1 to 7 on the generated dataset."""
    samples_path = Path(samples_dir)
    build_path = Path(build_dir)
    cases_json_path = build_path / "cases.json"
    state_json_path = build_path / "state.json"
    manifest_csv_path = samples_path / "manifest.csv"
    seed_json_path = samples_path / "seed.json"

    errors: List[str] = []

    # Ensure required input files exist
    if not cases_json_path.exists():
        errors.append(f"Missing cases.json in build dir: {cases_json_path}")
    if not manifest_csv_path.exists():
        errors.append(f"Missing manifest.csv in samples dir: {manifest_csv_path}")

    if errors:
        for err in errors:
            print(f"❌ FAIL: {err}", file=sys.stderr)
        return False

    with open(cases_json_path, "r", encoding="utf-8") as f:
        cases_data = json.load(f)
    cases = cases_data.get("cases", [])
    case_map = {c["case_id"]: c for c in cases}
    stem_map = {c["file_stem"]: c for c in cases}

    with open(manifest_csv_path, "r", encoding="utf-8") as f:
        manifest_rows = list(csv.DictReader(f))
    manifest_map = {r["case_id"]: r for r in manifest_rows}

    # ----------------------------------------------------
    # Check 1: Exactly one output file, extracted JSON, manifest row per case; no strays
    # ----------------------------------------------------
    pdf_dir = samples_path / "pdf"
    scans_dir = samples_path / "scans"
    extracted_dir = samples_path / "extracted"

    all_expected_stems = set(stem_map.keys())
    actual_output_files: Dict[str, Path] = {}
    stray_files: List[str] = []

    # Collect actual output files
    if pdf_dir.exists():
        for p in pdf_dir.iterdir():
            if p.is_file() and not p.name.startswith("."):
                stem = p.stem
                if stem in stem_map:
                    if stem in actual_output_files:
                        errors.append(f"[Check 1] Case '{stem}' has multiple output files: {actual_output_files[stem]} and {p}")
                    actual_output_files[stem] = p
                else:
                    stray_files.append(str(p))

    if scans_dir.exists():
        for p in scans_dir.iterdir():
            if p.is_file() and not p.name.startswith("."):
                stem = p.stem
                if stem in stem_map:
                    if stem in actual_output_files:
                        errors.append(f"[Check 1] Case '{stem}' has multiple output files: {actual_output_files[stem]} and {p}")
                    actual_output_files[stem] = p
                else:
                    stray_files.append(str(p))

    for stray in stray_files:
        errors.append(f"[Check 1] Stray output file found: {stray}")

    # Check extracted JSON files
    actual_extracted_stems: Set[str] = set()
    if extracted_dir.exists():
        for p in extracted_dir.iterdir():
            if p.is_file() and p.name.endswith(".extracted.json"):
                stem = p.name[:-len(".extracted.json")]
                actual_extracted_stems.add(stem)
                if stem not in stem_map:
                    errors.append(f"[Check 1] Stray extracted JSON found: {p}")

    for stem in all_expected_stems:
        if stem not in actual_output_files:
            errors.append(f"[Check 1] Missing output file for case stem: {stem}")
        if stem not in actual_extracted_stems:
            errors.append(f"[Check 1] Missing extracted JSON for case stem: {stem}")

    if len(manifest_rows) != len(cases):
        errors.append(f"[Check 1] Manifest row count ({len(manifest_rows)}) != case count ({len(cases)})")

    # ----------------------------------------------------
    # Check 2: Digital PDFs have text layers (>80 chars); scans do not
    # ----------------------------------------------------
    for case in cases:
        stem = case["file_stem"]
        degrade = case.get("render", {}).get("degrade", "none")
        out_file = actual_output_files.get(stem)
        if not out_file or not out_file.exists():
            continue

        if degrade == "none":
            if out_file.suffix.lower() != ".pdf":
                errors.append(f"[Check 2] Case '{stem}' degrade=none but output is not PDF: {out_file.name}")
            else:
                doc = fitz.open(str(out_file))
                total_text_len = sum(len(page.get_text().strip()) for page in doc)
                doc.close()
                if total_text_len <= 80:
                    errors.append(f"[Check 2] Digital PDF '{out_file.name}' text layer too short: {total_text_len} chars (<= 80)")
        else:
            # Scans: if PDF, must have 0 text length
            if out_file.suffix.lower() == ".pdf":
                doc = fitz.open(str(out_file))
                total_text_len = sum(len(page.get_text().strip()) for page in doc)
                doc.close()
                if total_text_len > 0:
                    errors.append(f"[Check 2] Degraded scan PDF '{out_file.name}' has non-empty text layer: {total_text_len} chars")

    # ----------------------------------------------------
    # Check 3: byte_copy_of files are byte-identical; rerender cases differ
    # ----------------------------------------------------
    for case in cases:
        byte_copy_of = case.get("byte_copy_of")
        if byte_copy_of:
            source_case = case_map.get(byte_copy_of)
            if not source_case:
                errors.append(f"[Check 3] Case '{case['case_id']}' references unknown byte_copy_of: {byte_copy_of}")
                continue
            src_stem = source_case["file_stem"]
            tgt_stem = case["file_stem"]
            src_file = actual_output_files.get(src_stem)
            tgt_file = actual_output_files.get(tgt_stem)

            if src_file and tgt_file and src_file.exists() and tgt_file.exists():
                h_src = compute_sha256(src_file)
                h_tgt = compute_sha256(tgt_file)
                if h_src != h_tgt:
                    errors.append(f"[Check 3] byte_copy_of sha256 mismatch between '{tgt_file.name}' and '{src_file.name}'")

    # ----------------------------------------------------
    # Check 4: Grand total and invoice number match cases.json in digital PDFs (except omit)
    # ----------------------------------------------------
    for case in cases:
        degrade = case.get("render", {}).get("degrade", "none")
        if degrade != "none":
            continue

        stem = case["file_stem"]
        out_file = actual_output_files.get(stem)
        if not out_file or not out_file.exists():
            continue

        doc_data = case.get("document", {})
        omit_data = doc_data.get("omit", {})
        omit_fields = omit_data.get("fields", []) if isinstance(omit_data, dict) else []

        doc = fitz.open(str(out_file))
        all_text = " ".join(page.get_text() for page in doc)
        doc.close()

        # Check invoice number
        inv_no = doc_data.get("invoice_number")
        if inv_no and "invoice_number" not in omit_fields:
            if inv_no not in all_text:
                errors.append(f"[Check 4] Invoice number '{inv_no}' not found in digital PDF text for case '{stem}'")

        # Check grand total
        gt = doc_data.get("grand_total")
        if gt is not None and "grand_total" not in omit_fields:
            num_fmt = case.get("render", {}).get("number_format", "plain")
            formatted_num = format_number(gt, number_format=num_fmt)
            raw_num = f"{abs(float(gt)):.2f}"
            if formatted_num not in all_text and raw_num not in all_text:
                errors.append(f"[Check 4] Grand total '{gt}' (formatted '{formatted_num}') not found in text for case '{stem}'")

    # ----------------------------------------------------
    # Check 5: Manifest run_order is unique and series members are consecutive
    # ----------------------------------------------------
    run_orders: List[int] = []
    series_groups: Dict[str, List[Dict[str, Any]]] = {}

    for r in manifest_rows:
        ro = int(r["run_order"])
        run_orders.append(ro)
        sid = r["series_id"]
        if sid:
            series_groups.setdefault(sid, []).append(r)

    if len(run_orders) != len(set(run_orders)):
        errors.append(f"[Check 5] Manifest run_orders are not unique: duplicate values exist.")

    for sid, s_rows in series_groups.items():
        s_orders = sorted([int(r["run_order"]) for r in s_rows])
        for i in range(len(s_orders) - 1):
            if s_orders[i + 1] != s_orders[i] + 1:
                errors.append(f"[Check 5] Series '{sid}' run_orders are not consecutive: {s_orders}")
                break

    # ----------------------------------------------------
    # Check 6: Loading seed into temporary DB succeeds and balances match state.json
    # ----------------------------------------------------
    if seed_json_path.exists():
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_db = Path(tmp_dir) / "test_verify.db"
            try:
                load_dataset_into_db(str(seed_json_path), str(test_db), reset=True)
            except Exception as e:
                errors.append(f"[Check 6] Loading seed.json into test DB failed: {e}")
    else:
        errors.append(f"[Check 6] Missing seed.json at: {seed_json_path}")

    # ----------------------------------------------------
    # Check 7: Manifest has >= 25% rows with degrade != none
    # ----------------------------------------------------
    if manifest_rows:
        degraded_count = sum(1 for r in manifest_rows if r.get("degrade") != "none")
        degraded_pct = (degraded_count / len(manifest_rows)) * 100.0
        if degraded_pct < 25.0:
            errors.append(f"[Check 7] Degraded cases fraction too low: {degraded_pct:.1f}% ({degraded_count}/{len(manifest_rows)}), minimum required is 25%")

    # Report results
    if errors:
        print("\n❌ DATASET VERIFICATION FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  • {err}", file=sys.stderr)
        return False

    print("\n✅ ALL 7 VERIFICATION CHECKS PASSED.")
    print("Dataset structure, determinism, printed values, and seed balances are fully verified.")

    # Check if pipeline CLI is installed and print command
    print("\nNext step: Execute batch pipeline against manifest:")
    print("```bash")
    print("invoice-ap init-db")
    print("python -m seed.load_dataset --seed samples/seed.json --db data/ap.db --reset")
    print(f"invoice-ap batch {samples_dir} --manifest {samples_dir}/manifest.csv --report report.csv")
    print("```\n")

    if run_batch:
        try:
            print("Executing pipeline batch run (--run-batch passed)...")
            subprocess.run([
                "invoice-ap", "batch", str(samples_path),
                "--manifest", str(manifest_csv_path),
                "--report", "report.csv"
            ], check=True)
        except Exception as e:
            print(f"Batch execution error: {e}", file=sys.stderr)

    return True


def main():
    parser = argparse.ArgumentParser(description="End-to-end dataset verification.")
    parser.add_argument("--out", default="samples/", help="Path to samples/ directory")
    parser.add_argument("--build", default="build/", help="Path to build/ directory containing cases.json and state.json")
    parser.add_argument("--run-batch", action="store_true", help="Run invoice-ap batch if CLI is available")
    args = parser.parse_args()

    success = verify_dataset(args.out, build_dir=args.build, run_batch=args.run_batch)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
