from __future__ import annotations

import copy
import datetime
import json
from pathlib import Path
import time
from typing import Any, Callable, Dict, Optional
import uuid

from invoice_pipeline.config import PipelineConfig, load_config
from invoice_pipeline.decision.aggregator import aggregate_decision, compute_confidence
from invoice_pipeline.decision.explainer import build_explanation
from invoice_pipeline.extract.extractor import Extractor
from invoice_pipeline.extract.grounding import check_grounding
from invoice_pipeline.ingest.loader import inspect_file
from invoice_pipeline.ingest.ocr.router import OCRRouter
from invoice_pipeline.matching.duplicates import check_duplicates
from invoice_pipeline.matching.router import MatchingRouter
from invoice_pipeline.matching.vendor_resolver import VendorResolver
from invoice_pipeline.models import (
    BatchItemResult,
    BatchProcessResult,
    CostSummary,
    DecisionEnum,
    DecisionResult,
    ExtractionSource,
    MatchMethodEnum,
    MatchResult,
    POBalanceSummary,
    ReasonCodeEnum,
    ReviewRequired,
    RuleResult,
    RuleStatusEnum,
    Timings,
)
from invoice_pipeline.normalize.normalizers import (
    normalize_currency,
    normalize_invoice_number,
    parse_date,
    parse_number,
)
from invoice_pipeline.store.db import get_connection, transaction
from invoice_pipeline.store.embeddings import get_embedder
from invoice_pipeline.store.index import InMemoryItemIndex
from invoice_pipeline.store.repositories import (
    AuditRepo,
    InvoiceRepo,
    ItemRepo,
    PORepo,
    VendorRepo,
)
from invoice_pipeline.trace import TraceRecorder
from invoice_pipeline.utils.hashing import hash_bytes
from invoice_pipeline.validation.engine import ValidationEngine
from invoice_pipeline.validation.rules import ValidationContext


