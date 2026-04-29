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
