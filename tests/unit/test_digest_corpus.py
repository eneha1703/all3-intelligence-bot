from datetime import date

from all3_radar.digest.corpus import (
    DigestCandidate,
    build_claude_revision_prompt,
    build_claude_writer_prompt,
    hydrate_digest_candidates,
    resolve_digest_window,
)


def test_resolve_digest_window_formats_same_month_range() -> None:
    window = resolve_digest_window("2026-W18")

    assert window.previous_thursday == date(2026, 4, 23)
    assert window.start_date == date(2026, 4, 24)
    assert window.current_thursday == date(2026, 4, 30)
    assert window.title == "Top 5 News Highlights | 24-30 April 2026 | Week 18"


def test_resolve_digest_window_formats_cross_month_range() -> None:
    window = resolve_digest_window("2026-W19")

    assert window.previous_thursday == date(2026, 4, 30)
    assert window.start_date == date(2026, 5, 1)
    assert window.current_thursday == date(2026, 5, 7)
    assert window.title == "Top 5 News Highlights | 1-7 May 2026 | Week 19"


def test_resolve_digest_window_formats_cross_year_range() -> None:
    window = resolve_digest_window("2027-W01")

    assert window.previous_thursday == date(2026, 12, 31)
    assert window.start_date == date(2027, 1, 1)
    assert window.current_thursday == date(2027, 1, 7)
    assert window.title == "Top 5 News Highlights | 1-7 January 2027 | Week 1"


def test_build_claude_writer_prompt_includes_house_style_and_examples() -> None:
    window = resolve_digest_window("2026-W18")
    candidate = DigestCandidate(
        canonical_event_id="event-1",
        normalized_item_id="item-1",
        source_id="source",
        title="Example title",
        canonical_url="https://example.com/story",
        published_ts=None,
        score=60,
        summary_text="Example summary",
        event_flags={"robotics": True},
    )

    prompt = build_claude_writer_prompt(window, [candidate])

    assert "House style guide:" in prompt
    assert "Write like a smart human editor producing a short weekly note." in prompt
    assert "Aim for roughly 45 to 75 words per item." in prompt
    assert "Prefer 2 or 3 short sentences per item." in prompt
    assert "Use currency formatting like USD 120B, USD 25M, and EUR 100M." in prompt
    assert 'avoid "we", "our", "our need", "our goals", or "our strategy".' in prompt
    assert "Do not simply restate the source headline in either the bold headline or the first sentence." in prompt
    assert "Do not repeat the same core fact or idea in the headline and the first sentence with only minor wording changes." in prompt
    assert "Headline = thesis. First sentence = core evidence. Final sentence = narrow implication." in prompt
    assert "Do not repeat a number, percentage, funding amount, valuation, unit count, or timeline" in prompt
    assert "Write like an industry editor, not a columnist, feature writer, or culture critic." in prompt
    assert "Use plain English. If a sentence can be simpler, make it simpler." in prompt
    assert "Avoid words like 'thesis', 'lineage', 'durable', 'utilisation'" in prompt
    assert "Do not sound like a market memo, strategy deck, or founder essay." in prompt
    assert "Do not default to starting every paragraph with the company name." in prompt
    assert "Mix the editorial voice across items so the digest reads like it was written by a person, not a template." in prompt
    assert "If a selected item has thin grounding, stay close to the provided title and summary" in prompt
    assert "Do not infer geography, market comparisons, buyer motivations, policy context, financing dynamics, or adoption drivers" in prompt
    assert "Story-type guidance:" in prompt
    assert "- timber_adoption: focus on adoption barriers, share shifts, competing delivery systems" in prompt
    assert "- construction_robotics_funding: the funding is not the point by itself." in prompt
    assert '"story_type": "general_relevant"' in prompt
    assert '"angle_guard": [' in prompt
    assert '"digest_grounding":' in prompt
    assert "When a story combines demand recovery with supply lag, name the actual bottleneck directly" in prompt
    assert "For funding and automation stories, explain the practical wedge" in prompt
    assert "Editorial memory rules:" in prompt
    assert "digest_human_editor_voice" in prompt
    assert "digest_name_pipeline_constraint" in prompt
    assert "digest_surface_operational_wedge" in prompt
    assert "Editorial memory good examples:" in prompt
    assert "Editorial memory bad examples:" in prompt
    assert "Data centers may become the next robotics construction site" in prompt
    assert "Germany's housing market is recovering before the pipeline does" in prompt
    assert "Xpanner finds a practical wedge for construction automation" in prompt
    assert "Germany's housing delivery is slowing as the system loses speed" in prompt
    assert "Mercer Mass Timber Offers Free CLT Design Tool" in prompt
    assert "Figure's humanoids are now making beds, not building cars" in prompt
    assert "That gap makes faster, more predictable construction more valuable." in prompt
    assert "worth noting" in prompt


