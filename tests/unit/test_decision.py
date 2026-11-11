import pytest
from invoice_pipeline.config import PipelineConfig
from invoice_pipeline.decision.aggregator import aggregate_decision, compute_confidence
from invoice_pipeline.models import (
    DecisionEnum,
    MatchMethodEnum,
    MatchResult,
    POCandidate,
    ReasonCodeEnum,
    RuleResult,
    RuleStatusEnum,
    SeverityEnum,
)


def test_decision_precedence():
    cfg = PipelineConfig()

    # 1. Terminal Reject (Duplicate)
    dec, code, rev = aggregate_decision(
        ReasonCodeEnum.DUPLICATE_EXACT, "Exact dup", None, None, MatchResult(), [], cfg
    )
    assert dec == DecisionEnum.REJECTED
    assert code == ReasonCodeEnum.DUPLICATE_EXACT

    # 2. Rule Fail (Overbilled)
    rule_fail = RuleResult(
        rule="balance_tolerance",
        status=RuleStatusEnum.FAIL,
        severity=SeverityEnum.HARD,
        message="Too high",
    )
    dec2, code2, rev2 = aggregate_decision(None, None, None, None, MatchResult(), [rule_fail], cfg)
    assert dec2 == DecisionEnum.REJECTED
    assert code2 == ReasonCodeEnum.OVERBILLED

    # 3. Rule Flag (Price drift -> Needs review)
    rule_flag = RuleResult(
        rule="line_price_variance",
        status=RuleStatusEnum.FLAG,
        severity=SeverityEnum.SOFT,
        message="Drifted",
    )
    dec3, code3, rev3 = aggregate_decision(None, None, None, None, MatchResult(), [rule_flag], cfg)
    assert dec3 == DecisionEnum.NEEDS_REVIEW
    assert code3 == ReasonCodeEnum.PRICE_DRIFT
    assert rev3.required is True

    # 4. Clean Pass with Explicit PO
    match = MatchResult(tier=1, method=MatchMethodEnum.EXPLICIT, selected_po="PO-1")
    dec4, code4, rev4 = aggregate_decision(None, None, None, None, match, [], cfg)
    assert dec4 == DecisionEnum.APPROVED
    assert code4 == ReasonCodeEnum.OK

    # 5. Non-existent Cited PO -> Direct Reject (NO_MATCHING_PO)
    dec5, code5, rev5 = aggregate_decision(
        ReasonCodeEnum.NO_MATCHING_PO, "Referenced PO 'PO-BOGUS' not found in procurement system.", None, None, MatchResult(tier=1, method=MatchMethodEnum.EXPLICIT), [], cfg
    )
    assert dec5 == DecisionEnum.REJECTED
    assert code5 == ReasonCodeEnum.NO_MATCHING_PO

    # 6. PO Typo with Candidates -> Review with select_po action options (INVALID_PO_REF)
    cand = POCandidate(po_id="PO-CLOSE", score=0.92, signals={}, line_matches=[])
    match_typo = MatchResult(tier=1, method=MatchMethodEnum.EXPLICIT, candidates=[cand])
    dec6, code6, rev6 = aggregate_decision(
        None, None, ReasonCodeEnum.INVALID_PO_REF, "Close match found", match_typo, [], cfg
    )
    assert dec6 == DecisionEnum.NEEDS_REVIEW
    assert code6 == ReasonCodeEnum.INVALID_PO_REF
    assert rev6.required is True
    assert len(rev6.actions) == 1
    assert rev6.actions[0].type == "select_po"
    assert rev6.actions[0].options == ["PO-CLOSE"]
