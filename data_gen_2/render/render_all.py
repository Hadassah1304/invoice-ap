from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from render.degrade import process_degraded_document
from render.extracted_json import build_extracted_invoice, save_extracted_json
from render.layouts import get_layout_renderer


def compute_file_sha256(filepath: str) -> str:
    """Compute hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def render_all_cases(
    cases_json_path: str,
    out_dir: str,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """Render all cases from cases.json into digital PDFs and degraded scans.
    
    Returns a list of dicts with manifest data for each case in run_order.
    """
    with open(cases_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cases = data.get("cases", [])
    # Sort cases by run_order
    cases.sort(key=lambda c: c.get("run_order", 0))

    out_base = Path(out_dir)
    pdf_dir = out_base / "pdf"
    scans_dir = out_base / "scans"
    extracted_dir = out_base / "extracted"

    pdf_dir.mkdir(parents=True, exist_ok=True)
    scans_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    rendered_results: Dict[str, Dict[str, Any]] = {}
    manifest_rows: List[Dict[str, Any]] = []

    for case in cases:
        case_id = case["case_id"]
        file_stem = case["file_stem"]
        run_order = case["run_order"]
        tag = case.get("tag", "")
        family = case.get("family", "")
        series_id = case.get("series_id")
        byte_copy_of = case.get("byte_copy_of")
        document = case.get("document", {})
        render_conf = case.get("render", {})
        expected = case.get("expected", {})

        layout = render_conf.get("layout", "itemised")
        degrade = render_conf.get("degrade", "none")

        # Determine target file extension and directory
        if degrade == "none":
            ext = ".pdf"
            dest_dir = pdf_dir
            rel_path = f"pdf/{file_stem}{ext}"
        elif degrade == "light":
            ext = ".pdf"
            dest_dir = scans_dir
            rel_path = f"scans/{file_stem}{ext}"
        elif degrade == "medium":
            ext = ".png"
            dest_dir = scans_dir
            rel_path = f"scans/{file_stem}{ext}"
        elif degrade == "heavy":
            ext = ".jpg"
            dest_dir = scans_dir
            rel_path = f"scans/{file_stem}{ext}"
        else:
            ext = ".pdf"
            dest_dir = pdf_dir
            rel_path = f"pdf/{file_stem}{ext}"

        dest_file = dest_dir / f"{file_stem}{ext}"

        if byte_copy_of:
            # Copy exact bytes of the source case's output file
            if byte_copy_of not in rendered_results:
                raise ValueError(f"Case '{case_id}' specifies byte_copy_of='{byte_copy_of}', but source case has not been rendered.")
            source_info = rendered_results[byte_copy_of]
            source_file = Path(source_info["full_path"])
            if source_file.suffix != ext:
                # Align extension with source file
                ext = source_file.suffix
                dest_file = dest_dir / f"{file_stem}{ext}"
                folder_name = "pdf" if degrade == "none" else "scans"
                rel_path = f"{folder_name}/{file_stem}{ext}"

            shutil.copyfile(source_file, dest_file)
            sha256 = compute_file_sha256(str(dest_file))
            if sha256 != source_info["sha256"]:
                raise RuntimeError(f"Byte copy mismatch for case {case_id}: sha256 differed from {byte_copy_of}")
            page_count = source_info["page_count"]

        else:
            # Ordinary render
            renderer = get_layout_renderer(layout)

            # Convert dict to simple namespace/object if needed
            class SimpleObj:
                def __init__(self, d):
                    for k, v in d.items():
                        if isinstance(v, dict):
                            setattr(self, k, SimpleObj(v))
                        elif isinstance(v, list):
                            setattr(self, k, [SimpleObj(i) if isinstance(i, dict) else i for i in v])
                        else:
                            setattr(self, k, v)

            doc_obj = SimpleObj(document)
            render_obj = SimpleObj(render_conf)

            if degrade == "none":
                # Digital PDF: render directly to destination
                bboxes = renderer(doc_obj, render_obj, str(dest_file))
                doc = fitz.open(str(dest_file))
                page_count = len(doc)
                doc.close()
                sha256 = compute_file_sha256(str(dest_file))

            else:
                # Scanned: render digital PDF in temporary directory, then degrade
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp_pdf = Path(tmp_dir) / f"{file_stem}_digital.pdf"
                    bboxes = renderer(doc_obj, render_obj, str(tmp_pdf))
                    doc = fitz.open(str(tmp_pdf))
                    page_count = len(doc)
                    doc.close()

                    process_degraded_document(
                        digital_pdf_path=str(tmp_pdf),
                        output_path=str(dest_file),
                        level=degrade,
                        seed=seed,
                        case_id=case_id,
                        bounding_boxes=bboxes,
                    )
                sha256 = compute_file_sha256(str(dest_file))

        # Build and save extracted JSON
        ext_json_path = extracted_dir / f"{file_stem}.extracted.json"
        extracted_obj = build_extracted_invoice(
            document=SimpleObj(document) if isinstance(document, dict) else document,
            file_name=dest_file.name,
            file_hash=sha256,
            page_count=page_count,
        )
        save_extracted_json(extracted_obj, str(ext_json_path))

        case_record = {
            "case_id": case_id,
            "file_stem": file_stem,
            "run_order": run_order,
            "tag": tag,
            "family": family,
            "series_id": series_id or "",
            "layout": layout,
            "degrade": degrade,
            "file": rel_path,
            "full_path": str(dest_file),
            "sha256": sha256,
            "page_count": page_count,
            "expected_decision": expected.get("decision", ""),
            "expected_reason_code": (expected.get("reason_codes_accepted") or [""])[0],
            "expected_po": expected.get("po_id") or "",
            "notes": expected.get("notes", ""),
            "expected_reason_codes_accepted": "|".join(expected.get("reason_codes_accepted", [])),
            "decision_accepted": "|".join(expected.get("decision_accepted", [])),
            "confidence": expected.get("confidence", "firm"),
            "expect_cached": expected.get("expect_cached", False),
            "config_dependency": "|".join(expected.get("config_dependency", [])),
        }

        rendered_results[case_id] = case_record
        manifest_rows.append(case_record)

    return manifest_rows
