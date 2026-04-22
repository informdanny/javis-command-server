from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import httpx

DUCKDUCKGO_INSTANT_ANSWER_URL = "https://api.duckduckgo.com/"


def search_web(*, query: str, max_results: int = 3, timeout_seconds: float = 8.0) -> dict[str, Any]:
    query_text = query.strip()
    if not query_text:
        return {
            "ok": False,
            "error": "query is required",
            "query": "",
            "provider": "duckduckgo_instant",
            "results": [],
        }

    bounded_results = max(1, min(max_results, 8))
    try:
        response = httpx.get(
            DUCKDUCKGO_INSTANT_ANSWER_URL,
            params={
                "q": query_text,
                "format": "json",
                "no_html": "1",
                "no_redirect": "1",
                "skip_disambig": "1",
            },
            headers={"User-Agent": "javis-command-server/0.2"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # pragma: no cover - covered through tool-level tests
        return {
            "ok": False,
            "error": f"web search failed: {exc.__class__.__name__}: {exc}",
            "query": query_text,
            "provider": "duckduckgo_instant",
            "results": [],
        }

    results = _collect_results(payload, max_results=bounded_results)
    abstract_text = _safe_text(payload.get("AbstractText"))
    abstract_url = _safe_text(payload.get("AbstractURL"))

    output: dict[str, Any] = {
        "ok": True,
        "query": query_text,
        "provider": "duckduckgo_instant",
        "result_count": len(results),
        "results": results,
        "search_url": f"https://duckduckgo.com/?q={quote_plus(query_text)}",
    }
    if abstract_text:
        output["answer"] = abstract_text
    if abstract_url:
        output["answer_url"] = abstract_url
    return output


def _collect_results(payload: Any, *, max_results: int) -> list[dict[str, str]]:
    if not isinstance(payload, dict):
        return []

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    def add_result(title: str, url: str, snippet: str) -> None:
        normalized_url = _safe_text(url)
        if not normalized_url or normalized_url in seen_urls:
            return
        normalized_title = _safe_text(title) or normalized_url
        normalized_snippet = _safe_text(snippet)
        seen_urls.add(normalized_url)
        results.append(
            {
                "title": normalized_title[:180],
                "url": normalized_url,
                "snippet": normalized_snippet[:500],
            }
        )

    heading = _safe_text(payload.get("Heading"))
    abstract_text = _safe_text(payload.get("AbstractText"))
    abstract_url = _safe_text(payload.get("AbstractURL"))
    if abstract_url:
        add_result(heading or "Top result", abstract_url, abstract_text)

    def walk(item: Any) -> None:
        if len(results) >= max_results:
            return
        if isinstance(item, dict):
            text = _safe_text(item.get("Text"))
            first_url = _safe_text(item.get("FirstURL"))
            if first_url:
                add_result(_title_from_text(text), first_url, text)
            topics = item.get("Topics")
            if isinstance(topics, list):
                for child in topics:
                    walk(child)
                    if len(results) >= max_results:
                        return
            return
        if isinstance(item, list):
            for child in item:
                walk(child)
                if len(results) >= max_results:
                    return

    walk(payload.get("RelatedTopics"))
    return results[:max_results]


def _title_from_text(text: str) -> str:
    value = text.strip()
    if not value:
        return "Result"
    for separator in (" - ", " — ", " | ", ": "):
        if separator in value:
            left = value.split(separator, 1)[0].strip()
            if left:
                return left
    return value[:120]


def _safe_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
