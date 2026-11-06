from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

MANIFEST_COLUMNS = [
    "file",
    "edge_case_tag",
    "expected_decision",
    "expected_reason_code",
    "expected_po",
    "run_order",
    "notes",
    "case_id",
    "family",
    "series_id",
    "expected_reason_codes_accepted",
    "decision_accepted",
    "confidence",
    "expect_cached",
    "config_dependency",
    "layout",
    "degrade",
    "sha256",
]


def compute_sha256(filepath: Path) -> str:
    """Compute sha256 hex digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_ocr_calibration(samples_dir: Path, manifest_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Optional informational OCR calibration on one sample per degradation level."""
    try:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()
    except Exception:
        return []

    # Pick one case per degrade level
    levels = ["light", "medium", "heavy"]
    results = []

    for lvl in levels:
        matching = [r for r in manifest_rows if r.get("degrade") == lvl]
        if not matching:
            continue
        sample = matching[0]
        file_path = samples_dir / sample["file"]
        if not file_path.exists():
            continue

        try:
            if file_path.suffix.lower() == ".pdf":
                import fitz
                doc = fitz.open(str(file_path))
                pix = doc[0].get_pixmap(dpi=150)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                if pix.n == 4:
                    img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
                ocr_res, _ = ocr(img)
                doc.close()
            else:
                ocr_res, _ = ocr(str(file_path))

            detected_text = " ".join([box[1] for box in ocr_res]) if ocr_res else ""

            # Check if case_id or numbers are recovered
            inv_no = sample.get("invoice_number", "")
            recovered_inv = bool(inv_no and inv_no in detected_text)

            results.append({
                "level": lvl,
                "file": sample["file"],
                "ocr_status": "OK" if ocr_res else "NO_TEXT",
                "detected_snippets": detected_text[:80],
            })
        except Exception as e:
            results.append({
                "level": lvl,
                "file": sample["file"],
                "ocr_status": f"ERROR ({e})",
                "detected_snippets": "",
            })

    return results


