"""Compiler pipeline: compile cases.json, manifest_base.csv, apply mutations and render hints.

02_PIPELINE_SCRIPTS.md Section 7:
1. Order cases: group by series; singles and series ordered by (family, series id or case id);
   series members consecutive by position; any derive_from must run after its source. Assign run_order 1..N deterministically.
2. Apply each case's mutation to its base document; run derivation; compare with intent; collect findings.
3. Resolve every auto render hint deterministically:
   - layouts rotate through the 4 layouts in a fixed cycle (balanced counts).
   - number and currency formats and date styles come from the per-case RNG.
   - mutations that need specific hints (reformat, embed_tax) override.
   - multi-page layout is forced for scenarios requesting it.
   - for rerender cases, ensure (layout, degrade) differs from the source.
4. Emit cases.json, state.json, manifest_base.csv.
5. Hard-fail (non-zero exit, no outputs written) if any validation error exists.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import random
from typing import Any, Dict, List, Optional, Tuple, Union

from datagen.constants import Config, REFERENCE_DATE_STR
from datagen.finalize import FinalizedState, finalize_state
from datagen.loader import LoadedBase, load_authored_base
from datagen.models import (
    AuthoredScenario,
    CaseExpected,
    CaseOutput,
    CasesMeta,
    CasesOutput,
    CompiledRender,
    Document,
)
from datagen.money import to_decimal
from datagen.mutate.registry import MutationContext, registry
from datagen.validate import (
    generate_validation_report,
    validate_collisions,
    validate_coverage,
    validate_mutation_derived_expectations,
    validate_oracle,
    validate_ownership,
    validate_schemas_and_ids,
    validate_structural,
)


LAYOUT_CYCLE = ["itemised", "bundled", "tax_embedded", "multi_page"]
NUMBER_FORMATS = ["plain", "indian", "eu"]
CURRENCY_STYLES = ["Rs.", "₹", "INR"]
DATE_STYLES = ["dmy_slash", "dmy_mon", "iso"]


class CompilationResult:
    def __init__(
        self,
        cases_output: CasesOutput,
        finalized_state: FinalizedState,
        manifest_csv_text: str,
        validation_report_md: str,
        validation_report_json: Dict[str, Any],
        has_errors: bool,
    ):
        self.cases_output = cases_output
        self.finalized_state = finalized_state
        self.manifest_csv_text = manifest_csv_text
        self.validation_report_md = validation_report_md
        self.validation_report_json = validation_report_json
        self.has_errors = has_errors


def compile_dataset(
    loaded: LoadedBase,
    seed: int = 42,
    config: Optional[Config] = None,
) -> CompilationResult:
    if config is None:
        config = Config()

    # Check for early load errors (e.g. invalid JSON, schema validation failure, missing files)
    if loaded.load_errors or not loaded.core:
        all_findings = list(loaded.load_errors)
        all_findings.extend(validate_schemas_and_ids(loaded))
        md_report, json_report = generate_validation_report(all_findings, {}, {})
        return CompilationResult(
            cases_output=CasesOutput(meta=CasesMeta(reference_date=REFERENCE_DATE_STR, seed=seed, case_count=0), cases=[]),
            finalized_state=None,
            manifest_csv_text="",
            validation_report_md=md_report,
            validation_report_json=json_report,
            has_errors=True,
        )

    # 1. Finalize POs and Base Documents
    finalized = finalize_state(loaded, seed=seed)

    # 2. Build Compiled Cases
    vendors_by_id = {v.vendor_id: v for v in loaded.core.vendors} if loaded.core else {}
    catalog_by_sku = {c.sku: c for c in loaded.core.catalog} if loaded.core else {}
    all_pos_by_id = {p.po_id: p for f in loaded.families.values() for p in f.pos}

    compiled_cases: List[CaseOutput] = []
    derived_expectations: Dict[str, Any] = {}
    base_documents_final: Dict[str, Document] = dict(finalized.base_documents)

    compiled_by_id: Dict[str, CaseOutput] = {}

    for run_order, (fam_name, sc) in enumerate(finalized.ordered_scenarios, start=1):
        case_id = sc.scenario_id
        tag = sc.tag
        file_stem = f"{fam_name.lower()}{run_order:02d}_{tag}"

        # Per-case RNG derived deterministically from master seed
        case_rng = random.Random(f"{seed}:{case_id}")

        # Base document: either from finalized.base_documents or derived from source
        byte_copy_of = None
        if sc.derive_from:
            src_id = sc.derive_from.scenario_id
            src_doc = base_documents_final.get(src_id)
            if src_doc:
                clean_doc = src_doc.model_copy(deep=True)
            else:
                clean_doc = Document()
            if sc.mutation.name == "resend_identical":
                byte_copy_of = src_id
        else:
            clean_doc = finalized.base_documents[case_id].model_copy(deep=True)

        # Mutate document
        mut_name = sc.mutation.name
        mut_params = sc.mutation.params
        mut_op = registry.get(mut_name)

        mut_ctx = MutationContext(
            scenario=sc,
            vendors_by_id=vendors_by_id,
            pos_by_id=all_pos_by_id,
            catalog_by_sku=catalog_by_sku,
            rng=case_rng,
            all_cases=compiled_cases,
            constants=config,
        )

        if mut_op:
            mutated_doc = mut_op.apply(clean_doc, mut_ctx, mut_params)
            derived = mut_op.derive(mutated_doc, mut_ctx, mut_params)
            if derived:
                derived_expectations[case_id] = derived
        else:
            mutated_doc = clean_doc

        base_documents_final[case_id] = mutated_doc

        # Resolve Render hints
        # Layouts rotate through the 4 layouts in fixed cycle
        default_layout = LAYOUT_CYCLE[(run_order - 1) % len(LAYOUT_CYCLE)]
        layout = sc.render.layout if sc.render.layout != "auto" else default_layout
        if mut_name == "embed_tax":
            layout = "tax_embedded"
        if tag == "tax_embedded":
            layout = "tax_embedded"

        degrade = sc.render.degrade

        # Number format, currency style, date style
        num_fmt = sc.render.number_format
        if num_fmt == "auto":
            if mut_name == "reformat" and mut_params.get("number_format"):
                num_fmt = mut_params["number_format"]
            elif tag == "number_formats_indian":
                num_fmt = "indian"
            elif tag == "number_formats_eu_ambiguous":
                num_fmt = "eu"
            else:
                num_fmt = case_rng.choice(NUMBER_FORMATS)

        curr_style = sc.render.currency_style
        if curr_style == "auto":
            if mut_name == "reformat" and mut_params.get("currency_style"):
                curr_style = mut_params["currency_style"]
            else:
                curr_style = case_rng.choice(CURRENCY_STYLES)

        date_style = sc.render.date_style
        if date_style == "auto":
            if mut_name == "reformat" and mut_params.get("date_style"):
                date_style = mut_params["date_style"]
            else:
                date_style = case_rng.choice(DATE_STYLES)

        # Rerender collision rule: ensure (layout, degrade) differs from source
        if mut_name == "rerender" and sc.derive_from:
            src_case = compiled_by_id.get(sc.derive_from.scenario_id)
            if src_case and src_case.render.layout == layout and src_case.render.degrade == degrade:
                # pick a different layout
                alt_layouts = [l for l in LAYOUT_CYCLE if l != src_case.render.layout]
                layout = alt_layouts[0]

        compiled_render = CompiledRender(
            layout=layout,
            degrade=degrade,
            number_format=num_fmt,
            currency_style=curr_style,
            date_style=date_style,
        )

        expected = CaseExpected(
            decision=sc.intent.decision,
            decision_accepted=sc.intent.decision_accepted if sc.intent.decision_accepted else [sc.intent.decision],
            reason_codes_accepted=sc.intent.reason_codes_accepted,
            po_id=sc.intent.po_id,
            confidence=sc.intent.confidence,
            expect_cached=sc.intent.expect_cached,
            config_dependency=sc.intent.config_dependency,
            notes=sc.intent.notes,
        )

        case_out = CaseOutput(
            case_id=case_id,
            run_order=run_order,
            file_stem=file_stem,
            tag=tag,
            family=fam_name,
            series_id=sc.series.id if sc.series else None,
            byte_copy_of=byte_copy_of,
            document=mutated_doc,
            render=compiled_render,
            expected=expected,
        )
        compiled_cases.append(case_out)
        compiled_by_id[case_id] = case_out

    # 3. Validation Passes
    all_findings: List[Dict[str, Any]] = []

    # V01-V05
    all_findings.extend(validate_schemas_and_ids(loaded))
    # V06-V09
    all_findings.extend(validate_ownership(loaded, config))
    # V10-V12, V21
    all_findings.extend(validate_structural(loaded, finalized, compiled_cases, config))
    # V13-V18
    all_findings.extend(validate_collisions(loaded, finalized, compiled_cases, config))
    # V19 Oracle
    oracle_findings, oracle_counts = validate_oracle(loaded, finalized, compiled_cases, config)
    all_findings.extend(oracle_findings)
    # V20 Mutation derivations
    all_findings.extend(validate_mutation_derived_expectations(compiled_cases, derived_expectations))
    # V22 Coverage
    cov_findings, cov_summary = validate_coverage(compiled_cases)
    all_findings.extend(cov_findings)

    # 4. Generate Reports
    md_report, json_report = generate_validation_report(all_findings, oracle_counts, cov_summary)

    # Check for hard errors
    has_errors = any(f["severity"] == "ERROR" for f in all_findings)

    # 5. Manifest CSV text
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow([
        "case_id",
        "run_order",
        "file_stem",
        "tag",
        "family",
        "series_id",
        "expected_decision",
        "expected_reason_code",
        "expected_po",
        "confidence",
    ])
    for c in compiled_cases:
        primary_reason = c.expected.reason_codes_accepted[0] if c.expected.reason_codes_accepted else ""
        writer.writerow([
            c.case_id,
            c.run_order,
            c.file_stem,
            c.tag,
            c.family,
            c.series_id or "",
            c.expected.decision,
            primary_reason,
            c.expected.po_id or "",
            c.expected.confidence,
        ])
    manifest_csv = csv_buf.getvalue()

    cases_out = CasesOutput(
        meta=CasesMeta(
            reference_date=REFERENCE_DATE_STR,
            seed=seed,
            case_count=len(compiled_cases),
        ),
        cases=compiled_cases,
    )

    return CompilationResult(
        cases_output=cases_out,
        finalized_state=finalized,
        manifest_csv_text=manifest_csv,
        validation_report_md=md_report,
        validation_report_json=json_report,
        has_errors=has_errors,
    )
