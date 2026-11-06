from __future__ import annotations

from typing import List
from invoice_pipeline.models import RuleResult
from invoice_pipeline.validation.rules import ALL_RULES, ValidationContext


class ValidationEngine:
    """Executes registered validation rules sequentially against a context."""

    def __init__(self, rules=None) -> None:
        self.rules = rules or ALL_RULES

    def run(self, ctx: ValidationContext) -> List[RuleResult]:
        results: List[RuleResult] = []
        for rule_fn in self.rules:
            res = rule_fn(ctx)
            results.append(res)
        return results
