from app.web_search import DUCKDUCKGO_HTML_SEARCH_URL, DUCKDUCKGO_INSTANT_ANSWER_URL, search_web


class _DummyResponse:
    def __init__(self, *, json_payload=None, text: str = "", status_code: int = 200):
        self._json_payload = json_payload
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http status {self.status_code}")

    def json(self):
        if self._json_payload is None:
            raise RuntimeError("json payload not set")
        return self._json_payload


def test_search_web_requires_query():
    result = search_web(query="   ", max_results=3, timeout_seconds=3.0)
    assert result["ok"] is False
    assert result["error"] == "query is required"
    assert result["results"] == []


def test_search_web_falls_back_to_html_results(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        if url == DUCKDUCKGO_INSTANT_ANSWER_URL:
            return _DummyResponse(json_payload={"AbstractText": "", "RelatedTopics": []})
        if url == DUCKDUCKGO_HTML_SEARCH_URL:
            return _DummyResponse(
                text=(
                    '<a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fnews">Example News</a>'
                    '<a class="result__snippet">Breaking update from example.</a>'
                )
            )
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("app.web_search.httpx.get", fake_get)

    result = search_web(query="latest example update", max_results=1, timeout_seconds=3.0)

    assert result["ok"] is True
    assert result["provider"] == "duckduckgo_instant+html"
    assert result["result_count"] == 1
    assert result["results"][0]["title"] == "Example News"
    assert result["results"][0]["url"] == "https://example.com/news"
