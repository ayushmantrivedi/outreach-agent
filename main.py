"""
main.py
=======
CLI entry point for the AI Outreach Agent.

Usage examples:
  python main.py --mode pipeline          # Run full daily pipeline
  python main.py --mode discover          # Only run discovery scrapers
  python main.py --mode rank              # Only rank companies
  python main.py --mode ingest            # Only ingest project knowledge
  python main.py --mode send              # Generate + send to qualified companies
  python main.py --mode monitor           # Start continuous inbox monitor
  python main.py --mode schema            # Apply DB schema only
  python main.py --mode status            # Print pipeline status summary
"""

import argparse
import sys

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# Configure loguru for clean output
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
    colorize=True,
)
logger.add(
    "logs/outreach_agent.log",
    rotation="10 MB",
    retention="30 days",
    level="DEBUG",
)


def run_pipeline(_args):
    from ai_outreach_agent.pipelines.daily_outreach_pipeline import daily_outreach_pipeline
    daily_outreach_pipeline()


def run_discover(_args):
    from ai_outreach_agent.agents.discovery_agent import run_discovery
    run_discovery(scrape_emails=False)


def run_rank(_args):
    from ai_outreach_agent.agents.ranking_agent import run_ranking
    run_ranking()


def run_ingest(_args):
    import yaml, os
    cfg_path = os.path.join(os.path.dirname(__file__), "ai_outreach_agent", "config", "settings.yaml")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    from ai_outreach_agent.models.embedding_model import EmbeddingModel
    em = EmbeddingModel(
        collection_name=cfg.get("chroma_collection", "project_knowledge"),
        model_name=cfg.get("embedding_model", "all-MiniLM-L6-v2"),
    )
    total = 0
    if cfg.get("github_repo"):
        total += em.ingest_github_repo(cfg["github_repo"])
    if cfg.get("project_description"):
        total += em.ingest_project_description(cfg["project_description"])
    logger.success(f"Ingest complete: {total} chunks stored.")


def run_send(_args):
    from ai_outreach_agent.database.db import get_qualified_companies
    from ai_outreach_agent.agents.email_generation_agent import run_email_generation
    from ai_outreach_agent.agents.email_sender_agent import run_email_sending
    companies = get_qualified_companies(already_emailed=False)
    logger.info(f"Qualified companies to email: {len(companies)}")
    emails = run_email_generation(companies)
    run_email_sending(emails)


def run_monitor(_args):
    from ai_outreach_agent.agents.reply_monitor_agent import run_reply_monitor
    run_reply_monitor()


def run_schema(_args):
    from ai_outreach_agent.database.db import apply_schema
    apply_schema()
    logger.success("Schema applied.")


def run_status(_args):
    from ai_outreach_agent.database.db import get_connection, get_daily_sent_count
    from psycopg2.extras import RealDictCursor

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS total FROM companies;")
            total_companies = cur.fetchone()["total"]
            cur.execute("SELECT COUNT(*) AS qualified FROM companies WHERE is_qualified=TRUE;")
            qualified = cur.fetchone()["qualified"]
            cur.execute("SELECT COUNT(*) AS sent FROM emails_sent WHERE status='sent';")
            sent = cur.fetchone()["sent"]
            cur.execute("SELECT COUNT(*) AS replies FROM replies;")
            replies = cur.fetchone()["replies"]

    sent_today = get_daily_sent_count()

    print(f"""
╔══════════════════════════════════════╗
║       AI Outreach Agent Status       ║
╠══════════════════════════════════════╣
║ Companies discovered : {total_companies:<15}║
║ Qualified (score>7)  : {qualified:<15}║
║ Emails sent (total)  : {sent:<15}║
║ Emails sent (today)  : {sent_today:<15}║
║ Replies received     : {replies:<15}║
╚══════════════════════════════════════╝
""")


_COMMANDS = {
    "pipeline": run_pipeline,
    "discover": run_discover,
    "rank": run_rank,
    "ingest": run_ingest,
    "send": run_send,
    "monitor": run_monitor,
    "schema": run_schema,
    "status": run_status,
}


def main():
    parser = argparse.ArgumentParser(
        description="AI Outreach Agent — autonomous startup outreach system",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=list(_COMMANDS.keys()),
        help="\n".join([
            "pipeline  : run full daily pipeline",
            "discover  : scrape companies only",
            "rank      : score companies with LLM",
            "ingest    : embed project knowledge",
            "send      : generate + send emails",
            "monitor   : watch inbox continuously",
            "schema    : apply DB schema",
            "status    : print quick stats",
        ]),
    )
    args = parser.parse_args()
    handler = _COMMANDS[args.mode]

    try:
        handler(args)
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    except Exception as exc:
        logger.exception(f"Fatal error in mode '{args.mode}': {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
