from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest

from invoice_pipeline.decision.explainer import build_explanation, generate_llm_reasoning
from invoice_pipeline.models import (
    CandidateSignals,
    DecisionEnum,
    LineMatchDetail,
    MatchResult,
    POBalanceSummary,
    POCandidate,
    ReasonCodeEnum,
    RuleResult,
    RuleStatusEnum,
    SeverityEnum,
)


def test_explainer_llm_reasoning_success():
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = (
        {
            "summary": "Vendors match, but the invoice quantity exceeds the purchase order limit.",
            "reasoning": [
                "Vendor identified as SafePack Containers & Boxes via exact GSTIN match.",
                "Line items match, but billed quantity of 30 pcs exceeds 25 ordered pcs.",
                "Invoice total exceeds remaining purchase order budget by INR 4,720.00.",
                "Invoice date is valid and post-dates the purchase order issuance.",
            ],
        },
        120,
        60,
    )

    match_res = MatchResult(
        tier=1,
        method="EXPLICIT",
        selected_po="PO-1",
        candidates=[
            POCandidate(
                po_id="PO-1",
                score=0.85,
                signals=CandidateSignals(price=1.0, quantity=0.8, total_coverage=0.9, line_coverage=1.0, date=1.0),
                notes=["Price match"],
                line_matches=[LineMatchDetail(invoice_line_no=1, invoice_description="Boxes", po_item_name="Boxes", match_method="exact", score=1.0)],
            )
        ],
    )
    rule_res = [
        RuleResult(rule="line_quantity", status=RuleStatusEnum.FLAG, severity=SeverityEnum.SOFT, message="Exceeds PO"),
        RuleResult(rule="arithmetic", status=RuleStatusEnum.PASS, severity=SeverityEnum.INFO, message="Pass"),
    ]
    po_bal = POBalanceSummary(
        po_id="PO-1",
        po_total=10000.0,
        previously_billed=0.0,
        reserved_pending=0.0,
        this_invoice=12000.0,
        remaining_after=-2000.0,
        variance_pct=20.0,
    )

    summary, reasoning, in_tok, out_tok = build_explanation(
        decision=DecisionEnum.NEEDS_REVIEW,
        reason_code=ReasonCodeEnum.QTY_EXCEEDS_REMAINING,
        match_result=match_res,
        rule_results=rule_res,
        po_balance=po_bal,
        vendor_name="SafePack Containers & Boxes",
        llm_client=mock_llm,
        use_llm_polish=True,
    )

    assert "Vendors match, but the invoice quantity exceeds" in summary
    assert len(reasoning) == 4
    assert in_tok == 120
    assert out_tok == 60

    # Verify LLM prompt did not contain technical jargon instructions
    mock_llm.generate_json.assert_called_once()
    system_prompt, user_prompt = mock_llm.generate_json.call_args[0]
    assert "STRICTLY NO TECHNICAL OR STATISTICAL JARGON" in system_prompt
    assert "heuristic score" in system_prompt  # in the "NEVER use" list
    assert "SafePack Containers & Boxes" in user_prompt


def test_explainer_llm_fallback_on_error():
    mock_llm = MagicMock()
    mock_llm.generate_json.side_effect = RuntimeError("LLM rate limit / timeout")

    match_res = MatchResult(
        tier=1,
        method="EXPLICIT",
        selected_po="PO-1",
    )

    summary, reasoning, in_tok, out_tok = build_explanation(
        decision=DecisionEnum.APPROVED,
        reason_code=ReasonCodeEnum.OK,
        match_result=match_res,
        rule_results=[],
        vendor_name="Vendor A",
        llm_client=mock_llm,
        use_llm_polish=True,
    )

    # Clean fallback to template reasoning without crashing
    assert "Invoice fully verified and approved against PO PO-1." == summary
    assert any("Vendor identified as 'Vendor A'" in r for r in reasoning)
    assert in_tok == 0
    assert out_tok == 0
