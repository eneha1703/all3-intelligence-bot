import json
from urllib.error import HTTPError

import pytest

from all3_radar.summarization.claude_final_card_client import (
    ClaudeFinalCardClient,
    ClaudeFinalCardUnavailableError,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def _client(**overrides: object) -> ClaudeFinalCardClient:
    defaults = {
        "enabled": True,
        "api_key": "test-key",
        "model": "claude-3-5-sonnet-latest",
        "timeout_seconds": 12,
        "max_tokens": 300,
    }
    defaults.update(overrides)
    return ClaudeFinalCardClient(**defaults)


def _payload(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _generate(client: ClaudeFinalCardClient) -> object:
    return client.generate_final_card(
        title="Acme launches warehouse robot pilot in Germany",
        source="The Robot Report",
        url="https://example.com/story",
        text_preview="Acme said the pilot covers three German facilities and will expand next quarter.",
        score=88,
        event_flags={"deployment_event": True},
        signals={"competitor_count": 1},
        existing_summary="Acme launched a warehouse robot pilot across three German facilities.",
    )


def test_client_parses_valid_send_ok_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": True,
                        "reject_reason": None,
                        "title": "Acme launches warehouse robot pilot in Germany",
                        "summary": "Acme launched a warehouse robot pilot across three German facilities. The company said expansion is planned next quarter.",
                        "why_it_matters": "The rollout shows a real multi-site warehouse deployment, not just a demo.",
                        "duplicate_risk": "low",
                        "confidence": "high",
                    }
                )
            )
        ),
    )

    result = _generate(_client())

    assert result.send_ok is True
    assert result.title == "Acme launches warehouse robot pilot in Germany"
    assert result.summary is not None
    assert result.duplicate_risk == "low"
    assert result.confidence == "high"
    assert result.used_claude is True


def test_client_parses_valid_rejection_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": False,
                        "reject_reason": "generic",
                        "title": None,
                        "summary": None,
                        "why_it_matters": None,
                        "duplicate_risk": "medium",
                        "confidence": "high",
                    }
                )
            )
        ),
    )

    result = _generate(_client())

    assert result.send_ok is False
    assert result.reject_reason == "generic"
    assert result.title is None
    assert result.summary is None


def test_invalid_json_raises_controlled_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(_payload("not-json")),
    )

    with pytest.raises(ClaudeFinalCardUnavailableError, match="not valid JSON"):
        _generate(_client())


def test_missing_send_ok_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(json.dumps({"title": "A", "summary": "B"}))
        ),
    )

    with pytest.raises(ClaudeFinalCardUnavailableError, match="send_ok"):
        _generate(_client())


def test_send_ok_requires_usable_title_and_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": True,
                        "reject_reason": None,
                        "title": "   ",
                        "summary": "",
                        "why_it_matters": None,
                        "duplicate_risk": "low",
                        "confidence": "high",
                    }
                )
            )
        ),
    )

    with pytest.raises(ClaudeFinalCardUnavailableError, match="usable title"):
        _generate(_client())


def test_invalid_duplicate_risk_or_confidence_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": True,
                        "reject_reason": None,
                        "title": "Acme launches warehouse robot pilot",
                        "summary": "Acme launched a warehouse robot pilot in Germany. The rollout covers three facilities.",
                        "why_it_matters": "This is an operational deployment.",
                        "duplicate_risk": "unclear",
                        "confidence": "high",
                    }
                )
            )
        ),
    )

    with pytest.raises(ClaudeFinalCardUnavailableError, match="duplicate_risk"):
        _generate(_client())


def test_overlong_output_is_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": True,
                        "reject_reason": None,
                        "title": "Acme launches warehouse robot pilot in Germany with additional detail that keeps going well past the expected title limit for a Telegram card",
                        "summary": (
                            "Acme launched a warehouse robot pilot across three German facilities. "
                            "The company said expansion is planned next quarter with additional detail that keeps going long beyond the desired Telegram summary length and should be trimmed safely without breaking validation."
                        ),
                        "why_it_matters": "This is a concrete deployment with scale details and it should remain short even if the raw model output is too long for the preferred card shape in Bot 1.",
                        "duplicate_risk": "low",
                        "confidence": "medium",
                    }
                )
            )
        ),
    )

    result = _generate(_client())

    assert result.title is not None and len(result.title) <= 110
    assert result.summary is not None and len(result.summary) <= 280
    assert result.why_it_matters is not None and len(result.why_it_matters) <= 140


def test_unavailable_without_api_key_is_controlled() -> None:
    with pytest.raises(ClaudeFinalCardUnavailableError, match="ANTHROPIC_API_KEY"):
        _generate(_client(api_key=None))


def test_timeout_or_http_error_is_controlled(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(request, timeout):
        raise HTTPError("https://api.anthropic.com/v1/messages", 429, "Too Many Requests", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", _raise)

    with pytest.raises(ClaudeFinalCardUnavailableError, match="Claude request failed"):
        _generate(_client())
