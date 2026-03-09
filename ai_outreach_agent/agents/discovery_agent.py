"""
agents/discovery_agent.py
=========================
Orchestrates all scrapers, deduplicates results, and stores
discovered companies into PostgreSQL.
"""

import os
from typing import List

import yaml
from dotenv import load_dotenv
from loguru import logger

from ai_outreach_agent.database.db import insert_company
from ai_outreach_agent.scrapers.yc_scraper import scrape_yc_companies
from ai_outreach_agent.scrapers.startup_directory_scraper import (
    scrape_github_orgs,
    scrape_ai_directory,
)

load_dotenv()

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

    logger.success(f"Discovery complete. Total new companies inserted: {inserted_count}")
    return inserted_count


if __name__ == "__main__":
    run_discovery()
