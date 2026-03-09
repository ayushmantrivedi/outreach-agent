"""
scrapers/yc_scraper.py
======================
Scrapes Y Combinator companies via their public API and HTML pages.
Filters to AI / ML related companies. Outputs structured dicts
compatible with the `companies` DB schema.
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

# YC Algolia search API — same one their website uses, fully public
_YC_ALGOLIA_URL = "https://45bwzj1sgc-dsn.algolia.net/1/indexes/*/queries"
_YC_ALGOLIA_APP_ID = "45BWZJ1SGC"
_YC_ALGOLIA_API_KEY = "Oa0057tn758szitnqu6HMtWaD7O1jMBXBWgKlLBDGaQ="

_AI_KEYWORDS = [
    "artificial intelligence", "machine learning", "deep learning",
    "large language model", "llm", "nlp", "computer vision",
    "generative ai", "foundation model", "mlops", "ai infrastructure",
    "neural network", "transformer", "rag", "vector database",
    "autonomous", "robotics ai", "diffusion model",
]


def _is_ai_company(description: str, tags: List[str]) -> bool:
    """Return True if the company appears to be AI-related."""
    text = (description + " " + " ".join(tags)).lower()
    return any(kw in text for kw in _AI_KEYWORDS)


def _extract_email_from_text(text: str) -> Optional[str]:
    """Pull the first email address out of a block of text."""
    match = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    return match.group(0) if match else None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=15))
def _fetch_yc_batch(page: int, hits_per_page: int = 50) -> List[Dict]:
    """Fetch one page of results from YC Algolia API."""
    payload = {
        "requests": [
            {
                "indexName": "YCCompany_production",
                "params": (
                    f"hitsPerPage={hits_per_page}&page={page}"
                    "&attributesToRetrieve=name,website,one_liner,long_description,"
                    "tags,batch,status,linkedin_url,location"
                    "&filters=status%3AActive%20OR%20status%3APublic"
                ),
            }
        ]
    }
    resp = requests.post(
        _YC_ALGOLIA_URL,
        json=payload,
        headers={
            **_HEADERS,
            "X-Algolia-Application-Id": _YC_ALGOLIA_APP_ID,
            "X-Algolia-API-Key": _YC_ALGOLIA_API_KEY,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["results"][0].get("hits", [])


def _scrape_contact_email(website: str) -> Optional[str]:
    """
    Try to find a contact email on the company website.
    Checks /contact, /about, and the root page.
    """
    if not website:
        return None
    base = website.rstrip("/")
    for path in ["", "/contact", "/about", "/team"]:
        try:
            resp = requests.get(f"{base}{path}", headers=_HEADERS, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                email = _extract_email_from_text(resp.text)
                if email:
                    return email
        except Exception:
            pass
        time.sleep(0.5)
    return None


def scrape_yc_companies(
    max_pages: int = 10,
    scrape_emails: bool = False,
) -> Generator[Dict, None, None]:
    """
    Yields structured company dicts from YC Algolia API.

    Parameters
    ----------
    max_pages : int
        How many pages (50 companies each) to fetch.
    scrape_emails : bool
        If True, attempts to find contact email by visiting each website.
        Slow but produces better data quality.
    """
    logger.info(f"Scraping YC companies — up to {max_pages * 50} records.")
    seen_domains = set()

    for page in range(max_pages):
        hits = _fetch_yc_batch(page=page)
        if not hits:
            logger.info(f"No more results at page {page}.")
            break

        for hit in hits:
            description = (hit.get("long_description") or hit.get("one_liner") or "").strip()
            tags: List[str] = hit.get("tags") or []

            if not _is_ai_company(description, tags):
                continue

            website = (hit.get("website") or "").rstrip("/")
            if not website:
                continue

            # Deduplicate by domain
            domain = re.sub(r"https?://(www\.)?", "", website).split("/")[0]
            if domain in seen_domains:
                continue
            seen_domains.add(domain)

            contact_email = None
            if scrape_emails:
                contact_email = _scrape_contact_email(website)

            record = {
                "company_name": hit.get("name", "").strip(),
                "website": website,
                "description": description,
                "tech_stack": tags,
                "contact_email": contact_email,
                "linkedin": hit.get("linkedin_url"),
                "location": hit.get("location", ""),
                "source": "yc",
            }
            logger.debug(f"YC: {record['company_name']} ({website})")
            yield record

        logger.info(f"YC page {page + 1}/{max_pages} done.")
        time.sleep(1)  # be polite
