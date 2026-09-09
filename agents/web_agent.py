"""
agents/web_agent.py -- Web search and URL browsing for Hermes.

Functions:
    web_search(query, max_results)  -- multi-engine search with fallback chain
    browse_url(url)                 -- Fetch and extract readable text from any URL

Search priority: Brave -> Exa -> OpenAlex -> Semantic Scholar -> DDG lite -> DDG html
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_TIMEOUT = 15.0
_MAX_TEXT = 8000  # chars returned to LLM


# -- Helpers ------------------------------------------------------------------

def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname or ""
        private = ("localhost", "127.", "10.", "192.168.", "172.16.", "::1")
        return not any(host.startswith(p) or host == p for p in private)
    except Exception:
        return False


# -- Public API ---------------------------------------------------------------

async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Multi-engine search with automatic fallback.
    Priority: Brave -> Exa -> OpenAlex -> Semantic Scholar -> DDG lite -> DDG html
    Returns list of {"title", "url", "snippet"} dicts.
    """
    encoded = quote_plus(query)
    engines = [
        ("brave",            lambda: _search_brave(query, max_results)),
        ("exa",              lambda: _search_exa(query, max_results)),
        ("openalex",         lambda: _search_openalex(query, max_results)),
        ("semantic-scholar", lambda: _search_semantic_scholar(query, max_results)),
        ("ddg-lite",         lambda: _fetch_ddg(
            "https://lite.duckduckgo.com/lite/?q=" + encoded, _parse_ddg_lite, max_results)),
        ("ddg-html",         lambda: _fetch_ddg(
            "https://html.duckduckgo.com/html/?q=" + encoded, _parse_ddg_html, max_results)),
    ]
    for name, fn in engines:
        try:
            results = await fn()
            if results:
                logger.info(f"web_search({query!r}) -> {len(results)} results via {name}")
                return results
        except Exception as e:
            logger.warning(f"web_search [{name}] failed: {e}, trying next...")
    logger.error(f"web_search({query!r}) -- all engines failed")
    return []


# -- Search backends ----------------------------------------------------------

async def _search_brave(query: str, max_results: int) -> list[dict]:
    if not config.BRAVE_API_KEY:
        raise RuntimeError("BRAVE_API_KEY not set")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"Accept": "application/json", "X-Subscription-Token": config.BRAVE_API_KEY},
        )
        resp.raise_for_status()
    items = resp.json().get("web", {}).get("results", [])
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
        for r in items[:max_results] if r.get("url")
    ]


async def _search_exa(query: str, max_results: int) -> list[dict]:
    if not config.EXA_API_KEY:
        raise RuntimeError("EXA_API_KEY not set")
    from exa_py import Exa  # type: ignore
    exa = Exa(api_key=config.EXA_API_KEY)
    response = exa.search_and_contents(query, type="auto", num_results=max_results, text=True)
    results = []
    for r in response.results:
        snippet = ""
        if hasattr(r, "text") and r.text:
            snippet = r.text[:300]
        elif hasattr(r, "highlights") and r.highlights:
            snippet = " ".join(r.highlights)[:300]
        results.append({"title": r.title or "", "url": r.url, "snippet": snippet})
    return results


async def _search_openalex(query: str, max_results: int) -> list[dict]:
    """OpenAlex -- free, 250M+ academic works, no API key needed."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://api.openalex.org/works",
            params={
                "search": query,
                "per-page": max_results,
                "select": "id,title,abstract_inverted_index,primary_location,publication_year,doi",
                "mailto": "hermes@bot.app",
            },
        )
        resp.raise_for_status()
    results = []
    for item in resp.json().get("results", []):
        title = item.get("title") or ""
        doi   = item.get("doi", "")
        loc   = item.get("primary_location") or {}
        url   = loc.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else "")
        if not url:
            continue
        inv = item.get("abstract_inverted_index") or {}
        abstract = ""
        if inv:
            words = sorted(
                [(pos, word) for word, positions in inv.items() for pos in positions]
            )
            abstract = " ".join(w for _, w in words)[:400]
        year = item.get("publication_year", "")
        snippet = f"({year}) {abstract}".strip() if year else abstract
        results.append({"title": title, "url": url, "snippet": snippet})
    return results


async def _search_semantic_scholar(query: str, max_results: int) -> list[dict]:
    """Semantic Scholar -- 200M+ papers, no API key needed."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": query,
                "limit": max_results,
                "fields": "title,abstract,url,year,openAccessPdf,externalIds",
            },
            headers={"User-Agent": "HermesBot/1.0"},
        )
        if resp.status_code == 429:
            raise RuntimeError("Semantic Scholar rate limited")
        resp.raise_for_status()
    results = []
    for item in resp.json().get("data", []):
        title = item.get("title") or ""
        url   = item.get("url", "")
        if not url:
            doi = (item.get("externalIds") or {}).get("DOI", "")
            url = f"https://doi.org/{doi}" if doi else ""
        if not url:
            continue
        abstract = (item.get("abstract") or "")[:400]
        oa_pdf   = (item.get("openAccessPdf") or {}).get("url", "")
        snippet  = f"[PDF: {oa_pdf}] {abstract}".strip() if oa_pdf else abstract
        results.append({"title": title, "url": url, "snippet": snippet})
    return results


# -- DDG fallbacks ------------------------------------------------------------

async def _fetch_ddg(url: str, parser, max_results: int) -> list[dict]:
    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    return parser(resp.text, max_results)


def _parse_ddg_lite(html: str, max_results: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    for a in soup.select("a.result-link"):
        title = a.get_text(strip=True)
        href  = a.get("href", "")
        snippet = ""
        parent = a.find_parent("tr")
        if parent:
            nxt = parent.find_next_sibling("tr")
            if nxt:
                td = nxt.select_one(".result-snippet")
                snippet = td.get_text(strip=True) if td else ""
        if title and href and href.startswith("http"):
            results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _parse_ddg_html(html: str, max_results: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    for item in soup.select(".result"):
        title_tag   = item.select_one(".result__title a")
        snippet_tag = item.select_one(".result__snippet")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        href  = title_tag.get("href", "")
        if "uddg=" in href:
            params = parse_qs(urlparse(href).query)
            href = params.get("uddg", [href])[0]
        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
        if title and href:
            results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


# -- browse_url ---------------------------------------------------------------

async def browse_url(url: str) -> dict:
    """
    Fetch a URL and return its readable text content.
    Returns {"url", "title", "text", "error": None} or {"url", "error"}.
    """
    if not _is_safe_url(url):
        return {"url": url, "error": "URL not allowed (invalid scheme or private address)"}

    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT,
                                     follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(f"browse_url HTTP error {e.response.status_code}: {url}")
        return {"url": url, "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        logger.error(f"browse_url failed for {url}: {e}")
        return {"url": url, "error": str(e)}

    content_type = resp.headers.get("content-type", "")
    if "text/html" not in content_type and "text/plain" not in content_type:
        return {"url": url, "error": f"Unsupported content type: {content_type}"}

    soup = BeautifulSoup(resp.text, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else url

    text = _clean_text(resp.text)
    if len(text) > _MAX_TEXT:
        text = text[:_MAX_TEXT] + "\n\n[... content truncated ...]"

    return {"url": url, "title": title, "text": text, "error": None}
