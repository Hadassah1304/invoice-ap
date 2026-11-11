from __future__ import annotations

from typing import List, Optional, Tuple
from invoice_pipeline.config import PipelineConfig
from invoice_pipeline.models import (
    DecisionEnum,
    DecisionResult,
    MatchMethodEnum,
    MatchResult,
    ReasonCodeEnum,
    ReviewAction,
    ReviewRequired,
    RuleResult,
    RuleStatusEnum,
)


def compute_confidence(
    extracted_confidences: List[float],
    match_result: MatchResult,
    rule_results: List[RuleResult],
) -> tuple[float, str]:
    """
    Transparent confidence calculation:
    - Min confidence of extracted fields
    - Times match confidence factor (1.0 explicit, top score inferred, 0.5 unselected)
    - Minus 0.05 penalty for each WARN, 0.15 penalty for each FLAG.
    Bounded in [0.05, 0.99].
    Returns (score, formula_description).
    """
    field_min = min(extracted_confidences) if extracted_confidences else 1.0

    if match_result.method in (MatchMethodEnum.EXPLICIT, MatchMethodEnum.MANUAL):
        match_conf = 1.0
    elif match_result.candidates:
        match_conf = max(0.5, match_result.candidates[0].score)
    else:
        match_conf = 0.5

    base = field_min * match_conf
    warn_count = sum(1 for r in rule_results if r.status == RuleStatusEnum.WARN)
    flag_count = sum(1 for r in rule_results if r.status == RuleStatusEnum.FLAG)

    warn_penalty = warn_count * 0.05
    flag_penalty = flag_count * 0.15

    raw_conf = base - warn_penalty - flag_penalty
    bounded = round(max(0.05, min(0.99, raw_conf)), 2)

    formula = (
        f"min_field_conf({field_min:.2f}) × match_factor({match_conf:.2f}) "
        f"- {warn_count}×warn(0.05) - {flag_count}×flag(0.15) = {bounded:.2f}"
    )
    return bounded, formula


def aggregate_decision(
    early_terminal_code: Optional[ReasonCodeEnum],
    early_terminal_msg: Optional[str],
    early_review_code: Optional[ReasonCodeEnum],
    early_review_msg: Optional[str],
    match_result: MatchResult,
    rule_results: List[RuleResult],
    config: PipelineConfig,
) -> Tuple[DecisionEnum, ReasonCodeEnum, ReviewRequired]:
    """
    Deterministic aggregation precedence:
    1. Early terminal reject (DUPLICATE_EXACT, VENDOR_NOT_APPROVED, VENDOR_MISMATCH, PO_CLOSED, NO_MATCHING_PO, UNSUPPORTED_DOCUMENT_TYPE) -> REJECTED
    2. Any validation rule with FAIL -> REJECTED
    3. Early terminal review (MISSING_FIELDS, DUPLICATE_POSSIBLE, VENDOR_UNCLEAR, INVALID_PO_REF, AMBIGUOUS_PO, UNREADABLE_DOCUMENT, GROUNDING_FAILED) -> NEEDS_REVIEW
    4. Any validation rule with FLAG -> NEEDS_REVIEW
    5. Inferred match when not auto_approved -> NEEDS_REVIEW / INFERRED_MATCH
    6. Any validation rule with WARN -> APPROVED / APPROVED_WITH_NOTE
    7. Otherwise -> APPROVED / OK
    """
    review = ReviewRequired(required=False, actions=[])

    # 1. Early terminal reject
    if early_terminal_code in (
        ReasonCodeEnum.DUPLICATE_EXACT,
        ReasonCodeEnum.VENDOR_NOT_APPROVED,
        ReasonCodeEnum.VENDOR_MISMATCH,
        ReasonCodeEnum.PO_CLOSED,
        ReasonCodeEnum.NO_MATCHING_PO,
        ReasonCodeEnum.CURRENCY_MISMATCH,
    ):
        return DecisionEnum.REJECTED, early_terminal_code, review

    # 2. Rule FAIL
    for r in rule_results:
        if r.status == RuleStatusEnum.FAIL:
            code_map = {
                "balance_tolerance": ReasonCodeEnum.OVERBILLED,
                "line_quantity": ReasonCodeEnum.QTY_EXCEEDS_REMAINING,
                "currency_match": ReasonCodeEnum.CURRENCY_MISMATCH,
            }
            code = code_map.get(r.rule, ReasonCodeEnum.OVERBILLED)
            return DecisionEnum.REJECTED, code, review

    # 3. Early review
    if early_review_code:
        review.required = True
        if early_review_code in (ReasonCodeEnum.AMBIGUOUS_PO, ReasonCodeEnum.INVALID_PO_REF):
            opts = [c.po_id for c in match_result.candidates]
            review.actions.append(ReviewAction(type="select_po", options=opts))
        elif early_review_code == ReasonCodeEnum.VENDOR_UNCLEAR:
            review.actions.append(ReviewAction(type="confirm_vendor"))
        elif early_review_code == ReasonCodeEnum.DUPLICATE_POSSIBLE:
            review.actions.append(ReviewAction(type="confirm_duplicate"))
        elif early_review_code == ReasonCodeEnum.MISSING_FIELDS:
            review.actions.append(ReviewAction(type="edit_field", field="missing_fields"))
        elif early_review_code == ReasonCodeEnum.UNSUPPORTED_DOCUMENT_TYPE:
            review.actions.append(ReviewAction(type="manual_override"))
        return DecisionEnum.NEEDS_REVIEW, early_review_code, review

    # 4. Any rule FLAG
    flagged_rules = [r for r in rule_results if r.status == RuleStatusEnum.FLAG]
    if flagged_rules:
        review.required = True
        first_flag = flagged_rules[0]
        code_map = {
            "arithmetic": ReasonCodeEnum.ARITHMETIC_MISMATCH,
            "line_price_variance": ReasonCodeEnum.PRICE_DRIFT,
            "line_quantity": ReasonCodeEnum.QTY_EXCEEDS_REMAINING,
            "balance_tolerance": ReasonCodeEnum.OVERBILLED,
            "date_sanity": ReasonCodeEnum.DATE_INVALID,
            "tax_check": ReasonCodeEnum.TAX_MISMATCH,
            "confidence_check": ReasonCodeEnum.LOW_CONFIDENCE_EXTRACTION,
            "vendor_bank_check": ReasonCodeEnum.VENDOR_UNCLEAR,
            "extra_or_missing_lines": ReasonCodeEnum.AMBIGUOUS_PO,
        }
        code = code_map.get(first_flag.rule, ReasonCodeEnum.ARITHMETIC_MISMATCH)
        return DecisionEnum.NEEDS_REVIEW, code, review

    # 5. Inferred match when not auto_approved
    if match_result.method in (MatchMethodEnum.INFERRED_VENDOR, MatchMethodEnum.INFERRED_ITEMS):
        if not config.matching.auto_approve_inferred:
            review.required = True
            opts = [c.po_id for c in match_result.candidates]
            review.actions.append(ReviewAction(type="select_po", options=opts))
            return DecisionEnum.NEEDS_REVIEW, ReasonCodeEnum.INFERRED_MATCH, review

    # 6. Any rule WARN
    warns = [r for r in rule_results if r.status == RuleStatusEnum.WARN]
    if warns:
        return DecisionEnum.APPROVED, ReasonCodeEnum.APPROVED_WITH_NOTE, review

    # 7. Clean approval
    return DecisionEnum.APPROVED, ReasonCodeEnum.OK, review
