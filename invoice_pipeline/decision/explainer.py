from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple
from invoice_pipeline.models import (
    DecisionEnum,
    MatchResult,
    POBalanceSummary,
    ReasonCodeEnum,
    ReasoningFactor,
    RuleResult,
    RuleStatusEnum,
)

REASONING_SYSTEM_PROMPT = """You are an expert Accounts Payable (AP) auditor explaining an automated invoice decision to a human business reviewer or buyer.

YOUR OBJECTIVE:
Explain clearly and concisely WHY this invoice was APPROVED, sent for human review (NEEDS_REVIEW), or REJECTED.

CRITICAL TONE & AUDIENCE RULES:
1. Speak in plain, everyday business language that any non-technical user can immediately understand.
2. STRICTLY NO TECHNICAL OR STATISTICAL JARGON:
   - NEVER use technical jargon such as "heuristic score", "min_field_conf", "Tier-1 explicit", "Tier-2 cosine similarity", "vector embedding", "deterministic formula", "Levenshtein", "regex match", "PARSE_DECLTYPES", or similar system internals.
3. USE DIRECT, HUMAN REASONING EXPLANATIONS:
   - "Vendors are matching, but the billed line items were not found on the purchase order."
   - "Vendor names and tax IDs (GSTIN) do not match our approved vendor records."
   - "The quantity billed on the invoice exceeds the quantity remaining on the purchase order."
   - "The unit price on the invoice is higher than the price agreed upon in the purchase order."
   - "All prices, quantities, and items match the purchase order exactly, and sufficient budget headroom is available."
   - "This is a valid partial milestone invoice covering X% of the purchase order commitment."
   - "The invoice is dated before the purchase order was issued, so manual verification is required."
   - "Multiple purchase orders are open for this vendor; a reviewer needs to select the correct order."
4. STRUCTURE:
   - summary: A crisp 1-2 sentence executive overview explaining why this decision was taken.
   - reasoning: 3 to 5 concise, high-value bullet points:
     * Bullet 1: Vendor verification (state clearly if vendor matches the purchase order, including GSTIN verification). If vendor_matched is true, confirm vendor alignment; do NOT report a mismatch based on internal vendor codes like 'V-STAT'.
     * Bullet 2: Line items and prices (items match/mismatch, price alignment or price drift).
     * Bullet 3: Quantities and PO balance (within remaining quantities, partial milestone draw, or budget overrun). If is_partial_draw is true, recognize this as a valid partial milestone claim within budget headroom; do NOT report that the invoice total mismatches the PO total.
     * Bullet 4: Timeline and policy checks (dates, tax rates, arithmetic, or duplicate status).
5. STRICT INTEGRITY:
   - NEVER contradict or change the provided decision (APPROVED, NEEDS_REVIEW, REJECTED).
   - Only state facts supported by the input data; do NOT hallucinate fictional transactions or numbers.

Format your output strictly as a JSON object:
{
  "summary": "1-2 sentence plain-language summary of why this decision was taken.",
  "reasoning": [
    {
      "status": "PASSED | FLAGGED | REJECTED | INFO",
      "text": "Plain-language bullet explaining this specific audit factor."
    }
  ]
}

CRITICAL RULES FOR "status":
- "PASSED": The factor was verified successfully and aligns with procurement rules (e.g. vendor entity matched, prices match PO, balance is fully covered without overspend).
- "FLAGGED": The factor requires human review, has a soft discrepancy, or is missing a required date/field (e.g. missing invoice date, ambiguous PO match, price drift).
- "REJECTED": The factor violates a strict rule and directly justifies rejecting the invoice (e.g. unapproved vendor, duplicate invoice, exceeded remaining quantity/headroom, closed PO).
- "INFO": Neutral informational context.
"""


