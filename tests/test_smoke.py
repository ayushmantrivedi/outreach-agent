"""
tests/test_smoke.py
====================
Smoke tests — verify each module imports and basic logic works
without needing a real DB, Ollama, or SMTP server.

Run with: pytest tests/ -v
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# LLM Interface
# ---------------------------------------------------------------------------

class TestLLMInterface:
    def test_score_output_keys(self):
        """score_company should always return relevance_score and reasoning."""
        from ai_outreach_agent.models.llm_interface import LLMInterface

        mock_response = json.dumps({"relevance_score": 8, "reasoning": "Great match."})

        with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"models": [{"name": "llama3"}]},
            )
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"response": mock_response},
            )
            mock_post.return_value.raise_for_status = MagicMock()
            mock_get.return_value.raise_for_status = MagicMock()

            llm = LLMInterface(model="llama3")
            result = llm.score_company("AI company", ["Python", "CUDA"], "My project")

        assert "relevance_score" in result
        assert "reasoning" in result
        assert 1.0 <= result["relevance_score"] <= 10.0

    def test_classify_reply(self):
        """classify_reply should return one of three classes."""
        from ai_outreach_agent.models.llm_interface import LLMInterface

        with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"models": [{"name": "llama3"}]},
            )
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"response": '{"classification": "positive"}'},
            )
            mock_post.return_value.raise_for_status = MagicMock()
            mock_get.return_value.raise_for_status = MagicMock()

            llm = LLMInterface(model="llama3")
            label = llm.classify_reply("Thanks! We'd love to chat.")

        assert label in ("positive", "neutral", "negative")


# ---------------------------------------------------------------------------
# Telegram Notifier
# ---------------------------------------------------------------------------

class TestTelegramNotifier:
    def test_send_without_credentials_returns_false(self):
        """Notifier should gracefully return False when no token is set."""
        from ai_outreach_agent.notifications.telegram_notifier import TelegramNotifier
        notifier = TelegramNotifier(token="", chat_id="")
        result = notifier.notify_reply("TestCo", "Hello", "positive")
        assert result is False

    def test_send_success(self):
        """Notifier should return True when the API call succeeds."""
        from ai_outreach_agent.notifications.telegram_notifier import TelegramNotifier

        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            mock_post.return_value.raise_for_status = MagicMock()

            notifier = TelegramNotifier(token="fake_token", chat_id="12345")
            result = notifier.notify_reply("TestCo", "Hello", "positive")

        assert result is True


# ---------------------------------------------------------------------------
# YC Scraper
# ---------------------------------------------------------------------------

class TestYCScraper:
    def test_ai_keyword_filter(self):
        """Only AI-related companies should pass the keyword filter."""
        from ai_outreach_agent.scrapers.yc_scraper import _is_ai_company

        assert _is_ai_company("We build large language models", []) is True
        assert _is_ai_company("We sell sandwiches", ["food", "delivery"]) is False

    def test_email_extraction(self):
        """Email regex should extract valid addresses."""
        from ai_outreach_agent.scrapers.yc_scraper import _extract_email_from_text

        text = "Contact us at hello@example.com for more info."
        assert _extract_email_from_text(text) == "hello@example.com"
        assert _extract_email_from_text("No email here.") is None


# ---------------------------------------------------------------------------
# Embedding Model (mocked)
# ---------------------------------------------------------------------------

class TestEmbeddingModel:
    def test_chunk_text(self):
        """Text chunking should split into correct sized pieces."""
        with (
            patch("ai_outreach_agent.models.embedding_model.SentenceTransformer"),
            patch("ai_outreach_agent.models.embedding_model.PersistentClient"),
        ):
            from ai_outreach_agent.models.embedding_model import EmbeddingModel
            em = EmbeddingModel.__new__(EmbeddingModel)
            em.chunk_size = 10
            em.chunk_overlap = 2

            chunks = em._chunk_text("abcdefghijklmnop")
            assert all(len(c) <= 10 for c in chunks)
            assert len(chunks) > 1


# ---------------------------------------------------------------------------
# Email Generation
# ---------------------------------------------------------------------------

class TestEmailGeneration:
    def test_generate_returns_subject_and_body(self):
        """generate_email should always return a non-empty (subject, body) tuple."""
        with (
            patch("ai_outreach_agent.models.llm_interface.requests.get"),
            patch("ai_outreach_agent.models.llm_interface.requests.post") as mock_post,
            patch("ai_outreach_agent.models.embedding_model.SentenceTransformer"),
            patch("ai_outreach_agent.models.embedding_model.PersistentClient"),
        ):
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"response": "SUBJECT: Test Email\nBODY:\nHello there."},
            )
            mock_post.return_value.raise_for_status = MagicMock()

            from ai_outreach_agent.agents.email_generation_agent import generate_email
            from ai_outreach_agent.models.llm_interface import LLMInterface
            from ai_outreach_agent.models.embedding_model import EmbeddingModel

            # Mock the embedding model's retrieve method
            em = MagicMock(spec=EmbeddingModel)
            em.retrieve.return_value = ["Relevant project context."]

            llm = MagicMock(spec=LLMInterface)
            llm.generate.return_value = "SUBJECT: Test Email\nBODY:\nHello there."

            cfg = {
                "developer_name": "Dev",
                "developer_title": "Engineer",
                "github_repo": "https://github.com/dev/repo",
                "project_name": "Test Project",
                "email_template": "engineering_role",
                "email_tone": "technical",
                "developer_linkedin": "",
                "llm_model": "llama3",
                "ollama_timeout": 30,
                "chroma_collection": "test",
                "embedding_model": "all-MiniLM-L6-v2",
            }

            company = {
                "id": 1,
                "company_name": "TestAI Corp",
                "description": "We build LLMs.",
                "tech_stack": ["Python", "CUDA"],
                "relevance_score": 8.5,
                "reasoning": "Great match for this project.",
            }

            subject, body = generate_email(company, cfg=cfg, embedding_model=em, llm=llm)
            assert isinstance(subject, str) and len(subject) > 0
            assert isinstance(body, str) and len(body) > 0
