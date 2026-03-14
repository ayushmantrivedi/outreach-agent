"""
agents/discovery_agent.py
=========================
Orchestrates all scrapers, deduplicates results, and stores
discovered companies into PostgreSQL.
"""

import os
from typing import List

import yaml
from ai_outreach_agent.utils import load_env
from loguru import logger

from ai_outreach_agent.database.db import insert_company
from ai_outreach_agent.scrapers.yc_scraper import scrape_yc_companies
from ai_outreach_agent.scrapers.startup_directory_scraper import (
    scrape_github_orgs,
    scrape_ai_directory,
)

load_env()

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def run_discovery(
    scrape_emails: bool = False,
    yc_pages: int = 10,
    directory_pages: int = 5,
) -> int:
    """
    Run the full discovery pipeline.

    Calls YC scraper, GitHub org scraper, and AI directory scraper.
    Deduplicates by website domain and bulk-inserts into the DB.

    Parameters
    ----------
    scrape_emails : bool
        Whether to visit each company website looking for emails (slow).
    yc_pages : int
        How many YC Algolia pages to fetch (50 companies/page).
    directory_pages : int
        How many TAAFT directory pages to fetch.

    Returns
    -------
    int
        Total number of new companies inserted (duplicates skipped).
    """
    cfg = _load_config()
    github_token = os.getenv("GITHUB_TOKEN")
    github_orgs: List[str] = cfg.get("github_orgs_to_scrape", [])
    sources: List[str] = cfg.get("scraping_sources", ["yc_companies"])

    inserted_count = 0

    # --- YC Companies ---
    if "yc_companies" in sources:
        logger.info("Starting YC Companies scrape …")
        for company in scrape_yc_companies(max_pages=yc_pages, scrape_emails=scrape_emails):
            company_id = insert_company(company)
            if company_id:
                inserted_count += 1
        logger.info(f"YC scrape done. {inserted_count} new records so far.")

    # --- GitHub Orgs ---
    if "github_orgs" in sources and github_orgs:
        logger.info(f"Scraping {len(github_orgs)} GitHub orgs …")
        before = inserted_count
        for company in scrape_github_orgs(github_orgs, github_token=github_token):
            company_id = insert_company(company)
            if company_id:
                inserted_count += 1
        logger.info(f"GitHub orgs done. {inserted_count - before} new records.")

    # --- AI Directory ---
    if "ai_directories" in sources:
        logger.info("Starting AI directory scrape …")
        before = inserted_count
        for company in scrape_ai_directory(max_pages=directory_pages):
            company_id = insert_company(company)
            if company_id:
                inserted_count += 1
        logger.info(f"AI directory done. {inserted_count - before} new records.")

    if inserted_count == 0:
        logger.warning("Scrapers yielded 0 companies (likely rate-limited). Using robust fallback seed list.")
        seed_companies = [
            {"company_name": "Hugging Face", "website": "https://huggingface.co", "description": "Open source ML platform and models.", "tech_stack": ["NLP", "Transformers", "Open Source"], "contact_email": "jobs@huggingface.co", "linkedin": None, "location": "New York, NY", "source": "fallback"},
            {"company_name": "OpenAI", "website": "https://openai.com", "description": "AI research and deployment company behind ChatGPT.", "tech_stack": ["LLM", "Generative AI", "RLHF"], "contact_email": "careers@openai.com", "linkedin": None, "location": "San Francisco, CA", "source": "fallback"},
            {"company_name": "Mistral AI", "website": "https://mistral.ai", "description": "Open weight frontier AI models in Europe.", "tech_stack": ["LLM", "Open Weights"], "contact_email": "contact@mistral.ai", "linkedin": None, "location": "Paris, France", "source": "fallback"},
            {"company_name": "Anthropic", "website": "https://anthropic.com", "description": "AI safety and research company behind Claude.", "tech_stack": ["Constitutional AI", "LLM", "Safety"], "contact_email": "info@anthropic.com", "linkedin": None, "location": "San Francisco, CA", "source": "fallback"},
            {"company_name": "Google DeepMind", "website": "https://deepmind.google", "description": "Building artificial general intelligence to solve global challenges.", "tech_stack": ["RL", "AlphaFold", "AGI"], "contact_email": "press@deepmind.com", "linkedin": None, "location": "London, UK", "source": "fallback"},
            {"company_name": "Cohere", "website": "https://cohere.com", "description": "Enterprise AI platform for search and generation.", "tech_stack": ["NLP", "RAG", "Enterprise AI"], "contact_email": "info@cohere.com", "linkedin": None, "location": "Toronto, Canada", "source": "fallback"},
            {"company_name": "EleutherAI", "website": "https://eleuther.ai", "description": "Non-profit AI research lab focusing on interpretability and alignment.", "tech_stack": ["Open Source", "Interpretability", "LLM"], "contact_email": "contact@eleuther.ai", "linkedin": None, "location": "Remote", "source": "fallback"},
            {"company_name": "Weights & Biases", "website": "https://wandb.ai", "description": "Developer tools for machine learning and MLOps.", "tech_stack": ["MLOps", "Tracking", "Evaluation"], "contact_email": "support@wandb.com", "linkedin": None, "location": "San Francisco, CA", "source": "fallback"},
            {"company_name": "Together AI", "website": "https://together.ai", "description": "Cloud platform for building and running open source AI.", "tech_stack": ["Cloud", "Inference", "Training"], "contact_email": "support@together.ai", "linkedin": None, "location": "San Francisco, CA", "source": "fallback"},
            {"company_name": "Scale AI", "website": "https://scale.com", "description": "Data infrastructure for AI, RLHF, and evaluation.", "tech_stack": ["Data Engine", "RLHF", "Evaluation"], "contact_email": "careers@scale.com", "linkedin": None, "location": "San Francisco, CA", "source": "fallback"},
        ]
        for comp in seed_companies:
            if insert_company(comp):
                inserted_count += 1
        logger.info(f"Fallback complete. Inserted {inserted_count} seed companies.")

    logger.success(f"Discovery complete. Total new companies inserted: {inserted_count}")
    return inserted_count


if __name__ == "__main__":
    run_discovery()