def generate_llm_reasoning(
    decision: DecisionEnum,
    reason_code: ReasonCodeEnum,
    match_result: MatchResult,
    rule_results: List[RuleResult],
    po_balance: Optional[POBalanceSummary] = None,
    vendor_name: Optional[str] = None,
    extracted_invoice: Optional[Any] = None,
    po_dict: Optional[dict] = None,
    po_items: Optional[List[dict]] = None,
    early_messages: Optional[List[str]] = None,
    llm_client: Optional[Any] = None,
    vendor_dict: Optional[dict] = None,
) -> Optional[Tuple[str, List[str], int, int]]:
    """
    Invokes the LLM with structured pipeline audit findings to produce
    plain-language, jargon-free business reasoning explaining why the decision was taken.
    Returns (summary, reasoning_list, in_tokens, out_tokens) or None if LLM is unavailable/fails.
    """
    if not llm_client:
        return None

    # Resolve PO vendor name and GSTIN
    po_vendor_id = po_dict.get("vendor_id") if po_dict else None
    po_vendor_name = None
    po_vendor_gstin = None
    if vendor_dict and po_dict:
        if vendor_dict.get("vendor_id") == po_vendor_id or not po_vendor_id:
            po_vendor_name = vendor_dict.get("name")
            po_vendor_gstin = vendor_dict.get("gstin")
    if not po_vendor_name and po_dict:
        po_vendor_name = po_dict.get("vendor_name") or po_dict.get("vendor_id")

    invoice_v_name = vendor_name or (extracted_invoice.vendor.name if extracted_invoice and extracted_invoice.vendor else "Unknown")
    invoice_v_gstin = extracted_invoice.vendor.gstin if extracted_invoice and extracted_invoice.vendor else None

    # Determine vendor match status
    is_vendor_matched = False
    if po_dict:
        if vendor_dict and vendor_dict.get("vendor_id") == po_vendor_id:
            is_vendor_matched = True
        elif po_vendor_name and invoice_v_name and (po_vendor_name.lower().strip() == invoice_v_name.lower().strip()):
            is_vendor_matched = True

    # Build structured factual context for LLM
    context: dict[str, Any] = {
        "decision": decision.value,
        "reason_code": reason_code.value,
        "vendor": {
            "invoice_vendor_name": invoice_v_name,
            "invoice_gstin": invoice_v_gstin,
            "po_vendor_name": po_vendor_name,
            "po_vendor_gstin": po_vendor_gstin,
            "po_vendor_id": po_vendor_id,
            "vendor_matched": is_vendor_matched,
            "vendor_match_status": "EXACT_MATCH" if is_vendor_matched else ("MISMATCH" if po_dict else "NO_PO"),
        },
    }

    if extracted_invoice:
        context["invoice"] = {
            "invoice_number": extracted_invoice.invoice_number.value if extracted_invoice.invoice_number else None,
            "invoice_date": extracted_invoice.invoice_date.value if extracted_invoice.invoice_date else None,
            "grand_total": extracted_invoice.grand_total.value if extracted_invoice.grand_total else None,
            "currency": extracted_invoice.currency.value if extracted_invoice.currency else "INR",
            "line_items": [
                {
                    "description": it.description,
                    "quantity": it.quantity,
                    "unit_price": it.unit_price,
                    "line_total": it.line_total,
                }
                for it in (extracted_invoice.line_items or [])
            ],
        }

    if po_dict:
        context["purchase_order"] = {
            "po_id": po_dict.get("po_id"),
            "po_date": str(po_dict.get("po_date")),
            "po_total": po_dict.get("total"),
            "currency": po_dict.get("currency", "INR"),
            "items": [
                {
                    "item_name": pi.get("item_name"),
                    "qty_ordered": pi.get("qty_ordered"),
                    "qty_remaining": pi.get("qty_remaining"),
                    "unit_price": pi.get("unit_price"),
                }
                for pi in (po_items or [])
            ],
        }

    if match_result and match_result.candidates:
        context["candidate_purchase_orders"] = [
            {
                "po_id": c.po_id,
                "score_pct": f"{int(c.score * 100)}%",
                "notes": c.notes,
            }
            for c in match_result.candidates
        ]

    if po_balance:
        po_tot = max(0.01, po_balance.po_total)
        cov_pct = round((po_balance.this_invoice / po_tot) * 100.0, 1)
        is_partial = po_balance.this_invoice < (po_balance.po_total - 0.01)
        is_full = abs(po_balance.this_invoice - po_balance.po_total) <= 0.01

        context["po_balance"] = {
            "po_total": po_balance.po_total,
            "previously_billed": po_balance.previously_billed,
            "this_invoice": po_balance.this_invoice,
            "remaining_after": po_balance.remaining_after,
            "is_overspent": po_balance.remaining_after < 0,
            "fulfillment": {
                "is_partial_draw": is_partial,
                "is_full_fulfillment": is_full,
                "coverage_pct": f"{cov_pct}%",
                "notes": (
                    f"Valid partial/milestone claim drawing {cov_pct}% of the total PO commitment"
                    if is_partial
                    else "Full fulfillment claim covering 100% of PO commitment"
                ),
            },
        }

    notable_checks = [
        {"rule": r.rule, "status": r.status.value, "severity": r.severity.value, "message": r.message}
        for r in rule_results
        if r.status in (RuleStatusEnum.FAIL, RuleStatusEnum.FLAG, RuleStatusEnum.WARN)
    ]
    if notable_checks:
        context["rule_exceptions"] = notable_checks

    if early_messages:
        context["system_notices"] = [m for m in early_messages if m]

    user_prompt = (
        "Here are the accounts payable audit findings for this invoice:\n\n"
        f"{json.dumps(context, indent=2)}\n\n"
        "Explain to the reviewer in plain, non-technical business language why this decision was taken. "
        "Highlight vendor match, line item agreement, quantities, and budget headroom clearly."
    )

    try:
        data, in_tok, out_tok = llm_client.generate_json(REASONING_SYSTEM_PROMPT, user_prompt)
        summary = data.get("summary")
        reasoning_raw = data.get("reasoning")
        if summary and isinstance(reasoning_raw, list) and len(reasoning_raw) > 0:
            cleaned_factors: List[ReasoningFactor] = []
            for item in reasoning_raw:
                if isinstance(item, dict):
                    st = str(item.get("status", "INFO")).upper().strip()
                    if st not in ("PASSED", "FLAGGED", "REJECTED", "INFO"):
                        st = "INFO"
                    tx = str(item.get("text", "")).strip()
                    if tx:
                        cleaned_factors.append(ReasoningFactor(status=st, text=tx))
                elif isinstance(item, str) and item.strip():
                    cleaned_factors.append(ReasoningFactor(status="INFO", text=item.strip()))
            if cleaned_factors:
                return str(summary).strip(), cleaned_factors, in_tok, out_tok
    except Exception:
        # LLM failure must NEVER crash the pipeline; fallback to template reasoning
        pass

    return None


