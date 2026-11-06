from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple
from invoice_pipeline.config import LLMConfig
from invoice_pipeline.extract.prompts import EXTRACTION_SYSTEM_PROMPT
from invoice_pipeline.extract.schema import EXTRACTION_SCHEMA


class LLMClient:
    """Wrapper for Google Gemini SDK with retries and structured schema support."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            api_key = os.environ.get(self.config.api_key_env)
            if not api_key:
                raise PermissionError(
                    f"LLM API key not found in environment variable '{self.config.api_key_env}'. "
                    "Cannot perform extraction."
                )
            from google import genai
            self._client = genai.Client(api_key=api_key)
        return self._client

    def extract_from_text(self, text: str) -> Tuple[Dict[str, Any], int, int]:
        client = self._get_client()
        prompt = f"Invoice raw text:\n\n{text}"

        retries = 0
        last_err = None

        while retries <= self.config.max_retries:
            try:
                response = client.models.generate_content(
                    model=self.config.model,
                    contents=[prompt],
                    config=dict(
                        system_instruction=EXTRACTION_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=EXTRACTION_SCHEMA,
                        temperature=self.config.temperature,
                    ),
                )
                if not response.text:
                    raise ValueError("Empty or blocked response from Gemini model")
                data = json.loads(response.text)
                in_tok = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
                out_tok = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
                return data, in_tok, out_tok
            except Exception as e:
                last_err = e
                retries += 1
                time.sleep(0.5 * (2 ** retries))

        raise RuntimeError(f"Failed to extract structured data from LLM after retries: {last_err}")

    def extract_from_images(self, images: List[Any]) -> Tuple[Dict[str, Any], int, int]:
        client = self._get_client()
        contents: List[Any] = ["Extract all invoice details from these page images:"]
        contents.extend(images)

        retries = 0
        last_err = None

        while retries <= self.config.max_retries:
            try:
                response = client.models.generate_content(
                    model=self.config.model,
                    contents=contents,
                    config=dict(
                        system_instruction=EXTRACTION_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=EXTRACTION_SCHEMA,
                        temperature=self.config.temperature,
                    ),
                )
                if not response.text:
                    raise ValueError("Empty or blocked response from Gemini vision")
                data = json.loads(response.text)
                in_tok = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
                out_tok = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
                return data, in_tok, out_tok
            except Exception as e:
                last_err = e
                retries += 1
                time.sleep(0.5 * (2 ** retries))

        raise RuntimeError(f"Failed vision extraction after retries: {last_err}")
