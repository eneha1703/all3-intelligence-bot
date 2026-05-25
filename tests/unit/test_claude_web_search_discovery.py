import json

from all3_radar.discovery.claude_web_search import ClaudeWebDiscoveryClient, build_discovery_prompt
from all3_radar.discovery.models import DiscoveryQueryPack, DiscoveryRuntimeConfig


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def _pack() -> DiscoveryQueryPack:
    return DiscoveryQueryPack(
        id="construction_robotics_deployment",
        name="Construction robotics deployment",
        goal="Find deployed construction robotics.",
        include_signals=("named contractor", "measurable labor gain"),
        exclude_signals=("generic demos",),
        queries=("construction robotics deployment contractor",),
        max_results=5,
    )


def test_build_discovery_prompt_contains_editorial_brief() -> None:
    prompt = build_discovery_prompt(query_packs=(_pack(),), freshness_days=3, max_candidates=10)

    assert "daily web-discovery analyst" in prompt
    assert "Treat the query packs as editorial search briefs" in prompt
    assert "Only return articles published within freshness_days" in prompt
    assert "return no candidate for that pack instead of substituting older relevant material" in prompt
    assert "Do not return older articles, reports, guides, rankings, top-10 lists" in prompt
    assert "Start your response with { and end it with }" in prompt
    assert "Do not include citations, commentary, source lists, or any text outside the JSON object" in prompt
    assert "Do not write a digest" in prompt
    assert "construction_robotics_deployment" in prompt
    assert "generic demos" in prompt
    assert '"candidates"' in prompt


def test_claude_web_discovery_client_parses_candidates_and_sends_web_search_tool(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "candidates": [
                                    {
                                        "title": "Robot contractor deploys drilling automation",
                                        "url": "https://example.com/robot-drilling",
                                        "source_name": "Example News",
                                        "published_date": "2026-05-25",
                                        "summary": "A contractor deployed drilling robots on live sites.",
                                        "query_pack_id": "construction_robotics_deployment",
                                        "matched_signal": "active deployment",
                                        "why_relevant": "Workflow-specific construction automation.",
                                        "confidence": "high",
                                    }
                                ]
                            }
                        ),
                    }
                ],
                "usage": {"server_tool_use": {"web_search_requests": 2}},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    client = ClaudeWebDiscoveryClient(
        DiscoveryRuntimeConfig(
            api_key="test-key",
            model="claude-test",
            timeout_seconds=12,
            max_tokens=900,
            max_search_uses=4,
            max_candidates_returned=10,
            max_new_candidates=5,
            blocked_domains=("spam.test",),
        )
    )

    result = client.discover(query_packs=(_pack(),), freshness_days=3)

    assert captured["timeout"] == 12
    payload = captured["payload"]
    assert payload["model"] == "claude-test"
    assert payload["tools"] == [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 4,
            "blocked_domains": ["spam.test"],
        }
    ]
    assert result.web_search_requests == 2
    assert len(result.candidates) == 1
    assert result.candidates[0].title == "Robot contractor deploys drilling automation"
    assert result.candidates[0].confidence == "high"
