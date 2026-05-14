import json

from all3_radar.digest.digest_service import _prepare_digest_rows


def _row(
    *,
    event_id: str,
    title: str,
    score: int,
    send_status: str = "stored_only",
    skip_reason: str | None = None,
    event_flags: dict | None = None,
) -> dict[str, object]:
    return {
        "canonical_event_id": event_id,
        "normalized_item_id": f"item-{event_id}",
        "source_id": "test_source",
        "title": title,
        "canonical_url": f"https://example.com/{event_id}",
        "published_ts": "2026-05-14T12:00:00+00:00",
        "score": score,
        "send_status": send_status,
        "skip_reason": skip_reason,
        "summary_text": title,
        "signals_json": json.dumps({"event_flags": event_flags or {}}, sort_keys=True),
        "manual_shortlist_signal": False,
    }


def test_prepare_digest_rows_excludes_claude_editorial_rejections() -> None:
    rows = [
        _row(
            event_id="good-1",
            title="Mind Robotics raises funding for industrial robotics deployment",
            score=80,
            send_status="sent",
            event_flags={"funding_event": True, "industrial_robotics_signal": True},
        ),
        _row(
            event_id="bad-1",
            title="Lviv to Build Ukraine's First Timber School Ahead of National Rollout",
            score=89,
            skip_reason="claude_editorial_rejected",
            event_flags={"timber_policy_signal": True, "deployment_event": True},
        ),
    ]

    prepared = _prepare_digest_rows(rows, limit=5)

    assert [row["canonical_event_id"] for row in prepared] == ["good-1"]


def test_prepare_digest_rows_excludes_adjacent_logistics_candidates() -> None:
    rows = [
        _row(
            event_id="good-2",
            title="Flo Mobility raises funding for construction-site autonomous handling",
            score=86,
            send_status="sent",
            event_flags={"funding_event": True, "construction_innovation_signal": True},
        ),
        _row(
            event_id="bad-2",
            title="SAP and Cyberwave deploy autonomous robots in logistics warehouse",
            score=53,
            skip_reason="claude_final_card_invalid_output",
            event_flags={"adjacent_logistics_only": True, "industrial_robotics_signal": True, "deployment_event": True},
        ),
    ]

    prepared = _prepare_digest_rows(rows, limit=5)

    assert [row["canonical_event_id"] for row in prepared] == ["good-2"]


def test_prepare_digest_rows_excludes_consumer_robotics_marketing_noise() -> None:
    rows = [
        _row(
            event_id="good-3",
            title="Comau partners with Omron to accelerate advanced industrial automation",
            score=69,
            send_status="stored_only",
            skip_reason="claude_final_card_rejected",
            event_flags={"partnership_event": True, "industrial_robotics_signal": True},
        ),
        _row(
            event_id="bad-3",
            title="Tech's hottest job: Documentary filmmaker",
            score=58,
            send_status="stored_only",
            skip_reason="claude_final_card_rejected",
            event_flags={"funding_event": True, "product_launch_event": True},
        ) | {
            "summary_text": "A consumer robotics startup has launched a founder documentary, launch video and behind the scenes doc ahead of shipping this summer."
        },
    ]

    prepared = _prepare_digest_rows(rows, limit=5)

    assert [row["canonical_event_id"] for row in prepared] == ["good-3"]