def process_invoice(
    file_path: str | Path,
    config: Optional[PipelineConfig] = None,
    overrides: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    pre_extracted_json: Optional[Dict[str, Any]] = None,
    force_ocr_engine: Optional[str] = None,
    target_invoice_id: Optional[int] = None,
    as_of_date: Optional[datetime.date] = None,
    progress_callback: Optional[Callable[[str, str, float], None]] = None,
) -> DecisionResult:
    """
    Main pipeline entry point.
    Runs complete Ingest -> Extract -> Normalize -> Validate -> Match -> Decide -> Persist cycle.
    """
    start_total_ns = time.perf_counter_ns()
    cfg = config or load_config()
    recorder = TraceRecorder()
    request_id = str(uuid.uuid4())

    path = Path(file_path)
    file_bytes = path.read_bytes() if path.exists() and path.is_file() else b""
    f_hash = hash_bytes(file_bytes) if file_bytes else ""

    conn = get_connection(cfg.app.db_path)
    inv_repo = InvoiceRepo(conn)
    vendor_repo = VendorRepo(conn)
    po_repo = PORepo(conn)
    item_repo = ItemRepo(conn)
    audit_repo = AuditRepo(conn)

    # 1. Cache Check (skipped for overrides, dry runs, or when re-evaluating)
    if cfg.app.cache_by_file_hash and f_hash and not overrides and not target_invoice_id and not pre_extracted_json:
        recorder.start_stage("cache_check")
        cached_row = inv_repo.get_by_file_hash(f_hash)
        if cached_row and cached_row.get("decision_json"):
            try:
                data = json.loads(cached_row["decision_json"])
                data["cached"] = True
                if cached_row.get("invoice_id"):
                    data["invoice_id"] = cached_row["invoice_id"]
                if cached_row.get("vendor_id"):
                    data["vendor_id"] = cached_row["vendor_id"]
                if cached_row.get("file_name"):
                    data["file_name"] = cached_row["file_name"]
                if cached_row.get("file_path"):
                    data["file_path"] = cached_row["file_path"]
                if progress_callback:
                    try:
                        progress_callback("cache", "Retrieved from cache...", 1.0)
                    except Exception:
                        pass
                conn.close()
                return DecisionResult(**data)
            except Exception:
                pass
        recorder.end_stage("cache_check", status="ok", summary="No cache hit")

    # 2. Ingest and Text Extraction
    if progress_callback:
        try:
            progress_callback("ingest", "Extracting text...", 0.20)
        except Exception:
            pass
    recorder.start_stage("ingest", inputs_summary=f"file: {path.name}, force_ocr: {force_ocr_engine}")
    start_ocr_ns = time.perf_counter_ns()

    if pre_extracted_json:
        raw_text = pre_extracted_json.get("raw_text") or "pre_extracted_invoice"
        ext_method = "pre_extracted_json"
        ocr_conf = 1.0
        page_images = []
        page_count = 1
        needs_vision = False
        per_page_confs = [1.0]
    else:
        try:
            ocr_router = OCRRouter(cfg.ocr)
            raw_text, ext_method, ocr_conf, page_images, needs_vision, per_page_confs = ocr_router.extract_text(
                path, force_engine=force_ocr_engine
            )
            _, page_count = inspect_file(path)
        except Exception as e:
            recorder.end_stage("ingest", status="error", summary=f"Ingest failed: {e}")
            conn.close()
            return DecisionResult(
                request_id=request_id,
                decision=DecisionEnum.NEEDS_REVIEW,
                reason_code=ReasonCodeEnum.UNREADABLE_DOCUMENT,
                confidence=0.05,
                summary=f"Unreadable document: {e}",
                reasoning=[f"Document ingestion failed: {e}"],
                trace=recorder.to_list(),
            )

    ocr_duration_ms = int((time.perf_counter_ns() - start_ocr_ns) / 1_000_000)
    recorder.end_stage(
        "ingest",
        status="ok",
        summary=f"{ext_method}, {page_count} page(s), conf {ocr_conf:.2f}",
        outputs_summary=f"pages: {page_count}, conf: {ocr_conf:.2f}, needs_vision: {needs_vision}",
    )

    # 3. LLM Extraction
    if progress_callback:
        try:
            progress_callback("extraction", "Extracting invoice fields and items...", 0.45)
        except Exception:
            pass
    recorder.start_stage("extraction", inputs_summary=f"mode: {cfg.llm.extraction.input_mode}")
    start_llm_ns = time.perf_counter_ns()
    extractor = Extractor(cfg.llm)
    source = ExtractionSource(
        file_name=path.name,
        file_hash=f_hash,
        extraction_method=ext_method,
        ocr_confidence=round(ocr_conf, 2),
        page_count=page_count,
    )

    in_tokens, out_tokens = 0, 0
    try:
        extracted, in_tokens, out_tokens = extractor.extract(
            raw_text=raw_text,
            source=source,
            page_images=page_images,
            pre_extracted_json=pre_extracted_json,
            needs_vision=needs_vision,
        )
        recorder.end_stage(
            "extraction",
            status="ok",
            summary=f"Extracted {len(extracted.line_items)} lines, doc_type: {extracted.document_type}",
        )
    except PermissionError as pe:
        # Fatal configuration error: missing API key
        recorder.end_stage("extraction", status="error", summary=str(pe))
        conn.close()
        raise pe
    except Exception as e:
        recorder.end_stage("extraction", status="error", summary=str(e))
        conn.close()
        return DecisionResult(
            request_id=request_id,
            decision=DecisionEnum.NEEDS_REVIEW,
            reason_code=ReasonCodeEnum.UNREADABLE_DOCUMENT,
            confidence=0.05,
            summary=f"Extraction failure: {e}",
            reasoning=[f"Failed to parse document text: {e}"],
            trace=recorder.to_list(),
        )

    llm_duration_ms = int((time.perf_counter_ns() - start_llm_ns) / 1_000_000)

    # 4. Vision Fallback Step
    if (
        cfg.ocr.vision_fallback.enabled
        and page_images
        and not pre_extracted_json
        and extracted.source.extraction_method != "vision_llm"
    ):
        missing_triggers = [
            f for f in cfg.ocr.vision_fallback.trigger_on_missing_fields
            if getattr(extracted, f, None) is None or getattr(extracted, f).value is None
        ]
        if missing_triggers or needs_vision:
            recorder.start_stage("vision_fallback", inputs_summary=f"triggered by: {missing_triggers or 'low_ocr_conf'}")
            try:
                v_data, v_in, v_out = extractor.llm_client.extract_from_images(page_images)
                in_tokens += v_in
                out_tokens += v_out
                # Merge missing fields from vision without overwriting confident text values
                for trig in missing_triggers:
                    if trig in v_data and v_data[trig] and v_data[trig].get("value"):
                        setattr(
                            extracted,
                            trig,
                            type(getattr(extracted, trig))(
                                value=v_data[trig]["value"],
                                confidence=float(v_data[trig].get("confidence") or 0.8),
                            ),
                        )
                recorder.end_stage("vision_fallback", status="ok", summary=f"Vision fallback filled: {missing_triggers}")
            except Exception as ve:
                recorder.end_stage("vision_fallback", status="flag", summary=f"Vision fallback failed: {ve}")

    # 5. Manual Overrides (if reviewer provided overrides)
    overridden_fields = set()
    if overrides:
        recorder.start_stage("manual_override", inputs_summary=str(list(overrides.keys())))
        if "fields" in overrides and isinstance(overrides["fields"], dict):
            fields = overrides["fields"]
            if "invoice_number" in fields:
                extracted.invoice_number.value = str(fields["invoice_number"])
                extracted.invoice_number.confidence = 1.0
                overridden_fields.add("invoice_number")
            if "invoice_date" in fields:
                extracted.invoice_date.value = str(fields["invoice_date"])
                extracted.invoice_date.confidence = 1.0
                overridden_fields.add("invoice_date")
            if "grand_total" in fields:
                extracted.grand_total.value = parse_number(fields["grand_total"])
                extracted.grand_total.confidence = 1.0
                overridden_fields.add("grand_total")
            if "vendor_name" in fields:
                extracted.vendor.name = str(fields["vendor_name"])
                extracted.vendor.confidence = 1.0
                overridden_fields.add("vendor_name")
            if "vendor_gstin" in fields:
                extracted.vendor.gstin = str(fields["vendor_gstin"]).strip().upper()
                extracted.vendor.confidence = 1.0
                overridden_fields.add("vendor_gstin")
        recorder.end_stage("manual_override", status="ok", summary=f"Applied overrides on: {list(overridden_fields)}")

    # Recompute missing fields
    new_missing = []
    if not extracted.invoice_number.value:
        new_missing.append("invoice_number")
    if not extracted.invoice_date.value:
        new_missing.append("invoice_date")
    if extracted.grand_total.value is None:
        new_missing.append("grand_total")
    if not extracted.vendor.name and not extracted.vendor.gstin:
        new_missing.append("vendor")
    if not extracted.line_items:
        new_missing.append("line_items")
    extracted.missing_fields = new_missing

    # 6. Grounding Check
    recorder.start_stage("grounding")
    grounding_res = check_grounding(extracted, raw_text, tolerance=cfg.grounding.numeric_tolerance)
    extracted.grounding = grounding_res
    early_review_code: Optional[ReasonCodeEnum] = None
    early_review_msg: Optional[str] = None
    early_messages: List[str] = []

    if cfg.grounding.enabled and grounding_res.failed:
        warn_msg = f"{len(grounding_res.failed)} field(s) failed text grounding verification"
        recorder.end_stage("grounding", status="flag", summary=warn_msg, warnings=grounding_res.failed)
        if cfg.grounding.on_failure == "review":
            early_review_code = ReasonCodeEnum.GROUNDING_FAILED
            early_review_msg = warn_msg
            early_messages.append(warn_msg)
    else:
        recorder.end_stage("grounding", status="ok", summary=f"Checked {grounding_res.checked} values, verified grounded")

    # 7. Completeness & Document Gate
    recorder.start_stage("completeness_gate")
    early_terminal_code: Optional[ReasonCodeEnum] = None
    early_terminal_msg: Optional[str] = None

    if extracted.document_type != "invoice":
        early_review_code = ReasonCodeEnum.UNSUPPORTED_DOCUMENT_TYPE
        early_review_msg = f"Unsupported document type: '{extracted.document_type}'. Only vendor invoices are accepted."
        early_messages.append(early_review_msg)
        recorder.end_stage("completeness_gate", status="flag", summary=early_review_msg)
    elif cfg.validation.block_negative_amounts and (extracted.grand_total.value or 0.0) < 0:
        early_review_code = ReasonCodeEnum.UNSUPPORTED_DOCUMENT_TYPE
        early_review_msg = "Negative invoice totals are not supported on standard vendor invoices."
        early_messages.append(early_review_msg)
        recorder.end_stage("completeness_gate", status="flag", summary=early_review_msg)
    elif extracted.missing_fields:
        early_review_code = ReasonCodeEnum.MISSING_FIELDS
        early_review_msg = f"Missing mandatory field(s): {', '.join(extracted.missing_fields)}"
        early_messages.append(early_review_msg)
        recorder.end_stage("completeness_gate", status="flag", summary=early_review_msg)
    else:
        recorder.end_stage("completeness_gate", status="ok", summary="All mandatory fields present")

    # 8. Normalization
    recorder.start_stage("normalization")
    raw_inv_no = extracted.invoice_number.value
    norm_inv_no = normalize_invoice_number(raw_inv_no)
    iso_date, is_amb_date = parse_date(
        str(extracted.invoice_date.value) if extracted.invoice_date.value else None,
        priority_formats=cfg.normalization.date_formats_priority,
    )
    if iso_date:
        extracted.invoice_date.value = iso_date
    if is_amb_date and cfg.normalization.ambiguous_date_policy == "flag":
        extracted.invoice_date.ambiguous = True

    norm_currency = normalize_currency(extracted.currency.value, cfg.normalization.default_currency)
    extracted.currency.value = norm_currency
    recorder.end_stage("normalization", status="ok", summary=f"Normalized #{norm_inv_no}, date: {iso_date}, curr: {norm_currency}")

    # 9. Vendor Resolution
    recorder.start_stage("vendor_resolution")
    vendor_resolver = VendorResolver(vendor_repo, cfg.vendor)
    v_res = vendor_resolver.resolve(
        gstin=extracted.vendor.gstin,
        raw_name=extracted.vendor.name,
        email=extracted.vendor.email,
    )

    resolved_vendor = v_res.vendor
    if overrides and "vendor_id" in overrides:
        candidate_v = vendor_repo.get_by_id(overrides["vendor_id"])
        if candidate_v:
            resolved_vendor = candidate_v
            v_res.status = "ok" if candidate_v.get("approved", 1) else "not_approved"

    if v_res.status == "not_approved":
        early_terminal_code = ReasonCodeEnum.VENDOR_NOT_APPROVED
        early_terminal_msg = f"Vendor '{resolved_vendor.get('name') if resolved_vendor else ''}' is unapproved."
        early_messages.append(early_terminal_msg)
        recorder.end_stage("vendor_resolution", status="fail", summary=early_terminal_msg)
    elif v_res.status == "unclear" and not early_review_code:
        early_review_code = ReasonCodeEnum.VENDOR_UNCLEAR
        early_review_msg = f"Vendor '{extracted.vendor.name}' is unclear; closest match is {resolved_vendor.get('name') if resolved_vendor else ''}."
        early_messages.append(early_review_msg)
        recorder.end_stage("vendor_resolution", status="flag", summary=early_review_msg)
    else:
        v_name = resolved_vendor.get("name") if resolved_vendor else "Unknown"
        recorder.end_stage("vendor_resolution", status="ok", summary=f"Resolved vendor: {v_name} (conf {v_res.confidence:.2f})")

    # 10. Duplicate Detection
    recorder.start_stage("duplicate_check")
    v_id = resolved_vendor["vendor_id"] if resolved_vendor else None
    dup_code, dup_msg, dup_row = check_duplicates(
        repo=inv_repo,
        vendor_id=v_id,
        invoice_no_raw=raw_inv_no,
        invoice_no_norm=norm_inv_no,
        invoice_date=extracted.invoice_date.value,
        grand_total=extracted.grand_total.value,
        config=cfg.duplicates,
        exclude_invoice_id=target_invoice_id,
    )

    if dup_code == ReasonCodeEnum.DUPLICATE_EXACT:
        early_terminal_code = dup_code
        early_terminal_msg = dup_msg
        early_messages.append(dup_msg or "")
        recorder.end_stage("duplicate_check", status="fail", summary=dup_msg or "")
    elif dup_code == ReasonCodeEnum.DUPLICATE_POSSIBLE and not early_review_code:
        early_review_code = dup_code
        early_review_msg = dup_msg
        early_messages.append(dup_msg or "")
        recorder.end_stage("duplicate_check", status="flag", summary=dup_msg or "")
    else:
        recorder.end_stage("duplicate_check", status="ok", summary="No duplicate found in ledger")

    # 11. PO Matching
    if progress_callback:
        try:
            progress_callback("matching", "Matching purchase orders...", 0.70)
        except Exception:
            pass
    recorder.start_stage("po_matching")
    start_match_ns = time.perf_counter_ns()
    embedder = get_embedder(cfg.embeddings.backend, cfg.embeddings.model_name)
    item_index = InMemoryItemIndex(embedder)
    item_index.build_from_db(conn)

    matching_router = MatchingRouter(conn, cfg.matching, embedder, item_index, exclude_invoice_id=target_invoice_id)
    po_ref_val = overrides.get("po_id") if overrides and "po_id" in overrides else (extracted.po_reference.value if extracted.po_reference else None)

    match_res, match_reason_code, match_msg = matching_router.route_match(
        po_reference=po_ref_val,
        resolved_vendor=resolved_vendor,
        invoice_lines=extracted.line_items,
        invoice_total=float(extracted.grand_total.value or 0.0),
        invoice_date=extracted.invoice_date.value,
        currency=extracted.currency.value or "INR",
    )

    if overrides and "po_id" in overrides:
        match_res.method = MatchMethodEnum.MANUAL
        match_res.selected_po = overrides["po_id"]

    match_duration_ms = int((time.perf_counter_ns() - start_match_ns) / 1_000_000)

    # Backfill vendor ONLY if invoice had zero vendor information (never if it had an unresolvable name/gstin)
    has_invoice_vendor = bool((extracted.vendor.name and extracted.vendor.name.strip()) or (extracted.vendor.gstin and extracted.vendor.gstin.strip()))
    if not resolved_vendor and match_res.selected_po and not has_invoice_vendor:
        selected_po_row = po_repo.get_by_id(match_res.selected_po)
        if selected_po_row:
            resolved_vendor = vendor_repo.get_by_id(selected_po_row["vendor_id"])

    # Update early terminal/review codes from matching
    if match_msg:
        early_messages.append(match_msg)

    if match_reason_code in (
        ReasonCodeEnum.VENDOR_MISMATCH,
        ReasonCodeEnum.PO_CLOSED,
        ReasonCodeEnum.NO_MATCHING_PO,
    ):
        if not early_terminal_code:
            early_terminal_code = match_reason_code
            early_terminal_msg = match_msg
    elif match_reason_code in (ReasonCodeEnum.INVALID_PO_REF, ReasonCodeEnum.AMBIGUOUS_PO):
        if not early_review_code:
            early_review_code = match_reason_code
            early_review_msg = match_msg

    recorder.end_stage(
        "po_matching",
        status="ok" if not match_reason_code else "flag",
        summary=f"Tier {match_res.tier}, method {match_res.method.value if match_res.method else 'none'}, selected: {match_res.selected_po}",
    )

    # 12. PO Balance Summary & Validation Rules
    recorder.start_stage("validation")
    start_val_ns = time.perf_counter_ns()
    po_balance_summary: Optional[POBalanceSummary] = None

    po_data = po_repo.get_by_id(match_res.selected_po) if match_res.selected_po else None
    po_items = (
        item_repo.list_by_po(
            match_res.selected_po,
            exclude_invoice_id=target_invoice_id,
            include_pending=cfg.validation.reserve_pending_invoices,
        )
        if match_res.selected_po
        else []
    )
    consumed = (
        inv_repo.get_po_consumed_amount(
            match_res.selected_po,
            include_pending=cfg.validation.reserve_pending_invoices,
            exclude_invoice_id=target_invoice_id,
        )
        if match_res.selected_po
        else 0.0
    )

    if po_data:
        p_total = float(po_data["total"])
        this_inv_total = float(extracted.grand_total.value or 0.0)
        rem_after = p_total - (consumed + this_inv_total)
        overage = this_inv_total - max(0.0, p_total - consumed)
        var_pct = (overage / max(1.0, p_total - consumed)) * 100.0 if overage > 0 else 0.0

        po_balance_summary = POBalanceSummary(
            po_id=match_res.selected_po,
            po_total=p_total,
            previously_billed=consumed,
            reserved_pending=0.0,
            this_invoice=this_inv_total,
            remaining_after=round(rem_after, 2),
            variance_pct=round(var_pct, 2),
            currency=po_data.get("currency") or "INR",
        )

    chosen_candidate = next((c for c in match_res.candidates if c.po_id == match_res.selected_po), None)
    line_matches = chosen_candidate.line_matches if chosen_candidate else []

    val_ctx = ValidationContext(
        config=cfg.validation,
        extracted_invoice=extracted,
        po_data=po_data,
        po_items=po_items,
        consumed_balance=consumed,
        vendor_data=resolved_vendor,
        line_matches=line_matches,
        as_of_date=as_of_date,
    )

    val_engine = ValidationEngine()
    rule_results = val_engine.run(val_ctx)
    val_duration_ms = int((time.perf_counter_ns() - start_val_ns) / 1_000_000)

    num_fails = sum(1 for r in rule_results if r.status == RuleStatusEnum.FAIL)
    num_flags = sum(1 for r in rule_results if r.status == RuleStatusEnum.FLAG)
    num_warns = sum(1 for r in rule_results if r.status == RuleStatusEnum.WARN)
    recorder.end_stage(
        "validation",
        status="fail" if num_fails > 0 else ("flag" if num_flags > 0 else "ok"),
        summary=f"Ran {len(rule_results)} rules: {num_fails} fail, {num_flags} flag, {num_warns} warn",
    )

    # 13. Aggregate Decision
    recorder.start_stage("decision")
    decision, reason_code, review_req = aggregate_decision(
        early_terminal_code=early_terminal_code,
        early_terminal_msg=early_terminal_msg,
        early_review_code=early_review_code,
        early_review_msg=early_review_msg,
        match_result=match_res,
        rule_results=rule_results,
        config=cfg,
    )

    extracted_confs = [
        extracted.invoice_number.confidence,
        extracted.invoice_date.confidence,
        extracted.grand_total.confidence,
    ]
    confidence_score, conf_formula = compute_confidence(extracted_confs, match_res, rule_results)
    recorder.end_stage("decision", status="ok", summary=f"{decision.value} ({reason_code.value}), conf {confidence_score:.2f}")

    # 14. Explanation
    if progress_callback:
        try:
            progress_callback("explanation", "Validating rules & generating AP reasoning...", 0.90)
        except Exception:
            pass
    recorder.start_stage("explanation")
    v_display_name = resolved_vendor.get("name") if resolved_vendor else (extracted.vendor.name or None)
    summary_text, reasoning_list, exp_in, exp_out = build_explanation(
        decision=decision,
        reason_code=reason_code,
        match_result=match_res,
        rule_results=rule_results,
        po_balance=po_balance_summary,
        vendor_name=v_display_name,
        early_messages=early_messages,
        confidence_formula=conf_formula,
        extracted_invoice=extracted,
        po_dict=po_data,
        po_items=po_items,
        llm_client=extractor.llm_client if extractor else None,
        use_llm_polish=cfg.llm.explanation.use_llm_polish,
        vendor_dict=resolved_vendor,
    )
    in_tokens += exp_in
    out_tokens += exp_out
    recorder.end_stage("explanation", status="ok", summary=f"Explanation generated ({'LLM' if exp_in > 0 else 'template'})")

    total_duration_ms = int((time.perf_counter_ns() - start_total_ns) / 1_000_000)
    timings = Timings(
        total=total_duration_ms,
        ocr=ocr_duration_ms,
        llm=llm_duration_ms,
        matching=match_duration_ms,
        validation=val_duration_ms,
    )
    cost = CostSummary(llm_input_tokens=in_tokens, llm_output_tokens=out_tokens)

    # Strip raw_text before constructing public/persisted DecisionResult
    safe_extracted = copy.deepcopy(extracted)
    safe_extracted.raw_text = None

    f_path_str = str(path.resolve()) if path.exists() and path.is_file() else str(path)
    f_name_str = path.name

    decision_result = DecisionResult(
        invoice_id=target_invoice_id,
        vendor_id=resolved_vendor.get("vendor_id") if resolved_vendor else None,
        vendor_name=resolved_vendor.get("name") if resolved_vendor else (safe_extracted.vendor.name if safe_extracted and safe_extracted.vendor else None),
        file_name=f_name_str,
        file_path=f_path_str,
        request_id=request_id,
        decision=decision,
        reason_code=reason_code,
        confidence=confidence_score,
        summary=summary_text,
        reasoning=reasoning_list,
        extracted=safe_extracted,
        match=match_res,
        po_balance=po_balance_summary,
        checks=rule_results,
        review=review_req,
        trace=recorder.to_list(),
        timings_ms=timings,
        cost=cost,
        cached=False,
    )

    # 15. Persistence with IMMEDIATE lock and rollback safety
    if not dry_run:
        recorder.start_stage("persistence")
        try:
            with transaction(conn, mode="IMMEDIATE"):
                if decision == DecisionEnum.APPROVED and match_res.selected_po:
                    # Concurrency safety: atomic re-check of balance and quantities
                    fresh_consumed = inv_repo.get_po_consumed_amount(
                        match_res.selected_po,
                        include_pending=cfg.validation.reserve_pending_invoices,
                        exclude_invoice_id=target_invoice_id,
                    )
                    po_row = po_repo.get_by_id(match_res.selected_po)
                    inv_total = extracted.grand_total.value or 0.0
                    po_total = float(po_row["total"]) if po_row else 0.0
                    rem_bal = po_total - fresh_consumed

                    if rem_bal <= 0.01:
                        decision = DecisionEnum.REJECTED
                        decision_code = ReasonCodeEnum.PO_CLOSED
                        decision_result.decision = decision
                        decision_result.reason_code = decision_code
                        decision_result.summary = f"PO {match_res.selected_po} has zero remaining balance ({rem_bal:.2f})"
                        decision_result.reasoning.append(
                            f"[CONCURRENCY CHECK] PO balance exhausted by prior transaction (remaining: {rem_bal:.2f})"
                        )
                    auto_limit = rem_bal * (1.0 + cfg.validation.tolerance_auto_pct / 100.0)
                    review_limit = rem_bal * (1.0 + cfg.validation.tolerance_review_pct / 100.0)
                    if inv_total > auto_limit + cfg.validation.rounding_tolerance:
                        decision = (
                            DecisionEnum.REJECTED
                            if inv_total > review_limit
                            else DecisionEnum.NEEDS_REVIEW
                        )
                        decision_code = ReasonCodeEnum.OVERBILLED
                        decision_result.decision = decision
                        decision_result.reason_code = decision_code
                        decision_result.summary = f"Invoice total ({inv_total}) exceeds remaining balance ({rem_bal:.2f})"
                        decision_result.reasoning.append(
                            f"[CONCURRENCY CHECK] Exceeded remaining balance ({rem_bal:.2f})"
                        )

                    fresh_items = {it["row_id"]: it for it in item_repo.list_by_po(match_res.selected_po)}
                    for l in extracted.line_items:
                        lm = next((m for m in line_matches if m.invoice_line_no == l.line_no), None)
                        if lm and lm.po_item_row_id and l.quantity is not None:
                            fresh_it = fresh_items.get(lm.po_item_row_id)
                            if fresh_it and l.quantity > float(fresh_it["qty_remaining"]):
                                decision = (
                                    DecisionEnum.NEEDS_REVIEW
                                    if cfg.validation.qty_over_remaining_policy == "review"
                                    else DecisionEnum.REJECTED
                                )
                                decision_code = ReasonCodeEnum.QTY_EXCEEDS_REMAINING
                                decision_result.decision = decision
                                decision_result.reason_code = decision_code
                                decision_result.summary = f"Invoiced qty ({l.quantity}) exceeds remaining ({fresh_it['qty_remaining']})"
                                decision_result.reasoning.append(
                                    f"[CONCURRENCY CHECK] Line '{l.description}' exceeds remaining quantity ({fresh_it['qty_remaining']})"
                                )
                                break

                db_status = (
                    "APPROVED"
                    if decision == DecisionEnum.APPROVED
                    else ("PENDING_REVIEW" if decision == DecisionEnum.NEEDS_REVIEW else "REJECTED")
                )

                if target_invoice_id:
                    # Update in place
                    inv_id = target_invoice_id
                    inv_repo.update_invoice(
                        invoice_id=inv_id,
                        status=db_status,
                        decision_json=decision_result.model_dump_json(),
                        po_id=match_res.selected_po,
                        match_method=match_res.method.value if match_res.method else None,
                        clear_override=True,
                    )
                    inv_repo.delete_lines(inv_id)
                else:
                    inv_id = inv_repo.create(
                        vendor_id=resolved_vendor.get("vendor_id") if resolved_vendor else None,
                        invoice_no_raw=raw_inv_no,
                        invoice_no_norm=norm_inv_no,
                        invoice_date=extracted.invoice_date.value,
                        total=extracted.grand_total.value,
                        currency=extracted.currency.value,
                        po_id=match_res.selected_po,
                        match_method=match_res.method.value if match_res.method else None,
                        status=db_status,
                        decision_json=decision_result.model_dump_json(),
                        file_hash=f_hash if f_hash else None,
                        file_name=f_name_str,
                        file_path=f_path_str,
                    )

                for l in extracted.line_items:
                    lm = next((m for m in line_matches if m.invoice_line_no == l.line_no), None)
                    po_item_row_id = lm.po_item_row_id if lm else None
                    inv_repo.add_line(
                        invoice_id=inv_id,
                        po_item_row_id=po_item_row_id,
                        description=l.description,
                        quantity=l.quantity,
                        unit_price=l.unit_price,
                        line_total=l.line_total,
                    )

                    if po_item_row_id and l.quantity is not None and (
                        decision == DecisionEnum.APPROVED
                        or (decision == DecisionEnum.NEEDS_REVIEW and cfg.validation.reserve_pending_invoices)
                    ):
                        item_repo.decrement_qty(po_item_row_id, l.quantity)

                if match_res.selected_po and decision == DecisionEnum.APPROVED:
                    all_items = item_repo.list_by_po(match_res.selected_po)
                    consumed_after = inv_repo.get_po_consumed_amount(match_res.selected_po, include_pending=True)
                    po_row = po_repo.get_by_id(match_res.selected_po)
                    is_zero_balance = po_row and (float(po_row["total"]) - consumed_after <= 0.01)
                    all_qty_zero = all(float(it["qty_remaining"]) <= 0 for it in all_items)

                    if is_zero_balance or all_qty_zero:
                        po_repo.update_status(match_res.selected_po, "CLOSED")
                    else:
                        po_repo.update_status(match_res.selected_po, "PARTIAL")

                for entry in recorder.to_list():
                    audit_repo.log(
                        invoice_id=inv_id,
                        stage=entry.stage,
                        status=entry.status,
                        detail_json=json.dumps({"summary": entry.summary, "warnings": entry.warnings}),
                        duration_ms=entry.duration_ms,
                    )

                decision_result.invoice_id = inv_id
            recorder.end_stage("persistence", status="ok", summary=f"Persisted to ledger (ID: {inv_id})")
        except Exception as e:
            recorder.end_stage("persistence", status="error", summary=f"Persistence error: {e}")
            conn.close()
            raise RuntimeError(f"Database transaction failure: {e}")
        finally:
            conn.close()
    else:
        conn.close()

    if progress_callback:
        try:
            progress_callback("complete", "Finalizing decision...", 1.0)
        except Exception:
            pass

    return decision_result