def build_manifest_and_report(
    build_dir: str,
    out_dir: str,
    embedder_backend: str = "tfidf",
) -> Tuple[Path, Path]:
    """Generate samples/manifest.csv and samples/dataset_report.md."""
    build_path = Path(build_dir)
    samples_path = Path(out_dir)
    cases_json = build_path / "cases.json"
    state_json = build_path / "state.json"

    with open(cases_json, "r", encoding="utf-8") as f:
        cases_data = json.load(f)

    cases = cases_data.get("cases", [])
    cases.sort(key=lambda c: c.get("run_order", 0))

    manifest_rows: List[Dict[str, Any]] = []

    for case in cases:
        case_id = case["case_id"]
        file_stem = case["file_stem"]
        run_order = case["run_order"]
        tag = case.get("tag", "")
        family = case.get("family", "")
        series_id = case.get("series_id") or ""
        doc = case.get("document", {})
        render_conf = case.get("render", {})
        expected = case.get("expected", {})

        layout = render_conf.get("layout", "itemised")
        degrade = render_conf.get("degrade", "none")

        # Determine file relative path
        if degrade == "none":
            rel_file = f"pdf/{file_stem}.pdf"
        elif degrade == "light":
            rel_file = f"scans/{file_stem}.pdf"
        elif degrade == "medium":
            rel_file = f"scans/{file_stem}.png"
        elif degrade == "heavy":
            rel_file = f"scans/{file_stem}.jpg"
        else:
            rel_file = f"pdf/{file_stem}.pdf"

        full_file = samples_path / rel_file
        if not full_file.exists():
            # Check alternative extensions if byte_copy_of used source extension
            for ext in [".pdf", ".png", ".jpg"]:
                cand = samples_path / (f"scans/{file_stem}{ext}" if degrade != "none" else f"pdf/{file_stem}{ext}")
                if cand.exists():
                    full_file = cand
                    rel_file = f"scans/{file_stem}{ext}" if degrade != "none" else f"pdf/{file_stem}{ext}"
                    break

        sha256 = compute_sha256(full_file) if full_file.exists() else ""
        file_size = full_file.stat().st_size if full_file.exists() else 0

        reason_codes = expected.get("reason_codes_accepted", [])
        decisions = expected.get("decision_accepted", [])
        config_dep = expected.get("config_dependency", [])

        manifest_rows.append({
            "file": rel_file,
            "edge_case_tag": tag,
            "expected_decision": expected.get("decision", ""),
            "expected_reason_code": reason_codes[0] if reason_codes else "",
            "expected_po": expected.get("po_id") or "",
            "run_order": run_order,
            "notes": expected.get("notes", ""),
            "case_id": case_id,
            "family": family,
            "series_id": series_id,
            "expected_reason_codes_accepted": "|".join(reason_codes),
            "decision_accepted": "|".join(decisions),
            "confidence": expected.get("confidence", "firm"),
            "expect_cached": expected.get("expect_cached", False),
            "config_dependency": "|".join(config_dep),
            "layout": layout,
            "degrade": degrade,
            "sha256": sha256,
            "file_size": file_size,
            "invoice_number": doc.get("invoice_number", ""),
            "grand_total": doc.get("grand_total"),
        })

    # Write samples/manifest.csv
    manifest_csv_path = samples_path / "manifest.csv"
    manifest_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(manifest_rows)

    # Compile report statistics
    total_cases = len(manifest_rows)
    family_counts: Dict[str, int] = {}
    tag_counts: Dict[str, int] = {}
    layout_counts: Dict[str, int] = {}
    degrade_counts: Dict[str, int] = {}
    confidence_counts: Dict[str, int] = {}
    series_map: Dict[str, List[Dict[str, Any]]] = {}

    total_bytes = 0
    min_bytes = float("inf") if total_cases > 0 else 0
    max_bytes = 0

    for r in manifest_rows:
        fam = r["family"]
        family_counts[fam] = family_counts.get(fam, 0) + 1

        t = r["edge_case_tag"]
        tag_counts[t] = tag_counts.get(t, 0) + 1

        ly = r["layout"]
        layout_counts[ly] = layout_counts.get(ly, 0) + 1

        deg = r["degrade"]
        degrade_counts[deg] = degrade_counts.get(deg, 0) + 1

        conf = r["confidence"]
        confidence_counts[conf] = confidence_counts.get(conf, 0) + 1

        sz = r["file_size"]
        total_bytes += sz
        if sz < min_bytes:
            min_bytes = sz
        if sz > max_bytes:
            max_bytes = sz

        s_id = r["series_id"]
        if s_id:
            series_map.setdefault(s_id, []).append(r)

    # OCR calibration
    ocr_rows = run_ocr_calibration(samples_path, manifest_rows)

    # Write samples/dataset_report.md
    report_md_path = samples_path / "dataset_report.md"
    with open(report_md_path, "w", encoding="utf-8") as f:
        f.write("# Synthetic Invoice Dataset Report\n\n")
        f.write(f"- **Total Cases**: {total_cases}\n")
        f.write(f"- **Embedder Backend**: `{embedder_backend}`\n")
        f.write(f"- **Total File Size**: {total_bytes / 1024:.1f} KB (Min: {min_bytes} B, Max: {max_bytes / 1024:.1f} KB)\n\n")

        f.write("## 1. Counts by Family\n\n")
        f.write("| Family | Case Count |\n|---|---|\n")
        for fam, cnt in sorted(family_counts.items()):
            f.write(f"| {fam} | {cnt} |\n")

        f.write("\n## 2. Counts by Degradation Level\n\n")
        f.write("| Degradation Level | Count | Pct |\n|---|---|---|\n")
        for deg, cnt in sorted(degrade_counts.items()):
            pct = (cnt / total_cases * 100) if total_cases > 0 else 0
            f.write(f"| `{deg}` | {cnt} | {pct:.1f}% |\n")

        f.write("\n## 3. Counts by Layout\n\n")
        f.write("| Layout | Count |\n|---|---|\n")
        for ly, cnt in sorted(layout_counts.items()):
            f.write(f"| `{ly}` | {cnt} |\n")

        f.write("\n## 4. Confidence Breakdown\n\n")
        f.write("| Confidence | Count |\n|---|---|\n")
        for conf, cnt in sorted(confidence_counts.items()):
            f.write(f"| `{conf}` | {cnt} |\n")

        f.write("\n## 5. Series Sequences\n\n")
        if series_map:
            f.write("| Series ID | Run Orders | Cases |\n|---|---|---|\n")
            for sid, s_rows in sorted(series_map.items()):
                orders = ", ".join(str(r["run_order"]) for r in s_rows)
                c_ids = ", ".join(r["case_id"] for r in s_rows)
                f.write(f"| `{sid}` | {orders} | {c_ids} |\n")
        else:
            f.write("No multi-step series declared.\n")

        if ocr_rows:
            f.write("\n## 6. Informational OCR Calibration\n\n")
            f.write("| Level | Sample File | OCR Status | Detected Snippets |\n|---|---|---|---|\n")
            for o in ocr_rows:
                f.write(f"| `{o['level']}` | `{o['file']}` | {o['ocr_status']} | `{o['detected_snippets']}` |\n")

        f.write("\n## 7. Pipeline Execution Commands\n\n")
        f.write("To load this dataset into the pipeline database and run the batch evaluation:\n\n")
        f.write("```bash\n")
        f.write("# 1. Initialize DB and load seed data (including ledger preload):\n")
        f.write("invoice-ap init-db\n")
        f.write("python -m seed.load_dataset --seed samples/seed.json --db data/ap.db --reset\n\n")
        f.write("# 2. Execute batch pipeline against manifest:\n")
        f.write("invoice-ap batch samples/ --manifest samples/manifest.csv --report report.csv\n")
        f.write("```\n\n")
        f.write("> **Important**: Invoices must be processed strictly in `run_order` sequence. The database must be initialized with `seed.json` prior to execution.\n")

    return manifest_csv_path, report_md_path


def main():
    parser = argparse.ArgumentParser(description="Generate manifest.csv and dataset_report.md")
    parser.add_argument("--build", default="build/", help="Path to build/ directory containing cases.json")
    parser.add_argument("--out", default="samples/", help="Path to samples/ directory")
    parser.add_argument("--embedder", default="tfidf", help="Embedder backend used")
    args = parser.parse_args()

    m_path, r_path = build_manifest_and_report(args.build, args.out, embedder_backend=args.embedder)
    print(f"Generated manifest: {m_path}")
    print(f"Generated dataset report: {r_path}")


if __name__ == "__main__":
    main()
