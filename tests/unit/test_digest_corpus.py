from datetime import date

from all3_radar.digest.corpus import DigestCandidate, build_claude_writer_prompt, resolve_digest_window


def test_resolve_digest_window_formats_same_month_range() -> None:
    window = resolve_digest_window("2026-W18")

    assert window.previous_thursday == date(2026, 4, 23)
    assert window.current_thursday == date(2026, 4, 30)
    assert window.title == "Top 5 News Highlights | 23-30 April 2026 | Week 18"


def test_resolve_digest_window_formats_cross_month_range() -> None:
    window = resolve_digest_window("2026-W19")

    assert window.previous_thursday == date(2026, 4, 30)
    assert window.current_thursday == date(2026, 5, 7)
    assert window.title == "Top 5 News Highlights | 30 April-7 May 2026 | Week 19"


def test_resolve_digest_window_formats_cross_year_range() -> None:
    window = resolve_digest_window("2027-W01")

    assert window.previous_thursday == date(2026, 12, 31)
    assert window.current_thursday == date(2027, 1, 7)
    assert window.title == "Top 5 News Highlights | 31 December 2026-7 January 2027 | Week 1"


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
    assert "Editorial memory rules:" in prompt
    assert "digest_human_editor_voice" in prompt
    assert "Editorial memory good examples:" in prompt
    assert "Editorial memory bad examples:" in prompt
    assert "Data centers may become the next robotics construction site" in prompt
    assert "Germany's housing delivery is slowing as the system loses speed" in prompt
    assert "Mercer Mass Timber Offers Free CLT Design Tool" in prompt
    assert "Figure's humanoids are now making beds, not building cars" in prompt
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