def test_build_claude_writer_prompt_requires_exactly_five_items() -> None:
    window = resolve_digest_window("2026-W20")
    candidates = [
        DigestCandidate(
            canonical_event_id=f"event-{idx}",
            normalized_item_id=f"item-{idx}",
            source_id="source",
            title=f"Example title {idx}",
            canonical_url=f"https://example.com/story-{idx}",
            published_ts=None,
            score=60,
            summary_text="Example summary",
            event_flags={"robotics": True},
        )
        for idx in range(1, 5)
    ]

    prompt = build_claude_writer_prompt(window, candidates)

    assert "Use exactly 5 items" in prompt
    assert "Do not create synthetic wrap-up items" in prompt


def test_build_claude_revision_prompt_includes_quality_checks() -> None:
    window = resolve_digest_window("2026-W21")
    candidate = DigestCandidate(
        canonical_event_id="event-1",
        normalized_item_id="item-1",
        source_id="ai_insider_rss",
        title="August Robotics Raises $30M in Series B Funding for Autonomous Construction Robotics",
        canonical_url="https://example.com/august",
        published_ts=None,
        score=66,
        summary_text=(
            "August Robotics has raised $30 million to expand production, increase deployments and develop additional automation systems."
        ),
        event_flags={"funding_event": True, "construction_innovation_signal": True},
        story_type="construction_robotics_funding",
        angle_guard=(
            "Investor roll call is secondary unless the investor itself is the signal. Focus on the workflow wedge, retrofit model, task packaging, or measurable labour/time gain.",
        ),
    )

    draft = (
        "Top 5 News Highlights | 15-21 May 2026 | Week 21\n\n"
        "1. <b>August Robotics raises USD 30M to scale autonomous construction systems</b>\n"
        'The Series B round was led by Big Pi Ventures with multiple existing backers returning. <a href="https://example.com/august">Link</a>'
    )

    prompt = build_claude_revision_prompt(window, [candidate], draft)

    assert "Review the drafted Weekly Digest Bot 2 message item by item" in prompt
    assert "Remove investor laundry lists unless the investor identity itself is the signal." in prompt
    assert "For construction_robotics_funding stories, the workflow wedge matters more than the cap table." in prompt
    assert "Treat `summary` as the cleaned editorial grounding." in prompt
    assert "Return the full final digest only." in prompt
    assert draft in prompt


def test_build_claude_writer_prompt_includes_specific_angle_guards_for_timber_and_deployment() -> None:
    window = resolve_digest_window("2026-W21")
    candidates = [
        DigestCandidate(
            canonical_event_id="event-timber",
            normalized_item_id="item-timber",
            source_id="wood_central_api",
            title="Mid-Rise Surge Marks Timber Frame's Inflection Point",
            canonical_url="https://example.com/timber",
            published_ts=None,
            score=48,
            summary_text=(
                "Australia's mid-rise approvals jumped sharply in 2025, while structural timber consumption fell "
                "and imported prefabricated dwellings and LVL volumes rose."
            ),
            event_flags={"timber_strategic_signal": True},
            story_type="timber_adoption",
            angle_guard=(
                "Surface the adoption barrier, delivery-system mismatch, or share shift. Do not default to generic timber momentum or sustainability language.",
                "Center the contradiction between rising mid-rise demand and timber losing practical share; do not drift into a generic 'timber is becoming normal' angle.",
            ),
        ),
        DigestCandidate(
            canonical_event_id="event-deploy",
            normalized_item_id="item-deploy",
            source_id="business_insider_feed",
            title="Silicon Valley's latest binge-watch is a humanoid warehouse worker",
            canonical_url="https://example.com/figure",
            published_ts=None,
            score=86,
            summary_text=(
                "Figure AI's humanoids drew over 3 million views on X as they sorted packages with zero failures for 24 hours."
            ),
            event_flags={"industrial_robotics_signal": True, "deployment_event": True},
            story_type="industrial_deployment",
            angle_guard=(
                "Treat this as an operational proof or deployment-threshold story. Focus on what the run or rollout shows and what it still does not prove.",
                "Ignore audience, virality, or character-name details unless they change the operating claim.",
            ),
        ),
    ]

    prompt = build_claude_writer_prompt(window, candidates)

    assert '"story_type": "timber_adoption"' in prompt
    assert '"story_type": "industrial_deployment"' in prompt
    assert "Center the contradiction between rising mid-rise demand and timber losing practical share" in prompt
    assert "Ignore audience, virality, or character-name details unless they change the operating claim." in prompt


