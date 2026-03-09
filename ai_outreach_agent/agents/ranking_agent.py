"""
agents/ranking_agent.py
=======================
Reads unranked companies from the DB, scores each one against the
current project using the local LLM, and writes results back.
Companies scoring above the configured threshold are promoted to the
outreach queue (is_qualified = TRUE).
"""

import os

import yaml
from dotenv import load_dotenv
from loguru import logger

from ai_outreach_agent.database.db import (
    get_unranked_companies,
    update_company_score,
)
from ai_outreach_agent.models.llm_interface import LLMInterface

load_dotenv()

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def run_ranking(batch_size: int = 100) -> dict:
    """
    Score all unranked companies against the active project.

    Parameters
    ----------
    batch_size : int
        How many companies to process in this run.

    Returns
    -------
    dict
        Summary: {'ranked': N, 'qualified': M}
    """
    cfg = _load_config()
    project_description: str = cfg.get("project_description", "")
    model: str = cfg.get("llm_model", "llama3")
    threshold: float = float(cfg.get("relevance_threshold", 7))
    timeout: int = int(cfg.get("ollama_timeout", 120))

    if not project_description:
        logger.error(
            "project_description is empty in settings.yaml. "
            "Please fill it in before running the ranking agent."
        )
        return {"ranked": 0, "qualified": 0}

    llm = LLMInterface(model=model, timeout=timeout)
    companies = get_unranked_companies(limit=batch_size)

    if not companies:
        logger.info("No unranked companies found. DB is up to date.")
        return {"ranked": 0, "qualified": 0}

    logger.info(f"Ranking {len(companies)} companies with model '{model}' …")
    ranked = 0
    qualified = 0

    for company in companies:
        company_id = company["id"]
        name = company["company_name"]
        description = company.get("description") or ""
        tech_stack = company.get("tech_stack") or []

        # De-serialise JSONB array from psycopg2 (comes back as list already)
        if isinstance(tech_stack, str):
            import json
            tech_stack = json.loads(tech_stack)

        try:
            result = llm.score_company(
                company_description=description,
                tech_stack=tech_stack,
                project_description=project_description,
            )
            score = result.get("relevance_score", 0.0)
            reasoning = result.get("reasoning", "")

            update_company_score(company_id, score, reasoning)
            ranked += 1

            if score > threshold:
                qualified += 1
                logger.info(f"✅  {name}: score={score:.1f} — QUALIFIED")
            else:
                logger.info(f"❌  {name}: score={score:.1f} — below threshold")

        except Exception as exc:
            logger.error(f"Failed to rank company {company_id} ({name}): {exc}")
            # Mark with score 0 so it isn't retried endlessly next run
            update_company_score(company_id, 0.0, f"Error: {exc}")

    logger.success(
        f"Ranking complete: {ranked} companies scored, {qualified} qualified (score > {threshold})."
    )
    return {"ranked": ranked, "qualified": qualified}


if __name__ == "__main__":
    run_ranking()
