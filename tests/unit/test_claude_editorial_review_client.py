import json
from urllib.error import HTTPError

import pytest

from all3_radar.summarization.claude_editorial_review_client import (
    ClaudeEditorialReviewClient,
    ClaudeEditorialReviewUnavailableError,
    build_claude_editorial_review_prompt,
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


def _client(**overrides: object) -> ClaudeEditorialReviewClient:
    defaults = {
        "enabled": True,
        "api_key": "test-key",
        "model": "claude-sonnet-4-6",
        "timeout_seconds": 30,
        "max_tokens": 700,
    }
    defaults.update(overrides)
    return ClaudeEditorialReviewClient(**defaults)


def _payload(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _review(client: ClaudeEditorialReviewClient) -> object:
    return client.review_candidate(
        title="SoftBank is creating a robotics company that builds data centers",
        url="https://example.com/softbank-robotics-datacenter",
        source="TechCrunch",
        summary=(
            "SoftBank is forming a robotics company focused on automated data-center construction and "
            "physical infrastructure execution."
        ),
        score=24,
        ranking_signals={
            "event_flags": {
                "funding_event": True,
                "industrial_robotics_signal": True,
                "construction_innovation_signal": True,
            }
        },
        freshness="fresh",
        relevance="keep",
    )


def test_build_claude_editorial_review_prompt_includes_scope_rules() -> None:
    prompt = build_claude_editorial_review_prompt(
        title="Taco Bell expands AI menu recommendations",
        url="https://example.com/taco-bell-ai",
        source="TechCrunch",
        summary="Taco Bell is using AI for menu personalization in drive-through ordering.",
        score=18,
        ranking_signals={"event_flags": {"funding_event": False}},
        freshness="fresh",
        relevance="keep",
    )

    assert "physical AI" in prompt
    assert "industrial robotics" in prompt
    assert "factory automation tied to robotics, AI, or autonomous systems" in prompt
    assert "construction automation" in prompt
    assert "housing industrialization or productivity" in prompt
    assert "timber adoption, scaling, economics, or policy" in prompt
    assert "timber building-performance evidence" in prompt
    assert "quantified heat-loss" in prompt
    assert "robotics, automation, platform funding, deployment, or physical infrastructure automation" in prompt
    assert "Industrial automation engineering enablement can also be in scope" in prompt
    assert "manufacturing language models" in prompt
    assert "automation cell design" in prompt
    assert "designed, programmed, integrated, commissioned, or deployed" in prompt
    assert "restaurant or menu personalization AI" in prompt
    assert "generic automotive capex" in prompt
    assert "gas-car or EV-demand stories" in prompt
    assert "generic enterprise AI, ERP, workflow, procurement, or back-office automation" in prompt
    assert "access-control, security, or generic Industrial IoT security automation" in prompt
    assert "generic manufacturing without robotics, AI, or automation" in prompt
    assert "Do not reject strategic capability acquisitions" in prompt
    assert "buying robotics, humanoid, industrial automation, construction automation, prefab, modular, contech, or physical-AI capability" in prompt
    assert "Do not reject quantified timber building-performance evidence as mere thought leadership" in prompt
    assert "prefer low or medium confidence over a high-confidence rejection" in prompt
    assert "Return only a single JSON object" in prompt
    assert "Do not use markdown" in prompt
    assert "Do not wrap the response in code fences" in prompt
    assert "Do not include explanation outside JSON" in prompt


def test_review_candidate_parses_high_confidence_promotion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": True,
                        "reject_reason": None,
                        "edited_title": "SoftBank forms robotics company for automated data-center buildout",
                        "edited_summary": (
                            "SoftBank is creating a robotics company focused on automated data-center "
                            "construction and physical infrastructure execution."
                        ),
                        "confidence": "high",
                    }
                )
            )
        ),
    )

    result = _review(_client())

    assert result.send_ok is True
    assert result.confidence == "high"
    assert result.edited_title is not None
    assert result.edited_summary is not None
    assert result.is_high_confidence_promotion is True
    assert result.is_high_confidence_rejection is False


def test_review_candidate_parses_fenced_json_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                """```json
{"send_ok": true, "reject_reason": null, "edited_title": "SoftBank forms robotics company for automated data-center buildout", "edited_summary": "SoftBank is creating a robotics company focused on automated data-center construction and physical infrastructure execution.", "confidence": "high"}
```"""
            )
        ),
    )

    result = _review(_client())

    assert result.is_high_confidence_promotion is True


