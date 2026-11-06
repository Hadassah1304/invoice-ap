"""Pydantic v2 models for authored and compiled schemas.

Strict mode with extra='forbid' to satisfy validation rules (e.g. V01, V02).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


# --- Date Offsets ---
class DateOffset(StrictBase):
    offset_days: int


# --- Authored Core Schemas ---
class AuthoredVendor(StrictBase):
    vendor_id: str
    name: str
    aliases: List[str] = Field(default_factory=list)
    gstin: Optional[str] = None
    email_domain: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    approved: bool = True
    bank_account: Optional[str] = None
    owner_family: Literal["0", "R", "B", "I", "N"]


class AuthoredCatalogItem(StrictBase):
    sku: str
    name: str
    description: str
    uom: str
    unit_price: Union[float, Decimal]
    tax_rate: Union[int, float, Decimal]
    category: str
    twin_group: Optional[str] = None
    distinguisher: Optional[str] = None
    reworded: List[str] = Field(default_factory=list)
    unique_item: bool = False


class AuthoredCore(StrictBase):
    schema_version: Literal[1]
    vendors: List[AuthoredVendor]
    catalog: List[AuthoredCatalogItem]


# --- Authored Family Schemas ---
class AuthoredPOLine(StrictBase):
    line_no: int
    sku: str
    item_name: str
    description: str
    uom: str
    qty_ordered: int
    unit_price: Union[float, Decimal]
    tax_rate: Union[int, float, Decimal]


class AuthoredPO(StrictBase):
    po_id: str
    vendor_id: str
    po_date: DateOffset
    currency: str = "INR"
    status: Literal["OPEN", "PARTIAL", "CLOSED", "CANCELLED"]
    payment_terms_days: int = 30
    group: Optional[str] = None
    lines: List[AuthoredPOLine]


class AuthoredPreloadLine(StrictBase):
    po_line_no: int
    qty: int
    unit_price: Union[float, Decimal]


class AuthoredPreload(StrictBase):
    preload_id: str
    po_id: str
    vendor_id: str
    invoice_no: str
    invoice_date: DateOffset
    currency: str = "INR"
    lines: List[AuthoredPreloadLine]


class AuthoredInvoiceLine(StrictBase):
    po_line_no: Optional[int] = None
    description: Optional[str] = None
    qty: int
    unit_price: Union[float, Decimal]
    tax_rate: Union[int, float, Decimal]


class AuthoredExtraLine(StrictBase):
    description: str
    qty: int = 1
    unit_price: Union[float, Decimal]
    tax_rate: Union[int, float, Decimal] = 0


class AuthoredInvoice(StrictBase):
    invoice_no: str
    invoice_date: DateOffset
    vendor_id: str
    po_reference: Optional[str] = None
    currency: str = "INR"
    lines: List[AuthoredInvoiceLine]
    extra_lines: List[AuthoredExtraLine] = Field(default_factory=list)


class AuthoredDeriveFrom(StrictBase):
    scenario_id: str


class AuthoredSeries(StrictBase):
    id: str
    position: int


class AuthoredRelation(StrictBase):
    type: Literal["none", "duplicate_of", "control_of"] = "none"
    scenario_id: Optional[str] = None


class AuthoredMutation(StrictBase):
    name: str
    params: Dict[str, Any] = Field(default_factory=dict)


class AuthoredIntent(StrictBase):
    decision: Literal["APPROVED", "REJECTED", "NEEDS_REVIEW"]
    decision_accepted: List[Literal["APPROVED", "REJECTED", "NEEDS_REVIEW"]] = Field(default_factory=list)
    reason_codes_accepted: List[str] = Field(default_factory=list)
    po_id: Optional[str] = None
    confidence: Literal["firm", "soft"] = "firm"
    expect_cached: bool = False
    config_dependency: List[str] = Field(default_factory=list)
    notes: str = ""


class AuthoredRender(StrictBase):
    layout: Literal["auto", "itemised", "bundled", "tax_embedded", "multi_page"] = "auto"
    degrade: Literal["none", "light", "medium", "heavy"] = "none"
    number_format: Literal["auto", "plain", "indian", "eu"] = "auto"
    currency_style: Literal["auto", "Rs.", "₹", "INR"] = "auto"
    date_style: Literal["auto", "dmy_slash", "dmy_mon", "iso"] = "auto"


class AuthoredScenario(StrictBase):
    scenario_id: str
    tag: str
    description: str
    po_id: Optional[str] = None
    series: Optional[AuthoredSeries] = None
    relation: Optional[AuthoredRelation] = None
    invoice: Optional[AuthoredInvoice] = None
    derive_from: Optional[AuthoredDeriveFrom] = None
    mutation: AuthoredMutation = Field(default_factory=lambda: AuthoredMutation(name="none", params={}))
    intent: AuthoredIntent
    render: AuthoredRender = Field(default_factory=AuthoredRender)


class AuthoredFamily(StrictBase):
    schema_version: Literal[1]
    family: Literal["R", "B", "I", "N"]
    pos: List[AuthoredPO] = Field(default_factory=list)
    ledger_preload: List[AuthoredPreload] = Field(default_factory=list)
    scenarios: List[AuthoredScenario] = Field(default_factory=list)


# --- Compiled / Output Schemas (state.json & cases.json) ---
# Note: In compiled documents, numbers are converted to float or Decimal for JSON serialization.

class StateVendor(StrictBase):
    vendor_id: str
    name: str
    aliases: List[str] = Field(default_factory=list)
    gstin: Optional[str] = None
    email_domain: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    approved: bool = True
    bank_account: Optional[str] = None
    owner_family: Literal["0", "R", "B", "I", "N"]


class StatePOLine(StrictBase):
    line_no: int
    sku: str
    item_name: str
    description: str
    uom: str
    qty_ordered: int
    qty_remaining: int
    unit_price: float
    tax_rate: float
    line_total: float
    embedding: Optional[Any] = None


class StatePO(StrictBase):
    po_id: str
    vendor_id: str
    po_date: str  # ISO date YYYY-MM-DD
    currency: str
    status: Literal["OPEN", "PARTIAL", "CLOSED", "CANCELLED"]
    payment_terms_days: int
    group: Optional[str] = None
    subtotal: float
    tax_total: float
    total: float
    lines: List[StatePOLine]


class StatePreloadLine(StrictBase):
    po_line_no: int
    description: str
    qty: int
    unit_price: float
    line_total: float


class StatePreload(StrictBase):
    preload_id: str
    po_id: str
    vendor_id: str
    invoice_no: str
    invoice_no_norm: str
    invoice_date: str  # ISO date
    currency: str
    subtotal: float
    tax_total: float
    total: float
    lines: List[StatePreloadLine]


class StateMeta(StrictBase):
    reference_date: str
    seed: int


class StateOutput(StrictBase):
    meta: StateMeta
    vendors: List[StateVendor]
    catalog: List[AuthoredCatalogItem]
    purchase_orders: List[StatePO]
    ledger_preload: List[StatePreload]


# --- cases.json schemas ---

class VendorBlock(StrictBase):
    name: Optional[str] = None
    gstin: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    bank_account: Optional[str] = None


class DocumentLine(StrictBase):
    line_no: int
    description: str
    uom: str
    qty: int
    unit_price: float
    line_total: float
    tax_rate: float


class DocumentOmit(StrictBase):
    fields: List[str] = Field(default_factory=list)
    omit_label: bool = False


class DocumentFlags(StrictBase):
    ambiguous_date: bool = False


class Document(StrictBase):
    title: str = "TAX INVOICE"
    document_type: str = "invoice"
    vendor_block: Optional[VendorBlock] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None  # ISO date YYYY-MM-DD
    due_date: Optional[str] = None
    po_reference: Optional[str] = None
    currency: str = "INR"
    tax_mode: Literal["separate", "embedded"] = "separate"
    lines: List[DocumentLine] = Field(default_factory=list)
    subtotal: Optional[float] = None
    tax_total: Optional[float] = None
    grand_total: Optional[float] = None
    omit: DocumentOmit = Field(default_factory=DocumentOmit)
    flags: DocumentFlags = Field(default_factory=DocumentFlags)


class CompiledRender(StrictBase):
    layout: Literal["itemised", "bundled", "tax_embedded", "multi_page"]
    degrade: Literal["none", "light", "medium", "heavy"]
    number_format: Literal["plain", "indian", "eu"]
    currency_style: Literal["Rs.", "₹", "INR"]
    date_style: Literal["dmy_slash", "dmy_mon", "iso"]


class CaseExpected(StrictBase):
    decision: Literal["APPROVED", "REJECTED", "NEEDS_REVIEW"]
    decision_accepted: List[Literal["APPROVED", "REJECTED", "NEEDS_REVIEW"]]
    reason_codes_accepted: List[str]
    po_id: Optional[str] = None
    confidence: Literal["firm", "soft"]
    expect_cached: bool = False
    config_dependency: List[str] = Field(default_factory=list)
    notes: str = ""


class CaseOutput(StrictBase):
    case_id: str
    run_order: int
    file_stem: str
    tag: str
    family: Literal["R", "B", "I", "N"]
    series_id: Optional[str] = None
    byte_copy_of: Optional[str] = None
    document: Document
    render: CompiledRender
    expected: CaseExpected


class CasesMeta(StrictBase):
    reference_date: str
    seed: int
    case_count: int


class CasesOutput(StrictBase):
    meta: CasesMeta
    cases: List[CaseOutput]
