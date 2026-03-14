"""
pipelines/daily_outreach_pipeline.py
=====================================
Prefect flow that runs the full outreach pipeline once per day.

Tasks (in order):
  1. discover    — scrape new companies
  2. rank        — score companies with LLM
  3. ingest      — embed project knowledge in ChromaDB
  4. generate    — write personalised emails
  5. send        — deliver emails via SMTP
  6. monitor     — check inbox for replies and notify

Run manually: python -m ai_outreach_agent.pipelines.daily_outreach_pipeline
Schedule:     prefect deployment run daily-outreach-pipeline/local
"""

import os
from typing import Dict

import yaml
from ai_outreach_agent.utils import load_env
from loguru import logger
from prefect import flow, task

# Agent imports
from ai_outreach_agent.agents.discovery_agent import run_discovery
from ai_outreach_agent.agents.ranking_agent import run_ranking
from ai_outreach_agent.agents.email_generation_agent import run_email_generation
from ai_outreach_agent.agents.email_sender_agent import run_email_sending
from ai_outreach_agent.agents.reply_monitor_agent import check_inbox_once
from ai_outreach_agent.database.db import get_qualified_companies, apply_schema
from ai_outreach_agent.models.embedding_model import EmbeddingModel
from ai_outreach_agent.notifications.telegram_notifier import TelegramNotifier

load_env()

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Individual Prefect tasks
# ---------------------------------------------------------------------------

@task(name="Ensure DB Schema", retries=2)
def task_ensure_schema() -> None:
    """Apply DB schema (idempotent)."""
    logger.info("Ensuring database schema is up to date …")
    apply_schema()


@task(name="Discover Companies", retries=1)
def task_discover(yc_pages: int = 10, directory_pages: int = 3) -> int:
    """Run all scrapers and return number of new companies inserted."""
    return run_discovery(yc_pages=yc_pages, directory_pages=directory_pages)


@task(name="Rank Companies", retries=1)
def task_rank(batch_size: int = 200) -> Dict:
    """Score unranked companies and return ranking stats."""
    return run_ranking(batch_size=batch_size)


@task(name="Ingest Project Knowledge", retries=1)
def task_ingest_knowledge() -> int:
    """Embed GitHub README + project description into ChromaDB."""
    cfg = _load_config()
    em = EmbeddingModel(
        collection_name=cfg.get("chroma_collection", "project_knowledge"),
        model_name=cfg.get("embedding_model", "all-MiniLM-L6-v2"),
        chunk_size=cfg.get("chunk_size", 500),
        chunk_overlap=cfg.get("chunk_overlap", 50),
    )
    total = 0
    repo = cfg.get("github_repo", "")
    if repo:
        total += em.ingest_github_repo(repo)
    desc = cfg.get("project_description", "")
    if desc:
        total += em.ingest_project_description(desc)
    return total


@task(name="Generate Emails", retries=1)
def task_generate_emails(companies: list) -> list:
    """Generate personalised emails for each qualified company."""
    cfg = _load_config()
    return run_email_generation(companies, cfg=cfg)


@task(name="Send Emails", retries=0)
def task_send_emails(emails: list) -> Dict:
    """Send generated emails via SMTP; returns stats dict."""
    return run_email_sending(emails)


@task(name="Monitor Inbox", retries=0)
def task_monitor_inbox() -> int:
    """Do a single inbox check and process any replies."""
    return check_inbox_once()


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

@flow(name="daily-outreach-pipeline", log_prints=True)
def daily_outreach_pipeline(
    yc_pages: int = 10,
    directory_pages: int = 3,
    ranking_batch_size: int = 200,
) -> Dict:
    """
    Full daily outreach pipeline.

    Parameters
    ----------
    yc_pages : int
        YC Algolia pages to scrape (50 companies each).
    directory_pages : int
        AI directory pages.
    ranking_batch_size : int
        Max companies to rank in one run.

    Returns
    -------
    dict
        Summary of the pipeline run.
    """
    logger.info("=== Daily Outreach Pipeline Started ===")
    notifier = TelegramNotifier()

    # Step 1 — Schema
    task_ensure_schema()

    # Step 2 — Discovery
    discovered = task_discover(yc_pages=yc_pages, directory_pages=directory_pages)

    # Step 3 — Ranking
    rank_stats = task_rank(batch_size=ranking_batch_size)

    # Step 4 — Ingest project knowledge
    chunks_ingested = task_ingest_knowledge()
    logger.info(f"Knowledge base: {chunks_ingested} chunks ingested/updated.")

    # Step 5 — Generate emails for qualified companies
    qualified = get_qualified_companies(already_emailed=False)
    logger.info(f"{len(qualified)} qualified companies pending outreach.")

    emails = task_generate_emails(qualified)

    # Step 6 — Send
    send_stats = task_send_emails(emails)

    # Step 7 — Monitor inbox once
    replies_found = task_monitor_inbox()

    # Summary
    stats = {
        "discovered": discovered,
        "ranked": rank_stats.get("ranked", 0),
        "qualified": rank_stats.get("qualified", 0),
        "emails_generated": len(emails),
        "sent": send_stats.get("sent", 0),
        "failed": send_stats.get("failed", 0),
        "replies_found": replies_found,
    }

    logger.success(f"=== Pipeline Complete: {stats} ===")
    notifier.notify_pipeline_complete(stats)
    return stats


if __name__ == "__main__":
    daily_outreach_pipeline()