def test_review_candidate_parses_plain_fenced_json_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                """```
{"send_ok": false, "reject_reason": "consumer_ai_not_operational", "edited_title": null, "edited_summary": null, "confidence": "high"}
```"""
            )
        ),
    )

    result = _review(_client())

    assert result.is_high_confidence_rejection is True


def test_review_candidate_parses_json_object_wrapped_in_prose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                'Here is the decision:\n{"send_ok": true, "reject_reason": null, "edited_title": "SoftBank forms robotics company for automated data-center buildout", "edited_summary": "SoftBank is creating a robotics company focused on automated data-center construction and physical infrastructure execution.", "confidence": "high"}\nThanks.'
            )
        ),
    )

    result = _review(_client())

    assert result.is_high_confidence_promotion is True


def test_review_candidate_parses_high_confidence_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": False,
                        "reject_reason": "consumer_ai_not_operational",
                        "edited_title": None,
                        "edited_summary": None,
                        "confidence": "high",
                    }
                )
            )
        ),
    )

    result = _review(_client())

    assert result.send_ok is False
    assert result.reject_reason == "consumer_ai_not_operational"
    assert result.confidence == "high"
    assert result.is_high_confidence_rejection is True
    assert result.is_high_confidence_promotion is False


@pytest.mark.parametrize("confidence", ["low", "medium"])
def test_review_candidate_keeps_low_or_medium_confidence_result(
    monkeypatch: pytest.MonkeyPatch, confidence: str
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": True,
                        "reject_reason": None,
                        "edited_title": "Borderline automation signal",
                        "edited_summary": "The story may matter, but deterministic review should keep control.",
                        "confidence": confidence,
                    }
                )
            )
        ),
    )

    result = _review(_client())

    assert result.confidence == confidence
    assert result.is_high_confidence_promotion is False
    assert result.is_high_confidence_rejection is False


def test_review_candidate_invalid_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(_payload("not-json")),
    )

    with pytest.raises(ClaudeEditorialReviewUnavailableError, match="not valid JSON") as exc_info:
        _review(_client())
    assert exc_info.value.reason == "response_not_json"


def test_review_candidate_multiple_json_objects_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                '{"send_ok": true, "reject_reason": null, "edited_title": "A", "edited_summary": "B", "confidence": "high"} '
                '{"send_ok": false, "reject_reason": "consumer_ai_not_operational", "edited_title": null, "edited_summary": null, "confidence": "high"}'
            )
        ),
    )

    with pytest.raises(ClaudeEditorialReviewUnavailableError, match="multiple JSON objects") as exc_info:
        _review(_client())
    assert exc_info.value.reason == "response_not_json"


def test_review_candidate_missing_send_ok_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(json.dumps({"edited_title": "A", "edited_summary": "B", "confidence": "high"}))
        ),
    )

    with pytest.raises(ClaudeEditorialReviewUnavailableError, match="send_ok") as exc_info:
        _review(_client())
    assert exc_info.value.reason == "response_missing_send_ok"


def test_review_candidate_high_confidence_rejection_requires_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": False,
                        "reject_reason": "   ",
                        "edited_title": None,
                        "edited_summary": None,
                        "confidence": "high",
                    }
                )
            )
        ),
    )

    with pytest.raises(ClaudeEditorialReviewUnavailableError, match="reject_reason") as exc_info:
        _review(_client())
    assert exc_info.value.reason == "response_invalid_rejection"


def test_review_candidate_high_confidence_promotion_requires_title_and_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": True,
                        "reject_reason": None,
                        "edited_title": "   ",
                        "edited_summary": "",
                        "confidence": "high",
                    }
                )
            )
        ),
    )

    with pytest.raises(ClaudeEditorialReviewUnavailableError, match="usable title") as exc_info:
        _review(_client())
    assert exc_info.value.reason == "response_invalid_promotion"


def test_review_candidate_softbank_robotics_datacenter_example_is_valid_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": True,
                        "reject_reason": None,
                        "edited_title": "SoftBank robotics venture targets automated data-center construction",
                        "edited_summary": (
                            "SoftBank is creating a robotics venture centered on automated data-center "
                            "construction and physical infrastructure execution."
                        ),
                        "confidence": "high",
                    }
                )
            )
        ),
    )

    result = _review(_client())

    assert result.is_high_confidence_promotion is True
    assert "robotics" in (result.edited_title or "").lower()


