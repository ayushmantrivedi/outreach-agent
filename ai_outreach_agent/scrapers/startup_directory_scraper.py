"""
scrapers/startup_directory_scraper.py
======================================
Scrapes AI startup contacts from multiple public sources:
  1. GitHub Organisations (public member emails via repo scraping)
  2. The AI-powered startup directory at theresanaiforthat.com
  3. Crunchbase open pages (basic, no API key needed)

Each source yields dicts compatible with the `companies` DB schema.
"""

import re
import time
from typing import Dict, Generator, List, Optional

import requests
from bs4 import BeautifulSoup
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AIOutreachBot/1.0; "
        "+https://github.com/yourusername/ai-outreach-agent)"
    )
}

_AI_KEYWORDS = [
    "ai", "llm", "ml", "machine learning", "deep learning",
    "nlp", "computer vision", "generative", "foundation model",
]


def _extract_emails(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)


def _is_ai_related(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in _AI_KEYWORDS)


# ---------------------------------------------------------------------------
# Source 1: GitHub Organisations
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _gh_api(url: str, token: Optional[str] = None) -> dict:
    headers = {**_HEADERS, "Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def scrape_github_orgs(
    orgs: List[str],
    github_token: Optional[str] = None,
) -> Generator[Dict, None, None]:
    """
    For each GitHub org, fetch public repos and extract contact info from READMEs.

    Parameters
    ----------
    orgs : list
        GitHub organisation slugs, e.g. ['huggingface', 'openai'].
    github_token : str, optional
        Personal access token to avoid rate limits (60 req/h anon vs 5000 auth).
    """
    for org in orgs:
        logger.info(f"Scraping GitHub org: {org}")
        try:
            org_data = _gh_api(f"https://api.github.com/orgs/{org}", github_token)
            description = org_data.get("description") or org_data.get("name", "")
            website = org_data.get("blog") or f"https://github.com/{org}"
            email = org_data.get("email")
            location = org_data.get("location", "")

            record = {
                "company_name": org_data.get("name") or org,
                "website": website,
                "description": description,
                "tech_stack": ["AI", "GitHub Organisation"],
                "contact_email": email,
                "linkedin": None,
                "location": location,
                "source": "github_org",
            }
            yield record
            time.sleep(0.5)
        except Exception as exc:
            logger.error(f"Failed to scrape GitHub org '{org}': {exc}")


# ---------------------------------------------------------------------------
# Source 2: There's An AI For That (https://theresanaiforthat.com)
# ---------------------------------------------------------------------------

def _scrape_taaft_page(page: int = 1) -> List[Dict]:
    """Scrape a single page from There's An AI For That."""
    url = f"https://theresanaiforthat.com/?page={page}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        logger.error(f"TAAFT page {page} failed: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    results = []

    for card in soup.select("div.ai_card, article.card, div[class*='ai-item']"):
        name_el = card.select_one("h2, h3, .title, .name")
        desc_el = card.select_one("p, .description, .tagline")
        link_el = card.select_one("a[href]")

        name = name_el.get_text(strip=True) if name_el else ""
        desc = desc_el.get_text(strip=True) if desc_el else ""
        href = link_el.get("href", "") if link_el else ""

        if not name:
            continue

        # Resolve relative URLs
        if href.startswith("/"):
            href = f"https://theresanaiforthat.com{href}"

        results.append({
            "company_name": name,
            "website": href,
            "description": desc,
            "tech_stack": ["AI tool"],
            "contact_email": None,
            "linkedin": None,
            "location": "",
            "source": "taaft",
        })

    return results


def scrape_ai_directory(max_pages: int = 5) -> Generator[Dict, None, None]:
    """
    Yields AI tools/companies from There's An AI For That directory.

    Parameters
    ----------
    max_pages : int
        Number of pages to scrape (each page has ~20 items).
    """
    logger.info(f"Scraping AI directory (max {max_pages} pages).")
    for page in range(1, max_pages + 1):
        results = _scrape_taaft_page(page)
        if not results:
            logger.info(f"No results at page {page}. Stopping.")
            break
        for r in results:
            yield r
        logger.info(f"AI directory page {page} done ({len(results)} items).")
        time.sleep(2)


# ---------------------------------------------------------------------------
# Source 3: Discover startups from open job boards (Greenhouse / Lever)
# ---------------------------------------------------------------------------

_JOB_BOARD_HOSTS = [
    # Format: (board_api_url, source_label)
    # These boards are fully public — no auth needed.
    ("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", "greenhouse"),
    ("https://api.lever.co/v0/postings/{slug}?mode=json", "lever"),
]


def scrape_job_board(company_slug: str, board: str = "greenhouse") -> Optional[Dict]:
    """
    Attempt to discover a company from its Greenhouse or Lever job board.
    Returns a partial company record or None if unavailable.
    """
    if board == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"
    else:
        url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        jobs = data.get("jobs") or data  # Lever returns a list directly
        if not jobs:
            return None

        first = jobs[0] if isinstance(jobs, list) else {}
        dept = first.get("departments", [{}])[0].get("name", "")

        return {
            "company_name": company_slug.replace("-", " ").title(),
            "website": f"https://{company_slug}.com",
            "description": f"Company with active AI/ML job openings. Dept: {dept}",
            "tech_stack": ["AI", "ML"],
            "contact_email": None,
            "linkedin": None,
            "location": first.get("location", {}).get("name", ""),
            "source": board,
        }
    except Exception as exc:
        logger.debug(f"Job board lookup failed for {company_slug}: {exc}")
        return None