def build_explanation(
    decision: DecisionEnum,
    reason_code: ReasonCodeEnum,
    match_result: MatchResult,
    rule_results: List[RuleResult],
    po_balance: Optional[POBalanceSummary] = None,
    vendor_name: Optional[str] = None,
    early_messages: Optional[List[str]] = None,
    confidence_formula: Optional[str] = None,
    extracted_invoice: Optional[Any] = None,
    po_dict: Optional[dict] = None,
    po_items: Optional[List[dict]] = None,
    llm_client: Optional[Any] = None,
    use_llm_polish: bool = False,
    vendor_dict: Optional[dict] = None,
) -> tuple[str, List[str], int, int]:
    """Generates structured human-readable summary and bulleted reasoning points with full provenance."""
    # 1. Attempt LLM plain-language reasoning if enabled
    if use_llm_polish and llm_client:
        llm_res = generate_llm_reasoning(
            decision=decision,
            reason_code=reason_code,
            match_result=match_result,
            rule_results=rule_results,
            po_balance=po_balance,
            vendor_name=vendor_name,
            extracted_invoice=extracted_invoice,
            po_dict=po_dict,
            po_items=po_items,
            early_messages=early_messages,
            llm_client=llm_client,
            vendor_dict=vendor_dict,
        )
        if llm_res:
            return llm_res

    # 2. Deterministic Template Fallback
    reasoning: List[ReasoningFactor] = []

    # Inject early messages (e.g. PO typo suggestions, duplicate ledger citation, unapproved vendor notice)
    if early_messages:
        for msg in early_messages:
            if msg:
                st = "REJECTED" if decision == DecisionEnum.REJECTED else "FLAGGED"
                reasoning.append(ReasoningFactor(status=st, text=f"[NOTICE] {msg}"))

    # Vendor statement
    if vendor_name:
        reasoning.append(ReasoningFactor(status="PASSED", text=f"Vendor identified as '{vendor_name}'."))

    # Match statement
    if match_result.method:
        if match_result.selected_po:
            reasoning.append(
                ReasoningFactor(status="PASSED", text=f"Matched against purchase order {match_result.selected_po} via {match_result.method.value} matching.")
            )
        else:
            reasoning.append(ReasoningFactor(status="FLAGGED", text=f"PO matching attempted via {match_result.method.value}; no definitive PO selected."))

    # Balance statement
    if po_balance:
        st = "REJECTED" if po_balance.remaining_after < 0 else "PASSED"
        reasoning.append(
            ReasoningFactor(
                status=st,
                text=f"PO Total: {po_balance.po_total:.2f}, Previously Billed: {po_balance.previously_billed:.2f}, "
                     f"This Invoice: {po_balance.this_invoice:.2f}, Remaining After: {po_balance.remaining_after:.2f}."
            )
        )

    # Check results statements
    for r in rule_results:
        if r.status in (RuleStatusEnum.FAIL, RuleStatusEnum.FLAG, RuleStatusEnum.WARN):
            st = "REJECTED" if r.status == RuleStatusEnum.FAIL else "FLAGGED"
            reasoning.append(ReasoningFactor(status=st, text=f"[{r.status.value}] {r.rule}: {r.message}"))

    # Confidence transparency statement
    if confidence_formula:
        reasoning.append(ReasoningFactor(status="INFO", text=f"[CONFIDENCE FORMULA] Heuristic score calculation: {confidence_formula}"))

    # Summary generator
    if decision == DecisionEnum.APPROVED:
        if reason_code == ReasonCodeEnum.APPROVED_WITH_NOTE:
            summary = f"Invoice approved with minor advisory notes for PO {match_result.selected_po}."
        else:
            summary = f"Invoice fully verified and approved against PO {match_result.selected_po}."
    elif decision == DecisionEnum.REJECTED:
        reason_detail = next((m for m in (early_messages or []) if m), None)
        if not reason_detail:
            failed_rule = next((r.message for r in rule_results if r.status == RuleStatusEnum.FAIL), None)
            reason_detail = failed_rule or f"Failed on policy ({reason_code.value})"
        summary = f"Invoice rejected: {reason_detail}"
    else:
        review_detail = next((m for m in (early_messages or []) if m), None)
        summary = f"Invoice requires AP human review ({reason_code.value}): {review_detail or 'Pending manual verification'}"

    return summary, reasoning, 0, 0