def test_review_candidate_launchpad_style_industrial_automation_design_example_can_be_valid_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": True,
                        "reject_reason": None,
                        "edited_title": "Launchpad Build AI targets industrial automation engineering bottlenecks",
                        "edited_summary": (
                            "Launchpad Build AI is pitching a manufacturing language model for automation cell design and "
                            "industrial automation engineering workflows, pointing to a potentially important software layer "
                            "for how robotics and factory automation systems are designed and integrated."
                        ),
                        "confidence": "high",
                    }
                )
            )
        ),
    )

    result = _client().review_candidate(
        title="Launchpad Build AI offers MLM to speed industrial automation design",
        url="https://www.therobotreport.com/launchpad-build-ai-offers-manufacturing-language-model-industrial-automation/",
        source="Robot Report",
        summary=(
            "Launchpad Build AI says its Manufacturing Language Model can democratize automation for high-mix, "
            "low-volume production with inputs from photos, videos, or CAD."
        ),
        score=33,
        ranking_signals={"event_flags": {"industrial_robotics_signal": True}},
        freshness="fresh",
        relevance="keep",
    )

    assert result.is_high_confidence_promotion is True
    assert "automation" in (result.edited_title or "").lower()


def test_review_candidate_taco_bell_menu_ai_example_is_valid_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": False,
                        "reject_reason": "consumer_ai_menu_personalization",
                        "edited_title": None,
                        "edited_summary": None,
                        "confidence": "high",
                    }
                )
            )
        ),
    )

    result = _client().review_candidate(
        title="Taco Bell expands AI menu recommendations",
        url="https://example.com/taco-bell-ai",
        source="TechCrunch",
        summary="Taco Bell is using AI for menu personalization in drive-through ordering.",
        score=19,
        ranking_signals={"event_flags": {"funding_event": False}},
        freshness="fresh",
        relevance="keep",
    )

    assert result.is_high_confidence_rejection is True
    assert result.reject_reason == "consumer_ai_menu_personalization"


@pytest.mark.parametrize(
    ("title", "url", "source", "summary", "reject_reason"),
    [
        (
            "How Procurement Automation Creates Audit-Ready Supply Chains in Manufacturing",
            "https://example.com/procurement-automation",
            "Robotics & Automation News",
            "The article covers procurement workflow automation and audit-ready supply chain software in manufacturing organizations.",
            "back_office_procurement_automation",
        ),
        (
            "How Access Control Systems Integrate with Industrial IoT for Real-Time Security Automation",
            "https://example.com/access-control-iot",
            "Robotics & Automation News",
            "The article describes access-control systems and industrial IoT security automation for facilities.",
            "industrial_security_automation_out_of_scope",
        ),
        (
            "Enterprise AI assistant helps teams summarize meetings faster",
            "https://example.com/enterprise-ai-productivity",
            "TechCrunch",
            "A generic enterprise AI productivity assistant helps office teams summarize meetings and manage tasks.",
            "generic_enterprise_ai_productivity",
        ),
    ],
)
def test_review_candidate_out_of_scope_software_automation_examples_remain_valid_rejections(
    monkeypatch: pytest.MonkeyPatch,
    title: str,
    url: str,
    source: str,
    summary: str,
    reject_reason: str,
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "send_ok": False,
                        "reject_reason": reject_reason,
                        "edited_title": None,
                        "edited_summary": None,
                        "confidence": "high",
                    }
                )
            )
        ),
    )

    result = _client().review_candidate(
        title=title,
        url=url,
        source=source,
        summary=summary,
        score=25,
        ranking_signals={"event_flags": {"funding_event": False}},
        freshness="fresh",
        relevance="keep",
    )

    assert result.is_high_confidence_rejection is True
    assert result.reject_reason == reject_reason


def test_review_candidate_http_error_is_controlled(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(request, timeout):
        raise HTTPError("https://api.anthropic.com/v1/messages", 429, "Too Many Requests", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", _raise)

    with pytest.raises(ClaudeEditorialReviewUnavailableError, match="HTTP error") as exc_info:
        _review(_client())
    assert exc_info.value.reason == "api_http_error"
    assert exc_info.value.status_code == 429
