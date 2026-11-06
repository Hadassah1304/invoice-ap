from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional
import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseModel):
    db_path: str = "./data/ap.db"
    upload_dir: str = "./data/uploads"
    log_level: str = "INFO"
    cache_by_file_hash: bool = True


class TextLayerConfig(BaseModel):
    enabled: bool = True
    min_chars: int = 80
    min_alnum_ratio: float = 0.5


class PreprocessConfig(BaseModel):
    enabled: bool = True
    deskew: bool = True
    denoise: bool = True
    upscale_dpi: int = 300


class TesseractConfig(BaseModel):
    lang: str = "eng"
    psm: int = 6
    cmd: str = "tesseract"


class RapidOCRConfig(BaseModel):
    use_angle_cls: bool = True


class VisionFallbackConfig(BaseModel):
    enabled: bool = True
    trigger_on_missing_fields: List[str] = Field(
        default_factory=lambda: ["invoice_number", "invoice_date", "grand_total"]
    )


class OCRConfig(BaseModel):
    engine: str = "rapidocr"  # tesseract | rapidocr
    text_layer: TextLayerConfig = Field(default_factory=TextLayerConfig)
    preprocess: PreprocessConfig = Field(default_factory=PreprocessConfig)
    pdf_render_dpi: int = 200
    tesseract: TesseractConfig = Field(default_factory=TesseractConfig)
    rapidocr: RapidOCRConfig = Field(default_factory=RapidOCRConfig)
    min_confidence: float = 0.70
    vision_fallback: VisionFallbackConfig = Field(default_factory=VisionFallbackConfig)


class ExtractionConfig(BaseModel):
    input_mode: str = "text"  # text | image | auto
    require_source_snippets: bool = False


class ExplanationConfig(BaseModel):
    use_llm_polish: bool = False


class LLMConfig(BaseModel):
    provider: str = "gemini"
    api_key_env: str = "GEMINI_API_KEY"
    model: str = "gemini-2.5-flash"
    temperature: float = 0.0
    timeout_s: int = 45
    max_retries: int = 2
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    explanation: ExplanationConfig = Field(default_factory=ExplanationConfig)


class GroundingConfig(BaseModel):
    enabled: bool = True
    numeric_tolerance: float = 0.01
    on_failure: str = "flag"  # flag | null_out | review


class NormalizationConfig(BaseModel):
    default_currency: str = "INR"
    date_formats_priority: List[str] = Field(
        default_factory=lambda: ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y"]
    )
    ambiguous_date_policy: str = "flag"  # flag | first_priority


class VendorConfig(BaseModel):
    match_threshold: float = 0.90
    reject_threshold: float = 0.75
    use_gstin_first: bool = True
    use_email_domain: bool = True


class DuplicatesConfig(BaseModel):
    near_dup_window_days: int = 7
    near_dup_amount_tolerance_pct: float = 0.0
    invoice_no_similarity_threshold: float = 0.92


class Tier2Config(BaseModel):
    min_score: float = 0.80
    min_margin: float = 0.15
    top_k: int = 5


class Tier3Config(BaseModel):
    item_similarity_threshold: float = 0.88
    item_margin: float = 0.03
    top_k_per_line: int = 10
    price_tolerance_pct: float = 5.0
    use_lexical_check: bool = True
    min_line_coverage_for_partial: float = 0.6
    top_k_candidates_to_user: int = 5


class LineMatchConfig(BaseModel):
    exact_first: bool = True
    fuzzy_threshold: float = 90.0
    use_embeddings: bool = True


class WeightsConfig(BaseModel):
    price: float = 0.30
    quantity: float = 0.25
    total_coverage: float = 0.20
    line_coverage: float = 0.15
    date: float = 0.10

    @model_validator(mode="after")
    def check_weights_sum(self) -> WeightsConfig:
        s = self.price + self.quantity + self.total_coverage + self.line_coverage + self.date
        if abs(s - 1.0) > 1e-4:
            raise ValueError(f"Matching weights must sum to 1.0, got {s:.4f}")
        return self


class MatchingConfig(BaseModel):
    tier2: Tier2Config = Field(default_factory=Tier2Config)
    tier3: Tier3Config = Field(default_factory=Tier3Config)
    line_match: LineMatchConfig = Field(default_factory=LineMatchConfig)
    weights: WeightsConfig = Field(default_factory=WeightsConfig)
    auto_approve_inferred: bool = False


class EmbeddingsConfig(BaseModel):
    backend: str = "tfidf"  # tfidf | minilm
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    cache_description_embeddings: bool = True


class ValidationConfig(BaseModel):
    rounding_tolerance: float = 1.00
    tolerance_auto_pct: float = 2.0
    tolerance_review_pct: float = 5.0
    price_variance_line_pct: float = 2.0
    qty_over_remaining_policy: str = "review"  # review | reject
    reserve_pending_invoices: bool = True
    max_invoice_age_days: int = 90
    allow_future_dated: bool = False
    tax_rates_plausible: List[float] = Field(default_factory=lambda: [0.0, 5.0, 12.0, 18.0, 28.0])
    allow_extra_lines: List[str] = Field(default_factory=lambda: ["freight", "handling", "shipping"])
    block_negative_amounts: bool = True


class DecisionConfig(BaseModel):
    review_if_inferred: bool = True
    review_on_low_confidence_below: float = 0.75


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    max_upload_mb: int = 15
    cors_origins: List[str] = Field(default_factory=lambda: ["*"])


class PipelineConfig(BaseSettings):
    app: AppConfig = Field(default_factory=AppConfig)
    ocr: OCRConfig = Field(default_factory=OCRConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    grounding: GroundingConfig = Field(default_factory=GroundingConfig)
    normalization: NormalizationConfig = Field(default_factory=NormalizationConfig)
    vendor: VendorConfig = Field(default_factory=VendorConfig)
    duplicates: DuplicatesConfig = Field(default_factory=DuplicatesConfig)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    decision: DecisionConfig = Field(default_factory=DecisionConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_prefix="INVOICE_",
        extra="ignore",
    )


def load_config(config_path: Optional[str | Path] = None) -> PipelineConfig:
    """Loads configuration from YAML file and applies environment variable overrides."""
    data: dict[str, Any] = {}
    path = config_path or os.environ.get("INVOICE_CONFIG", "config.yaml")
    p = Path(path)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if loaded and isinstance(loaded, dict):
                data = loaded
    return PipelineConfig(**data)
