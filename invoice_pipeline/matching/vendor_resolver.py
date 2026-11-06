from __future__ import annotations

import json
from typing import List, Optional, Tuple
from rapidfuzz import fuzz
from invoice_pipeline.config import VendorConfig
from invoice_pipeline.normalize.normalizers import normalize_vendor_name
from invoice_pipeline.store.repositories import VendorRepo


class VendorResolutionResult:
    def __init__(
        self,
        vendor: Optional[dict] = None,
        confidence: float = 0.0,
        method: Optional[str] = None,  # GSTIN | FUZZY_NAME | EMAIL_DOMAIN
        candidates: Optional[List[Tuple[dict, float]]] = None,
        is_approved: bool = True,
        status: str = "ok",  # ok | not_approved | unclear | not_found
    ) -> None:
        self.vendor = vendor
        self.confidence = confidence
        self.method = method
        self.candidates = candidates or []
        self.is_approved = is_approved
        self.status = status


class VendorResolver:
    """Resolves vendor using GSTIN exact, fuzzy name matching with margin checks, or email domain."""

    def __init__(self, repo: VendorRepo, config: VendorConfig) -> None:
        self.repo = repo
        self.config = config

    def resolve(
        self,
        gstin: Optional[str] = None,
        raw_name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> VendorResolutionResult:
        # 1. GSTIN Exact
        if self.config.use_gstin_first and gstin:
            clean_gstin = gstin.strip().upper()
            vendor = self.repo.get_by_gstin(clean_gstin)
            if vendor:
                approved = bool(vendor.get("approved", 1))
                return VendorResolutionResult(
                    vendor=vendor,
                    confidence=1.0,
                    method="GSTIN",
                    is_approved=approved,
                    status="ok" if approved else "not_approved",
                )

        # 2. Fuzzy Name Match against name + aliases
        all_vendors = self.repo.list_all()
        if raw_name and all_vendors:
            norm_query = normalize_vendor_name(raw_name)
            scored: List[Tuple[dict, float]] = []

            for v in all_vendors:
                names_to_check = [v["name"]]
                if v.get("aliases"):
                    try:
                        aliases = json.loads(v["aliases"]) if isinstance(v["aliases"], str) else v["aliases"]
                        if isinstance(aliases, list):
                            names_to_check.extend(aliases)
                    except Exception:
                        pass

                best_sim = 0.0
                for n in names_to_check:
                    norm_target = normalize_vendor_name(n)
                    sim = fuzz.token_set_ratio(norm_query, norm_target) / 100.0
                    if sim > best_sim:
                        best_sim = sim

                if best_sim > 0.4:
                    scored.append((v, best_sim))

            scored.sort(key=lambda x: x[1], reverse=True)

            if scored:
                top_vendor, top_score = scored[0]
                second_score = scored[1][1] if len(scored) > 1 else 0.0
                margin = top_score - second_score

                # Require high score AND positive margin against lookalikes
                if top_score >= self.config.match_threshold and margin >= 0.05:
                    approved = bool(top_vendor.get("approved", 1))
                    return VendorResolutionResult(
                        vendor=top_vendor,
                        confidence=top_score,
                        method="FUZZY_NAME",
                        candidates=scored[:3],
                        is_approved=approved,
                        status="ok" if approved else "not_approved",
                    )
                elif top_score >= self.config.reject_threshold:
                    return VendorResolutionResult(
                        vendor=top_vendor,
                        confidence=top_score,
                        method="FUZZY_NAME",
                        candidates=scored[:3],
                        is_approved=bool(top_vendor.get("approved", 1)),
                        status="unclear",
                    )

        # 3. Email domain
        if self.config.use_email_domain and email and "@" in email:
            domain = email.split("@")[-1].strip().lower()
            if domain and domain not in ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com"]:
                matches = self.repo.get_by_email_domain(domain)
                if len(matches) == 1:
                    v = matches[0]
                    approved = bool(v.get("approved", 1))
                    return VendorResolutionResult(
                        vendor=v,
                        confidence=0.85,
                        method="EMAIL_DOMAIN",
                        is_approved=approved,
                        status="ok" if approved else "not_approved",
                    )

        return VendorResolutionResult(status="not_found")
