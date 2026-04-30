import json
from urllib.error import HTTPError

import pytest

from all3_radar.digest.claude_client import ClaudeDigestClient, ClaudeDigestUnavailableError


class _FakeResponse:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_claude_digest_client_requires_feature_flag() -> None:
    client = ClaudeDigestClient(
        enabled=False,
        api_key="secret",
        model="claude-test",
        timeout_seconds=10,
        max_tokens=500,
    )

    with pytest.raises(ClaudeDigestUnavailableError):
        client.generate_digest_section("prompt")


def test_claude_digest_client_parses_markdown_section(monkeypatch) -> None:
    client = ClaudeDigestClient(
        enabled=True,
        api_key="secret",
        model="claude-test",
        timeout_seconds=10,
        max_tokens=500,
    )

    def fake_urlopen(request, timeout):  # noqa: ANN001
        assert timeout == 10
        return _FakeResponse(
            {
                "content": [
                    {
                        "type": "text",
                        "text": "## Claude Synthesis\n- Funding remained concentrated in construction robotics.\n",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = client.generate_digest_section("prompt")

    assert result.startswith("## Claude Synthesis")


def test_claude_digest_client_rejects_invalid_response(monkeypatch) -> None:
    client = ClaudeDigestClient(
        enabled=True,
        api_key="secret",
        model="claude-test",
        timeout_seconds=10,
        max_tokens=500,
    )

    def fake_urlopen(request, timeout):  # noqa: ANN001
        raise HTTPError("https://api.anthropic.com/v1/messages", 429, "Too Many Requests", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(ClaudeDigestUnavailableError):
        client.generate_digest_section("prompt")


def test_claude_digest_client_selects_exactly_five_unique_ids(monkeypatch) -> None:
    client = ClaudeDigestClient(
        enabled=True,
        api_key="secret",
        model="claude-test",
        timeout_seconds=10,
        max_tokens=500,
    )

    def fake_urlopen(request, timeout):  # noqa: ANN001
        return _FakeResponse(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "selected_ids": ["event-1", "event-2", "event-3", "event-4", "event-5"],
                            }
                        ),
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    selected_ids = client.select_top_story_ids(
        "prompt",
        allowed_ids={"event-1", "event-2", "event-3", "event-4", "event-5", "event-6"},
    )

    assert selected_ids == ["event-1", "event-2", "event-3", "event-4", "event-5"]


def test_claude_digest_client_rejects_invalid_selection_payload(monkeypatch) -> None:
    client = ClaudeDigestClient(
        enabled=True,
        api_key="secret",
        model="claude-test",
        timeout_seconds=10,
        max_tokens=500,
    )

    def fake_urlopen(request, timeout):  # noqa: ANN001
        return _FakeResponse({"content": [{"type": "text", "text": '{"selected_ids":["event-1","event-1"]}'}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(ClaudeDigestUnavailableError):
        client.select_top_story_ids("prompt", allowed_ids={"event-1", "event-2", "event-3", "event-4", "event-5"})


def test_claude_digest_client_validates_telegram_digest_output(monkeypatch) -> None:
    client = ClaudeDigestClient(
        enabled=True,
        api_key="secret",
        model="claude-test",
        timeout_seconds=10,
        max_tokens=500,
    )
    expected_title = "Top 5 News Highlights | 23-30 April 2026 | Week 18"

    def fake_urlopen(request, timeout):  # noqa: ANN001
        return _FakeResponse(
            {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"{expected_title}\n\n"
                            '1. <b>German construction orders recover before capacity does</b>\n'
                            'Destatis signals improving order intake ahead of labor capacity normalization. '
                            '<a href="https://example.com/destatis">Link</a>'
                        ),
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    digest_text = client.generate_telegram_digest("prompt", expected_title=expected_title)

    assert digest_text.startswith(expected_title)
    assert '<a href="https://example.com/destatis">Link</a>' in digest_text


def test_claude_digest_client_rejects_visible_raw_urls(monkeypatch) -> None:
    client = ClaudeDigestClient(
        enabled=True,
        api_key="secret",
        model="claude-test",
        timeout_seconds=10,
        max_tokens=500,
    )
    expected_title = "Top 5 News Highlights | 23-30 April 2026 | Week 18"

    def fake_urlopen(request, timeout):  # noqa: ANN001
        return _FakeResponse(
            {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"{expected_title}\n\n"
                            "1. <b>Bad item</b>\n"
                            'This paragraph leaks https://example.com/raw and also has <a href="https://example.com/raw">Link</a>'
                        ),
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(ClaudeDigestUnavailableError):
        client.generate_telegram_digest("prompt", expected_title=expected_title)
