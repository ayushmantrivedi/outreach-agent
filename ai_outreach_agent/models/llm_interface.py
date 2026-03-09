"""
models/llm_interface.py
=======================
Thin wrapper around the local Ollama REST API.
Supports Llama 3 and Mistral. All agents use this for LLM calls.
"""

import json
import os
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()

_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


class LLMInterface:
    """
    Wrapper around Ollama's local REST API.

    Parameters
    ----------
    model : str
        Ollama model tag, e.g. 'llama3' or 'mistral'.
    timeout : int
        Request timeout in seconds (default 120).
    """

    def __init__(self, model: str = "llama3", timeout: int = 120):
        self.model = model
        self.timeout = timeout
        self.base_url = _OLLAMA_BASE_URL.rstrip("/")
        self._check_ollama_running()

    def _check_ollama_running(self) -> None:
        """Verify Ollama server is reachable; log a helpful message if not."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            tags = [m["name"] for m in resp.json().get("models", [])]
            logger.info(f"Ollama is running. Available models: {tags}")
            if not any(self.model in t for t in tags):
                logger.warning(
                    f"Model '{self.model}' not found locally. "
                    f"Run: ollama pull {self.model}"
                )
        except requests.exceptions.ConnectionError:
            logger.error(
                "Cannot connect to Ollama. Make sure Ollama is running: "
                "https://ollama.ai  →  ollama serve"
            )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def generate(self, prompt: str, system: Optional[str] = None, json_mode: bool = False) -> str:
        """
        Generate a completion from the local LLM.

        Parameters
        ----------
        prompt : str
            The user prompt.
        system : str, optional
            System-level instruction prepended to context.
        json_mode : bool
            If True, ask Ollama to return raw JSON (format=json).

        Returns
        -------
        str
            Raw text response from the model.
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"

        logger.debug(f"LLM → model={self.model} prompt_len={len(prompt)}")
        resp = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        result = resp.json().get("response", "")
        logger.debug(f"LLM ← response_len={len(result)}")
        return result

    def generate_json(self, prompt: str, system: Optional[str] = None) -> Dict[str, Any]:
        """
        Like generate() but parses and returns a dict.
        Falls back to empty dict on JSON parse error.
        """
        raw = self.generate(prompt, system=system, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"LLM returned non-JSON: {raw[:200]}")
            return {}

    def score_company(self, company_description: str, tech_stack: list,
                      project_description: str) -> Dict[str, Any]:
        """
        Ask the LLM to score company relevance to the project.

        Returns
        -------
        dict with keys: relevance_score (int 1-10), reasoning (str)
        """
        system = (
            "You are an expert AI startup analyst. "
            "Your task is to evaluate how relevant an AI company is to a developer's project. "
            "Always respond in valid JSON with exactly two keys: "
            "'relevance_score' (integer 1-10) and 'reasoning' (one or two sentences)."
        )
        prompt = f"""Company Description:
{company_description}

Company Tech Stack:
{', '.join(tech_stack) if tech_stack else 'Not specified'}

Developer Project:
{project_description}

Score the relevance of this company from 1 (completely irrelevant) to 10 (perfect match).
Return JSON only."""

        result = self.generate_json(prompt, system=system)
        # Normalise types
        score = float(result.get("relevance_score", 0))
        reasoning = result.get("reasoning", "")
        return {"relevance_score": max(1.0, min(10.0, score)), "reasoning": reasoning}

    def classify_reply(self, email_body: str) -> str:
        """
        Classify a reply email as 'positive', 'neutral', or 'negative'.
        """
        system = (
            "You are an expert email classifier. "
            "Classify the email as exactly one of: positive, neutral, negative. "
            "Respond with a JSON object: {\"classification\": \"<label>\"}"
        )
        prompt = f"Email:\n{email_body[:2000]}"
        result = self.generate_json(prompt, system=system)
        return result.get("classification", "neutral").lower()
