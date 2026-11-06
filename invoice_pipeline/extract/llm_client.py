from __future__ import annotations

import base64
import io
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple
from invoice_pipeline.config import LLMConfig
from invoice_pipeline.extract.prompts import EXTRACTION_SYSTEM_PROMPT
from invoice_pipeline.extract.schema import EXTRACTION_SCHEMA


class LLMClient:
    """Wrapper for OpenAI-compatible LLM endpoint with retries and structured schema support."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            api_key = (
                os.environ.get(self.config.api_key_env)
                or os.environ.get("EXPLABS_API_KEY")
                or os.environ.get("GEMINI_API_KEY")
            )
            if not api_key:
                raise PermissionError(
                    f"LLM API key not found in environment variable '{self.config.api_key_env}'. "
                    "Cannot perform extraction."
                )
            from openai import OpenAI
            self._client = OpenAI(
                base_url=self.config.base_url,
                api_key=api_key,
                timeout=self.config.timeout_s,
            )
        return self._client

    @staticmethod
    def _parse_json(raw_text: str) -> Dict[str, Any]:
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return json.loads(text)

    def _get_system_prompt(self) -> str:
        return (
            f"{EXTRACTION_SYSTEM_PROMPT}\n\n"
            "Expected JSON schema format:\n"
            f"{json.dumps(EXTRACTION_SCHEMA, indent=2)}"
        )

    def extract_from_text(self, text: str) -> Tuple[Dict[str, Any], int, int]:
        client = self._get_client()
        system_content = self._get_system_prompt()
        prompt = f"Invoice raw text:\n\n{text}"

        retries = 0
        last_err = None

        while retries <= self.config.max_retries:
            try:
                response = client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=self.config.temperature,
                )
                choice = response.choices[0]
                raw_text = choice.message.content or ""
                if not raw_text:
                    raise ValueError("Empty or blocked response from LLM model")
                data = self._parse_json(raw_text)
                in_tok = getattr(response.usage, "prompt_tokens", 0) or 0
                out_tok = getattr(response.usage, "completion_tokens", 0) or 0
                return data, in_tok, out_tok
            except Exception as e:
                last_err = e
                retries += 1
                time.sleep(0.5 * (2 ** retries))

        raise RuntimeError(f"Failed to extract structured data from LLM after retries: {last_err}")

    def generate_json(self, system_prompt: str, user_prompt: str) -> Tuple[Dict[str, Any], int, int]:
        """Generates structured JSON response from custom system and user prompts."""
        client = self._get_client()
        retries = 0
        last_err = None

        while retries <= self.config.max_retries:
            try:
                response = client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=self.config.temperature,
                )
                choice = response.choices[0]
                raw_text = choice.message.content or ""
                if not raw_text:
                    raise ValueError("Empty or blocked response from LLM model")
                data = self._parse_json(raw_text)
                in_tok = getattr(response.usage, "prompt_tokens", 0) or 0
                out_tok = getattr(response.usage, "completion_tokens", 0) or 0
                return data, in_tok, out_tok
            except Exception as e:
                last_err = e
                retries += 1
                time.sleep(0.5 * (2 ** retries))

        raise RuntimeError(f"Failed to generate JSON from LLM after retries: {last_err}")

    def extract_from_images(self, images: List[Any]) -> Tuple[Dict[str, Any], int, int]:
        client = self._get_client()
        system_content = self._get_system_prompt()

        user_content: List[Dict[str, Any]] = [
            {"type": "text", "text": "Extract all invoice details from these page images:"}
        ]

        for img in images:
            if hasattr(img, "save"):  # PIL Image
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64_str}"},
                })
            elif isinstance(img, bytes):
                b64_str = base64.b64encode(img).decode("utf-8")
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64_str}"},
                })
            elif isinstance(img, str) and os.path.exists(img):
                with open(img, "rb") as f:
                    b64_str = base64.b64encode(f.read()).decode("utf-8")
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64_str}"},
                })

        retries = 0
        last_err = None

        while retries <= self.config.max_retries:
            try:
                response = client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": user_content},
                    ],
                    response_format={"type": "json_object"},
                    temperature=self.config.temperature,
                )
                choice = response.choices[0]
                raw_text = choice.message.content or ""
                if not raw_text:
                    raise ValueError("Empty or blocked response from LLM vision")
                data = self._parse_json(raw_text)
                in_tok = getattr(response.usage, "prompt_tokens", 0) or 0
                out_tok = getattr(response.usage, "completion_tokens", 0) or 0
                return data, in_tok, out_tok
            except Exception as e:
                last_err = e
                retries += 1
                time.sleep(0.5 * (2 ** retries))

        raise RuntimeError(f"Failed vision extraction after retries: {last_err}")
