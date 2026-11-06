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