def test_hydrate_digest_candidates_builds_timber_grounding_without_attribution_noise() -> None:
    candidates = hydrate_digest_candidates(
        [
            {
                "canonical_event_id": "event-timber",
                "normalized_item_id": "item-timber",
                "source_id": "wood_central_api",
                "title": "Just Look Up — Mid-Rise Surge Marks Timber Frame’s Inflection Point",
                "canonical_url": "https://example.com/timber",
                "published_ts": None,
                "score": 48,
                "summary_text": (
                    "Mid-rise has overtaken detached housing as the building typology driving Australia’s housing growth, "
                    "with established frame and truss supply chains now ceding ground in a market they have historically "
                    "dominated. That is according to IndustryEdge Managing Director Tim Woods, who addressed FTMA’s National Conference."
                ),
                "signals_json": '{"event_flags":{"timber_strategic_signal":true}}',
            }
        ]
    )

    candidate = candidates[0]
    assert candidate.story_type == "timber_adoption"
    assert candidate.digest_grounding is not None
    assert "growth typology" in candidate.digest_grounding
    assert "ceding ground" in candidate.digest_grounding
    assert "Tim Woods" not in candidate.digest_grounding
    assert "National Conference" not in candidate.digest_grounding


def test_hydrate_digest_candidates_builds_cleaner_funding_and_deployment_grounding() -> None:
    candidates = hydrate_digest_candidates(
        [
            {
                "canonical_event_id": "event-funding",
                "normalized_item_id": "item-funding",
                "source_id": "ai_insider_rss",
                "title": "August Robotics Raises $30M in Series B Funding for Autonomous Construction Robotics",
                "canonical_url": "https://example.com/august",
                "published_ts": None,
                "score": 66,
                "summary_text": (
                    "Insider Brief August Robotics has raised $30 million in a Series B funding round led by Big Pi Ventures "
                    "as the construction robotics company looks to expand production, increase deployments and develop additional "
                    "automation systems. Existing investors Blackbird, Skip Capital, Tanarra and Future Family Office joined the round."
                ),
                "signals_json": '{"event_flags":{"funding_event":true,"construction_innovation_signal":true}}',
            },
            {
                "canonical_event_id": "event-deploy",
                "normalized_item_id": "item-deploy",
                "source_id": "business_insider_feed",
                "title": "Silicon Valley's latest binge-watch is a humanoid warehouse worker",
                "canonical_url": "https://example.com/figure",
                "published_ts": None,
                "score": 86,
                "summary_text": (
                    "Viewers gave the three humanoids sorting packages names: Bob, Frank and Gary. "
                    "Figure AI's humanoids drew over 3 million views on X as it sorted packages on a viral livestream. "
                    "CEO Brett Adcock said the robots worked autonomously with zero failures for 24 hours."
                ),
                "signals_json": '{"event_flags":{"industrial_robotics_signal":true,"deployment_event":true}}',
            },
        ]
    )

    funding_candidate = candidates[0]
    assert funding_candidate.story_type == "construction_robotics_funding"
    assert funding_candidate.digest_grounding == (
        "The new funding is being used to expand production, increase deployments and develop additional automation systems."
    )
    assert "Big Pi Ventures" not in funding_candidate.digest_grounding

    deployment_candidate = candidates[1]
    assert deployment_candidate.story_type == "industrial_deployment"
    assert "24 hours" in (deployment_candidate.digest_grounding or "")
    assert "zero reported failures" in (deployment_candidate.digest_grounding or "")
    assert "3 million views" not in (deployment_candidate.digest_grounding or "")
