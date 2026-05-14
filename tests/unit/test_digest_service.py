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


def test_prepare_digest_rows_prioritizes_sustained_factory_operation_as_fifth_item() -> None:
    rows = [
        _row(
            event_id="funding-1",
            title="Mind Robotics raises funding for industrial robotics deployment",
            score=82,
            send_status="sent",
            event_flags={"funding_event": True, "industrial_robotics_signal": True},
        ) | {
            "summary_text": "Physical industries platform opportunity with advanced manufacturing deployment."
        },
        _row(
            event_id="timber-1",
            title="22-storey mass timber pod hotel targets Vancouver's Howe Street",
            score=78,
            send_status="sent",
            event_flags={"timber_strategic_signal": True},
        ) | {
            "summary_text": "A mass timber project with rezoning, urban site constraints and 408 units."
        },
        _row(
            event_id="infra-1",
            title="Xpanner lands $18M to automate construction sites",
            score=77,
            send_status="sent",
            event_flags={"funding_event": True, "construction_innovation_signal": True},
        ) | {
            "summary_text": "A physical delivery problem for construction automation infrastructure."
        },
        _row(
            event_id="robotics-1",
            title="Comau and Omron partner on advanced industrial automation",
            score=74,
            send_status="sent",
            event_flags={"industrial_robotics_signal": True, "partnership_event": True},
        ) | {
            "summary_text": "A construction robotics adjacent industrial automation platform signal."
        },
        _row(
            event_id="proof-1",
            title="Helix-02 robots now sustain full factory-style 8-hour shifts without intervention",
            score=63,
            send_status="stored_only",
            event_flags={"industrial_robotics_signal": True},
        ),
        _row(
            event_id="generic-1",
            title="Industrial startup expands its automation offering",
            score=91,
            send_status="sent",
            event_flags={"industrial_robotics_signal": True},
        ) | {
            "summary_text": "The company expanded its offering for industrial customers."
        },
    ]

    prepared = _prepare_digest_rows(rows, limit=5)

    assert [row["canonical_event_id"] for row in prepared] == [
        "proof-1",
        "timber-1",
        "funding-1",
        "infra-1",
        "robotics-1",
    ]


def test_prepare_digest_rows_emergency_backfills_to_five_items() -> None:
    rows = [
        _row(
            event_id="good-1",
            title="Mind Robotics raises funding for industrial robotics deployment",
            score=82,
            send_status="sent",
            event_flags={"funding_event": True, "industrial_robotics_signal": True},
        ) | {"summary_text": "Platform opportunity in advanced manufacturing."},
        _row(
            event_id="good-2",
            title="Xpanner lands $18M to automate construction sites",
            score=77,
            send_status="sent",
            event_flags={"funding_event": True, "construction_innovation_signal": True},
        ) | {"summary_text": "A physical delivery problem for construction automation."},
        _row(
            event_id="good-3",
            title="22-storey mass timber pod hotel targets Vancouver's Howe Street",
            score=76,
            send_status="sent",
            event_flags={"timber_strategic_signal": True},
        ) | {"summary_text": "A mass timber project with rezoning and 408 units."},
        _row(
            event_id="good-4",
            title="Helix-02 robots now sustain full factory-style 8-hour shifts without intervention",
            score=63,
            send_status="stored_only",
            event_flags={"industrial_robotics_signal": True},
        ),
        _row(
            event_id="fallback-5",
            title="Industrial automation company expands manufacturing offering",
            score=56,
            send_status="stored_only",
            event_flags={"industrial_robotics_signal": True},
        ) | {
            "summary_text": "A generic industrial automation expansion story.",
        },
    ]

    prepared = _prepare_digest_rows(rows, limit=5)

    assert len(prepared) == 5
    assert [row["canonical_event_id"] for row in prepared][-1] == "fallback-5"
