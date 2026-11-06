from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest

from invoice_pipeline.config import LLMConfig
from invoice_pipeline.extract.llm_client import LLMClient


def test_llm_client_missing_key(monkeypatch):
    monkeypatch.delenv("EXPLABS_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cfg = LLMConfig(api_key_env="EXPLABS_API_KEY")
    client = LLMClient(cfg)
    with pytest.raises(PermissionError, match="LLM API key not found"):
        client._get_client()


def test_llm_client_initialization(monkeypatch):
    monkeypatch.setenv("EXPLABS_API_KEY", "test-explabs-key")
    cfg = LLMConfig(
        provider="openai",
        base_url="https://api.experientiallabs.ai/v1",
        api_key_env="EXPLABS_API_KEY",
        model="gemini-2.5-flash-lite",
    )
    client = LLMClient(cfg)
    with patch("openai.OpenAI") as mock_openai_cls:
        c = client._get_client()
        mock_openai_cls.assert_called_once_with(
            base_url="https://api.experientiallabs.ai/v1",
            api_key="test-explabs-key",
            timeout=45,
        )


def test_llm_client_extract_from_text(monkeypatch):
    monkeypatch.setenv("EXPLABS_API_KEY", "test-key")
    cfg = LLMConfig(max_retries=1)
    client = LLMClient(cfg)

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({"invoice_number": {"value": "INV-100", "confidence": 0.95}})
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 150
    mock_response.usage.completion_tokens = 50

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_instance = MagicMock()
        mock_openai_cls.return_value = mock_instance
        mock_instance.chat.completions.create.return_value = mock_response

        data, in_tok, out_tok = client.extract_from_text("Dummy Invoice Text")

        assert data["invoice_number"]["value"] == "INV-100"
        assert in_tok == 150
        assert out_tok == 50

        # Verify call arguments
        mock_instance.chat.completions.create.assert_called_once()
        call_kwargs = mock_instance.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gemini-2.5-flash-lite"
        assert call_kwargs["response_format"] == {"type": "json_object"}
        assert len(call_kwargs["messages"]) == 2
        assert call_kwargs["messages"][0]["role"] == "system"
        assert "Invoice raw text:\n\nDummy Invoice Text" in call_kwargs["messages"][1]["content"]


def test_llm_client_markdown_fence_cleaning(monkeypatch):
    monkeypatch.setenv("EXPLABS_API_KEY", "test-key")
    cfg = LLMConfig(max_retries=1)
    client = LLMClient(cfg)

    mock_response = MagicMock()
    mock_choice = MagicMock()
    # Model wrapped json in markdown code fences
    mock_choice.message.content = "```json\n{\"invoice_number\": {\"value\": \"INV-FENCE\", \"confidence\": 0.99}}\n```"
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 80
    mock_response.usage.completion_tokens = 30

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_instance = MagicMock()
        mock_openai_cls.return_value = mock_instance
        mock_instance.chat.completions.create.return_value = mock_response

        data, in_tok, out_tok = client.extract_from_text("Some invoice")
        assert data["invoice_number"]["value"] == "INV-FENCE"


def test_llm_client_extract_from_images(monkeypatch):
    monkeypatch.setenv("EXPLABS_API_KEY", "test-key")
    cfg = LLMConfig(max_retries=1)
    client = LLMClient(cfg)

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({"invoice_number": {"value": "INV-VISION", "confidence": 0.90}})
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 200
    mock_response.usage.completion_tokens = 60

    img = Image.new("RGB", (50, 50), color="white")

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_instance = MagicMock()
        mock_openai_cls.return_value = mock_instance
        mock_instance.chat.completions.create.return_value = mock_response

        data, in_tok, out_tok = client.extract_from_images([img])
        assert data["invoice_number"]["value"] == "INV-VISION"
        assert in_tok == 200
        assert out_tok == 60

        mock_instance.chat.completions.create.assert_called_once()
        call_kwargs = mock_instance.chat.completions.create.call_args.kwargs
        user_msg = call_kwargs["messages"][1]["content"]
        assert isinstance(user_msg, list)
        assert any(item.get("type") == "image_url" and "data:image/png;base64," in item["image_url"]["url"] for item in user_msg)
