"""
agents/email_generation_agent.py
=================================
Generates personalised outreach emails for each qualified company.
Uses ChromaDB to retrieve relevant project context, then passes it
to the local LLM to write a tailored email.

Templates available:
  - research          : collaboration on research / papers
  - engineering_role  : applying / pitching engineering role
  - showcase          : showcasing a tool / project to the company
"""

import os
from typing import Dict, Optional, Tuple

import yaml
from ai_outreach_agent.utils import load_env
from loguru import logger

from ai_outreach_agent.models.llm_interface import LLMInterface
from ai_outreach_agent.models.embedding_model import EmbeddingModel

load_env()

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Email Templates (used as prompt scaffolding for the LLM)
# ---------------------------------------------------------------------------

_TEMPLATE_INSTRUCTIONS = {
    "research": (
        "Write a professional, concise email from an undergraduate/early-career researcher "
        "to a research lab or company, proposing a potential research internship or collaboration "
        "on topics related to the developer's project. "
        "Mention specific technical overlap between the project and the company's work. "
        "Keep it under 180 words. Be specific and genuine — no generic phrases."
    ),
    "engineering_role": (
        "Write a concise, technical cold email from an AI/ML student or early-career developer "
        "seeking an internship or entry-level opportunity at the company. "
        "Lead with the EvoNet project as evidence of hands-on ML skills (evolutionary algorithms, "
        "PyTorch, GPU acceleration, genetic operators like SBX crossover and CMA-ES). "
        "Connect the project's approach to the company's work specifically. "
        "Include a GitHub link. End with a clear, low-pressure ask (e.g. 'Would love to explore "
        "if there are any internship or research opportunities'). Under 200 words. "
        "Tone: technical but human. No buzzwords."
    ),
    "showcase": (
        "Write a brief, enthusiastic email showcasing the EvoNet open-source project "
        "to a company or research lab that works on related areas (evolutionary AI, NAS, RL, etc). "
        "Mention what makes it novel (no backpropagation, population-based GPU training, CMA-ES). "
        "End with an invitation to give feedback or collaborate. Under 150 words."
    ),
}


def generate_email(
    company: Dict,
    cfg: Optional[dict] = None,
    embedding_model: Optional[EmbeddingModel] = None,
    llm: Optional[LLMInterface] = None,
) -> Tuple[str, str]:
    """
    Generate a personalised subject + body for one company.

    Parameters
    ----------
    company : dict
        Company record from the DB (must have company_name, description, etc.)
    cfg : dict, optional
        Settings; loaded from settings.yaml if not provided.
    embedding_model : EmbeddingModel, optional
        Pre-loaded model (avoids reloading for batch calls).
    llm : LLMInterface, optional
        Pre-loaded LLM (avoids reloading for batch calls).

    Returns
    -------
    (subject, body) : Tuple[str, str]
    """
    if cfg is None:
        cfg = _load_config()
    if embedding_model is None:
        embedding_model = EmbeddingModel(
            collection_name=cfg.get("chroma_collection", "project_knowledge"),
            model_name=cfg.get("embedding_model", "all-MiniLM-L6-v2"),
        )
    if llm is None:
        llm = LLMInterface(
            model=cfg.get("llm_model", "llama3"),
            timeout=cfg.get("ollama_timeout", 120),
        )

    developer_name = cfg.get("developer_name", "Developer")
    developer_title = cfg.get("developer_title", "AI Engineer")
    github_repo = cfg.get("github_repo", "")
    project_name = cfg.get("project_name", "My Project")
    template = cfg.get("email_template", "engineering_role")
    email_tone = cfg.get("email_tone", "technical")
    linkedin = cfg.get("developer_linkedin", "")

    company_name = company.get("company_name", "the company")
    company_desc = company.get("description", "")[:400]
    reasoning = company.get("reasoning", "")[:200]

    # Retrieve relevant project knowledge for this company
    query = f"{company_name} {company_desc}"
    relevant_chunks = embedding_model.retrieve(query, top_k=2)
    context_snippet = "\n\n".join(relevant_chunks[:2]) if relevant_chunks else cfg.get("project_description", "")

    template_instruction = _TEMPLATE_INSTRUCTIONS.get(template, _TEMPLATE_INSTRUCTIONS["engineering_role"])

    system = (
        "You are a professional email writer. "
        "Write clear, direct, and human emails. "
        "Avoid buzzwords like 'leverage', 'synergy', 'delighted', 'thrilled'. "
        f"Tone: {email_tone}."
    )

    prompt = f"""Developer Info:
Name: {developer_name}
Title: {developer_title}
GitHub: {github_repo}
LinkedIn: {linkedin}

Project Summary:
{context_snippet}

Company Info:
Name: {company_name}
Description: {company_desc}
Why they're a match: {reasoning}

Task:
{template_instruction}

Format your response as:
SUBJECT: <subject line here>
BODY:
<email body here>"""

    raw = llm.generate(prompt, system=system)

    # Parse subject/body from the LLM output
    subject = f"Re: {project_name} — Connection with {company_name}"
    body = raw.strip()

    if "SUBJECT:" in raw:
        try:
            lines = raw.strip().split("\n")
            for i, line in enumerate(lines):
                if line.startswith("SUBJECT:"):
                    subject = line.replace("SUBJECT:", "").strip()
                if line.strip() == "BODY:":
                    body = "\n".join(lines[i + 1:]).strip()
                    break
        except Exception:
            pass  # fallback to defaults above

    logger.info(f"Email generated for {company_name}: '{subject}'")
    return subject, body


def run_email_generation(companies: list, cfg: Optional[dict] = None) -> list:
    """
    Batch-generate emails for a list of company dicts.

    Returns
    -------
    list of dicts: [{company, subject, body}, ...]
    """
    if cfg is None:
        cfg = _load_config()

    # Preload shared resources
    embedding_model = EmbeddingModel(
        collection_name=cfg.get("chroma_collection", "project_knowledge"),
        model_name=cfg.get("embedding_model", "all-MiniLM-L6-v2"),
    )
    llm = LLMInterface(
        model=cfg.get("llm_model", "llama3"),
        timeout=cfg.get("ollama_timeout", 120),
    )

    results = []
    for company in companies:
        try:
            subject, body = generate_email(company, cfg=cfg, embedding_model=embedding_model, llm=llm)
            results.append({"company": company, "subject": subject, "body": body})
        except Exception as exc:
            logger.error(f"Email generation failed for {company.get('company_name')}: {exc}")

    logger.success(f"Generated {len(results)}/{len(companies)} emails.")
    return results
