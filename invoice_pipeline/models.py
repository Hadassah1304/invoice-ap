from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# --- Enums ---

class DecisionEnum(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ReasonCodeEnum(str, Enum):
    OK = "OK"
    APPROVED_WITH_NOTE = "APPROVED_WITH_NOTE"
    MISSING_FIELDS = "MISSING_FIELDS"
    LOW_CONFIDENCE_EXTRACTION = "LOW_CONFIDENCE_EXTRACTION"
    GROUNDING_FAILED = "GROUNDING_FAILED"
    ARITHMETIC_MISMATCH = "ARITHMETIC_MISMATCH"
    DUPLICATE_EXACT = "DUPLICATE_EXACT"
    DUPLICATE_POSSIBLE = "DUPLICATE_POSSIBLE"
    VENDOR_NOT_APPROVED = "VENDOR_NOT_APPROVED"
    VENDOR_UNCLEAR = "VENDOR_UNCLEAR"
    VENDOR_MISMATCH = "VENDOR_MISMATCH"
    INVALID_PO_REF = "INVALID_PO_REF"
    PO_CLOSED = "PO_CLOSED"
    NO_MATCHING_PO = "NO_MATCHING_PO"
    AMBIGUOUS_PO = "AMBIGUOUS_PO"
    INFERRED_MATCH = "INFERRED_MATCH"
    OVERBILLED = "OVERBILLED"
    QTY_EXCEEDS_REMAINING = "QTY_EXCEEDS_REMAINING"
    PRICE_DRIFT = "PRICE_DRIFT"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    DATE_INVALID = "DATE_INVALID"
    TAX_MISMATCH = "TAX_MISMATCH"
    UNSUPPORTED_DOCUMENT_TYPE = "UNSUPPORTED_DOCUMENT_TYPE"
    UNREADABLE_DOCUMENT = "UNREADABLE_DOCUMENT"


class MatchMethodEnum(str, Enum):
    EXPLICIT = "EXPLICIT"
    INFERRED_VENDOR = "INFERRED_VENDOR"
    INFERRED_ITEMS = "INFERRED_ITEMS"
    MANUAL = "MANUAL"


class RuleStatusEnum(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FLAG = "FLAG"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


class SeverityEnum(str, Enum):
    INFO = "info"
    SOFT = "soft"
    HARD = "hard"


# --- Trace Models ---

class TraceEntry(BaseModel):
    stage: str
    status: str
    duration_ms: int
    inputs_summary: Optional[str] = None
    outputs_summary: Optional[str] = None
    summary: str
    warnings: List[str] = Field(default_factory=list)


# --- Extraction Models ---

class ExtractionSource(BaseModel):
    file_name: str
    file_hash: str
    extraction_method: str  # text_layer | ocr_tesseract | ocr_rapidocr | vision_llm
    ocr_confidence: float = 1.0
    page_count: int = 1


class ExtractedVendor(BaseModel):
    name: Optional[str] = None
    gstin: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    bank_account: Optional[str] = None
    confidence: float = 0.0


class FieldValue(BaseModel):
    value: Optional[Any] = None
    confidence: float = 0.0
    ambiguous: Optional[bool] = None


class ExtractedLineItem(BaseModel):
    line_no: Optional[int] = None
    description: str
    quantity: Optional[float] = None
    uom: Optional[str] = None
    unit_price: Optional[float] = None
    line_total: Optional[float] = None
    tax_rate: Optional[float] = None
    confidence: float = 0.0


class GroundingResult(BaseModel):
    checked: int = 0
    failed: List[str] = Field(default_factory=list)


class ExtractedInvoice(BaseModel):
    source: ExtractionSource
    vendor: ExtractedVendor
    invoice_number: FieldValue
    invoice_date: FieldValue
    due_date: Optional[FieldValue] = None
    po_reference: Optional[FieldValue] = None
    currency: FieldValue
    line_items: List[ExtractedLineItem] = Field(default_factory=list)
    subtotal: Optional[FieldValue] = None
    tax_total: Optional[FieldValue] = None
    grand_total: FieldValue
    document_type: str = "invoice"  # invoice | credit_note | other
    raw_text: Optional[str] = None
    missing_fields: List[str] = Field(default_factory=list)
    grounding: GroundingResult = Field(default_factory=GroundingResult)


# --- Matching Models ---

class CandidateSignals(BaseModel):
    price: float = 0.0
    quantity: float = 0.0
    total_coverage: float = 0.0
    line_coverage: float = 0.0
    date: float = 0.0


class LineMatchDetail(BaseModel):
    invoice_line_no: int
    invoice_description: str
    po_item_row_id: Optional[int] = None
    po_item_name: Optional[str] = None
    match_method: str  # exact | fuzzy | embedding | none
    score: float = 0.0
    notes: List[str] = Field(default_factory=list)


class POCandidate(BaseModel):
    po_id: str
    score: float
    signals: CandidateSignals = Field(default_factory=CandidateSignals)
    notes: List[str] = Field(default_factory=list)
    line_matches: List[LineMatchDetail] = Field(default_factory=list)


class MatchResult(BaseModel):
    tier: Optional[int] = None
    method: Optional[MatchMethodEnum] = None
    selected_po: Optional[str] = None
    candidates: List[POCandidate] = Field(default_factory=list)
    unmatched_lines: List[str] = Field(default_factory=list)


# --- Validation Models ---

class RuleResult(BaseModel):
    rule: str
    status: RuleStatusEnum
    severity: SeverityEnum
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)


class POBalanceSummary(BaseModel):
    po_id: str
    po_total: float
    previously_billed: float
    reserved_pending: float
    this_invoice: float
    remaining_after: float
    variance_pct: float = 0.0


# --- Review & Decision Models ---

class ReviewAction(BaseModel):
    type: str  # select_po | edit_field | confirm_vendor | confirm_duplicate | general
    field: Optional[str] = None
    options: List[str] = Field(default_factory=list)


class ReviewRequired(BaseModel):
    required: bool = False
    actions: List[ReviewAction] = Field(default_factory=list)


class Timings(BaseModel):
    total: int = 0
    ocr: int = 0
    llm: int = 0
    matching: int = 0
    validation: int = 0


class CostSummary(BaseModel):
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0


class DecisionResult(BaseModel):
    request_id: str
    decision: DecisionEnum
    reason_code: ReasonCodeEnum
    confidence: float
    summary: str
    reasoning: List[str] = Field(default_factory=list)
    extracted: Optional[ExtractedInvoice] = None
    match: MatchResult = Field(default_factory=MatchResult)
    po_balance: Optional[POBalanceSummary] = None
    checks: List[RuleResult] = Field(default_factory=list)
    review: ReviewRequired = Field(default_factory=ReviewRequired)
    trace: List[TraceEntry] = Field(default_factory=list)
    timings_ms: Timings = Field(default_factory=Timings)
    cost: CostSummary = Field(default_factory=CostSummary)
    cached: bool = False
