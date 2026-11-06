import pytest
from invoice_pipeline.config import PipelineConfig, load_config
from invoice_pipeline.trace import TraceRecorder


def test_load_default_config():
    cfg = load_config()
    assert cfg.ocr.engine in ["rapidocr", "tesseract"]
    assert cfg.matching.weights.price == 0.30
    assert cfg.matching.weights.quantity == 0.25
    assert cfg.matching.weights.total_coverage == 0.20
    assert cfg.matching.weights.line_coverage == 0.15
    assert cfg.matching.weights.date == 0.10
    assert cfg.llm.provider == "openai"
    assert cfg.llm.base_url == "https://api.experientiallabs.ai/v1"
    assert cfg.llm.api_key_env == "EXPLABS_API_KEY"
    assert cfg.llm.model == "gemini-2.5-flash-lite"


def test_weights_sum_validation():
    with pytest.raises(ValueError, match="Matching weights must sum to 1.0"):
        PipelineConfig(
            matching={
                "weights": {
                    "price": 0.5,
                    "quantity": 0.5,
                    "total_coverage": 0.2,  # sum is 1.2
                    "line_coverage": 0.0,
                    "date": 0.0,
                }
            }
        )


def test_trace_recorder():
    recorder = TraceRecorder()
    recorder.start_stage("ingest")
    entry = recorder.end_stage("ingest", status="ok", summary="text layer found")
    assert entry.stage == "ingest"
    assert entry.status == "ok"
    assert entry.summary == "text layer found"
    assert entry.duration_ms >= 0
    assert len(recorder.to_list()) == 1
