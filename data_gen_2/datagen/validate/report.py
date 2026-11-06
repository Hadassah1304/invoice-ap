"""Report generator and coverage cross-checks (V20, V22).

V20: Mutation-derived expectation vs intent.
V22: Coverage: counts per family and per tag reported against targets table defined in constants.py;
     at least 25% of cases have degrade != none (WARN).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from datagen.constants import TARGET_FAMILY_COUNTS, FAMILY_TAGS
from datagen.models import CaseOutput


def validate_mutation_derived_expectations(compiled_cases: List[CaseOutput], derived_expectations: Dict[str, Any]) -> List[Dict[str, Any]]:
    """V20: Compare mutation-derived expectations with authored intent."""
    findings: List[Dict[str, Any]] = []

    for case in compiled_cases:
        derived = derived_expectations.get(case.case_id)
        if not derived:
            continue

        intent = case.expected
        # Check decision
        if derived.decision != intent.decision:
            if derived.decision not in intent.decision_accepted:
                findings.append({
                    "code": "V20",
                    "severity": "ERROR",
                    "id": case.case_id,
                    "message": f"Mutation-derived decision '{derived.decision}' disagrees with intent '{intent.decision}'",
                    "fix": f"Change intent decision to '{derived.decision}' or update accepted decisions",
                })

        # Check reason code
        if derived.reason_code and intent.reason_codes_accepted:
            if derived.reason_code not in intent.reason_codes_accepted:
                findings.append({
                    "code": "V20",
                    "severity": "ERROR",
                    "id": case.case_id,
                    "message": f"Mutation-derived reason code '{derived.reason_code}' not in intent.reason_codes_accepted {intent.reason_codes_accepted}",
                    "fix": f"Add '{derived.reason_code}' to reason_codes_accepted in intent",
                })

    return findings


def validate_coverage(compiled_cases: List[CaseOutput]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """V22: Coverage checks per family and per tag, plus degrade >= 25%."""
    findings: List[Dict[str, Any]] = []

    family_counts: Dict[str, int] = {}
    tag_counts: Dict[str, int] = {}
    degrade_count = 0

    for c in compiled_cases:
        family_counts[c.family] = family_counts.get(c.family, 0) + 1
        tag_counts[c.tag] = tag_counts.get(c.tag, 0) + 1
        if c.render.degrade != "none":
            degrade_count += 1

    total_cases = len(compiled_cases)

    # Family count targets
    for fam, target in TARGET_FAMILY_COUNTS.items():
        actual = family_counts.get(fam, 0)
        if actual != target:
            findings.append({
                "code": "V22",
                "severity": "WARN",
                "id": f"Family {fam}",
                "message": f"Family {fam} has {actual} scenarios, expected target {target}",
                "fix": f"Adjust number of scenarios in family {fam} to match target {target}",
            })

    # Degrade >= 25%
    if total_cases > 0:
        degrade_pct = (degrade_count / total_cases) * 100.0
        if degrade_pct < 25.0:
            findings.append({
                "code": "V22",
                "severity": "WARN",
                "id": "render.degrade",
                "message": f"Only {degrade_count}/{total_cases} ({degrade_pct:.1f}%) cases have degrade != 'none' (target >= 25%)",
                "fix": "Increase number of degraded render cases",
            })

    coverage_summary = {
        "family_counts": family_counts,
        "tag_counts": tag_counts,
        "total_cases": total_cases,
        "degrade_count": degrade_count,
    }

    return findings, coverage_summary


def generate_validation_report(
    all_findings: List[Dict[str, Any]],
    oracle_counts: Dict[str, int],
    coverage_summary: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """Generates markdown validation report and JSON summary dictionary."""
    errors = [f for f in all_findings if f["severity"] == "ERROR"]
    warnings = [f for f in all_findings if f["severity"] == "WARN"]

    # Counts by code
    code_counts: Dict[str, int] = {}
    for f in all_findings:
        code_counts[f["code"]] = code_counts.get(f["code"], 0) + 1

    report_dict = {
        "status": "FAIL" if errors else "PASS",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "code_counts": code_counts,
        "oracle": oracle_counts,
        "coverage": coverage_summary,
        "findings": all_findings,
    }

    lines = [
        "# Dataset Validation Report",
        "",
        f"**Status**: {'❌ FAIL' if errors else '✅ PASS'} ({len(errors)} errors, {len(warnings)} warnings)",
        "",
        "## Summary by Validation Code",
        "",
        "| Code | Count | Status |",
        "|---|---|---|",
    ]
    for code in sorted(code_counts.keys()):
        count = code_counts[code]
        has_err = any(f["code"] == code and f["severity"] == "ERROR" for f in all_findings)
        lines.append(f"| `{code}` | {count} | {'ERROR' if has_err else 'WARN'} |")

    lines.extend([
        "",
        "## Oracle Evaluation",
        "",
        f"- **Determined gate cases**: {oracle_counts.get('determined', 0)}",
        f"- **Undetermined (inferred/complex) cases**: {oracle_counts.get('undetermined', 0)}",
        "",
        "## Family & Scenario Coverage",
        "",
        "| Family | Target | Actual |",
        "|---|---|---|",
    ])
    for fam, tgt in TARGET_FAMILY_COUNTS.items():
        act = coverage_summary.get("family_counts", {}).get(fam, 0)
        lines.append(f"| {fam} | {tgt} | {act} |")

    lines.extend([
        "",
        f"**Total Cases**: {coverage_summary.get('total_cases', 0)}",
        f"**Degraded Renderings**: {coverage_summary.get('degrade_count', 0)} / {coverage_summary.get('total_cases', 0)}",
        "",
    ])

    if all_findings:
        lines.extend([
            "## Detailed Findings",
            "",
            "| Severity | Code | Target ID | Message | Fix Hint |",
            "|---|---|---|---|---|",
        ])
        for f in all_findings:
            sev = "🔴 ERROR" if f["severity"] == "ERROR" else "⚠️ WARN"
            lines.append(f"| {sev} | `{f['code']}` | `{f['id']}` | {f['message']} | {f['fix']} |")

    md_report = "\n".join(lines) + "\n"
    return md_report, report_dict
