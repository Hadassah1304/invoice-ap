from __future__ import annotations

from typing import List, Optional
from invoice_pipeline.models import (
    DecisionEnum,
    MatchResult,
    POBalanceSummary,
    ReasonCodeEnum,
    RuleResult,
    RuleStatusEnum,
)


def build_explanation(
    decision: DecisionEnum,
    reason_code: ReasonCodeEnum,
    match_result: MatchResult,
    rule_results: List[RuleResult],
    po_balance: Optional[POBalanceSummary] = None,
    vendor_name: Optional[str] = None,
    early_messages: Optional[List[str]] = None,
    confidence_formula: Optional[str] = None,
) -> tuple[str, List[str]]:
    """Generates structured human-readable summary and bulleted reasoning points with full provenance."""
    reasoning: List[str] = []

    # Inject early messages (e.g. PO typo suggestions, duplicate ledger citation, unapproved vendor notice)
    if early_messages:
        for msg in early_messages:
            if msg:
                reasoning.append(f"[NOTICE] {msg}")

    # Vendor statement
    if vendor_name:
        reasoning.append(f"Vendor identified as '{vendor_name}'.")

    # Match statement
    if match_result.method:
        if match_result.selected_po:
            reasoning.append(
                f"Matched against purchase order {match_result.selected_po} via {match_result.method.value} matching."
            )
        else:
            reasoning.append(f"PO matching attempted via {match_result.method.value}; no definitive PO selected.")

    # Balance statement
    if po_balance:
        reasoning.append(
            f"PO Total: {po_balance.po_total:.2f}, Previously Billed: {po_balance.previously_billed:.2f}, "
            f"This Invoice: {po_balance.this_invoice:.2f}, Remaining After: {po_balance.remaining_after:.2f}."
        )

    # Check results statements
    for r in rule_results:
        if r.status in (RuleStatusEnum.FAIL, RuleStatusEnum.FLAG, RuleStatusEnum.WARN):
            reasoning.append(f"[{r.status.value}] {r.rule}: {r.message}")

    # Confidence transparency statement
    if confidence_formula:
        reasoning.append(f"[CONFIDENCE FORMULA] Heuristic score calculation: {confidence_formula}")

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

    return summary, reasoning