def resolve_invoice(
    invoice_id: int,
    action: str,
    overrides: Optional[Dict[str, Any]] = None,
    config: Optional[PipelineConfig] = None,
    note: Optional[str] = None,
) -> DecisionResult:
    """
    Applies human reviewer action to resolve a PENDING_REVIEW invoice in place without self-duplicate collisions.
    Supports 'approve'/'force_approve', 'reject', 'undo'/'revert', and 'select_po'.
    """
    cfg = config or load_config()
    conn = get_connection(cfg.app.db_path)
    inv_repo = InvoiceRepo(conn)
    item_repo = ItemRepo(conn)

    row = inv_repo.get_by_id(invoice_id)
    if not row:
        conn.close()
        raise ValueError(f"Invoice #{invoice_id} not found")

    decision_json = row.get("decision_json")
    if not decision_json:
        conn.close()
        raise ValueError("Cannot resolve invoice without prior decision trace")

    prev_dec = json.loads(decision_json)
    pre_ext = prev_dec.get("extracted")

    if action in ("approve", "force_approve"):
        with transaction(conn, mode="IMMEDIATE"):
            prev_status = row.get("status", "")
            if prev_status == "REJECTED":
                lines = inv_repo.get_lines(invoice_id)
                for l in lines:
                    if l.get("po_item_row_id") and l.get("quantity"):
                        item_repo.decrement_qty(l["po_item_row_id"], float(l["quantity"]))

            if not prev_dec.get("original_decision"):
                prev_dec["original_decision"] = prev_dec.get("decision", "NEEDS_REVIEW")
            if not prev_dec.get("original_reason_code"):
                prev_dec["original_reason_code"] = prev_dec.get("reason_code", "REVIEW_REQUIRED")

            prev_dec["decision"] = "APPROVED"
            prev_dec["is_manual_override"] = True
            prev_dec["override_action"] = "approve"
            prev_dec["override_note"] = note
            prev_dec["review"] = {"required": False, "actions": []}
            note_str = f" Note: {note}" if note else ""
            prev_dec.setdefault("reasoning", []).append(
                {"status": "INFO", "text": f"[MANUAL OVERRIDE] Approved by reviewer.{note_str}"}
            )
            prev_dec["invoice_id"] = invoice_id
            new_json = json.dumps(prev_dec)
            inv_repo.update_invoice(
                invoice_id=invoice_id,
                status="APPROVED",
                decision_json=new_json,
                is_manual_override=1,
                override_note=note,
            )

            selected_po = row.get("po_id") or (prev_dec.get("match") or {}).get("selected_po")
            if selected_po:
                po_repo = PORepo(conn)
                all_items = item_repo.list_by_po(selected_po)
                consumed_after = inv_repo.get_po_consumed_amount(selected_po, include_pending=True)
                po_row = po_repo.get_by_id(selected_po)
                is_zero_balance = po_row and (float(po_row["total"]) - consumed_after <= 0.01)
                all_qty_zero = all_items and all(float(it["qty_remaining"]) <= 0 for it in all_items)
                if is_zero_balance or all_qty_zero:
                    po_repo.update_status(selected_po, "CLOSED")
                else:
                    po_repo.update_status(selected_po, "PARTIAL")

        conn.close()
        return DecisionResult(**prev_dec)

    elif action == "reject":
        with transaction(conn, mode="IMMEDIATE"):
            prev_status = row.get("status", "")
            if prev_status != "REJECTED":
                lines = inv_repo.get_lines(invoice_id)
                for l in lines:
                    if l.get("po_item_row_id") and l.get("quantity"):
                        item_repo.restore_qty(l["po_item_row_id"], float(l["quantity"]))

            if not prev_dec.get("original_decision"):
                prev_dec["original_decision"] = prev_dec.get("decision", "NEEDS_REVIEW")
            if not prev_dec.get("original_reason_code"):
                prev_dec["original_reason_code"] = prev_dec.get("reason_code", "REVIEW_REQUIRED")

            prev_dec["decision"] = "REJECTED"
            prev_dec["is_manual_override"] = True
            prev_dec["override_action"] = "reject"
            prev_dec["override_note"] = note
            prev_dec["review"] = {"required": False, "actions": []}
            note_str = f" Note: {note}" if note else ""
            prev_dec.setdefault("reasoning", []).append(
                {"status": "INFO", "text": f"[MANUAL OVERRIDE] Rejected by reviewer.{note_str}"}
            )
            prev_dec["invoice_id"] = invoice_id
            new_json = json.dumps(prev_dec)
            inv_repo.update_invoice(
                invoice_id=invoice_id,
                status="REJECTED",
                decision_json=new_json,
                is_manual_override=1,
                override_note=note,
            )

            selected_po = row.get("po_id") or (prev_dec.get("match") or {}).get("selected_po")
            if selected_po:
                po_repo = PORepo(conn)
                po_repo.update_status(selected_po, "PARTIAL")

        conn.close()
        return DecisionResult(**prev_dec)

    elif action in ("undo", "revert"):
        with transaction(conn, mode="IMMEDIATE"):
            prev_status = row.get("status", "")
            if prev_status == "REJECTED" and cfg.validation.reserve_pending_invoices:
                lines = inv_repo.get_lines(invoice_id)
                for l in lines:
                    if l.get("po_item_row_id") and l.get("quantity"):
                        item_repo.decrement_qty(l["po_item_row_id"], float(l["quantity"]))

            orig_dec = prev_dec.get("original_decision", "NEEDS_REVIEW")
            orig_rc = prev_dec.get("original_reason_code", "REVIEW_REQUIRED")

            prev_dec["decision"] = orig_dec
            prev_dec["reason_code"] = orig_rc
            prev_dec["is_manual_override"] = False
            prev_dec["override_action"] = None
            prev_dec["override_note"] = None
            prev_dec["review"] = {
                "required": True,
                "actions": [{"type": "select_po", "options": []}],
            }
            prev_dec.setdefault("reasoning", []).append(
                {"status": "INFO", "text": "[MANUAL OVERRIDE] Override undone by reviewer - restored to pending review."}
            )
            prev_dec["invoice_id"] = invoice_id
            new_json = json.dumps(prev_dec)
            inv_repo.update_invoice(
                invoice_id=invoice_id,
                status="PENDING_REVIEW",
                decision_json=new_json,
                clear_override=True,
            )
        conn.close()
        return DecisionResult(**prev_dec)

    # Re-run pipeline targeting the existing invoice row
    conn.close()
    return process_invoice(
        file_path=Path("re-resolve"),
        config=cfg,
        overrides=overrides,
        dry_run=False,
        pre_extracted_json=pre_ext,
        target_invoice_id=invoice_id,
    )


