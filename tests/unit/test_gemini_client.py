from urllib.error import HTTPError

import pytest

from all3_radar.summarization.gemini_client import GeminiClient, GeminiUnavailableError


def test_gemini_client_disables_after_http_429(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GeminiClient(api_key="test-key", model="gemini-2.0-flash-lite")

    def _raise_429(*args, **kwargs):
        raise HTTPError("https://example.com", 429, "Too Many Requests", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", _raise_429)

    with pytest.raises(GeminiUnavailableError):
        client.generate_summary("Title", "Preview")

    assert client.is_available is False

    with pytest.raises(GeminiUnavailableError, match="disabled for run"):
        client.generate_summary("Title", "Preview")
