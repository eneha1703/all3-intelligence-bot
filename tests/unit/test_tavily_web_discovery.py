import json

from all3_radar.discovery.models import DiscoveryQueryPack, DiscoveryRuntimeConfig
from all3_radar.discovery.tavily_search import TavilyWebDiscoveryClient, build_tavily_review_prompt


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
        queries=("construction robotics deployment contractor", "robotic layout customer deployment"),
        max_results=3,
    )


def test_build_tavily_review_prompt_contains_search_batches() -> None:
    prompt = build_tavily_review_prompt(
        query_packs=(_pack(),),
        search_batches=[
            {
                "query_pack_id": "construction_robotics_deployment",
                "query": "construction robotics deployment contractor",
                "goal": "Find deployed construction robotics.",
                "include_signals": ["named contractor"],
                "exclude_signals": ["generic demos"],
                "results": [
                    {
                        "title": "Robot contractor deploys drilling automation",
                        "url": "https://example.com/robot-drilling",
                        "source_name": "Example News",
                        "published_date": "2026-05-25",
                        "content": "Contractor deployed drilling robots on live sites.",
                        "score": 0.92,
                    }
                ],
            }
        ],
        freshness_days=2,
        max_candidates=10,
    )

    assert "Tavily has already searched the web" in prompt
    assert "Only use articles present in search_batches" in prompt
    assert "freshness window is" in prompt
    assert "Do not substitute older relevant stories" in prompt
    assert '"search_batches"' in prompt


def test_tavily_web_discovery_client_searches_tavily_then_reviews_with_claude(monkeypatch) -> None:
    captured: dict[str, object] = {"tavily_payloads": []}

    def _fake_urlopen(request, timeout):
        url = request.full_url
        payload = json.loads(request.data.decode("utf-8"))
        if "tavily.com/search" in url:
            captured["timeout"] = timeout
            captured["tavily_payloads"].append(payload)
            return _FakeResponse(
                {
                    "results": [
                        {
                            "title": "Robot contractor deploys drilling automation",
                            "url": "https://example.com/robot-drilling",
                            "source": "Example News",
                            "published_date": "2026-05-25",
                            "content": "A contractor deployed drilling robots on live sites.",
                            "score": 0.91,
                        }
                    ]
                }
            )
        captured["claude_payload"] = payload
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
                                        "matched_signal": "named contractor",
                                        "why_relevant": "Real construction robotics deployment.",
                                        "confidence": "high",
                                    }
                                ]
                            }
                        ),
                    }
                ],
                "usage": {"input_tokens": 123, "output_tokens": 45},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    client = TavilyWebDiscoveryClient(
        DiscoveryRuntimeConfig(
            api_key="anthropic-key",
            search_api_key="tavily-key",
            model="claude-test",
            timeout_seconds=15,
            max_tokens=900,
            max_search_uses=1,
            max_candidates_returned=10,
            max_new_candidates=5,
            tavily_search_depth="advanced",
            tavily_include_raw_content=True,
            blocked_domains=("spam.test",),
        )
    )

    result = client.discover(query_packs=(_pack(),), freshness_days=2)

    assert captured["timeout"] == 15
    assert captured["tavily_payloads"] == [
        {
            "days": 2,
            "exclude_domains": ["spam.test"],
            "include_answer": False,
            "include_favicon": False,
            "include_images": False,
            "include_raw_content": "markdown",
            "max_results": 3,
            "query": "construction robotics deployment contractor",
            "search_depth": "advanced",
            "topic": "news",
        }
    ]
    assert captured["claude_payload"]["model"] == "claude-test"
    assert result.web_search_requests == 1
    assert len(result.candidates) == 1
    assert result.candidates[0].title == "Robot contractor deploys drilling automation"
    assert result.usage["claude_usage"]["input_tokens"] == 123
    assert result.usage["tavily_search_batches"][0]["result_count"] == 1