def process_invoice_batch(
    file_paths: list[str | Path],
    config: Optional[PipelineConfig] = None,
    dry_run: bool = False,
    force_ocr_engine: Optional[str] = None,
    as_of_date: Optional[datetime.date] = None,
    batch_callback: Optional[Callable[[dict], None]] = None,
) -> BatchProcessResult:
    """
    Processes a list of invoice files sequentially one-by-one.
    Catches per-file errors to guarantee fault-isolation across the batch.
    Aggregates batch stats (approved, review required, rejected, failed, average confidence).
    """
    cfg = config or load_config()
    batch_id = str(uuid.uuid4())
    start_total_ns = time.perf_counter_ns()

    items: list[BatchItemResult] = []
    approved_count = 0
    needs_review_count = 0
    rejected_count = 0
    failed_count = 0
    confidence_sum = 0.0

    for idx, fp in enumerate(file_paths):
        path = Path(fp)
        file_name = path.name
        file_size = path.stat().st_size if path.exists() and path.is_file() else 0
        item_start_ns = time.perf_counter_ns()
        processed_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if batch_callback:
            try:
                batch_callback({
                    "type": "file_start",
                    "file_index": idx,
                    "total_files": len(file_paths),
                    "file_name": file_name,
                    "file_size_bytes": file_size,
                })
            except Exception:
                pass

        def _item_stage_cb(stage: str, msg: str, pct: float):
            if batch_callback:
                try:
                    overall = round(((idx + pct) / len(file_paths)) * 100, 1)
                    batch_callback({
                        "type": "file_progress",
                        "file_index": idx,
                        "total_files": len(file_paths),
                        "file_name": file_name,
                        "stage": stage,
                        "message": msg,
                        "file_pct": pct,
                        "overall_pct": overall,
                    })
                except Exception:
                    pass

        try:
            res = process_invoice(
                file_path=path,
                config=cfg,
                dry_run=dry_run,
                force_ocr_engine=force_ocr_engine,
                as_of_date=as_of_date,
                progress_callback=_item_stage_cb,
            )
            item_duration_ms = (time.perf_counter_ns() - item_start_ns) // 1_000_000

            inv_no = res.extracted.invoice_number.value if res.extracted and res.extracted.invoice_number else None
            vendor_id = res.vendor_id or (res.extracted.vendor.gstin if res.extracted and res.extracted.vendor else None)
            vendor_name = (
                res.vendor_name
                or (res.extracted.vendor.name if res.extracted and res.extracted.vendor else None)
                or (res.vendor_id if res.vendor_id else "Unknown")
            )
            total_val = res.extracted.grand_total.value if res.extracted and res.extracted.grand_total else None
            curr_val = res.extracted.currency.value if res.extracted and res.extracted.currency else None

            if res.decision == DecisionEnum.APPROVED:
                approved_count += 1
            elif res.decision == DecisionEnum.NEEDS_REVIEW:
                needs_review_count += 1
            elif res.decision == DecisionEnum.REJECTED:
                rejected_count += 1

            confidence_sum += float(res.confidence)

            item_result = BatchItemResult(
                file_name=file_name,
                file_path=str(path.resolve()) if path.exists() else str(path),
                file_size_bytes=file_size,
                status="SUCCESS",
                invoice_id=res.invoice_id,
                invoice_no=inv_no,
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                total=total_val,
                currency=curr_val,
                decision=res.decision,
                reason_code=res.reason_code,
                confidence=round(float(res.confidence), 4),
                summary=res.summary,
                duration_ms=item_duration_ms,
                processed_at=processed_ts,
                result=res,
            )
            items.append(item_result)

            if batch_callback:
                try:
                    valid_cnt = approved_count + needs_review_count + rejected_count
                    cur_avg_conf = round(confidence_sum / valid_cnt, 4) if valid_cnt > 0 else 0.0
                    batch_callback({
                        "type": "file_done",
                        "file_index": idx,
                        "total_files": len(file_paths),
                        "file_name": file_name,
                        "item": item_result.model_dump(mode="json"),
                        "stats": {
                            "total_files": len(file_paths),
                            "processed_count": len(items),
                            "approved_count": approved_count,
                            "needs_review_count": needs_review_count,
                            "rejected_count": rejected_count,
                            "failed_count": failed_count,
                            "avg_confidence": cur_avg_conf,
                        },
                    })
                except Exception:
                    pass

        except Exception as e:
            item_duration_ms = (time.perf_counter_ns() - item_start_ns) // 1_000_000
            failed_count += 1
            item_result = BatchItemResult(
                file_name=file_name,
                file_path=str(path.resolve()) if path.exists() else str(path),
                file_size_bytes=file_size,
                status="FAILED",
                error_message=str(e),
                duration_ms=item_duration_ms,
                processed_at=processed_ts,
            )
            items.append(item_result)

            if batch_callback:
                try:
                    valid_cnt = approved_count + needs_review_count + rejected_count
                    cur_avg_conf = round(confidence_sum / valid_cnt, 4) if valid_cnt > 0 else 0.0
                    batch_callback({
                        "type": "file_done",
                        "file_index": idx,
                        "total_files": len(file_paths),
                        "file_name": file_name,
                        "item": item_result.model_dump(mode="json"),
                        "stats": {
                            "total_files": len(file_paths),
                            "processed_count": len(items),
                            "approved_count": approved_count,
                            "needs_review_count": needs_review_count,
                            "rejected_count": rejected_count,
                            "failed_count": failed_count,
                            "avg_confidence": cur_avg_conf,
                        },
                    })
                except Exception:
                    pass

    total_duration_ms = (time.perf_counter_ns() - start_total_ns) // 1_000_000
    valid_decisions_count = approved_count + needs_review_count + rejected_count
    avg_conf = round(confidence_sum / valid_decisions_count, 4) if valid_decisions_count > 0 else 0.0

    batch_res = BatchProcessResult(
        batch_id=batch_id,
        total_files=len(file_paths),
        processed_count=len(items),
        approved_count=approved_count,
        needs_review_count=needs_review_count,
        rejected_count=rejected_count,
        failed_count=failed_count,
        avg_confidence=avg_conf,
        total_duration_ms=total_duration_ms,
        items=items,
    )

    if batch_callback:
        try:
            batch_callback({
                "type": "batch_done",
                "batch": batch_res.model_dump(mode="json"),
            })
        except Exception:
            pass

    return batch_res

